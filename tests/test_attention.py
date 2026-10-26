"""Presentation-only stale warning acknowledgements; no native execution required."""

from tests.policy_fixtures import SyntheticPolicy
from copy import deepcopy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard, make_server


class AttentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.directory = Path(self.temp.name) / 'runtime'
        self.app = Dashboard(self.directory, policy_provider=SyntheticPolicy())
        self.task = self.add_task()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def add_task(self, status='failed'):
        task = {'id': uuid.uuid4().hex, 'project_id': uuid.uuid4().hex,
                'title': 'Synthetic task', 'role': 'backend_developer', 'status': status,
                'updated_at': '2026-10-18T10:00:00+00:00', 'thread_id': None, 'turn_id': None,
                'diagnostics': [{'code': 'transport_lost', 'at': '2026-10-18T10:00:00+00:00'}]}
        self.app.tasks[task['id']] = task
        self.app.store.put('task', task)
        return task

    def state_task(self, task=None):
        identifier = (task or self.task)['id']
        return next(item for item in self.app.snapshot()['tasks'] if item['id'] == identifier)

    def dismiss(self, task=None):
        task = task or self.task
        return self.app.dismiss_attention(task['id'], {'version': self.state_task(task)['attention_version']})

    def test_clear_preserves_status_history_and_other_tasks(self):
        other = self.add_task('unknown')
        before = deepcopy(self.app.tasks)
        result = self.dismiss()
        self.assertEqual(self.task['id'], result['task_id'])
        self.assertTrue(result['attention_dismissed'])
        self.assertTrue(self.state_task()['attention_dismissed'])
        self.assertFalse(self.state_task(other)['attention_dismissed'])
        self.assertEqual(before, self.app.tasks)
        stored = self.app.store.load('attention_dismissal')
        self.assertEqual({'id', 'version', 'at'}, set(stored[0]))
        self.assertEqual(before[self.task['id']], self.app.store.load('task')[0])

    def test_dismissal_survives_restart(self):
        self.dismiss()
        self.app.close()
        self.app = Dashboard(self.directory, policy_provider=SyntheticPolicy())
        self.assertTrue(self.state_task()['attention_dismissed'])
        self.assertEqual('failed', self.state_task()['status'])

    def test_new_diagnostic_and_updated_state_reappear(self):
        self.dismiss()
        self.task['diagnostics'].append({'code': 'execution_failed', 'at': '2026-10-18T10:01:00+00:00'})
        self.assertFalse(self.state_task()['attention_dismissed'])
        self.dismiss()
        self.task['updated_at'] = '2026-10-18T10:02:00+00:00'
        self.assertFalse(self.state_task()['attention_dismissed'])
        self.dismiss()
        self.task['status'] = 'unknown'
        self.assertFalse(self.state_task()['attention_dismissed'])

    def test_stale_version_rejected_without_record(self):
        version = self.state_task()['attention_version']
        self.task['updated_at'] = '2026-10-18T10:03:00+00:00'
        with self.assertRaises(FileAccessError) as error:
            self.app.dismiss_attention(self.task['id'], {'version': version})
        self.assertEqual(409, error.exception.status)
        self.assertEqual([], self.app.store.load('attention_dismissal'))

    def test_active_and_nonwarning_statuses_rejected(self):
        for status in ('queued', 'running', 'waiting_approval', 'completed', 'interrupted'):
            with self.subTest(status=status):
                self.task['status'] = status
                with self.assertRaises(FileAccessError) as error:
                    self.dismiss()
                self.assertEqual(409, error.exception.status)

    def test_pending_approval_and_question_cannot_be_hidden(self):
        for target, record in (
            ('approvals', {'id': 'approval', 'task_id': self.task['id'], 'status': 'pending'}),
            ('questions', {'id': 'question', 'task_id': self.task['id'], 'status': 'pending'}),
            ('questions', {'id': 'question', 'task_id': self.task['id'], 'status': 'answering'}),
            ('pending', {'task_id': self.task['id']}),
            ('question_requests', {'task_id': self.task['id']}),
        ):
            with self.subTest(target=target, status=record.get('status')):
                collection = getattr(self.app, target)
                collection['request'] = record
                # Direct action checks do not invoke review or question operations.
                with self.assertRaises(FileAccessError):
                    self.app.dismiss_attention(self.task['id'], {'version': self.app._attention_version(self.task)})
                self.assertEqual(record, collection['request'])
                collection.clear()

    def test_active_child_cannot_be_hidden(self):
        self.app.owned_threads['child'] = {'task_id': self.task['id'], 'parent': 'root', 'active': True}
        with self.assertRaises(FileAccessError):
            self.dismiss()
        self.app.owned_threads['child']['active'] = False
        self.assertTrue(self.dismiss()['attention_dismissed'])

    def test_prior_dismissal_does_not_hide_new_pending_decision(self):
        self.dismiss()
        self.app.question_requests['question'] = {'task_id': self.task['id']}
        self.assertFalse(self.state_task()['attention_dismissed'])
        self.app.question_requests.clear()

    def test_invalid_fields_and_unknown_task_rejected(self):
        for payload in ({}, {'version': 'invalid'}, {'version': None},
                        {'version': 'a' * 64, 'extra': True}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.app.dismiss_attention(self.task['id'], payload)
        with self.assertRaises(FileAccessError) as error:
            self.app.dismiss_attention(uuid.uuid4().hex, {'version': 'a' * 64})
        self.assertEqual(404, error.exception.status)

    def test_http_guard_conflict_and_success(self):
        server = make_server(self.app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)

        def post(data, include_origin=True):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            headers = {'Content-Type': 'application/json'}
            if include_origin:
                headers['Origin'] = origin
            connection.request('POST', '/api/tasks/' + self.task['id'] + '/dismiss-attention',
                               json.dumps(data), headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read()), response.getheader('Cache-Control')
            connection.close()
            return result

        try:
            data = {'version': self.state_task()['attention_version']}
            self.assertEqual(403, post(data, False)[0])
            self.assertEqual(409, post({'version': '0' * 64})[0])
            status, result, cache = post(data)
            self.assertEqual(200, status)
            self.assertTrue(result['attention_dismissed'])
            self.assertIn('no-store', cache)
            self.assertEqual('failed', self.task['status'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == '__main__':
    unittest.main()
