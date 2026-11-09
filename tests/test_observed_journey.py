"""Observed sessions: end-to-end journeys through the HTTP API (Task 8).

Evidence kind: fake-binary journey tests. Real loopback HTTP to both the dashboard API (``make_test_server``) and the
observed listener (``Dashboard.start_observed(0)``); no ``claude`` binary is started. Each journey follows the owner's
path: read the hook URL from ``/api/observed/hook-config``, post hook events to it as Claude Code would, read
``/api/observed`` and answer with ``POST /api/observed/approvals/<id>/allow|deny``. The install token lives in a
temporary folder (never the real home), every hook payload is synthetic, and credential-shaped values are built at
runtime and are obviously fake.

Spec: docs/superpowers/specs/2026-11-06-claude-observed-sessions-design.md (5.1 never block the terminal, 5.2 two-way
record of decisions).
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from dashboard import server as server_module
from dashboard.backends import claude_hook
from dashboard.backends.claude import ClaudeBackend
from dashboard.observed_receiver import ObservedReceiver
from dashboard.server import Dashboard
from dashboard.settings import SettingsStore
from tests.dashboard_key_harness import make_test_server
from tests.policy_fixtures import SyntheticPolicy

ALLOW = claude_hook.allow_reply()
DENY = claude_hook.deny_reply()
NO_DECISION = (200, b"{}")
MAIN = "00000000-0000-4000-8000-00000000d001"
OTHER = "00000000-0000-4000-8000-00000000d002"
INFERRED = "terminal (inferred)"
NOT_AVAILABLE = {"error": "not available for this provider"}
UNKNOWN_ID = "b" * 32
# Credential-shaped, obviously fake, built at runtime.
FAKE_KEY = "sk-" + "y" * 32
MARKER = b"sk-"


def fake_scan(data):
    """Stand-in for the reviewed scanner: refuses anything holding the fake credential prefix."""
    if MARKER in bytes(data):
        raise server_module.SensitiveContentError()


def until(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def hook_body(name, session=MAIN, cwd="/synthetic/projects/alpha", **extra):
    data = {"hook_event_name": name, "session_id": session}
    if cwd is not None:
        data["cwd"] = cwd
    data.update(extra)
    return json.dumps(data).encode()


def permission(command="echo synthetic", session=MAIN, **extra):
    return hook_body("PermissionRequest", session=session, permission_mode="default", tool_name="Bash",
                     tool_input={"command": command}, **extra)


def post_tool_use(command="echo synthetic", session=MAIN, **extra):
    return hook_body("PostToolUse", session=session, tool_name="Bash", tool_input={"command": command}, **extra)


class Journey(unittest.TestCase):
    """One owner at a time: boot() opens a Claude dashboard with its API server and observed listener."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(os.path.realpath(temp.name))  # macOS temp folders sit under a symlinked /var
        scanner = patch("dashboard.conversation.scan_preview", side_effect=fake_scan)
        scanner.start()
        self.addCleanup(scanner.stop)
        self.config = self.root / "config"
        self.state = self.root / "state"
        self.receivers, self.threads, self.seen = [], [], []
        self.wait = None  # None keeps the settings wait; a number shortens the hold for expiry journeys
        self.app = self.server = None
        self.addCleanup(self.check_clean)

    # ---- dashboard -----------------------------------------------------------------------------------
    def boot(self, wait=None, backend="claude", start=True):
        self.wait = wait
        kwargs = {"backend": ClaudeBackend()} if backend == "claude" else {}
        app = Dashboard(self.state, policy_provider=SyntheticPolicy(), observed_config_dir=self.config,
                        observed_receiver_factory=self.receiver_factory, **kwargs)
        app.settings = SettingsStore(self.root, config_path=self.root / "settings.toml")
        closed = {"done": False}

        def close():
            if not closed["done"]:
                closed["done"] = True
                app.close()
        app.close_once = close
        self.addCleanup(close)
        server = make_test_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop_server():
            server.shutdown()
            thread.join(3)
            server.server_close()
        self.addCleanup(stop_server)
        self.app, self.server, self.port = app, server, server.server_port
        if start and backend == "claude":
            app.start_observed(0)
            self.assertIsNotNone(app.observed_receiver, "the observed listener did not start")
        return app

    def receiver_factory(self, *args, **kwargs):
        if self.wait is not None:
            kwargs["wait_seconds"] = self.wait
        receiver = ObservedReceiver(*args, poll_interval=0.05, **kwargs)
        self.receivers.append(receiver)
        return receiver

    def check_clean(self):
        for thread in self.threads:
            thread.join(5)
            self.assertFalse(thread.is_alive(), "a hook request was left waiting")
        for receiver in self.receivers:
            self.assertTrue(receiver._thread is None or not receiver._thread.is_alive(), "listener thread left")

    def api(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Origin": "http://127.0.0.1:" + str(self.port)}
        payload = None
        if body is not None or method == "POST":
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body if body is not None else {})
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        self.seen.append(data)
        return response.status, json.loads(data)

    def hook_url(self):
        status, config = self.api("GET", "/api/observed/hook-config")
        self.assertEqual(200, status)
        return config["url"]

    def observed(self):
        status, body = self.api("GET", "/api/observed")
        self.assertEqual(200, status)
        return body

    def card(self, approval_id):
        found = [c for c in self.observed()["approvals"] if c["id"] == approval_id]
        self.assertEqual(1, len(found), "card not listed")
        return found[0]

    def pending_cards(self):
        return [c for c in self.observed()["approvals"] if c["status"] == "pending"]

    def wait_pending(self, count=1, seconds=5.0):
        self.assertTrue(until(lambda: len(self.pending_cards()) >= count, seconds), "no pending observed approval")
        return self.pending_cards()

    def answer(self, approval_id, decision):
        return self.api("POST", "/api/observed/approvals/%s/%s" % (approval_id, decision), {})

    # ---- observed listener (as Claude Code's http hook would call it) ---------------------------------
    @staticmethod
    def split(url):
        match = re.match(r"http://127\.0\.0\.1:(\d+)(/.*)\Z", url)
        return int(match.group(1)), match.group(2)

    def hook(self, url, data, timeout=10):
        port, path = self.split(url)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        connection.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def async_hook(self, url, data):
        out = {}

        def run():
            try:
                out["reply"] = self.hook(url, data, timeout=30)
            except Exception as error:  # noqa: BLE001
                out["error"] = type(error).__name__
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.threads.append(thread)
        out["thread"] = thread
        return out

    def reply(self, out, seconds=10):
        out["thread"].join(seconds)
        self.assertFalse(out["thread"].is_alive(), "the hook request is still held")
        self.assertNotIn("error", out)
        return out.get("reply")

    def raw_hook(self, url, data):
        """A held request whose socket the test closes itself (the terminal answered and Claude hung up)."""
        port, path = self.split(url)
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                      "Content-Length: %d\r\n\r\n" % (path, port, len(data))).encode() + data)
        return sock

    def stored(self):
        return self.app.store.db.execute(
            "SELECT id, body FROM records WHERE kind = 'observed_session' ORDER BY id").fetchall()


