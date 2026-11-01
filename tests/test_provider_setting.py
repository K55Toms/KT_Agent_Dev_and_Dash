"""Start-up provider setting: exact-name resolution that fails closed (Review Focus 1 and 2)."""
from tests.policy_fixtures import SyntheticPolicy
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from dashboard import backends
from dashboard.backends.base import NO, UNCONFIRMED, NoBackend, ProviderUnavailable
from dashboard.backends.claude import ClaudeBackendStub
from dashboard.backends.codex import CODEX_CAPABILITIES, CodexBackend
from dashboard import server
from dashboard.codex_client import CodexClient
from dashboard.server import Dashboard, dashboard_for_provider, make_server
from tests.test_dashboard_acceptance import ManagedRunFixture
from tests.test_dashboard_backend import FakeClient

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_dashboard.sh"
USAGE = "Usage: sh scripts/run_dashboard.sh codex|claude\n"
TASK = {"title": "Implement feature", "instruction": "SYNTHETIC_PRIVATE_TASK_INSTRUCTION",
        "role": "backend_developer"}


class RecordingFactory:
    def __init__(self):
        self.calls = []
        self.clients = []

    def __call__(self, message, disconnect):
        self.calls.append((message, disconnect))
        client = ManagedRunFixture(message, disconnect)
        self.clients.append(client)
        return client


class SpawnRecordingFactory:
    """Builds real CodexClients whose process_factory records the spawn argv and refuses to start it.

    Patching subprocess.Popen cannot observe CodexClient, which binds Popen as a default argument
    at definition time; this recorder is the process factory those clients would actually call.
    """
    def __init__(self):
        self.calls = []
        self.spawns = []

    def spawn(self, argv, **kwargs):
        self.spawns.append(list(argv))
        raise OSError("spawn refused in tests")

    def __call__(self, message, disconnect):
        self.calls.append((message, disconnect))
        return CodexClient(message, disconnect, process_factory=self.spawn)


class MainAborted(Exception):
    pass


class ProviderSettingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            app.close()
        self.temp.cleanup()

    def dashboard(self, **kwargs):
        app = Dashboard(self.root / "state", policy_provider=SyntheticPolicy(), **kwargs)
        self.apps.append(app)
        return app

    def request(self, app, path):
        server = make_server(app, 0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            port = server.server_port
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", path, headers={"Origin": f"http://127.0.0.1:{port}"})
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response.status, json.loads(body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_resolve_exact_names_only(self):
        get_client = object
        self.assertIsInstance(backends.resolve("codex", get_client), CodexBackend)
        self.assertIsInstance(backends.resolve("claude", get_client), ClaudeBackendStub)
        for name in (None, "", "Codex", "CLAUDE", "codex ", " claude", "claude2", "none", "codex\n"):
            with self.subTest(name=name):
                self.assertIsInstance(backends.resolve(name, get_client), NoBackend)

    def test_resolved_codex_backend_follows_the_given_client(self):
        holder = {"client": None}
        backend = backends.resolve("codex", lambda: holder["client"])
        fake = FakeClient()
        holder["client"] = fake
        backend.list_models()
        self.assertEqual("model/list", fake.requests[0][0])

    def test_claude_stub_capabilities_and_methods(self):
        stub = ClaudeBackendStub()
        self.assertEqual({"provider": "claude", "guidance_while_running": NO, "subagent_questions": NO,
                          "plan": UNCONFIRMED, "recovery": NO, "assessment": NO, "approval_alternative": NO},
                         stub.capabilities.public())
        for name, call in {"translate": lambda: stub.translate({}), "list_models": lambda: stub.list_models(),
                           "start_thread": lambda: stub.start_thread({}), "start_turn": lambda: stub.start_turn({}),
                           "steer": lambda: stub.steer({}), "interrupt": lambda: stub.interrupt("t", "u"),
                           "answer_approval": lambda: stub.answer_approval(None, "accept")}.items():
            with self.subTest(method=name):
                with self.assertRaisesRegex(ProviderUnavailable, "Claude backend is not implemented yet"):
                    call()

    def test_provider_unavailable_is_a_validation_error(self):
        self.assertTrue(issubclass(ProviderUnavailable, ValueError))

    def test_no_backend_dashboard_starts_no_connection(self):
        factory = SpawnRecordingFactory()
        app = self.dashboard(client_factory=factory, backend=NoBackend())
        app.start()
        time.sleep(0.05)
        self.assertEqual([], factory.calls)
        self.assertEqual([], factory.spawns)
        self.assertIsNone(app.client)
        self.assertFalse(hasattr(app, "connector"))
        self.assertEqual("disabled", app.connection["status"])
        self.assertEqual("No provider configured.", app.connection["detail"])
        self.assertEqual({"status", "detail", "last_event_at", "server_version"}, set(app.connection))
        self.assertEqual("disabled", app.snapshot()["connection"]["status"])

    def test_spawn_recorder_sees_the_codex_process_when_codex_connects(self):
        # Positive control: the recorder used by the fail-closed tests does observe a Codex spawn.
        factory = SpawnRecordingFactory()
        app = self.dashboard(client_factory=factory)
        app.start()
        for _ in range(500):
            if factory.spawns:
                break
            time.sleep(0.01)
        self.assertEqual([["codex", "app-server"]], factory.spawns[:1])

    def test_codex_default_dashboard_still_starts_its_connect_loop(self):
        factory = RecordingFactory()
        app = self.dashboard(client_factory=factory)
        self.assertIsInstance(app.backend, CodexBackend)
        app.start()
        for _ in range(500):
            if app.connection["status"] == "connected":
                break
            time.sleep(0.01)
        self.assertEqual(1, len(factory.calls))
        self.assertIs(factory.clients[0], app.client)
        self.assertEqual("connected", app.connection["status"])
        self.assertEqual("Live App Server; opening this page starts no runs", app.connection["detail"])

    def test_no_backend_refuses_run_start(self):
        app = self.dashboard(backend=NoBackend())
        fake = FakeClient()
        app.client = fake
        app.connection["status"] = "connected"  # Even a forced connection never reaches a backend.
        project = app.add_project({"name": "Project One", "path": str(self.root)})
        with self.assertRaisesRegex(ValueError, r"^No provider configured\.$"):
            app.start_task(dict(TASK, project_id=project["id"]))
        self.assertEqual([], fake.requests)
        self.assertEqual({}, app.tasks)
        self.assertEqual([], app.workers)

    def test_claude_stub_start_run_answers_not_implemented_without_spawning(self):
        factory = SpawnRecordingFactory()
        app = self.dashboard(client_factory=factory, backend=ClaudeBackendStub())
        app.start()
        project = app.add_project({"name": "Project One", "path": str(self.root)})
        with self.assertRaisesRegex(ValueError, r"^Claude backend is not implemented yet\.$"):
            app.start_task(dict(TASK, project_id=project["id"]))
        time.sleep(0.05)
        self.assertEqual([], factory.calls)
        self.assertEqual([], factory.spawns)
        self.assertIsNone(app.client)
        self.assertEqual({}, app.tasks)
        self.assertEqual("disabled", app.connection["status"])
        self.assertEqual("Claude backend is not implemented yet.", app.connection["detail"])

    def test_on_message_with_no_backend_treats_message_as_unrecognized(self):
        app = self.dashboard()
        fake = FakeClient()
        app.client = fake
        app.connection["status"] = "connected"
        project = app.add_project({"name": "Project One", "path": str(self.root)})
        task = app.start_task(dict(TASK, project_id=project["id"]))
        self.assertTrue(fake.started.wait(5))
        app.workers[-1].join(5)
        before = dict(app.tasks[task["id"]])
        self.assertEqual("running", before["status"])
        app.backend = NoBackend()
        app.on_message({"method": "turn/completed", "params": {
            "threadId": before["thread_id"], "turn": {"id": before["turn_id"], "status": "completed"}}})
        self.assertEqual(before, app.tasks[task["id"]])

    def test_api_provider_reports_codex_by_default(self):
        status, body = self.request(self.dashboard(), "/api/provider")
        self.assertEqual(200, status)
        self.assertEqual({"provider": "codex", "configured": True, "capabilities": CODEX_CAPABILITIES.public()}, body)

    def test_api_provider_reports_none_for_no_backend(self):
        status, body = self.request(self.dashboard(backend=NoBackend()), "/api/provider")
        self.assertEqual(200, status)
        self.assertEqual({"provider": "none", "configured": False,
                          "capabilities": NoBackend.capabilities.public()}, body)

    def test_api_provider_reports_claude_stub(self):
        status, body = self.request(self.dashboard(backend=ClaudeBackendStub()), "/api/provider")
        self.assertEqual(200, status)
        self.assertEqual({"provider": "claude", "configured": True,
                          "capabilities": ClaudeBackendStub.capabilities.public()}, body)

    def test_dashboard_for_provider_wires_backend(self):
        missing = dashboard_for_provider(None, directory=self.root / "none", policy_provider=SyntheticPolicy())
        self.apps.append(missing)
        self.assertIsInstance(missing.backend, NoBackend)
        codex = dashboard_for_provider("codex", directory=self.root / "codex", policy_provider=SyntheticPolicy())
        self.apps.append(codex)
        self.assertIsInstance(codex.backend, CodexBackend)
        fake = FakeClient()
        codex.client = fake  # The Codex backend follows the dashboard's own current client.
        codex.backend.list_models()
        self.assertEqual("model/list", fake.requests[0][0])
        claude = dashboard_for_provider("claude", directory=self.root / "claude", policy_provider=SyntheticPolicy())
        self.apps.append(claude)
        self.assertIsInstance(claude.backend, ClaudeBackendStub)

    def main_provider(self, *flags):
        """Run main() with argv flags; return the provider it passes on, aborting before any server."""
        recorded = []

        def record(provider, **kwargs):
            recorded.append((provider, sorted(kwargs)))
            raise MainAborted()

        with mock.patch.object(sys, "argv", ["dashboard.server", *flags]), \
                mock.patch.object(server, "dashboard_for_provider", record), \
                mock.patch.object(server, "RuntimeOwner", lambda _path: mock.MagicMock()), \
                mock.patch.object(server, "make_server", side_effect=AssertionError("server started")), \
                mock.patch.object(server.os, "umask"):
            with self.assertRaises(MainAborted):
                server.main()
        self.assertEqual(1, len(recorded))
        self.assertEqual(["runtime_owner"], recorded[0][1])
        return recorded[0][0]

    def test_main_passes_provider_verbatim_and_defaults_to_none(self):
        self.assertIsNone(self.main_provider())
        self.assertIsNone(self.main_provider("--port", "8766"))
        self.assertEqual("codex", self.main_provider("--provider", "codex"))
        self.assertEqual("claude", self.main_provider("--provider", "claude"))
        self.assertEqual("Codex", self.main_provider("--provider", "Codex"))
        self.assertEqual("codex ", self.main_provider("--provider", "codex "))
        self.assertEqual("", self.main_provider("--provider", ""))

    def test_script_exit_codes(self):
        cases = [[], ["claude2"], ["Codex"], ["CLAUDE"], ["codex "], [""], ["codex", "claude"], ["codex", ""]]
        env = dict(os.environ, PATH="/usr/bin:/bin")
        for args in cases:
            with self.subTest(args=args):
                result = subprocess.run(["sh", str(SCRIPT), *args], cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual(USAGE, result.stderr)
        # Valid arguments are never run here (they would start a server); pin the wiring instead.
        text = SCRIPT.read_text()
        self.assertIn('exec "$dashboard_python" -m dashboard.server --port 8765 --provider "$1"', text)
        self.assertIn('if [ "$1" = codex ] && ! command -v codex >/dev/null 2>&1; then', text)


if __name__ == "__main__":
    unittest.main()
