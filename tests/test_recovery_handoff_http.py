"""Same-origin HTTP contract tests for checked local recovery handoffs."""
import http.client
import json
import threading
import unittest
import uuid

from dashboard.server import make_server
from tests import test_recovery_handoff as handoff_tests


class RecoveryHandoffHTTPTests(unittest.TestCase):
    def setUp(self):
        handoff_tests.RecoveryHandoffTests.setUp(self)
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.route = '/api/tasks/' + self.origin['id'] + '/recovery'

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()
        handoff_tests.RecoveryHandoffTests.tearDown(self)

    summary = handoff_tests.RecoveryHandoffTests.summary

    def request(self, method, route, data=None, origin=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = 'http://127.0.0.1:' + str(self.port)
        connection.request(method, route, body=json.dumps(data) if data is not None else None, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    def create(self):
        data = {'expected_revision': self.summary()['revision'], 'operation_id': uuid.uuid4().hex,
            'selected_message_ids': [], 'text': 'Assess the checked evidence only.', 'confirmed': True}
        status, body, _ = self.request('POST', self.route + '/handoffs', data)
        self.assertEqual(200, status)
        return body

    def test_http_prepare_preview_response_accept_no_store_and_no_effects(self):
        summary = self.create()
        route = self.route + '/handoffs/' + summary['handoff']['id']
        status, preview, headers = self.request('GET', route)
        self.assertEqual(200, status)
        self.assertIn('no-store', headers['Cache-Control'])
        payload = {'expected_revision': summary['revision'], 'operation_id': uuid.uuid4().hex,
            'packet_digest': preview['packet_digest'], 'expected_handoff_version': preview['version'],
            'text': 'Plain text from a human supplied external assessment.', 'confirmed': True}
        status, summary, _ = self.request('POST', route + '/responses', payload)
        self.assertEqual(200, status)
        self.assertFalse(summary['actions']['review_plan'])
        status, preview, _ = self.request('GET', route)
        self.assertEqual(200, status)
        response = preview['response']
        acceptance = {'expected_revision': summary['revision'], 'operation_id': uuid.uuid4().hex,
            'packet_digest': preview['packet_digest'], 'expected_handoff_version': preview['version'],
            'response_id': response['response_id'], 'response_digest': response['response_digest'],
            'response_version': response['response_version'], 'review_id': response['review_id'], 'confirmed': True}
        status, summary, _ = self.request('POST', route + '/accept', acceptance)
        self.assertEqual(200, status)
        self.assertEqual('reviewable', summary['assessment']['status'])
        self.assertEqual([], self.client.requests)
        self.assertEqual([], self.assessment.calls)

    def test_missing_origin_unknown_fields_wrong_task_and_bool_versions_rejected(self):
        summary = self.create()
        route = self.route + '/handoffs/' + summary['handoff']['id']
        data = {'expected_revision': summary['revision'], 'operation_id': uuid.uuid4().hex,
            'packet_digest': summary['handoff']['packet_digest'], 'expected_handoff_version': True,
            'text': 'Assessment', 'confirmed': True}
        self.assertEqual(403, self.request('POST', route + '/responses', data, origin=False)[0])
        self.assertEqual(409, self.request('POST', route + '/responses', data)[0])
        data['thread_id'] = 'foreign'
        self.assertEqual(400, self.request('POST', route + '/responses', data)[0])
        foreign = '/api/tasks/' + uuid.uuid4().hex + '/recovery/handoffs/' + summary['handoff']['id']
        self.assertEqual(404, self.request('GET', foreign)[0])
        self.assertEqual(404, self.request('POST', route + '/execute', {})[0])

    def test_scanner_failure_get_is_safe_bounded_error_without_bodies(self):
        from unittest.mock import patch
        from dashboard.project_files import FileAccessError
        summary = self.create()
        route = self.route + '/handoffs/' + summary['handoff']['id']
        with patch('dashboard.recovery_handoff.scan_preview', side_effect=FileAccessError(503, 'Fixture exception detail')):
            status, body, _ = self.request('GET', route)
        self.assertEqual(409, status)
        self.assertEqual({'error': 'Content checks did not pass. Nothing was revealed or saved.'}, body)