class OwnerJourneys(Journey):
    def test_owner_journey_end_to_end(self):
        self.boot()
        url = self.hook_url()  # the install token, as pasted into Claude Code's settings
        self.assertEqual([], self.observed()["sessions"])
        # The first event of the session is a PermissionRequest: no SessionStart is relied on.
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        observed = self.observed()
        self.assertEqual([(MAIN, "alpha", "active")],
                         [(s["id"], s["project"], s["status"]) for s in observed["sessions"]])
        self.assertEqual((MAIN, "alpha", "Bash", "pending", None, None, "unknown"),
                         (card["session_id"], card["project"], card["tool_name"], card["status"],
                          card["decided_by"], card["decision"], card["outcome"]))
        self.assertEqual('{"command":"echo synthetic"}', card["summary"])
        self.assertTrue(held["thread"].is_alive(), "the hook must be held until the owner answers")
        # Allow from the dashboard: the terminal gets the allow reply on the held connection.
        self.assertEqual((200, {"result": "ok"}), self.answer(card["id"], "allow"))
        self.assertEqual((200, ALLOW), self.reply(held))
        done = self.card(card["id"])
        self.assertEqual(("answered", "dashboard", "allow"), (done["status"], done["decided_by"], done["decision"]))
        self.assertIsNotNone(done["decided_at"])
        self.assertEqual(["active"], [s["status"] for s in self.observed()["sessions"]])
        # The call ran: the matching PostToolUse confirms it, the session stays active.
        self.assertEqual(NO_DECISION, self.hook(url, post_tool_use()))
        self.assertEqual("ran", self.card(card["id"])["outcome"])
        self.assertIsNone(self.card(card["id"])["warning"])
        self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], "deny"))
        # The session ends when Claude Code says so.
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("SessionEnd")))
        self.assertEqual(["ended"], [s["status"] for s in self.observed()["sessions"]])
        self.assertEqual([MAIN], [row[0] for row in self.stored()])

    def test_deny_journey(self):
        self.boot()
        url = self.hook_url()
        held = self.async_hook(url, permission("echo deny-me"))
        card = self.wait_pending()[0]
        self.assertEqual((200, {"result": "ok"}), self.answer(card["id"], "deny"))
        self.assertEqual((200, DENY), self.reply(held))
        done = self.card(card["id"])
        self.assertEqual(("answered", "dashboard", "deny", "unknown"),
                         (done["status"], done["decided_by"], done["decision"], done["outcome"]))
        self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], "allow"))
        # Claude refused the call and the agent moved on: the outcome is recorded, no warning.
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("Stop")))
        done = self.card(card["id"])
        self.assertEqual(("answered", "deny", "not run"), (done["status"], done["decision"], done["outcome"]))
        self.assertIsNone(done["warning"])


