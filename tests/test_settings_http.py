"""Settings HTTP boundaries and explicit repository-action coordination."""
import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from dashboard.server import Dashboard, make_server
from dashboard.settings import SettingsStore
from dashboard.project_files import FileAccessError
from tests.test_settings import png


class SettingsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / "state")
        self.app.settings = SettingsStore(self.root)
        (self.root / "dashboard").mkdir()
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()
        self.temp.cleanup()

    def request(self, method, path, data=None, origin=True):
        port = self.server.server_port
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = f"http://127.0.0.1:{port}"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, json.loads(body)

    def test_settings_save_persisted_and_mutation_requires_origin(self):
        status, initial = self.request("GET", "/api/config")
        self.assertEqual(200, status)
        changed = dict(initial, dashboard_name="Test Builders", theme="rebel", github_username="example-owner", github_visibility="private")
        self.assertEqual(403, self.request("POST", "/api/config", changed, origin=False)[0])
        self.assertEqual(initial, self.app.settings.load())
        self.assertEqual((200, changed), self.request("POST", "/api/config", changed))
        self.assertEqual(changed, SettingsStore(self.root).load())
        self.assertEqual(400, self.request("POST", "/api/config", dict(changed, token="SYNTHETIC_PLACEHOLDER"))[0])
        self.assertEqual(changed, self.app.settings.load())

    def test_logo_endpoint_rejects_non_png_and_missing_origin(self):
        payload = {"image": base64.b64encode(b"Not a PNG").decode()}
        self.assertEqual(403, self.request("POST", "/api/logo", payload, origin=False)[0])
        self.assertIn(self.request("POST", "/api/logo", payload)[0], (400, 415, 422))
        self.assertEqual(400, self.request("POST", "/api/logo", {"image": "%%%"})[0])
        self.assertEqual(404, self.request("GET", "/api/logo/" + "a" * 64 + ".png")[0])

    def test_logo_upload_activation_and_serving_are_separate(self):
        image = png()
        initial = self.app.settings.load()
        status, uploaded = self.request("POST", "/api/logo", {"image": base64.b64encode(image).decode()})
        self.assertEqual(200, status)
        self.assertEqual(initial, self.app.settings.load())
        port = self.server.server_port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", uploaded["logo_path"])
        response = connection.getresponse()
        self.assertEqual(200, response.status)
        self.assertEqual("image/png", response.getheader("Content-Type"))
        self.assertEqual(image, response.read())
        connection.close()
        desired = dict(initial, logo_path=uploaded["logo_path"])
        self.assertEqual((200, desired), self.request("POST", "/api/config", desired))

    def test_repository_creation_reserved_against_overlapping_run(self):
        project = self.app.add_project({"name": "Fixture", "path": str(self.root)})
        service = Mock()
        self.app.git_service = service
        self.app.tasks["synthetic"] = {"id": "synthetic", "project_id": project["id"], "status": "running"}
        data = {"owner": "example-owner", "name": "fixture", "visibility": "private", "confirmed": True}
        with self.assertRaises(FileAccessError) as error:
            self.app.create_repository(project["id"], data)
        self.assertEqual(409, error.exception.status)
        service.create_repository.assert_not_called()
        self.app.tasks.clear()
        def created(*_args):
            self.assertIn(self.root, self.app.publishing)
            return {"created": True, "attached": True}
        service.create_repository.side_effect = created
        self.assertEqual(403, self.request("POST", f"/api/projects/{project['id']}/repository", data, origin=False)[0])
        self.assertEqual(200, self.request("POST", f"/api/projects/{project['id']}/repository", data)[0])
        self.assertEqual(set(), self.app.publishing)
