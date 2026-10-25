"""Audit regressions with disposable storage and metadata doubles; no native execution."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from dashboard.codex_client import ProtocolError
from dashboard.project_files import FileAccessError
from dashboard.recovery_capabilities import MAX_RECOVERY_DESCENDANTS
from dashboard.server import Dashboard
from tests import test_recovery as recovery_fixtures
from tests import test_conversation as conversation_fixtures


class AuditRecoveryMetadataTests(unittest.TestCase):
    setUp = recovery_fixtures.RecoveryTests.setUp
    tearDown = recovery_fixtures.RecoveryTests.tearDown

    def inventory(self, count=25, *, active=None, invalid=None):
        rows = [{'id': 'child-' + str(n), 'parentThreadId': 'old-thread', 'cwd': str(self.root)}
                for n in range(count)]
        calls = []
        def read(method, params, *, timeout=30):
            calls.append((method, deepcopy(params), timeout))
            if method == 'thread/list':
                if params['archived']:
                    return {'data': [], 'nextCursor': None}
                offset = 0 if invalid == 'cursor' else int(params.get('cursor', '0'))
                page = deepcopy(rows[offset:offset + 100])
                cursor = str(offset + 100) if offset + 100 < count else None
                if invalid == 'cursor':
                    cursor = 'repeat'
                    page = []
                elif invalid == 'duplicate' and offset == 100:
                    page.append({**rows[0], 'parentThreadId': 'foreign'})
                elif invalid == 'cycle' and page:
                    page[0]['parentThreadId'] = page[0]['id']
                return {'data': page, 'nextCursor': cursor}
            if method == 'thread/read':
                identifier = params['threadId']
                parent = None if identifier == 'old-thread' else 'old-thread'
                return {'thread': {'id': identifier, 'parentThreadId': parent,
                    'cwd': str(self.root), 'ephemeral': False,
                    'status': {'type': 'active' if identifier == active else 'idle'}}}
            if method == 'thread/turns/list':
                return {'data': [{'id': 'old-turn', 'status': 'completed', 'items': []}], 'nextCursor': None}
            if method == 'thread/goal/get':
                return {'goal': None}
            if method == 'thread/backgroundTerminals/list':
                return {'data': [], 'nextCursor': None}
            raise AssertionError(method)
        self.client.request_readonly = read
        return calls

    def test_twenty_five_idle_children_complete_fresh_metadata_check(self):
        calls = self.inventory()
        record = self.app._recovery_record(self.origin['id'])[1]
        reasons, _, _, children, complete, _ = self.app._collect_recovery_evidence(
            self.client, self.origin, self.project, record)
        self.assertEqual([], reasons)
        self.assertTrue(complete)
        self.assertEqual({'count': 25, 'unresolved': 0}, children)
        self.assertEqual(26, sum(method == 'thread/read' for method, _, _ in calls))
        self.assertTrue(all(0 < timeout <= 3 for _, _, timeout in calls))

    def test_persisted_child_missing_from_inventory_remains_counted_and_unresolved(self):
        self.inventory(0)
        self.origin['status'] = 'completed'
        child = {'id': 'persisted-child', 'parent_task_id': self.origin['id'],
                 'project_id': self.project['id'], 'thread_id': 'missing-child',
                 'parent_thread_id': 'old-thread', 'role': None, 'status': 'unknown'}
        self.app.store.put('team_activity', child)
        self.app.observed_tasks[child['id']] = child
        record = self.app._recovery_record(self.origin['id'])[1]
        reasons, _, _, children, complete, _ = self.app._collect_recovery_evidence(
            self.client, self.origin, self.project, record)
        self.assertEqual({'count': 1, 'unresolved': 1}, children)
        self.assertIn('descendant_unverified', reasons)
        self.assertIn('historical_descendant_unresolved', reasons)
        self.assertFalse(complete)
        self.assertTrue(self.app.recovery_hold_roots())

    def test_root_and_descendants_share_one_deadline(self):
        self.inventory()
        record = self.app._recovery_record(self.origin['id'])[1]
        with patch.object(self.app, '_bounded_metadata', wraps=self.app._bounded_metadata) as root_check, \
                patch.object(self.app, '_activity_metadata', wraps=self.app._activity_metadata) as child_check:
            self.app._collect_recovery_evidence(self.client, self.origin, self.project, record)
        self.assertEqual(root_check.call_args.args[3], child_check.call_args.args[3])

    def test_paginated_archived_and_unarchived_inventory_is_checked(self):
        calls = self.inventory(125)
        reasons, _, children, complete = self.app._activity_metadata(self.client, self.origin, self.project)
        self.assertEqual([], reasons)
        self.assertTrue(complete)
        self.assertEqual(125, children['count'])
        lists = [params for method, params, _ in calls if method == 'thread/list']
        self.assertEqual([False, False, True], [params['archived'] for params in lists])
        self.assertEqual('100', lists[1]['cursor'])
        self.assertTrue(all(params['useStateDbOnly'] is True for params in lists))

    def test_overflow_repeated_cursor_conflicting_identity_and_cycle_fail_closed(self):
        for count, invalid in ((MAX_RECOVERY_DESCENDANTS + 1, None), (1, 'cursor'),
                               (125, 'duplicate'), (25, 'cycle')):
            with self.subTest(count=count, invalid=invalid):
                calls = self.inventory(count, invalid=invalid)
                reasons, _, _, complete = self.app._activity_metadata(self.client, self.origin, self.project)
                self.assertFalse(complete)
                self.assertTrue({'check_limit', 'ownership_unverified'}.intersection(reasons))
                self.assertLessEqual(sum(method == 'thread/list' for method, _, _ in calls), 8)

    def test_active_child_and_expired_shared_deadline_do_not_clear(self):
        self.inventory(active='child-24')
        reasons, _, children, _ = self.app._activity_metadata(self.client, self.origin, self.project)
        self.assertIn('active_descendant', reasons)
        self.assertEqual(1, children['unresolved'])
        calls = self.inventory()
        with patch('dashboard.recovery.time.monotonic', return_value=13):
            with self.assertRaises(ProtocolError):
                self.app._activity_metadata(self.client, self.origin, self.project, deadline=12)
        self.assertEqual([], calls)

    def test_clearance_predicate_uses_shared_descendant_bound(self):
        from tests.test_recovery_capabilities import RecoveryCapabilityTests
        fixture = RecoveryCapabilityTests()
        fixture.setUp()
        for count, allowed in ((25, True), (MAX_RECOVERY_DESCENDANTS, True),
                               (MAX_RECOVERY_DESCENDANTS + 1, False)):
            fixture.children['count'] = count
            fixture.record['clearance_evidence']['observations'][1]['count'] = count
            self.assertEqual(allowed, fixture.check()['cleared'])

    def test_failed_initial_task_and_project_saves_publish_no_phantom_state(self):
        self.app.tasks.clear()
        self.app.store.delete('task', self.origin['id'])
        before_projects, before_workers = deepcopy(self.app.projects), list(self.app.workers)
        self.app.store.db.execute("""CREATE TRIGGER fail_initial_insert BEFORE INSERT ON records
            WHEN NEW.kind IN ('task', 'project') BEGIN
            SELECT RAISE(ABORT, 'Synthetic unavailable storage'); END""")
        with self.assertRaises(FileAccessError) as task_error:
            self.app.start_task({'project_id': self.project['id'], 'title': 'Safe fixture',
                'instruction': 'Inspect fixture', 'role': 'backend_developer'})
        self.assertEqual(503, task_error.exception.status)
        directory = self.root / 'another-project'
        directory.mkdir()
        with self.assertRaises(FileAccessError) as project_error:
            self.app.add_project({'name': 'Another fixture', 'path': str(directory)})
        self.assertEqual(503, project_error.exception.status)
        self.assertEqual({}, self.app.tasks)
        self.assertEqual(before_projects, self.app.projects)
        self.assertEqual(before_workers, self.app.workers)
        self.assertEqual([], self.client.requests)
        self.assertEqual([], self.app.store.load('task'))


class AuditChildPersistenceTests(unittest.TestCase):
    def test_failed_child_insert_preserves_durable_parent_hold(self):
        fixture = conversation_fixtures.NativeConversationTests()
        fixture.setUp()
        try:
            task = fixture.start()
            fixture.app.store.db.execute("""CREATE TRIGGER fail_child BEFORE INSERT ON records
                WHEN NEW.kind = 'team_activity' BEGIN
                SELECT RAISE(ABORT, 'Synthetic unavailable child storage'); END""")
            fixture.event(task, 'thread/started', thread={'id': 'unknown-child',
                'parentThreadId': task['thread_id'], 'agentRole': 'unrecognized'})
            self.assertTrue(fixture.app.runtime_tracking_lost)
            self.assertTrue(task['recovery_hold'])
            self.assertTrue(fixture.app.store.load('task')[0]['recovery_hold'])
            self.assertEqual([], fixture.app.store.load('team_activity'))
            fixture.app.store.db.execute('DROP TRIGGER fail_child')
        finally:
            fixture.tearDown()

    def test_unknown_role_child_holds_completed_parent_across_disconnect_and_restart(self):
        fixture = conversation_fixtures.NativeConversationTests()
        fixture.setUp()
        try:
            task = fixture.start()
            fixture.metadata_client(task, agentRole='unrecognized')
            fixture.modern_child(task)
            fixture.app.wait_conversations()
            fixture.event(task, 'turn/completed', turn={'id': task['turn_id'], 'status': 'completed'})
            fixture.app.disconnected()
            task_id, path = task['id'], fixture.root / 'state'
            self.assertEqual('completed', task['status'])
            self.assertTrue(fixture.app.conversation(task_id)['recovery_available'])
            activity = fixture.app.snapshot()['delegated_activities'][0]
            self.assertEqual('unknown', activity['status'])
            self.assertIsNone(activity['role'])
            self.assertEqual('Unattributed delegated task', activity['title'])
            fixture.app.close()
            fixture.app = Dashboard(path)
            self.assertTrue(fixture.app.snapshot()['tasks'][0]['recovery_available'])
            self.assertTrue(fixture.app.recovery_hold_roots())
            self.assertEqual({}, fixture.app.owned_threads)
            fixture.app.client = fixture.client
            fixture.client.closed = False
            fixture.app.connection['status'] = 'connected'
            with self.assertRaisesRegex(ValueError, 'overlapping'):
                fixture.app.start_task({'project_id': fixture.project['id'], 'title': 'Another task',
                    'instruction': 'Inspect fixture', 'role': 'backend_developer'})
        finally:
            fixture.tearDown()