class TwoWayRecordJourneys(Journey):
    """Spec 5.2: the terminal's answer is inferred from later events; inference never answers the held hook."""

    def test_terminal_yes_then_post_tool_use_closes_card_ran(self):
        self.boot()
        url = self.hook_url()
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        # The owner pressed Yes in the terminal; the tool ran and Claude Code posts its PostToolUse.
        self.assertEqual(NO_DECISION, self.hook(url, post_tool_use()))
        done = self.card(card["id"])
        self.assertEqual(("closed", INFERRED, "ran", None),
                         (done["status"], done["decided_by"], done["outcome"], done["decision"]))
        self.assertIsNotNone(done["decided_at"])
        self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], "deny"))
        self.assertTrue(held["thread"].is_alive(), "inference must not answer the held hook")
        self.app.close_once()
        self.assertEqual(NO_DECISION, self.reply(held))  # never an allow or deny on the terminal's behalf
        self.assertEqual(("closed", INFERRED, "ran"),
                         tuple(self.card(card["id"])[k] for k in ("status", "decided_by", "outcome")))

    def test_terminal_no_then_stop_closes_card_not_run(self):
        self.boot()
        url = self.hook_url()
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        # The owner pressed No in the terminal; the agent stops without running the tool.
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("Stop")))
        done = self.card(card["id"])
        self.assertEqual(("closed", INFERRED, "not run", None),
                         (done["status"], done["decided_by"], done["outcome"], done["decision"]))
        self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], "allow"))
        # A late, matching PostToolUse does not rewrite a settled outcome.
        self.assertEqual(NO_DECISION, self.hook(url, post_tool_use()))
        self.assertEqual("not run", self.card(card["id"])["outcome"])
        self.app.close_once()
        self.assertEqual(NO_DECISION, self.reply(held))

    def test_dashboard_deny_then_post_tool_use_warns(self):
        self.boot()
        url = self.hook_url()
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        self.assertEqual((200, {"result": "ok"}), self.answer(card["id"], "deny"))
        self.assertEqual((200, DENY), self.reply(held))
        # The call ran anyway (the terminal overrode the dashboard): the card says so.
        self.assertEqual(NO_DECISION, self.hook(url, post_tool_use()))
        done = self.card(card["id"])
        self.assertEqual(("answered", "dashboard", "deny", "ran", "ran although denied here"),
                         (done["status"], done["decided_by"], done["decision"], done["outcome"], done["warning"]))

    def test_terminal_answered_first_then_dashboard_answer_is_closed(self):
        self.boot()
        url = self.hook_url()
        sock = self.raw_hook(url, permission())
        card = self.wait_pending()[0]
        sock.close()  # the owner answered in the terminal and Claude Code hung up on the hook
        self.assertTrue(until(lambda: self.card(card["id"])["status"] == "closed"), "card not closed")
        done = self.card(card["id"])
        self.assertEqual(("unknown", None, "unknown"), (done["decided_by"], done["decision"], done["outcome"]))
        for decision in ("allow", "deny"):
            self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], decision))
        self.assertEqual("closed", self.card(card["id"])["status"])
        self.assertTrue(until(lambda: not self.receivers[-1]._holds), "the hold was not released")

    def test_hook_timeout_then_answer_is_closed(self):
        self.boot(wait=0.4)
        url = self.hook_url()
        started = time.monotonic()
        self.assertEqual(NO_DECISION, self.hook(url, permission()))  # expiry: no decision, never deny
        self.assertLess(time.monotonic() - started, 5)
        card = self.observed()["approvals"][0]
        self.assertEqual(("closed", "timed out", None), (card["status"], card["decided_by"], card["decision"]))
        for decision in ("allow", "deny"):
            self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], decision))
        # The terminal's later answer is still recorded by inference.
        self.assertEqual(NO_DECISION, self.hook(url, post_tool_use()))
        self.assertEqual(("closed", INFERRED, "ran"),
                         tuple(self.card(card["id"])[k] for k in ("status", "decided_by", "outcome")))


