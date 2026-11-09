"""Observed sessions: Dashboard lifecycle and the /api/observed routes (Task 6).

Evidence kind: unit and loopback HTTP tests. The dashboard runs with a Claude backend that is never probed (no
``claude`` binary is started), the observed listener is bound to an ephemeral port, the install token lives in a
temporary folder (never the real home), and every hook payload is synthetic.
"""
from copy import deepcopy
import http.client
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from dashboard import server as server_module
from dashboard.backends import claude_hook
from dashboard.backends.base import NoBackend
from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_launch import http_hook_entry
from dashboard.observed_receiver import ObservedReceiver
from dashboard.server import DASHBOARD_KEY_HEADER, Dashboard
from dashboard.settings import SettingsStore
from tests.dashboard_key_harness import make_test_server
from tests.policy_fixtures import SyntheticPolicy

NOT_AVAILABLE = {"error": "not available for this provider"}
EVENTS = {"PermissionRequest", "PostToolUse", "Stop", "SessionEnd", "SubagentStart", "SubagentStop", "SessionStart"}
MAIN = "00000000-0000-4000-8000-00000000c001"
ALLOW = claude_hook.allow_reply()
DENY = claude_hook.deny_reply()
UNKNOWN_ID = "a" * 32
TOKEN_SHAPE = re.compile(r"/hook/observed/([A-Za-z0-9_-]+)")


def fake_scan(data):
    if b"sk-" in bytes(data):
        raise server_module.SensitiveContentError()


