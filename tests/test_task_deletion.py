"""Effects-free deletion tests: no native execution, source deletion or production state."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard, make_server
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient


class TaskDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.project = self.app.add_project({'name': 'Deletion fixture', 'path': str(self.root)})
        self.task = self.add_task()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def add_task(self, status='unknown'):
        task = {'id': uuid.uuid4().hex, 'project_id': self.project['id'], 'title': 'Synthetic run',
                'role': 'chief_of_staff', 'model': 'gpt-6.1-sol', 'reasoning': 'medium',
                'status': status, 'thread_id': 'old-' + uuid.uuid4().hex, 'turn_id': 'old-turn',
                'plan': [], 'created_at': '2026-10-25', 'updated_at': '2026-10-25',
                'error': None, 'diagnostics': [], 'usage': None, 'cost': {'basis': 'unknown', 'credits': None},
                'revision': 1, 'recovery_schema': 1, 'task_purpose': 'development', 'recovery_hold': True}
        self.app.tasks[task['id']] = task
        self.app.store.put('task', task)
        return task

    def payload(self, task=None):
        state = self.app.task_deletion_state(task or self.task)
        return {'expected_version': state['deletion_version'], 'confirmed': True}

    def test_unknown_deletion_releases_hold_and_allows_fresh_same_project_launch(self):
        child = {'id': 'old-child', 'parent_task_id': self.task['id'], 'project_id': self.project['id'],
                 'thread_id': 'historic-child', 'role': None, 'status': 'unknown', 'updated_at': '2026-10-25'}
        self.app.observed_tasks[child['id']] = child
        self.app.store.put('team_activity', child)
        self.assertTrue(self.app.active_project_roots())
        with patch('dashboard.conversation.scan_preview'), patch('dashboard.native_roles.scan_preview'):
            with self.assertRaisesRegex(ValueError, 'active agents'):
                self.app.start_task({'project_id': self.project['id'], 'title': 'New review',
                                     'role': 'chief_of_staff', 'instruction': 'Review synthetic work.'})
            result = self.app.delete_task(self.task['id'], self.payload())
            self.assertEqual({'task_id': self.task['id'], 'deleted': True}, result)
            self.assertEqual([], self.app.active_project_roots())
            started = self.app.start_task({'project_id': self.project['id'], 'title': 'New review',
                                           'role': 'chief_of_staff', 'instruction': 'Review synthetic work.'})
            for worker in list(self.app.workers):
                worker.join(3)
                self.assertFalse(worker.is_alive())
            self.assertEqual('running', self.app.tasks[started['id']]['status'])
            self.assertTrue(self.client.started.is_set())

    def test_atomic_cascade_preserves_other_tasks_plans_awards_and_source(self):
        other = self.add_task('completed')
        marker = self.root / 'source.txt'
        marker.write_text('Synthetic source remains.')
        rows = {
            'conversation': {'id': 'message', 'task_id': self.task['id']},
            'approval': {'id': 'approval', 'task_id': self.task['id'], 'status': 'unavailable'},
            'team_activity': {'id': 'child', 'parent_task_id': self.task['id'], 'status': 'unknown'},
            'attention_dismissal': {'id': self.task['id']},
            'recovery': {'id': self.task['id'], 'revision': 1, 'state': 'assessment_only'},
            'recovery_operation': {'id': 'operation', 'origin_task_id': self.task['id'],
                                   'target_task_id': other['id'], 'status': 'delivery_unknown'},
            'recovery_handoff': {'id': 'handoff', 'origin_task_id': self.task['id'], 'schema_version': 1},
            'assessment_context': {'id': self.task['id'], 'text': 'Synthetic context.'},
            'delivery_operation': {'id': 'delivery', 'subject_id': self.task['id'], 'task_id': other['id']},
        }
        maps = {'approval': self.app.approvals, 'team_activity': self.app.observed_tasks,
                'attention_dismissal': self.app.attention_dismissals, 'recovery': self.app.recoveries,
                'recovery_operation': self.app.recovery_operations, 'recovery_handoff': self.app.recovery_handoffs,
                'delivery_operation': self.app.delivery_operations}
        for kind, row in rows.items():
            self.app.store.put(kind, row)
            if kind in maps:
                maps[kind][row['id']] = row
        self.app.messages.append(rows['conversation'])
        self.app.store.put('check_plan', {'id': self.project['id'], 'version': 1})
        self.app.store.put('award', {'id': 'existing-award', 'source_task': self.task['id']})
        self.client.requests.clear()
        self.app.delete_task(self.task['id'], self.payload())
        for kind in rows:
            self.assertEqual([], self.app.store.load(kind), kind)
        self.assertEqual([other['id']], [row['id'] for row in self.app.store.load('task')])
        self.assertIn(other['id'], self.app.tasks)
        self.assertEqual(1, len(self.app.store.load('check_plan')))
        self.assertEqual(1, len(self.app.store.load('award')))
        self.assertTrue(marker.is_file())
        self.assertEqual([], self.client.requests)

    def test_storage_failure_preserves_memory_records_and_hold(self):
        before = deepcopy(self.app.tasks)
        with patch.object(self.app.store, 'put_many', side_effect=sqlite3.OperationalError('Synthetic save failure')):
            with self.assertRaises(FileAccessError) as caught:
                self.app.delete_task(self.task['id'], self.payload())
        self.assertEqual(503, caught.exception.status)
        self.assertEqual(before, self.app.tasks)
        self.assertEqual([self.task], self.app.store.load('task'))
        self.assertTrue(self.app.active_project_roots())

    def test_stale_root_child_and_recovery_revisions_reject_confirmation(self):
        changes = [lambda: self.task.update(updated_at='later'),
                   lambda: self.app.observed_tasks.update({'child': {'id': 'child', 'parent_task_id': self.task['id'], 'status': 'unknown'}}),
                   lambda: self.app.recoveries.update({self.task['id']: {'id': self.task['id'], 'revision': 2}})]
        for change in changes:
            payload = self.payload()
            change()
            with self.assertRaises(FileAccessError) as caught:
                self.app.delete_task(self.task['id'], payload)
            self.assertEqual(409, caught.exception.status)
            self.assertIn(self.task['id'], self.app.tasks)

    def test_known_active_or_busy_state_blocks_but_historical_unknown_operation_does_not(self):
        checks = [
            (lambda: self.task.update(status='running'), lambda: self.task.update(status='unknown')),
            (lambda: self.app.launching_tasks.add(self.task['id']), lambda: self.app.launching_tasks.clear()),
            (lambda: self.app.message_busy.add(self.task['id']), lambda: self.app.message_busy.clear()),
            (lambda: self.app.recoveries.update({self.task['id']: {'id': self.task['id'], 'state': 'checking'}}), lambda: self.app.recoveries.clear()),
            (lambda: self.app.approvals.update({'a': {'id': 'a', 'task_id': self.task['id'], 'status': 'pending'}}), lambda: self.app.approvals.clear()),
            (lambda: self.app.observed_tasks.update({'c': {'id': 'c', 'parent_task_id': self.task['id'], 'status': 'running'}}), lambda: self.app.observed_tasks.clear()),
            (lambda: self.app.owned_threads.update({'old': {'task_id': self.task['id'], 'parent': None, 'active': True, 'turns': set()}}), lambda: self.app.owned_threads.clear()),
        ]
        for prepare, restore in checks:
            prepare()
            with self.assertRaises(FileAccessError) as caught:
                self.app.delete_task(self.task['id'], self.payload())
            self.assertEqual(409, caught.exception.status)
            restore()
        self.app.recovery_operations['old-op'] = {'id': 'old-op', 'origin_task_id': self.task['id'], 'status': 'delivery_unknown'}
        self.assertTrue(self.app.task_deletion_state(self.task)['can_delete'])

    def test_late_events_and_old_metadata_cannot_resurrect_deleted_run(self):
        self.app.owned_threads[self.task['thread_id']] = {'task_id': self.task['id'], 'parent': None,
                'active': False, 'turns': {'old-turn'}, 'current_turn': 'old-turn'}
        self.app.delete_task(self.task['id'], self.payload())
        self.app.on_message({'method': 'thread/started', 'params': {'thread': {'id': 'late-child',
                              'parentThreadId': self.task['thread_id'], 'agentRole': 'backend_developer'}}})
        self.app.on_message({'method': 'turn/completed', 'params': {'threadId': self.task['thread_id'],
                              'turn': {'id': 'old-turn', 'status': 'completed'}}})
        self.app._read_child_metadata({'threadId': self.task['thread_id'], 'childThreadId': 'late-child', 'taskId': self.task['id']})
        self.app._append_message(self.task['id'], 'agent', 'Late synthetic result.', 'old-turn', self.task['thread_id'])
        with self.assertRaises(ValueError):
            self.app._register_thread('late-child', self.task['id'])
        self.assertEqual([], self.app.store.load('task'))
        self.assertEqual([], self.app.store.load('conversation'))
        self.assertEqual([], self.app.store.load('team_activity'))
        self.assertEqual([], self.app.active_project_roots())

    def test_restart_keeps_deleted_run_and_hold_absent(self):
        self.app.delete_task(self.task['id'], self.payload())
        self.app.close()
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.assertNotIn(self.task['id'], self.app.tasks)
        self.assertEqual([], self.app.active_project_roots())
        self.assertEqual([], self.app.snapshot()['tasks'])

    def test_exact_confirmation_and_http_same_origin(self):
        for payload in ({}, {**self.payload(), 'extra': True}, {**self.payload(), 'confirmed': 1}):
            with self.assertRaises(ValueError):
                self.app.delete_task(self.task['id'], payload)
        server = make_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            endpoint = '/api/tasks/' + self.task['id'] + '/delete'
            body = json.dumps(self.payload())
            connection.request('POST', endpoint, body, {'Content-Type': 'application/json', 'Origin': 'https://example.invalid'})
            self.assertEqual(403, connection.getresponse().status)
            connection.close()
            connection.request('POST', endpoint, body, {'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:' + str(server.server_port)})
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            self.assertEqual({'task_id': self.task['id'], 'deleted': True}, json.loads(response.read()))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(3)