class NeverBlockJourneys(Journey):
    """Spec 5.1: every ending that is not the owner's Allow or Deny replies 200 {}."""

    def test_terminal_never_denied_by_dashboard_on_expiry_cap_or_stop(self):
        replies = []
        # Expiry.
        self.boot(wait=0.4)
        url = self.hook_url()
        replies.append(self.hook(url, permission("echo expiry")))
        expired = self.observed()["approvals"][0]
        self.assertEqual(("closed", "timed out", None),
                         (expired["status"], expired["decided_by"], expired["decision"]))
        self.app.close_once()
        # The pending cap: 32 held, the 33rd is refused at once with no decision.
        self.boot(wait=60)
        url = self.hook_url()
        held = [self.async_hook(url, permission("echo held %d" % n, session=MAIN if n % 2 else OTHER))
                for n in range(32)]
        cards = self.wait_pending(32, seconds=15)
        self.assertEqual(32, len(cards))
        started = time.monotonic()
        replies.append(self.hook(url, permission("echo over the cap")))
        self.assertLess(time.monotonic() - started, 3, "a request over the cap must not be held")
        observed = self.observed()
        self.assertEqual(1, observed["refused"])
        self.assertEqual(32, len(observed["approvals"]))
        self.assertTrue(all(out["thread"].is_alive() for out in held))
        # The dashboard stops: every held request gets no decision.
        self.app.close_once()
        replies.extend(self.reply(out) for out in held)
        self.assertEqual(34, len(replies))
        for reply in replies:
            self.assertEqual(NO_DECISION, reply)
            self.assertNotIn(b"decision", reply[1])
        observed = self.observed()  # the API still answers after close; the listener is off
        self.assertFalse(observed["enabled"])
        for card in observed["approvals"]:
            self.assertEqual(("closed", None), (card["status"], card["decision"]))
            self.assertEqual((409, {"result": "closed"}), self.answer(card["id"], "allow"))


class BoundsAndSecrets(Journey):
    def test_flood_of_sessions_is_bounded(self):
        self.boot()
        url = self.hook_url()
        ids = ["00000000-0000-4000-8000-%012d" % n for n in range(1000)]
        names = ("SessionStart", "Stop", "PostToolUse", "SubagentStop", "SessionEnd")
        for n, session in enumerate(ids):
            self.assertEqual(NO_DECISION, self.hook(url, hook_body(names[n % len(names)], session=session)))
        observed = self.observed()
        limit = observed["limits"]["max_sessions"]
        self.assertEqual(256, limit)
        self.assertEqual(limit, len(observed["sessions"]))
        self.assertIn(ids[-1], {s["id"] for s in observed["sessions"]})
        self.assertEqual({s["id"] for s in observed["sessions"]}, {row[0] for row in self.stored()})
        # The listener still works after the flood and a held request still reaches the owner.
        held = self.async_hook(url, permission(session=ids[-1]))
        card = self.wait_pending()[0]
        self.assertEqual((200, {"result": "ok"}), self.answer(card["id"], "allow"))
        self.assertEqual((200, ALLOW), self.reply(held))
        self.assertEqual(limit, len(self.observed()["sessions"]))

    def test_credentials_in_cwd_and_tool_input_never_exposed(self):
        self.boot()
        url = self.hook_url()
        secret_cwd = "/synthetic/" + FAKE_KEY + "/project"
        secret_dir = "/synthetic/projects/" + FAKE_KEY
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("SessionStart", cwd=secret_dir)))
        held = self.async_hook(url, permission("curl -H 'Authorization: " + FAKE_KEY + "'", session=OTHER,
                                               cwd=secret_cwd))
        self.wait_pending()
        # A credential-shaped session id is recorded under an opaque stable id.
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("Stop", session=FAKE_KEY, cwd=secret_cwd)))
        self.assertEqual(NO_DECISION, self.hook(url, post_tool_use("echo " + FAKE_KEY, session=OTHER)))
        observed = self.observed()
        projects = {s["id"]: s["project"] for s in observed["sessions"]}
        self.assertEqual("unknown", projects[MAIN])
        self.assertEqual("project", projects[OTHER])  # only the final segment is kept: the path never is
        opaque = "s-" + hashlib.sha256(FAKE_KEY.encode()).hexdigest()[:12]
        self.assertEqual({MAIN, OTHER, opaque}, set(projects))
        card = [c for c in observed["approvals"] if c["session_id"] == OTHER][0]
        self.assertEqual(("withheld", "project"), (card["summary"], card["project"]))
        self.assertEqual((200, {"result": "ok"}), self.answer(card["id"], "deny"))
        self.assertEqual((200, DENY), self.reply(held))
        for path in ("/api/observed", "/api/state"):
            self.assertEqual(200, self.api("GET", path)[0])
        for body in self.seen:
            self.assertNotIn(MARKER, body)
            self.assertNotIn(b"curl", body)
            self.assertNotIn(b"/synthetic", body)
        rows = json.dumps(self.stored())
        self.assertNotIn(MARKER.decode(), rows)
        self.assertNotIn("/synthetic", rows)


