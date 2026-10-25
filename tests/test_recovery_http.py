"""Recovery HTTP contract and same-origin checks, with injected protocol capability only."""
import http.client
import json
import threading
import unittest
import uuid

from dashboard.server import make_server
from tests import test_recovery as recovery_tests


class RecoveryHTTPTests(recovery_tests.RecoveryTests):
    # Inherit the common fixture only; protocol journey tests are run in their own module.
    def setUp(self):
        super().setUp()
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()
        super().tearDown()

    def request(self, method, route, payload=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        request_headers = {'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:' + str(self.port)}
        if headers is not None:
            request_headers = headers
        connection.request(method, route, body=json.dumps(payload) if payload is not None else None,
                           headers=request_headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        status, result_headers = response.status, dict(response.getheaders())
        connection.close()
        return status, body, result_headers

    @property
    def route(self):
        return '/api/tasks/' + self.origin['id'] + '/recovery'

    def test_http_recovery_summary_metadata_check_and_no_cache(self):
        status, summary, headers = self.request('GET', self.route)
        self.assertEqual(200, status)
        self.assertIn('no-store', headers['Cache-Control'])
        status, checked, _ = self.request('POST', self.route + '/check', {'expected_revision': summary['revision']})
        self.assertEqual(200, status)
        self.assertIsInstance(checked['revision'], int)
        self.assertIsInstance(checked['actions']['assess'], bool)
        self.assertEqual('unknown', self.origin['status'])
        self.assertFalse(any(m == 'thread/start' for m, _ in self.client.requests))

    def test_http_recovery_stale_revision_and_untrusted_fields_are_rejected(self):
        self.assertEqual(409, self.request('POST', self.route + '/check', {'expected_revision': 999})[0])
        self.assertEqual(400, self.request('POST', self.route + '/check', {'expected_revision': 1, 'thread_id': 'foreign'})[0])
        self.assertEqual(400, self.request('POST', self.route + '/check', {'expected_revision': True})[0])
        self.assertEqual(404, self.request('GET', '/api/tasks/' + uuid.uuid4().hex + '/recovery')[0])

    def test_http_no_cross_origin_mutation_or_arbitrary_native_operation(self):
        self.assertEqual(403, self.request('POST', self.route + '/check', {'expected_revision': 1},
            {'Content-Type': 'application/json', 'Origin': 'https://invalid.example'})[0])
        self.assertEqual(404, self.request('POST', self.route + '/resume', {'threadId': 'foreign'})[0])
        self.assertEqual(400, self.request('POST', '/api/tasks', {'task_purpose': 'recovery_assessment'})[0])


# Do not duplicate every protocol test through the HTTP fixture subclass.
for _name in list(recovery_tests.RecoveryTests.__dict__):
    if _name.startswith('test_'):
        setattr(RecoveryHTTPTests, _name, None)
