"""Real local Git/scanner and hostile-path regressions; no Codex inference."""

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

from dashboard.project_files import FileAccessError, MAX_FILE_BYTES, _bounded_command, list_files, preview_file, scan_preview
from dashboard.server import Dashboard, make_server


class ProjectFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.git("init", "--quiet")
        (self.project / "README.md").write_text("# Project\nSafe source text.\n")
        self.git("add", "README.md")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=self.project,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    def assert_blocked(self, path, status=None):
        with self.assertRaises(FileAccessError) as error:
            preview_file(self.project, path)
        if status:
            self.assertEqual(status, error.exception.status)

    def test_safe_tracked_and_nonignored_untracked_utf8_preview(self):
        (self.project / "new.py").write_text("print('hello')\n", encoding="utf-8")
        files = list_files(self.project)
        self.assertFalse(files["limit_reached"])
        self.assertEqual({"README.md", "new.py"}, {entry["path"] for entry in files["files"]})
        preview = preview_file(self.project, "README.md")
        self.assertEqual("# Project\nSafe source text.\n", preview["content"])
        self.assertEqual(2, preview["line_count"])
        self.assertEqual(len(preview["content"].encode()), preview["size"])

    def test_sensitive_root_and_ancestor_rejected_before_git_or_content(self):
        with patch("dashboard.project_files._git", side_effect=AssertionError("Must not inspect sensitive roots")):
            for root in [self.root / ".aws", self.root / ".aws" / "nested", self.root / "node_modules"]:
                root.mkdir(parents=True, exist_ok=True)
                for operation in [lambda: list_files(root), lambda: preview_file(root, "config")]:
                    with self.assertRaises(FileAccessError) as error:
                        operation()
                    self.assertEqual(403, error.exception.status)

    def test_ignored_forcedtracked_and_credential_paths_never_opened_for_preview(self):
        (self.project / ".gitignore").write_text("hidden.txt\ntracked.txt\n.env\n")
        for name in ["hidden.txt", "tracked.txt", ".env"]:
            (self.project / name).write_text("Synthetic blocked fixture\n")
        self.git("add", "--force", "tracked.txt", ".env")
        with patch("dashboard.project_files.source_descriptor", side_effect=AssertionError("Must not open ignored source")):
            for name in ["hidden.txt", "tracked.txt", ".env", ".git/config"]:
                self.assert_blocked(name)
        paths = {entry["path"] for entry in list_files(self.project)["files"]}
        self.assertFalse(paths & {"hidden.txt", "tracked.txt", ".env", ".git/config"})

    def test_traversal_absolute_control_and_malformed_paths(self):
        with patch("dashboard.project_files._git", side_effect=AssertionError("Unsafe path must be rejected first")):
            for path in ["../outside", "/etc/passwd", "nested/../../outside", "./README.md", "a//b", "a\\b", "README.md\n", "", "a/../README.md"]:
                self.assert_blocked(path, 400)

    def test_symlink_components_leaf_and_hardlinks_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "source.txt").write_text("Outside synthetic source\n")
        (self.project / "leaf.txt").symlink_to(outside / "source.txt")
        (self.project / "linked").symlink_to(outside, target_is_directory=True)
        os.link(outside / "source.txt", self.project / "hardlink.txt")
        self.git("add", "leaf.txt", "linked", "hardlink.txt")
        self.assert_blocked("leaf.txt", 403)
        self.assert_blocked("hardlink.txt", 403)
        self.assert_blocked("linked/source.txt")
        paths = {entry["path"] for entry in list_files(self.project)["files"]}
        self.assertFalse(paths & {"leaf.txt", "hardlink.txt", "linked"})
        # Root replacement/ancestor links are blocked before Git or content access.
        (self.root / "alias").symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(FileAccessError):
            preview_file(self.root / "alias", "README.md")

    def test_binary_invalid_utf8_and_oversize_stop_before_scanner(self):
        for name, data in [("binary.bin", b"a\0b"), ("invalid.txt", b"\xff"),
                           ("large.txt", b"x" * (MAX_FILE_BYTES + 1))]:
            (self.project / name).write_bytes(data)
        with patch("dashboard.project_files.scan_preview", side_effect=AssertionError("Do not scan rejected data")):
            self.assert_blocked("binary.bin", 415)
            self.assert_blocked("invalid.txt", 415)
            self.assert_blocked("large.txt", 413)

    def test_git_visibility_and_non_git_helpful_failure(self):
        (self.project / "node_modules").mkdir()
        (self.project / "node_modules/source.py").write_text("safe = True\n")
        self.assert_blocked("node_modules/source.py", 403)
        self.assert_blocked("absent.py", 404)
        non_git = self.root / "non-git"
        non_git.mkdir()
        with self.assertRaises(FileAccessError) as error:
            list_files(non_git)
        self.assertEqual(422, error.exception.status)
        self.assertIn("Git working tree", str(error.exception))

    def test_scanner_missing_version_error_and_possible_secret_fail_closed(self):
        with patch("dashboard.project_files.shutil.which", return_value=None):
            self.assert_blocked("README.md", 503)
        with patch("dashboard.project_files._bounded_command", return_value=(0, b"0.0.0\n")):
            with self.assertRaises(FileAccessError) as error:
                scan_preview(b"safe text\n")
            self.assertEqual(503, error.exception.status)
        unreviewed = self.root / "unreviewed.toml"
        unreviewed.write_text("# Configuration has not been reviewed\n")
        with patch("dashboard.project_files.CONFIG", unreviewed):
            with self.assertRaises(FileAccessError) as error:
                scan_preview(b"safe text\n")
            self.assertEqual(503, error.exception.status)
        real_run = subprocess.run
        def scanner_error(argv, **kwargs):
            if "stdin" in argv:
                return subprocess.CompletedProcess(argv, 2)
            return real_run(argv, **kwargs)
        with patch("dashboard.project_files.subprocess.run", side_effect=scanner_error):
            with self.assertRaises(FileAccessError) as error:
                scan_preview(b"safe text\n")
            self.assertEqual(403, error.exception.status)
        # Construct a deliberately nonfunctional credential-shaped value at runtime.
        value = "synthetic" + "-nonfunctional-" + "fixture"
        content = ("api_" + "key = '" + value + "'\n").encode()
        with self.assertRaises(FileAccessError) as error:
            scan_preview(content)
        self.assertEqual(403, error.exception.status)
        self.assertNotIn(value, str(error.exception))

    def test_scanner_ignores_ambient_bypass_and_allow_comments(self):
        value = "constructed" + "-nonfunctional-" + "fixture"
        content = ("password = '" + value + "' # gitleaks:allow\n").encode()
        with patch.dict(os.environ, {"GITLEAKS_CONFIG": "/nonexistent/ambient-config", "GITLEAKS_EXIT_CODE": "0"}):
            with self.assertRaises(FileAccessError):
                scan_preview(content)

    def test_listing_limit_and_output_bound(self):
        for i in range(4):
            (self.project / ("file" + str(i) + ".py")).write_text("# safe\n")
        with patch("dashboard.project_files.MAX_FILES", 2):
            listing = list_files(self.project)
        self.assertEqual(2, len(listing["files"]))
        self.assertTrue(listing["limit_reached"])
        with patch("dashboard.project_files.MAX_CANDIDATES", 2):
            self.assertTrue(list_files(self.project)["limit_reached"])
        with self.assertRaises(FileAccessError) as error:
            _bounded_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 8192)"],
                             self.root, {}, maximum=1024)
        self.assertEqual(503, error.exception.status)
        with self.assertRaises(FileAccessError):
            _bounded_command([sys.executable, "-c", "import time; time.sleep(2)"],
                             self.root, {}, timeout=.05)

    def test_literal_filename_and_secret_preview_rejected_without_content(self):
        literal = "source[1].txt"
        (self.project / literal).write_text("Literal filename source\n")
        self.assertEqual("Literal filename source\n", preview_file(self.project, literal)["content"])
        value = "synthetic" + "-not-a-real-credential-" + "fixture"
        secret_shaped = "api_" + "key = '" + value + "'\n"
        (self.project / "blocked-source.txt").write_text(secret_shaped)
        with self.assertRaises(FileAccessError) as error:
            preview_file(self.project, "blocked-source.txt")
        self.assertEqual(403, error.exception.status)
        self.assertNotIn(value, str(error.exception))

    def test_http_routes_unknown_project_safe_errors_and_host_guard(self):
        app = Dashboard(self.root / "state")
        project = app.add_project({"name": "Source project", "path": str(self.project)})
        server = make_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def get(path, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        try:
            prefix = "/api/projects/" + project["id"]
            status, listing = get(prefix + "/files")
            self.assertEqual(200, status)
            self.assertEqual(project["id"], listing["project_id"])
            status, preview = get(prefix + "/file?path=" + quote("README.md", safe=""))
            self.assertEqual(200, status)
            self.assertEqual(project["id"], preview["project_id"])
            self.assertIn("Safe source text", preview["content"])
            self.assertEqual(400, get(prefix + "/file?path=../outside")[0])
            self.assertEqual(400, get(prefix + "/file?path=README.md&path=README.md")[0])
            self.assertEqual(404, get("/api/projects/" + "0" * 32 + "/files")[0])
            self.assertEqual(403, get(prefix + "/files", {"Host": "attacker.example"})[0])
            self.assertEqual(403, get(prefix + "/files", {"Origin": "https://attacker.example"})[0])
            status, git_state = get(prefix + "/git")
            self.assertEqual(200, status)
            self.assertTrue(git_state["is_repository"])
            self.assertEqual(project["id"], git_state["project_id"])
            self.assertFalse(git_state["can_publish"])
            self.assertEqual(404, get("/api/projects/" + "0" * 32 + "/git")[0])
            self.assertEqual(400, get(prefix + "/git?path=outside")[0])
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
            connection.request("POST", prefix + "/publish", body=json.dumps({"confirmed": False}), headers={
                "Origin": "http://127.0.0.1:" + str(server.server_port), "Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(400, response.status)
            self.assertIn("error", json.loads(response.read()))
            connection.close()
            self.assertFalse(app.publishing)
            self.assertIsNone(app.client)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            app.close()

    def test_git_publish_registration_and_overlapping_run_interlock(self):
        app = Dashboard(self.root / "git-state")
        project = app.add_project({"name": "Publish fixture", "path": str(self.project)})
        child_path = self.project / "child"
        child_path.mkdir()
        child = app.add_project({"name": "Child fixture", "path": str(child_path)})
        entered, release = threading.Event(), threading.Event()
        class FakeGitService:
            calls = []
            def status(self, root):
                self.calls.append(("status", root))
                return {"is_repository": True}
            def publish(self, root, data):
                self.calls.append(("publish", root, data))
                entered.set()
                release.wait(3)
                return {"published": True}
        service = FakeGitService()
        app.git_service = service
        result = []
        worker = None
        try:
            self.assertTrue(app.project_git(project["id"])["is_repository"])
            with self.assertRaises(FileAccessError) as error:
                app.project_git("0" * 32)
            self.assertEqual(404, error.exception.status)
            data = {"head": "synthetic-head", "branch": "main", "remote": "origin", "confirmed": True}
            worker = threading.Thread(target=lambda: result.append(app.publish_project(project["id"], data)))
            worker.start()
            self.assertTrue(entered.wait(2))
            app.connection["status"] = "connected"
            with self.assertRaises(ValueError):
                app.start_task({"project_id": child["id"], "title": "Blocked overlapping task",
                                "instruction": "Synthetic objective", "role": "backend_developer"})
            with self.assertRaises(FileAccessError) as error:
                app.publish_project(child["id"], data)
            self.assertEqual(409, error.exception.status)
            release.set()
            worker.join(2)
            self.assertTrue(result[0]["published"])
            self.assertFalse(app.publishing)
            app.tasks["synthetic"] = {"id": "synthetic", "project_id": child["id"], "status": "running"}
            with self.assertRaises(FileAccessError) as error:
                app.publish_project(project["id"], data)
            self.assertEqual(409, error.exception.status)
            app.tasks.clear()
        finally:
            release.set()
            if worker:
                worker.join(2)
            app.close()


if __name__ == "__main__":
    unittest.main()