class RestartAndSeparation(Journey):
    def test_restart_keeps_sessions_but_no_pending_cards(self):
        self.boot()
        url = self.hook_url()
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("SessionStart")))
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("SessionEnd", session=OTHER)))
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        self.app.close_once()
        self.assertEqual(NO_DECISION, self.reply(held))
        # A new dashboard on the same state and config folders.
        self.boot()
        observed = self.observed()
        self.assertEqual({(MAIN, "alpha", "active"), (OTHER, "alpha", "ended")},
                         {(s["id"], s["project"], s["status"]) for s in observed["sessions"]})
        self.assertEqual([], observed["approvals"])
        self.assertEqual((404, {"result": "unknown"}), self.answer(card["id"], "allow"))
        new_url = self.hook_url()
        self.assertEqual(url.rsplit("/", 1)[1], new_url.rsplit("/", 1)[1], "the install token survives a restart")
        # The session carries on where it left off.
        held = self.async_hook(new_url, permission())
        card = self.wait_pending()[0]
        self.assertEqual((200, {"result": "ok"}), self.answer(card["id"], "allow"))
        self.assertEqual((200, ALLOW), self.reply(held))

    def test_managed_and_observed_tokens_do_not_cross(self):
        app = self.boot()
        url = self.hook_url()
        install_token = url.rsplit("/", 1)[1]
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("SessionStart")))
        # A real managed run: the dashboard's own receiver writes the run settings file with its token.
        prepared = app._prepare_run_hook("synthetic-task")
        self.addCleanup(app._release_run_hook, prepared)
        settings = json.loads(Path(prepared["path"]).read_text())
        managed_url = settings["hooks"]["PermissionRequest"][0]["hooks"][0]["url"]
        managed_port, managed_path = self.split(managed_url)
        run_token = managed_path.rsplit("/", 1)[1]
        self.assertNotEqual(install_token, run_token)
        observed_port = self.split(url)[0]
        before_observed = self.observed()
        before_managed = (dict(app.hook_runs), dict(app.approvals), dict(app.pending))
        # The run token on the observed listener: bare 404 on either path, nothing recorded.
        for path in ("/hook/observed/" + run_token, "/hook/managed/" + run_token):
            self.assertEqual((404, b""), self.hook("http://127.0.0.1:%d%s" % (observed_port, path), permission()))
        # The install token on the managed listener: refused (deny, no callback), never held.
        self.assertEqual((200, DENY), self.hook("http://127.0.0.1:%d/hook/managed/%s" % (managed_port, install_token),
                                                permission()))
        self.assertEqual((404, b""), self.hook("http://127.0.0.1:%d/hook/observed/%s" % (managed_port, install_token),
                                               permission()))
        self.assertEqual(before_observed, self.observed())
        self.assertEqual(before_managed, (dict(app.hook_runs), dict(app.approvals), dict(app.pending)))
        self.assertEqual({}, app.hook_receiver._pending)
        # Each token still works on its own listener.
        self.assertEqual(NO_DECISION, self.hook(url, hook_body("Stop")))

    def test_codex_deployment_has_no_listener_and_routes_409(self):
        app = self.boot(backend="codex")
        app.start_observed(0)
        app.start_observed()
        self.assertEqual([], self.receivers)
        self.assertIsNone(app.observed_receiver)
        routes = [("GET", "/api/observed", None), ("GET", "/api/observed/hook-config", None),
                  ("POST", "/api/observed/rotate-token", {}),
                  ("POST", "/api/observed/approvals/%s/allow" % UNKNOWN_ID, {}),
                  ("POST", "/api/observed/approvals/%s/deny" % UNKNOWN_ID, {})]
        for method, path, body in routes:
            with self.subTest(path=path, method=method):
                self.assertEqual((409, NOT_AVAILABLE), self.api(method, path, body))
        self.assertFalse(self.config.exists(), "a Codex deployment must not create the token folder")
        self.assertEqual([], self.stored())


if __name__ == "__main__":
    unittest.main()
