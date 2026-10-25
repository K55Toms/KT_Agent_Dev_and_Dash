"""Independent audit acceptance: disposable storage and synthetic protocol, never native proof."""
from copy import deepcopy
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from dashboard.codex_client import CodexClient, ProtocolError
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard
from tests import test_conversation as conversation_fixtures
from tests import test_recovery as recovery_fixtures


class AuditRecoveryAcceptance(unittest.TestCase):
    setUp = recovery_fixtures.RecoveryTests.setUp
    tearDown = recovery_fixtures.RecoveryTests.tearDown

    def inventory(self, count, fault=None):
        """Split a nested lineage across archived and live pagination independently."""
        rows = [{'id': 'acceptance-child-' + str(n),
                 'parentThreadId': 'old-thread' if n == 0 else 'acceptance-child-' + str(n - 1),
                 'cwd': str(self.root)} for n in range(count)]
        by_id = {row['id']: row for row in rows}
        calls = []
        def request(method, params, *, timeout=30):
            calls.append((method, deepcopy(params)))
            if method == 'thread/list':
                group = rows[::2] if not params['archived'] else rows[1::2]
                offset = int(params.get('cursor', '0'))
                page = deepcopy(group[offset:offset + 40])
                next_cursor = str(offset + 40) if offset + 40 < len(group) else None
                if fault == 'cursor':
                    next_cursor = '0'
                if fault == 'lineage' and page:
                    page[-1]['parentThreadId'] = 'unobserved-parent'
                return {'data': page, 'nextCursor': next_cursor}
            if method == 'thread/read':
                row = by_id[params['threadId']]
                status = 'active' if fault == 'active' and row == rows[-1] else 'idle'
                return {'thread': {**row, 'ephemeral': False, 'status': {'type': status}}}
            if method == 'thread/goal/get':
                return {'goal': None}
            if method == 'thread/backgroundTerminals/list':
                return {'data': [], 'nextCursor': None}
            self.fail('Unexpected metadata operation: ' + method)
        self.client.request_readonly = request
        return calls

    def test_original_twenty_five_child_case_checks_every_child_without_mutation(self):
        calls = self.inventory(25)
        reasons, _, children, complete = self.app._activity_metadata(self.client, self.origin, self.project)
        self.assertEqual([], reasons)
        self.assertTrue(complete)
        self.assertEqual({'count': 25, 'unresolved': 0}, children)
        self.assertEqual(25, sum(method == 'thread/read' for method, _ in calls))
        self.assertEqual({'thread/list', 'thread/read', 'thread/goal/get',
                          'thread/backgroundTerminals/list'}, {method for method, _ in calls})
        self.assertEqual('unknown', self.origin['status'])
        self.assertTrue(self.origin['recovery_hold'])

    def test_one_hundred_twenty_five_nested_children_both_archives_and_all_pages(self):
        calls = self.inventory(125)
        reasons, _, children, complete = self.app._activity_metadata(self.client, self.origin, self.project)
        self.assertTrue(complete)
        self.assertEqual([], reasons)
        self.assertEqual({'count': 125, 'unresolved': 0}, children)
        pages = [params for method, params in calls if method == 'thread/list']
        self.assertEqual([False, False, True, True], [page['archived'] for page in pages])
        self.assertEqual(125, len({params['threadId'] for method, params in calls if method == 'thread/read'}))

    def test_inventory_over_two_hundred_fifty_six_cannot_claim_complete_coverage(self):
        self.inventory(257)
        reasons, _, _, complete = self.app._activity_metadata(self.client, self.origin, self.project)
        self.assertFalse(complete)
        self.assertIn('check_limit', reasons)

    def test_repeated_cursor_and_missing_lineage_fail_closed(self):
        for fault, expected in [('cursor', 'check_limit'), ('lineage', 'ownership_unverified')]:
            with self.subTest(fault=fault):
                calls = self.inventory(25, fault)
                reasons, _, _, complete = self.app._activity_metadata(self.client, self.origin, self.project)
                self.assertFalse(complete)
                self.assertIn(expected, reasons)
                self.assertLessEqual(sum(method == 'thread/list' for method, _ in calls), 8)

    def test_active_descendant_is_observed_but_never_cleared(self):
        self.inventory(25, 'active')
        reasons, _, children, _ = self.app._activity_metadata(self.client, self.origin, self.project)
        self.assertIn('active_descendant', reasons)
        self.assertEqual(1, children['unresolved'])

    def test_elapsed_deadline_rejects_even_successful_metadata_response(self):
        calls = self.inventory(25)
        with patch('dashboard.recovery.time.monotonic', side_effect=[9, 11]):
            with self.assertRaises(ProtocolError):
                self.app._activity_metadata(self.client, self.origin, self.project, deadline=10)
        self.assertEqual(1, len(calls))

    def test_storage_failure_publishes_nothing_and_retry_starts_exactly_once(self):
        self.app.tasks.clear()
        self.app.store.delete('task', self.origin['id'])
        payload = {'project_id': self.project['id'], 'title': 'Acceptance retry',
                   'instruction': 'Inspect synthetic fixture', 'role': 'backend_developer'}
        with patch.object(self.app.store, 'put', side_effect=sqlite3.OperationalError('Synthetic unavailable storage')):
            with self.assertRaises(FileAccessError) as error:
                self.app.start_task(payload)
        self.assertEqual(503, error.exception.status)
        self.assertEqual({}, self.app.tasks)
        self.assertEqual([], self.app.workers)
        self.assertEqual([], self.client.requests)
        created = self.app.start_task(payload)
        for worker in self.app.workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual([created['id']], list(self.app.tasks))
        self.assertEqual(1, sum(method == 'thread/start' for method, _ in self.client.requests))
        self.assertEqual(1, sum(method == 'turn/start' for method, _ in self.client.requests))

    def test_project_save_failure_leaves_registration_retry_available(self):
        directory = self.root / 'another-project'
        directory.mkdir()
        before = deepcopy(self.app.projects)
        payload = {'name': 'Synthetic registration retry', 'path': str(directory)}
        with patch.object(self.app.store, 'put', side_effect=sqlite3.OperationalError('Synthetic unavailable storage')):
            with self.assertRaises(FileAccessError) as error:
                self.app.add_project(payload)
        self.assertEqual(503, error.exception.status)
        self.assertEqual(before, self.app.projects)
        self.assertEqual(len(before), len(self.app.store.load('project')))
        created = self.app.add_project(payload)
        self.assertEqual(str(directory), self.app.projects[created['id']]['path'])
        self.assertEqual(len(before) + 1, len(self.app.store.load('project')))


class AuditChildAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixture = conversation_fixtures.NativeConversationTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_completed_parent_unknown_role_child_remains_recoverable_and_blocks_effects_after_restart(self):
        fixture = self.fixture
        parent = fixture.start()
        fixture.metadata_client(parent, agentRole='unrecognized')
        fixture.modern_child(parent)
        fixture.app.wait_conversations()
        fixture.event(parent, 'turn/completed', turn={'id': parent['turn_id'], 'status': 'completed'})
        fixture.app.disconnected()
        fixture.app.close()
        fixture.app = Dashboard(fixture.root / 'state')
        fixture.app.client = fixture.client
        fixture.client.closed = False
        fixture.app.connection['status'] = 'connected'
        saved = fixture.app.tasks[parent['id']]
        self.assertEqual('completed', saved['status'])
        self.assertTrue(fixture.app.conversation(parent['id'])['recovery_available'])
        self.assertTrue(next(iter(fixture.app.snapshot()['tasks']))['recovery_available'])
        self.assertEqual('unknown', next(iter(fixture.app.observed_tasks.values()))['status'])
        self.assertIn(fixture.root, fixture.app.active_project_roots())
        prior = len(fixture.client.requests)
        with self.assertRaises(ValueError):
            fixture.app.start_task({'project_id': fixture.project['id'], 'title': 'Another task',
                'instruction': 'Inspect fixture', 'role': 'backend_developer'})
        with self.assertRaises(ValueError):
            fixture.app.send_message(parent['id'], {'text': 'Continue', 'expected_turn_id': parent['turn_id']})
        service = Mock()
        fixture.app.git_service = service
        with self.assertRaises(FileAccessError) as error:
            fixture.app.publish_project(fixture.project['id'], {'confirmed': True})
        self.assertEqual(409, error.exception.status)
        service.publish.assert_not_called()
        self.assertEqual(prior, len(fixture.client.requests))

    def test_normal_completion_without_unresolved_children_stays_replyable_without_recovery(self):
        fixture = self.fixture
        parent = fixture.start()
        fixture.event(parent, 'turn/completed', turn={'id': parent['turn_id'], 'status': 'completed'})
        conversation = fixture.app.conversation(parent['id'])
        self.assertFalse(conversation['recovery_available'])
        self.assertEqual('followup', conversation['send_mode'])
        fixture.app.send_message(parent['id'], {'text': 'Inspect another synthetic requirement',
                                               'expected_turn_id': parent['turn_id']})
        fixture.app.wait_conversations()
        self.assertEqual(2, sum(method == 'turn/start' for method, _ in fixture.client.requests))


class AuditTimeoutAcceptance(unittest.TestCase):
    def test_real_pipe_read_timeout_preserves_other_work_but_mutation_timeout_is_fatal(self):
        script = '''import json,sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    if method in ('initialize', 'turn/start'):
        print(json.dumps({'id': message['id'], 'result': {'ok': True}}), flush=True)
'''
        disconnected = threading.Event()
        def factory(_argv, **kwargs):
            return subprocess.Popen([sys.executable, '-u', '-c', script], **kwargs)
        client = CodexClient(lambda _message: None, disconnected.set, process_factory=factory)
        try:
            client.connect()
            with self.assertRaises(ProtocolError):
                client.request_readonly('thread/read', {'threadId': 'synthetic-root', 'includeTurns': False}, timeout=.05)
            self.assertFalse(client.closed)
            self.assertFalse(disconnected.is_set())
            self.assertIsNone(client.process.poll())
            self.assertEqual({'ok': True}, client.request('turn/start', {}, timeout=1))
            with self.assertRaises(ProtocolError):
                client.request('turn/interrupt', {}, timeout=.05)
            self.assertTrue(client.closed)
            self.assertTrue(disconnected.wait(2))
            self.assertFalse(client.pending)
        finally:
            client.close()
