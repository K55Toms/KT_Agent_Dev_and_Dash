"""Per-run hook settings file, launch argv placement and the fake claude's hook mode (fake-binary evidence)."""
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dashboard.backends import claude_launch as cl
from dashboard.backends.claude_hook import allow_reply, deny_reply

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
TOKEN = "TOKENSENTINEL" + "a" * 30


def url(port, token=TOKEN):
    return "http://127.0.0.1:%d/hook/managed/%s" % (port, token)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(mode=0o700)
        self.url = url(4321)

    def tearDown(self):
        self.temp.cleanup()

    def test_settings_file_has_exactly_one_hook_and_no_other_keys(self):
        path = cl.write_run_settings(self.state, self.url, 960)
        data = json.loads(path.read_text())
        self.assertEqual(data, {"hooks": {"PermissionRequest": [{"hooks": [
            {"type": "http", "url": self.url, "timeout": 960}]}]}})
        self.assertEqual(path.read_text(), json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual(path.parent, self.state / "claude-runs")
        self.assertEqual(list(path.parent.glob(".*")), [])

    def test_file_writes_exactly_the_timeout_it_is_given(self):
        for timeout in (1, 120, 3660):
            path = cl.write_run_settings(self.state, self.url, timeout)
            self.assertEqual(json.loads(path.read_text())["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"], timeout)

    def test_url_and_timeout_are_validated_before_writing(self):
        bad = ["", "http://localhost:1/hook/managed/" + TOKEN, "https://127.0.0.1:1/hook/managed/" + TOKEN,
               "http://127.0.0.1:1/hook/managed/", "http://127.0.0.1:1/hook/other/" + TOKEN,
               "http://127.0.0.1:1/hook/managed/" + TOKEN + "/x", "http://127.0.0.1:1/hook/managed/a b",
               "http://127.0.0.1:0/hook/managed/" + TOKEN, "http://127.0.0.1:99999/hook/managed/" + TOKEN,
               "http://user@127.0.0.1:1/hook/managed/" + TOKEN, "http://127.0.0.1:1/hook/managed/" + TOKEN + "\n", None, 5]
        for item in bad:
            with self.assertRaises(ValueError, msg=repr(item)):
                cl.write_run_settings(self.state, item, 120)
        for timeout in (0, -1, True, 1.5, "120", None):
            with self.assertRaises(ValueError, msg=repr(timeout)):
                cl.write_run_settings(self.state, self.url, timeout)
        self.assertFalse((self.state / "claude-runs").exists())

    def test_modes_0600_0700(self):
        path = cl.write_run_settings(self.state, self.url, 120)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        (self.state / "claude-runs").chmod(0o755)
        path2 = cl.write_run_settings(self.state, self.url, 120)
        self.assertEqual(stat.S_IMODE(path2.parent.stat().st_mode), 0o700)
        self.assertNotEqual(path, path2)

    def test_remove_is_idempotent_and_refuses_paths_outside_state_dir(self):
        path = cl.write_run_settings(self.state, self.url, 120)
        cl.remove_run_settings(path)
        self.assertFalse(path.exists())
        cl.remove_run_settings(path)
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("{}")
        inside_other = self.state / "other.json"
        inside_other.write_text("{}")
        for target in (outside, inside_other, self.state / "claude-runs" / ".." / "other.json", Path("relative.json")):
            with self.assertRaises(ValueError):
                cl.remove_run_settings(target)
        self.assertTrue(outside.exists() and inside_other.exists())
        link = self.state / "claude-runs" / "link.json"
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            cl.remove_run_settings(link)
        self.assertTrue(outside.exists())

    def test_build_argv_places_settings_and_omits_when_none(self):
        base = dict(prompt="p", alias="opus", role_name="r", role_json="{}", instructions="", safety="S")
        plain = cl.build_argv("/bin/claude", **base)
        self.assertNotIn("--settings", plain)
        with_path = cl.build_argv("/bin/claude", settings_path=Path("/s/claude-runs/x.json"), **base)
        index = with_path.index("--settings")
        self.assertEqual(with_path[index - 2:index + 3], ["--setting-sources", "user", "--settings", "/s/claude-runs/x.json"] + ["--model"][:1])
        self.assertEqual(with_path[:index] + with_path[index + 2:], plain)

    def test_existing_argv_golden_unchanged_without_settings(self):
        out = cl.build_argv("/bin/claude", prompt="do it", alias="opus", role_name="qa_engineer", role_json="{}",
                            instructions="INS", safety="SAFE", effort=None, resume=None, settings_path=None)
        self.assertEqual(out, [
            "/bin/claude", "-p", "do it", "--output-format", "stream-json", "--verbose",
            "--setting-sources", "user", "--model", "opus", "--agents", "{}",
            "--agent", "qa_engineer", "--append-system-prompt", "SAFE\n\nINS"])
        for bad in ("", "relative.json", "-x", 3):
            with self.assertRaises(ValueError):
                cl.build_argv("/bin/claude", prompt="p", alias="opus", role_name="r", role_json="{}",
                              instructions="", safety="S", settings_path=bad)


class Stub:
    """A loopback hook receiver stand-in: mode per request is picked by `script(n)` -> allow|deny|silent|500|junk."""

    def __init__(self, script):
        self.script = script
        self.seen = []
        self.lock = threading.Lock()
        self.release = threading.Event()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                with stub.lock:
                    stub.seen.append((self.path, self.headers.get("Content-Type"), body))
                    n = len(stub.seen)
                mode = stub.script(n)
                if mode == "silent":
                    stub.release.wait(30)
                    return
                if mode == "500":
                    self.send_response(500); self.send_header("Content-Length", "0"); self.end_headers(); return
                reply = {"allow": allow_reply(), "deny": deny_reply(), "junk": b"{not json",
                         "allowish": allow_reply().replace(b"allow", b"allowx")}[mode]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class FakeHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(mode=0o700)
        self.record = Path(self.temp.name) / "rec.jsonl"
        self.stubs = []

    def tearDown(self):
        for stub in self.stubs:
            stub.close()
        self.temp.cleanup()

    def stub(self, script):
        stub = Stub(script)
        self.stubs.append(stub)
        return stub

    def start(self, scenario, stub, timeout=20, extra_env=None):
        settings = cl.write_run_settings(self.state, url(stub.port), timeout)
        env = {"PATH": os.environ.get("PATH", ""), "FAKE_CLAUDE_FIXTURE": "success", "FAKE_CLAUDE_HOOK": scenario,
               "FAKE_CLAUDE_RECORD": str(self.record)}
        env.update(extra_env or {})
        proc = subprocess.Popen([sys.executable, str(FAKE), "-p", "x", "--setting-sources", "user", "--settings", str(settings)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc

    def finish(self, proc, timeout=15):
        out, err = proc.communicate(timeout=timeout)
        return [json.loads(line) for line in out.splitlines() if line.strip()], out, err

    def hook_records(self):
        rows = [json.loads(x) for x in self.record.read_text().splitlines() if x.strip()]
        return [row["hook"] for row in rows if "hook" in row]

    def test_fake_claude_posts_and_obeys_allow_and_deny(self):
        stub = self.stub(lambda n: "allow")
        events, out, err = self.finish(self.start("ask_allowed", stub))
        self.assertEqual(len(stub.seen), 1)
        path, ctype, body = stub.seen[0]
        self.assertEqual(path, "/hook/managed/" + TOKEN)
        self.assertEqual(ctype, "application/json")
        payload = json.loads(body)
        self.assertEqual(payload["hook_event_name"], "PermissionRequest")
        self.assertEqual(payload["permission_mode"], "default")
        self.assertIn("SENTINEL_HOOK_INPUT", body.decode())
        kinds = [(e["type"], e.get("subtype")) for e in events]
        self.assertIn(("user", None), kinds)
        self.assertNotIn(("system", "permission_denied"), kinds)
        self.assertEqual(kinds[-1][0], "system")
        self.assertTrue(any(e["type"] == "result" and e["subtype"] == "success" for e in events))
        self.assertEqual(self.hook_records(), [{"scenario": "ask_allowed", "calls": 1, "told": ["allow"]}])

        stub2 = self.stub(lambda n: "deny")
        events, out, err = self.finish(self.start("ask_declined", stub2))
        kinds = [(e["type"], e.get("subtype")) for e in events]
        self.assertIn(("system", "permission_denied"), kinds)
        self.assertNotIn(("user", None), kinds)
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(sum(1 for e in events if e["type"] == "result"), 1)
        self.assertEqual(self.hook_records()[-1], {"scenario": "ask_declined", "calls": 1, "told": ["deny"]})

    def test_anything_but_the_exact_allow_reply_is_a_denial(self):
        for mode in ("500", "junk", "allowish", "deny"):
            stub = self.stub(lambda n, m=mode: m)
            events, out, err = self.finish(self.start("ask_allowed", stub))
            kinds = [(e["type"], e.get("subtype")) for e in events]
            self.assertIn(("system", "permission_denied"), kinds, mode)
            self.assertNotIn(("user", None), kinds, mode)
            self.assertEqual(self.hook_records()[-1]["told"], ["deny"], mode)

    def test_connection_error_and_timeout_are_denials(self):
        dead = self.stub(lambda n: "allow")
        dead.close()
        proc = self.start("ask_allowed", dead)
        events, _, _ = self.finish(proc)
        self.assertIn(("system", "permission_denied"), [(e["type"], e.get("subtype")) for e in events])
        self.assertEqual(self.hook_records()[-1]["told"], ["deny"])

    def test_ask_silent_times_out_at_the_hook_timeout_and_denies(self):
        stub = self.stub(lambda n: "silent")
        started = time.monotonic()
        events, out, err = self.finish(self.start("ask_silent", stub, timeout=2))
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 1.8)
        self.assertLess(elapsed, 10)
        self.assertIn(("system", "permission_denied"), [(e["type"], e.get("subtype")) for e in events])
        self.assertEqual(self.hook_records()[-1], {"scenario": "ask_silent", "calls": 1, "told": ["deny"]})

    def test_sigint_while_waiting_ends_the_run_promptly(self):
        stub = self.stub(lambda n: "silent")
        proc = self.start("ask_silent", stub, timeout=60)
        deadline = time.monotonic() + 10
        while not stub.seen and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(stub.seen)
        time.sleep(0.2)
        started = time.monotonic()
        proc.send_signal(signal.SIGINT)
        events, out, err = self.finish(proc, timeout=8)
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(any(e.get("subtype") == "task_notification" for e in events))

    def test_ask_two_posts_two_requests_concurrently_and_needs_both_allowed(self):
        barrier = threading.Barrier(2, timeout=5)
        seen_together = []

        def script(n):
            try:
                barrier.wait()
                seen_together.append(True)
            except threading.BrokenBarrierError:
                pass
            return "allow"

        stub = self.stub(script)
        events, out, err = self.finish(self.start("ask_two", stub))
        self.assertEqual(len(seen_together), 2)
        self.assertEqual(len(stub.seen), 2)
        self.assertEqual(len({json.loads(b)["tool_name"] + json.loads(b)["prompt_id"] for _, _, b in stub.seen}), 2)
        self.assertEqual(self.hook_records()[-1], {"scenario": "ask_two", "calls": 2, "told": ["allow", "allow"]})
        self.assertEqual(sum(1 for e in events if e["type"] == "user"), 2)

        stub2 = self.stub(lambda n: "allow" if n == 1 else "deny")
        events, _, _ = self.finish(self.start("ask_two", stub2))
        self.assertEqual(sorted(self.hook_records()[-1]["told"]), ["allow", "deny"])
        self.assertIn(("system", "permission_denied"), [(e["type"], e.get("subtype")) for e in events])

    def test_fake_never_prints_or_records_the_url_or_token(self):
        stub = self.stub(lambda n: "allow")
        _, out, err = self.finish(self.start("ask_allowed", stub))
        record = self.record.read_text()
        for text in (out, err, record):
            self.assertNotIn(TOKEN, text)
            self.assertNotIn("127.0.0.1", text)
            self.assertNotIn(str(stub.port), text)

    def test_bad_scenario_or_missing_settings_is_a_denial_not_a_crash(self):
        proc = subprocess.run([sys.executable, str(FAKE), "-p", "x"], capture_output=True, text=True, timeout=15,
                              env={"PATH": os.environ.get("PATH", ""), "FAKE_CLAUDE_FIXTURE": "success", "FAKE_CLAUDE_HOOK": "ask_allowed"})
        self.assertIn('"permission_denied"', proc.stdout)
        proc = subprocess.run([sys.executable, str(FAKE), "-p", "x"], capture_output=True, text=True, timeout=15,
                              env={"PATH": os.environ.get("PATH", ""), "FAKE_CLAUDE_FIXTURE": "success", "FAKE_CLAUDE_HOOK": "nope"})
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
