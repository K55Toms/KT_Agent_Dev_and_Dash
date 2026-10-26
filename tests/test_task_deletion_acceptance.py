"""Independent deletion acceptance checks using disposable storage and a fake native client.

These prove dashboard lifecycle behavior, not native stopping or browser accessibility.
"""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid

from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard, make_server
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient
from tests.test_recovery import FakeAssessmentTransport, FakeRecoveryCapabilities


class TaskDeletionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='delete-acceptance-', dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.app = self.new_app()
        self.project = self.app.add_project({'name': 'Disposable acceptance project', 'path': str(self.root)})
        self.origin = self.task('unknown', 'Historical unknown run')

    def new_app(self):
        app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy(),
                        recovery_capabilities=FakeRecoveryCapabilities(),
                        assessment_transport=FakeAssessmentTransport())
        app.client = FakeClient()
        app.connection['status'] = 'connected'
        return app

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def task(self, status, title):
        task = {'id': uuid.uuid4().hex, 'project_id': self.project['id'], 'title': title,
                'role': 'backend_developer', 'model': 'gpt-6.1-sol', 'reasoning': 'high',
                'status': status, 'thread_id': 'historical-' + uuid.uuid4().hex,
                'turn_id': 'historical-turn', 'plan': [], 'created_at': '2026-10-25T10:00:00Z',
                'updated_at': '2026-10-25T10:00:00Z', 'error': None, 'diagnostics': [],
                'usage': None, 'cost': {'basis': 'unknown', 'credits': None},
                'task_purpose': 'development', 'revision': 1, 'recovery_hold': status == 'unknown'}
        self.app.tasks[task['id']] = task
        self.app.store.put('task', task)
        return task

    def projection(self, task=None):
        identifier = (task or self.origin)['id']
        return next(row for row in self.app.snapshot()['tasks'] if row['id'] == identifier)

    def confirmation(self, task=None):
        return {'expected_version': self.projection(task)['deletion_version'], 'confirmed': True}

    def child(self, status='unknown'):
        row = {'id': uuid.uuid4().hex, 'parent_task_id': self.origin['id'],
               'project_id': self.project['id'], 'thread_id': 'historical-child',
               'parent_thread_id': self.origin['thread_id'], 'role': None,
               'title': 'Unattributed delegated task', 'status': status,
               'created_at': '2026-10-25T10:00:00Z', 'updated_at': '2026-10-25T10:00:00Z'}
        self.app.observed_tasks[row['id']] = row
        self.app.store.put('team_activity', row)
        return row

    def history(self):
        row = {'id': uuid.uuid4().hex, 'task_id': self.origin['id'], 'kind': 'user',
               'text': 'Synthetic history to remove.', 'created_at': '2026-10-25T10:00:00Z'}
        self.app.messages.append(row)
        self.app.store.put('conversation', row)
        return row

    def test_unknown_delete_releases_hold_and_new_same_project_fake_run_starts(self):
        self.child()
        self.history()
        source = self.root / 'project-work.txt'
        source.write_text('Synthetic project work must survive dashboard deletion.\n')
        request = {'project_id': self.project['id'], 'title': 'Fresh review',
                   'instruction': 'Review the synthetic project.', 'role': 'backend_developer'}
        with self.assertRaisesRegex(ValueError, 'overlapping project'):
            self.app.start_task(request)
        self.assertEqual([], self.app.client.requests)
        self.assertTrue(self.projection()['can_delete'])
        result = self.app.delete_task(self.origin['id'], self.confirmation())
        self.assertEqual({'task_id': self.origin['id'], 'deleted': True}, result)
        self.assertEqual([], self.app.recovery_hold_roots())
        self.assertFalse(self.app.tasks)
        self.assertFalse(self.app.messages)
        self.assertFalse(self.app.observed_tasks)
        self.assertEqual('Synthetic project work must survive dashboard deletion.\n', source.read_text())
        self.assertEqual([], self.app.client.requests, 'Deleting history must not dispatch native work')
        fresh = self.app.start_task(request)
        for worker in self.app.workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual('running', self.app.tasks[fresh['id']]['status'])
        self.assertEqual(1, sum(method == 'turn/start' for method, _ in self.app.client.requests))

    def test_failed_transaction_preserves_database_memory_and_hold(self):
        child = self.child()
        message = self.history()
        before = deepcopy(self.origin)
        with self.app.store.lock, self.app.store.db:
            self.app.store.db.execute("""CREATE TRIGGER synthetic_delete_failure BEFORE DELETE ON records
                WHEN OLD.kind = 'team_activity' BEGIN SELECT RAISE(ABORT, 'Synthetic deletion failure'); END""")
        with self.assertRaises(FileAccessError) as failure:
            self.app.delete_task(self.origin['id'], self.confirmation())
        self.assertEqual(503, failure.exception.status)
        self.assertEqual(before, self.app.tasks[self.origin['id']])
        self.assertIn(message, self.app.messages)
        self.assertIn(child['id'], self.app.observed_tasks)
        self.assertIn(self.origin, self.app.store.load('task'))
        self.assertIn(message, self.app.store.load('conversation'))
        self.assertIn(child, self.app.store.load('team_activity'))
        self.assertTrue(self.app.recovery_hold_roots())

    def test_stale_confirmation_after_child_change_cannot_delete(self):
        child = self.child()
        confirmation = self.confirmation()
        child['status'] = 'running'
        self.app.store.put('team_activity', child)
        self.assertFalse(self.projection()['can_delete'])
        with self.assertRaises(FileAccessError) as failure:
            self.app.delete_task(self.origin['id'], confirmation)
        self.assertEqual(409, failure.exception.status)
        self.assertIn(self.origin['id'], self.app.tasks)

    def test_known_live_and_inflight_operations_require_stop_or_completion(self):
        for status in ('queued', 'running', 'waiting_approval'):
            with self.subTest(status=status):
                self.origin['status'] = status
                self.assertFalse(self.projection()['can_delete'])
                with self.assertRaises(FileAccessError) as failure:
                    self.app.delete_task(self.origin['id'], self.confirmation())
                self.assertEqual(409, failure.exception.status)
        self.origin['status'] = 'unknown'
        self.app.starting_turn.add(self.origin['id'])
        self.assertFalse(self.projection()['can_delete'])
        self.app.starting_turn.clear()
        self.app.launching_tasks.add(self.origin['id'])
        self.assertFalse(self.projection()['can_delete'])
        self.app.launching_tasks.clear()
        self.app.recoveries[self.origin['id']] = {'id': self.origin['id'], 'revision': 1, 'state': 'checking'}
        self.assertFalse(self.projection()['can_delete'])
        self.app.recoveries.clear()
        self.app._register_thread(self.origin['thread_id'], self.origin['id'])
        self.assertFalse(self.projection()['can_delete'])
        with self.assertRaises(FileAccessError) as failure:
            self.app.delete_task(self.origin['id'], self.confirmation())
        self.assertEqual(409, failure.exception.status)
        self.app.owned_threads[self.origin['thread_id']]['active'] = False
        self.assertTrue(self.projection()['can_delete'])

    def test_uncertain_historical_operation_does_not_block_and_linked_task_survives(self):
        linked = self.task('completed', 'Separate linked result')
        operation = {'id': uuid.uuid4().hex, 'origin_task_id': self.origin['id'],
                     'target_task_id': linked['id'], 'kind': 'continue', 'status': 'delivery_unknown'}
        self.app.recovery_operations[operation['id']] = operation
        self.app.store.put('recovery_operation', operation)
        self.assertTrue(self.projection()['can_delete'])
        self.app.delete_task(self.origin['id'], self.confirmation())
        self.assertEqual(linked, self.app.tasks[linked['id']])
        self.assertIn(linked, self.app.store.load('task'))
        self.assertEqual([], self.app.store.load('recovery_operation'))
        self.assertFalse(self.app.recovery_hold_roots())

    def test_deleted_task_and_children_cannot_return_from_late_events_or_reload(self):
        self.child()
        self.history()
        other = self.task('completed', 'Preserved run')
        self.app._register_thread(self.origin['thread_id'], self.origin['id'])
        self.app.owned_threads[self.origin['thread_id']]['active'] = False
        self.app.delete_task(self.origin['id'], self.confirmation())
        for method, params in (
            ('thread/started', {'thread': {'id': 'late-child', 'parentThreadId': self.origin['thread_id']}}),
            ('turn/started', {'threadId': self.origin['thread_id'], 'turn': {'id': 'late-turn'}}),
            ('turn/completed', {'threadId': self.origin['thread_id'], 'turn': {'id': 'historical-turn', 'status': 'completed'}}),
            ('item/completed', {'threadId': self.origin['thread_id'], 'turnId': 'historical-turn',
                                'item': {'type': 'agentMessage', 'id': 'late-message', 'text': 'Late synthetic message.'}}),
        ):
            self.app.on_message({'method': method, 'params': params})
        self.app.wait_conversations()
        self.assertNotIn(self.origin['id'], self.app.tasks)
        self.assertFalse(self.app.observed_tasks)
        self.assertFalse(self.app.messages)
        self.assertFalse(self.app.owned_threads)
        self.app.close()
        self.app = self.new_app()
        self.assertEqual([other['id']], [row['id'] for row in self.app.snapshot()['tasks']])
        self.assertEqual([], self.app.store.load('conversation'))
        self.assertEqual([], self.app.store.load('team_activity'))
        self.assertFalse(self.app.recovery_hold_roots())

    def test_http_delete_requires_same_origin_exact_confirmation_and_current_version(self):
        server = make_server(self.app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        port = server.server_port
        path = '/api/tasks/' + self.origin['id'] + '/delete'
        def post(payload, origin=None):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            headers = {'Content-Type': 'application/json'}
            if origin is not None:
                headers['Origin'] = origin
            connection.request('POST', path, json.dumps(payload), headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        try:
            confirmation = self.confirmation()
            self.assertEqual(403, post(confirmation)[0])
            self.assertEqual(403, post(confirmation, 'https://unrelated.example')[0])
            origin = 'http://127.0.0.1:' + str(port)
            for invalid in ({'expected_version': confirmation['expected_version']},
                            {**confirmation, 'confirmed': False}, {**confirmation, 'extra': True}):
                self.assertEqual(400, post(invalid, origin)[0])
                self.assertIn(self.origin['id'], self.app.tasks)
            self.assertEqual(409, post({**confirmation, 'expected_version': '0' * 64}, origin)[0])
            status, result = post(confirmation, origin)
            self.assertEqual(200, status)
            self.assertEqual({'task_id': self.origin['id'], 'deleted': True}, result)
            self.assertEqual(404, post(confirmation, origin)[0])
            self.assertEqual([], self.app.client.requests)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == '__main__':
    unittest.main()
