"""Independent recovery acceptance using synthetic RPC; no native integration proof."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from dashboard.codex_client import RequestRejected
from dashboard.project_files import FileAccessError
from dashboard.recovery import digest
from dashboard.recovery_capabilities import RecoveryCapabilities
from tests import test_recovery as fixtures


class RecoveryMetadataAcceptance(unittest.TestCase):
    setUp_fixture = fixtures.RecoveryTests.setUp
    tearDown = fixtures.RecoveryTests.tearDown
    summary = fixtures.RecoveryTests.summary
    check = fixtures.RecoveryTests.check
    wait = fixtures.RecoveryTests.wait
    assess = fixtures.RecoveryTests.assess
    finish = fixtures.RecoveryTests.finish
    plan = fixtures.RecoveryTests.plan
    continuation = fixtures.RecoveryTests.continuation

    def setUp(self):
        self.setUp_fixture()
        self.loaded = {'data': [], 'nextCursor': None}
        self.states = {'old-thread': 'notLoaded', 'child-a': 'notLoaded', 'child-b': 'notLoaded'}
        self.goal_fault = False
        self.goal_unresolved = False
        self.background_fault = False
        self.private_marker = 'SYNTHETIC_NATIVE_TEXT_MUST_NOT_PERSIST'
        self.client.process = None
        self.client.on_message = self.app.on_message
        self.client.connect = lambda: setattr(self.client, 'process', object())
        self.client.request_readonly = self.request
        self.provider = RecoveryCapabilities()
        self.app.recovery_capabilities = self.provider
        self.app.runtime_owner = SimpleNamespace(exclusive=True, owner_id='a' * 32, boot_id='b' * 64)
        self.assertTrue(self.provider.connect_and_observe_startup(
            self.client, digest([self.app.recovery_epoch, id(self.client)])))
        self.summary()
        self.app.recoveries[self.origin['id']]['restart'] = {'planned': True, 'pre_boot_id': 'c' * 64}
        self.client.requests.clear()

    def request(self, method, params, *, timeout=30):
        self.client.requests.append((method, deepcopy(params)))
        if method == 'thread/loaded/list':
            return deepcopy(self.loaded)
        if method == 'thread/read':
            identifier = params['threadId']
            return {'thread': {'id': identifier, 'cwd': str(self.root), 'ephemeral': False,
                'parentThreadId': None if identifier == 'old-thread' else 'old-thread',
                'status': {'type': self.states[identifier]}, 'preview': self.private_marker}}
        if method == 'thread/turns/list':
            return {'data': [{'id': 'old-turn', 'status': 'interrupted', 'items': []}], 'nextCursor': None}
        if method == 'thread/list':
            return {'data': [] if params['archived'] else [
                {'id': identifier, 'parentThreadId': 'old-thread', 'cwd': str(self.root)}
                for identifier in ('child-a', 'child-b')], 'nextCursor': None}
        if method == 'thread/goal/get':
            if self.goal_fault:
                raise RequestRejected(self.private_marker)
            if self.goal_unresolved and params['threadId'] == 'child-b':
                return {'goal': {'threadId': 'child-b', 'status': 'inProgress'}}
            return {'goal': None}
        if method == 'thread/backgroundTerminals/list':
            if self.states[params['threadId']] == 'notLoaded' or self.background_fault:
                raise RequestRejected(self.private_marker)
            return {'data': [], 'nextCursor': None}
        self.fail('Unexpected operation in effects-free metadata test: ' + method)

    def assert_blocked(self, result):
        self.assertEqual('unverified', result['execution_clearance'])
        self.assertFalse(result['actions']['continue'])
        self.assertEqual('unknown', self.origin['status'])
        self.assertTrue(self.origin['recovery_hold'])

    def test_not_loaded_parent_and_children_have_complete_metadata_without_loaded_only_rpc(self):
        result = self.check()
        self.assertEqual('complete', result['coverage'])
        self.assertEqual('quiescent', result['execution_clearance'], result['reason_codes'])
        self.assertEqual({'count': 2, 'unresolved': 0}, result['children'])
        self.assertEqual('unknown', self.origin['status'])
        self.assertTrue(self.origin['recovery_hold'])
        self.assertNotIn('thread/backgroundTerminals/list', [method for method, _ in self.client.requests])
        self.assertEqual(3, sum(method == 'thread/goal/get' for method, _ in self.client.requests))
        self.assertNotIn(self.private_marker, json.dumps(result))
        self.assertNotIn(self.private_marker.encode(), (self.root / 'state/dashboard.sqlite3').read_bytes())

    def test_complete_metadata_before_boot_fence_remains_assessment_only(self):
        self.app.recoveries[self.origin['id']]['restart'] = None
        result = self.check()
        self.assertEqual('complete', result['coverage'])
        self.assertEqual({'count': 2, 'unresolved': 0}, result['children'])
        self.assert_blocked(result)
        self.assertIn('boot_fence_required', result['reason_codes'])
        self.assertTrue(result['actions']['assess'])

    def test_goal_unresolved_child_remains_counted_after_inventory_absence(self):
        self.goal_unresolved = True
        result = self.check()
        self.assert_blocked(result)
        self.assertIn('goal_unresolved', result['reason_codes'])
        self.assertEqual({'count': 2, 'unresolved': 1}, result['children'])

    def test_idle_loaded_root_still_requires_background_check(self):
        self.states['old-thread'] = 'idle'
        self.loaded['data'] = ['old-thread']
        self.assert_blocked(self.check())
        self.assertIn('thread/backgroundTerminals/list', [method for method, _ in self.client.requests])

    def test_unrelated_loaded_work_blocks_even_when_old_threads_are_not_loaded(self):
        self.loaded['data'] = ['other-work']
        self.assert_blocked(self.check())

    def test_incomplete_malformed_or_duplicate_inventory_never_establishes_absence(self):
        cases = [None, {'data': [], 'nextCursor': 'next'}, {'data': ['same', 'same'], 'nextCursor': None},
                 {'data': [None], 'nextCursor': None}, {'data': 'bad', 'nextCursor': None},
                 {'data': ['x' + str(i) for i in range(257)], 'nextCursor': None}]
        for response in cases:
            with self.subTest(response_type=type(response).__name__):
                self.loaded = response
                self.assert_blocked(self.check())

    def test_goal_failure_retains_parent_and_discovered_children_without_native_error_text(self):
        self.goal_fault = True
        result = self.check()
        self.assert_blocked(result)
        self.assertEqual('partial', result['coverage'])
        self.assertEqual({'count': 2, 'unresolved': 2}, result['children'])
        self.assertIn('goal_get_failed', result['reason_codes'])
        self.assertTrue(any(row['kind'] == 'root_runtime' for row in result['observations']))
        self.assertNotIn(self.private_marker, json.dumps(result))

    def test_final_preflight_rechecks_inventory_and_blocks_new_work(self):
        self.assertEqual('quiescent', self.check()['execution_clearance'])
        before = len(self.client.requests)
        self.loaded['data'] = ['new-work']
        with self.assertRaises(FileAccessError) as error:
            self.app._fresh_dispatch_clearance(self.origin['id'])
        self.assertEqual(409, error.exception.status)
        self.assertIn('thread/loaded/list', [method for method, _ in self.client.requests[before:]])
        self.assertFalse(any(method in {'thread/start', 'thread/resume', 'turn/start'}
                             for method, _ in self.client.requests))

    def test_explicit_approved_plan_can_continue_through_owned_attachment(self):
        original = self.client.request
        def mutation(method, params, timeout=30):
            result = original(method, params, timeout=timeout)
            if method == 'thread/start':
                self.loaded['data'].append(result['thread']['id'])
            return result
        self.client.request = mutation
        payload = self.continuation()
        self.app.recovery_continue(self.origin['id'], payload)
        self.wait()
        result = self.summary()
        self.assertEqual('acknowledged', result['operation']['status'])
        self.assertEqual(1, sum(method == 'thread/start' for method, _ in self.client.requests))
        self.assertEqual(1, sum(method == 'turn/start' for method, _ in self.client.requests))
        self.assertEqual('unknown', self.origin['status'])
        target = self.app.tasks[result['operation']['target_task_id']]
        self.finish(target)
        self.assertEqual('completed', target['status'])

    def test_current_inventory_cannot_waive_boot_owner_or_external_activity_guards(self):
        for guard in ('boot', 'owner', 'external'):
            with self.subTest(guard=guard):
                self.app.recoveries[self.origin['id']]['restart'] = {
                    'planned': True, 'pre_boot_id': 'b' * 64 if guard == 'boot' else 'c' * 64}
                self.app.runtime_owner.exclusive = guard != 'owner'
                self.origin['external_activity_unresolved'] = guard == 'external'
                self.assert_blocked(self.check())


if __name__ == '__main__':
    unittest.main()