def until(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def hook_body(name, session=MAIN, cwd="/synthetic/projects/alpha", **extra):
    data = {"hook_event_name": name, "session_id": session, "cwd": cwd}
    data.update(extra)
    return json.dumps(data).encode()


def permission(command="echo synthetic", **extra):
    return hook_body("PermissionRequest", permission_mode="default", tool_name="Bash",
                     tool_input={"command": command}, **extra)


class Base(unittest.TestCase):
    backend_kind = "claude"

    def setUp(self):
        self.seen = []  # every dashboard response body, for the token scan
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(os.path.realpath(temp.name))  # macOS temp folders sit under a symlinked /var
        scanner = patch("dashboard.conversation.scan_preview", side_effect=fake_scan)
        scanner.start()
        self.addCleanup(scanner.stop)
        self.config = self.root / "config"
        self.receivers, self.threads = [], []
        self.addCleanup(self.check_clean)  # runs after the app is closed (cleanups run last-in, first-out)
        self.app = self.make_app()
        self.server = make_test_server(self.app, 0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.stop_server, thread)
        self.port = self.server.server_port

    def make_app(self):
        kwargs = {"backend": ClaudeBackend()} if self.backend_kind == "claude" else (
            {"backend": NoBackend()} if self.backend_kind == "none" else {})
        app = Dashboard(self.root / "state", policy_provider=SyntheticPolicy(), observed_config_dir=self.config,
                        observed_receiver_factory=self.receiver_factory, **kwargs)
        self.app_closed = False
        self.addCleanup(lambda: None if self.app_closed else app.close())
        app.settings = SettingsStore(self.root, config_path=self.root / "settings.toml")
        return app

    def close_app(self):
        self.app_closed = True
        self.app.close()

    def receiver_factory(self, *args, **kwargs):
        receiver = ObservedReceiver(*args, poll_interval=0.05, **kwargs)
        self.receivers.append(receiver)
        return receiver

    def stop_server(self, thread):
        self.server.shutdown()
        thread.join(3)
        self.server.server_close()

    def check_clean(self):
        for thread in self.threads:
            thread.join(5)
            self.assertFalse(thread.is_alive(), "a hook request was left waiting")
        for receiver in self.receivers:
            self.assertTrue(receiver._thread is None or not receiver._thread.is_alive(), "listener thread left")

    # ---- dashboard API -----------------------------------------------------------------------------
    def request(self, method, path, body=None, key=None, raw=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Origin": "http://127.0.0.1:" + str(self.port)}
        if key is not None:
            headers[DASHBOARD_KEY_HEADER] = key
        payload = None
        if body is not None or method == "POST":
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body if body is not None else {})
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        self.seen.append(data)
        if raw:
            return response, data
        return response.status, json.loads(data)

    # ---- observed listener -------------------------------------------------------------------------
    def hook(self, url, data):
        host, path = url.split("/", 3)[2], "/" + url.split("/", 3)[3]
        connection = http.client.HTTPConnection(host.split(":")[0], int(host.split(":")[1]), timeout=10)
        connection.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def async_hook(self, url, data):
        out = {}

        def run():
            try:
                out["reply"] = self.hook(url, data)
            except Exception as error:  # noqa: BLE001
                out["error"] = type(error).__name__
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.threads.append(thread)
        out["thread"] = thread
        return out

    def reply(self, out):
        out["thread"].join(10)
        self.assertFalse(out["thread"].is_alive(), "the hook request is still held")
        return out.get("reply")

    def started(self):
        self.app.start_observed(0)
        self.assertIsNotNone(self.app.observed_receiver)
        status, config = self.request("GET", "/api/observed/hook-config")
        self.assertEqual(200, status)
        return config["url"]

    def pending_cards(self):
        _, observed = self.request("GET", "/api/observed")
        return [card for card in observed["approvals"] if card["status"] == "pending"]

    def wait_pending(self, count=1):
        self.assertTrue(until(lambda: len(self.pending_cards()) >= count), "no pending observed approval")
        return self.pending_cards()

    def listening(self, port):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            return False


ROUTES = [("GET", "/api/observed", None), ("GET", "/api/observed/hook-config", None),
          ("POST", "/api/observed/rotate-token", {}),
          ("POST", "/api/observed/approvals/" + UNKNOWN_ID + "/allow", {}),
          ("POST", "/api/observed/approvals/" + UNKNOWN_ID + "/deny", {})]


class CodexDeploymentTests(Base):
    backend_kind = "codex"

    def test_codex_deployment_opens_no_listener_and_routes_409(self):
        self.app.start_observed(0)
        self.app.start_observed()
        self.assertEqual([], self.receivers)
        self.assertIsNone(self.app.observed_receiver)
        self.assertIsNone(self.app.observed_sessions)
        self.assertIsNone(self.app.observed_token_file)
        for method, path, body in ROUTES + [("POST", "/api/observed/rotate-token", {"unexpected": 1})]:
            with self.subTest(method=method, path=path):
                self.assertEqual((409, NOT_AVAILABLE), self.request(method, path, body))
        self.assertFalse(self.config.exists(), "a Codex deployment must not create the token folder")
        rows = self.app.store.db.execute("SELECT kind FROM records WHERE kind = 'observed_session'").fetchall()
        self.assertEqual([], rows)

    def test_routes_still_require_the_key_first(self):
        for method, path, body in ROUTES:
            with self.subTest(method=method, path=path):
                self.assertEqual(403, self.request(method, path, body, key="wrong")[0])


class NoProviderTests(Base):
    backend_kind = "none"

    def test_no_provider_deployment_routes_409(self):
        self.app.start_observed(0)
        self.assertEqual([], self.receivers)
        for method, path, body in ROUTES:
            with self.subTest(method=method, path=path):
                self.assertEqual((409, NOT_AVAILABLE), self.request(method, path, body))


class LifecycleTests(Base):
    def test_not_started_in_init(self):
        self.assertEqual([], self.receivers)
        self.assertIsNone(self.app.observed_receiver)
        self.assertFalse(self.config.exists())
        status, observed = self.request("GET", "/api/observed")
        self.assertEqual(200, status)
        self.assertEqual((False, None, None), (observed["enabled"], observed["reason"], observed["port"]))
        self.assertEqual([], observed["sessions"])
        status, refused = self.request("GET", "/api/observed/hook-config")
        self.assertEqual(409, status)
        self.assertNotIn("url", refused)
        self.assertIsNone(refused["reason"])

    def test_claude_deployment_listener_started_and_stopped_on_close(self):
        self.app.start_observed(0)
        receiver = self.app.observed_receiver
        self.assertEqual([receiver], self.receivers)
        port = receiver.port
        self.assertNotEqual(0, port)
        self.assertTrue(self.listening(port))
        self.app.start_observed(0)  # a second call keeps the running listener
        self.assertEqual([receiver], self.receivers)
        status, observed = self.request("GET", "/api/observed")
        self.assertEqual((200, True, None, port), (status, observed["enabled"], observed["reason"], observed["port"]))
        self.assertEqual({"sessions", "approvals", "refused", "limits", "enabled", "reason", "port"}, set(observed))
        self.close_app()
        self.assertIsNone(self.app.observed_receiver)
        self.assertFalse(self.listening(port))
        self.app.start_observed(0)  # never reopened once closing has begun
        self.assertEqual([receiver], self.receivers)

    def test_default_port_comes_from_the_observed_port_setting(self):
        holder = socket.socket()
        self.addCleanup(holder.close)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        config = self.app.settings.load()
        config["observed_port"] = port
        self.app.save_settings(config)
        self.app.start_observed()
        self.assertEqual(1, len(self.receivers))
        self.assertEqual(port, self.receivers[0].port)
        _, observed = self.request("GET", "/api/observed")
        self.assertEqual((False, "port_in_use", port), (observed["enabled"], observed["reason"], observed["port"]))

    def test_main_calls_start_observed_after_start(self):
        dashboard = MagicMock()
        http_server = MagicMock()
        owner = MagicMock()
        owner.__enter__.return_value = owner
        owner.__exit__.return_value = False
        with patch.object(sys, "argv", ["dashboard", "--provider", "claude"]), \
                patch.object(server_module, "RuntimeOwner", return_value=owner), \
                patch.object(server_module, "dashboard_for_provider", return_value=dashboard), \
                patch.object(server_module, "make_server", return_value=http_server), \
                patch.object(server_module.signal, "signal"), \
                patch.object(server_module.os, "umask"), \
                redirect_stdout(io.StringIO()):
            server_module.main()
        names = [call[0] for call in dashboard.mock_calls]
        self.assertEqual(["start", "start_observed", "close"], names)
        self.assertEqual((), dashboard.start_observed.call_args.args)
        self.assertEqual({}, dashboard.start_observed.call_args.kwargs)
        http_server.serve_forever.assert_called_once_with()


class FailureTests(Base):
    def test_port_in_use_dashboard_still_starts_and_reports_reason(self):
        holder = socket.socket()
        self.addCleanup(holder.close)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        self.app.start_observed(port)  # never raises
        self.assertIsNone(self.app.observed_receiver)
        status, observed = self.request("GET", "/api/observed")
        self.assertEqual((200, False, "port_in_use", port),
                         (status, observed["enabled"], observed["reason"], observed["port"]))
        self.assertEqual(200, self.request("GET", "/api/state")[0])
        status, refused = self.request("GET", "/api/observed/hook-config")
        self.assertEqual(409, status)
        self.assertEqual("port_in_use", refused["reason"])
        self.assertNotIn("url", refused)
        self.assertNotIn("snippet", refused)

    def test_token_permissions_and_unreadable_reported_never_raised(self):
        self.config.mkdir(mode=0o755)
        os.chmod(self.config, 0o755)
        self.app.start_observed(0)
        self.assertIsNone(self.app.observed_receiver)
        _, observed = self.request("GET", "/api/observed")
        self.assertEqual((False, "token_permissions"), (observed["enabled"], observed["reason"]))
        os.chmod(self.config, 0o700)
        (self.config / "observed-token").mkdir()  # not a regular file: unreadable
        self.app.start_observed(0)  # a failed start may be retried
        _, observed = self.request("GET", "/api/observed")
        self.assertEqual((False, "token_unreadable"), (observed["enabled"], observed["reason"]))
        status, refused = self.request("POST", "/api/observed/rotate-token", {})
        self.assertEqual((409, "token_unreadable"), (status, refused["reason"]))
        self.assertNotIn(str(self.config), json.dumps(refused))

    def test_any_os_error_is_recorded_not_raised(self):
        def broken(*_args, **_kwargs):
            raise OSError("synthetic")
        self.app.observed_receiver_factory = broken
        self.app.start_observed(0)
        self.assertIsNone(self.app.observed_receiver)
        self.assertEqual("port_in_use", self.request("GET", "/api/observed")[1]["reason"])

    def test_unreadable_settings_keep_the_listener_off(self):
        self.app.settings = MagicMock()
        self.app.settings.load.side_effect = server_module.SettingsError(500, "Settings file is invalid")
        self.app.start_observed()
        self.assertEqual([], self.receivers)
        self.assertIsNone(self.app.observed_receiver)
        self.assertEqual("settings_unavailable", self.app.observed_status()["reason"])


class HookConfigTests(Base):
    def test_hook_config_requires_key_and_contains_token_once(self):
        self.app.start_observed(0)
        token = self.app.observed_token_file.token()
        response, data = self.request("GET", "/api/observed/hook-config", key="wrong", raw=True)
        self.assertEqual(403, response.status)
        self.assertNotIn(token.encode(), data)
        response, data = self.request("GET", "/api/observed/hook-config", raw=True)
        self.assertEqual(200, response.status)
        self.assertEqual("no-store", response.getheader("Cache-Control"))
        config = json.loads(data)
        port = self.app.observed_receiver.port
        url = "http://127.0.0.1:%d/hook/observed/%s" % (port, token)
        self.assertEqual({"url", "snippet", "note"}, set(config))
        self.assertEqual(url, config["url"])
        # Exactly one token in the response: every hook URL carries the current token and no other.
        self.assertEqual({token}, set(TOKEN_SHAPE.findall(data.decode())))
        self.assertIsInstance(config["note"], str)
        self.assertNotIn(token, config["note"])
        wait = self.app.settings.load()["claude_approval_wait_seconds"]
        timeout = claude_hook.hook_timeout(wait)
        self.assertGreater(timeout, wait)
        self.assertEqual({"hooks"}, set(config["snippet"]))
        self.assertEqual(EVENTS, set(config["snippet"]["hooks"]))
        for event, entries in config["snippet"]["hooks"].items():
            with self.subTest(event=event):
                self.assertEqual([{"hooks": [{"type": "http", "url": url, "timeout": timeout}]}], entries)
                self.assertEqual(http_hook_entry(url, timeout), entries)
        # The URL works: an event posted to it is recorded.
        self.assertEqual((200, b"{}"), self.hook(url, hook_body("SessionEnd")))
        _, observed = self.request("GET", "/api/observed")
        self.assertEqual([(MAIN, "alpha", "ended")], [(s["id"], s["project"], s["status"]) for s in observed["sessions"]])

    def test_rotate_changes_hook_config_token(self):
        old_url = self.started()
        old_token = old_url.rsplit("/", 1)[1]
        held = self.async_hook(old_url, permission())  # checked against the old token before the rotation
        card = self.wait_pending()[0]
        response, data = self.request("POST", "/api/observed/rotate-token", {}, raw=True)
        self.assertEqual((200, {"rotated": True}), (response.status, json.loads(data)))
        new_token = self.app.observed_token_file.token()
        self.assertNotEqual(old_token, new_token)
        self.assertNotIn(new_token.encode(), data)
        self.assertNotIn(old_token.encode(), data)
        self.assertEqual(200, self.request("POST", "/api/observed/approvals/%s/allow" % card["id"], {})[0])
        self.assertEqual((200, ALLOW), self.reply(held))
        new_url = self.request("GET", "/api/observed/hook-config")[1]["url"]
        self.assertEqual(new_token, new_url.rsplit("/", 1)[1])
        self.assertEqual(404, self.hook(old_url, hook_body("Stop"))[0])
        self.assertEqual((200, b"{}"), self.hook(new_url, hook_body("Stop")))
        self.assertEqual(400, self.request("POST", "/api/observed/rotate-token", {"unexpected": 1})[0])


class ApprovalTests(Base):
    def test_allow_deny_closed_unknown_status_codes(self):
        url = self.started()
        first = self.async_hook(url, permission("echo first"))
        card = self.wait_pending()[0]
        self.assertRegex(card["id"], r"\A[0-9a-f]{32}\Z")
        self.assertEqual((200, {"result": "ok"}),
                         self.request("POST", "/api/observed/approvals/%s/allow" % card["id"], {}))
        self.assertEqual((200, ALLOW), self.reply(first))
        self.assertEqual((409, {"result": "closed"}),
                         self.request("POST", "/api/observed/approvals/%s/deny" % card["id"], {}))
        self.assertEqual((404, {"result": "unknown"}),
                         self.request("POST", "/api/observed/approvals/%s/allow" % UNKNOWN_ID, {}))
        second = self.async_hook(url, permission("echo second"))
        card = self.wait_pending()[0]
        self.assertEqual(400, self.request("POST", "/api/observed/approvals/%s/deny" % card["id"],
                                           {"unexpected": 1})[0])
        self.assertEqual((200, {"result": "ok"}),
                         self.request("POST", "/api/observed/approvals/%s/deny" % card["id"], {}))
        self.assertEqual((200, DENY), self.reply(second))
        self.assertEqual(404, self.request("POST", "/api/observed/approvals/not-an-id/allow", {})[0])
        self.assertEqual(404, self.request("POST", "/api/observed/approvals/%s/maybe" % UNKNOWN_ID, {})[0])
        _, observed = self.request("GET", "/api/observed")
        self.assertEqual(["deny", "allow"], [c["decision"] for c in observed["approvals"]])

    def test_observed_approvals_not_in_state_approvals_and_never_automatic(self):
        project_dir = self.root / "alpha"
        project_dir.mkdir()
        project = self.app.add_project({"name": "alpha", "path": str(project_dir)})
        config = self.app.settings.load()
        config["project_approval_modes"] = {project["id"]: "automatic"}
        self.app.save_settings(config)
        url = self.started()
        held = self.async_hook(url, hook_body("PermissionRequest", cwd=str(project_dir), permission_mode="default",
                                              tool_name="Bash", tool_input={"command": "echo synthetic"}))
        card = self.wait_pending()[0]
        time.sleep(0.5)  # an automatic decision, if any existed, would have been taken by now
        self.assertEqual("pending", [c for c in self.pending_cards() if c["id"] == card["id"]][0]["status"])
        self.assertTrue(held["thread"].is_alive(), "the observed request must stay held for the owner")
        _, state = self.request("GET", "/api/state")
        self.assertEqual([], state["approvals"])
        self.assertNotIn(card["id"], json.dumps(state))
        self.assertEqual({}, self.app.approvals)
        self.assertEqual({}, self.app.pending)
        self.assertEqual(200, self.request("POST", "/api/observed/approvals/%s/deny" % card["id"], {})[0])
        self.assertEqual((200, DENY), self.reply(held))

    def test_observed_does_not_touch_managed_state(self):
        def managed():
            rows = self.app.store.db.execute(
                "SELECT kind, id, body FROM records WHERE kind != 'observed_session' ORDER BY kind, id").fetchall()
            return {"rows": rows, "approvals": deepcopy(self.app.approvals), "pending": dict(self.app.pending),
                    "tasks": deepcopy(self.app.tasks), "runs": dict(self.app.runs),
                    "hook_runs": dict(self.app.hook_runs), "hook_receiver": self.app.hook_receiver}
        before = managed()
        url = self.started()
        self.assertEqual((200, b"{}"), self.hook(url, hook_body("SubagentStart", agent_id="agent-1")))
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        self.assertEqual(200, self.request("POST", "/api/observed/approvals/%s/allow" % card["id"], {})[0])
        self.assertEqual((200, ALLOW), self.reply(held))
        self.assertEqual((200, b"{}"), self.hook(url, hook_body("PostToolUse", tool_name="Bash",
                                                                tool_input={"command": "echo synthetic"})))
        self.request("POST", "/api/observed/rotate-token", {})
        self.assertEqual(before, managed())
        self.assertIsNone(self.app.hook_receiver)
        rows = self.app.store.db.execute("SELECT id FROM records WHERE kind = 'observed_session'").fetchall()
        self.assertEqual([(MAIN,)], rows)


class TokenLeakTests(Base):
    def test_snapshot_and_listing_never_contain_token(self):
        url = self.started()
        token = self.app.observed_token_file.token()
        self.assertEqual((200, b"{}"), self.hook(url, hook_body("SessionStart")))
        held = self.async_hook(url, permission())
        card = self.wait_pending()[0]
        self.seen.clear()
        for path in ("/api/state", "/api/observed", "/api/team", "/api/config", "/api/provider"):
            with self.subTest(path=path):
                self.assertEqual(200, self.request("GET", path)[0])
        # Refusals of every kind.
        self.assertEqual(403, self.request("GET", "/api/observed/hook-config", key="wrong")[0])
        self.assertEqual(403, self.request("GET", "/api/observed", key="wrong")[0])
        self.assertEqual(403, self.request("POST", "/api/observed/rotate-token", {}, key="wrong")[0])
        self.assertEqual(404, self.request("POST", "/api/observed/approvals/%s/allow" % UNKNOWN_ID, {})[0])
        self.assertEqual(400, self.request("POST", "/api/observed/approvals/%s/allow" % card["id"], {"x": 1})[0])
        self.assertEqual(400, self.request("POST", "/api/observed/rotate-token", {"x": 1})[0])
        self.assertEqual(404, self.request("GET", "/api/observed/rotate-token")[0])
        self.assertEqual(405, self.request("DELETE", "/api/observed")[0])
        self.assertEqual(200, self.request("POST", "/api/observed/approvals/%s/allow" % card["id"], {})[0])
        self.assertEqual((200, ALLOW), self.reply(held))
        self.assertEqual(409, self.request("POST", "/api/observed/approvals/%s/deny" % card["id"], {})[0])
        self.assertGreaterEqual(len(self.seen), 14)
        for body in self.seen:
            self.assertNotIn(token.encode(), body)
        # The off state's refusal carries no token either.
        self.close_app()
        status, refused = self.request("GET", "/api/observed/hook-config")
        self.assertEqual(409, status)
        self.assertNotIn(token, json.dumps(refused))


if __name__ == "__main__":
    unittest.main()
