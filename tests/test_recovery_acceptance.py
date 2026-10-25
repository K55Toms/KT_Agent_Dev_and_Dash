"""Independent journey acceptance using synthetic transports, never native proof.

Real account sign-in, inference, native execution and external outcomes are not
exercised. Directory recovery checks move only disposable empty test directories.
"""
from copy import deepcopy
from types import SimpleNamespace
import threading
import time
import unittest
import uuid

from dashboard.codex_client import RequestRejected
from dashboard.project_files import FileAccessError
from dashboard.recovery import digest
from dashboard.recovery_capabilities import RecoveryCapabilities
from tests import test_recovery as fixtures


class RecoveryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests('runTest')
        self.fixture.setUp()
        self.app = self.fixture.app
        self.client = self.fixture.client
        self.origin = self.fixture.origin

    def tearDown(self):
        self.fixture.tearDown()

    def test_assessment_questions_plan_explicit_approval_checked_request_and_completion(self):
        f = self.fixture
        checked = f.check()
        self.assertTrue(checked['actions']['assess'])
        self.assertFalse(any(method in {'thread/start', 'turn/start', 'turn/steer'}
                             for method, _ in self.client.requests))
        assessment, _ = f.assess()
        for question in ('Which facts are directly observed?', 'What should I preserve?'):
            self.app.send_message(assessment['id'], {'text': question,
                'expected_turn_id': assessment['turn_id']})
            f.wait()
        self.assertEqual(3, len(f.assessment.calls))
        self.assertFalse(any(method in {'model/list', 'thread/start', 'turn/start', 'turn/steer'}
                             for method, _ in self.client.requests))
        summary = f.summary()
        planned = self.app.recovery_plan(self.origin['id'], {
            'expected_revision': summary['revision'], 'assessment_task_id': assessment['id'],
            'instruction': 'Preserve existing changes and implement the reviewed missing behavior.',
            'target_strategy': 'new_linked', 'role': 'backend_developer'})
        checked = f.check()
        payload = {'receipt_id': checked['receipt_id'], 'operation_id': uuid.uuid4().hex,
            'assessment_task_id': assessment['id'], 'plan_id': planned['plan']['id'],
            'plan_digest': planned['plan']['digest'], 'confirmed': True}
        with self.assertRaises(ValueError):
            self.app.recovery_continue(self.origin['id'], {**payload, 'confirmed': False})
        self.app.recovery_continue(self.origin['id'], payload)
        f.wait()
        target = self.app.tasks[f.summary()['operation']['target_task_id']]
        self.assertEqual('running', target['status'])
        self.assertTrue(target['recovery_manual'])
        self.assertEqual(self.origin['id'], target['origin_task_id'])
        self.assertNotEqual(assessment['id'], target['id'])
        self.app.on_message({'id': 801, 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': target['thread_id'], 'turnId': target['turn_id'], 'itemId': 'checked-runtime-action',
            'startedAtMs': 1, 'command': '/usr/bin/true', 'cwd': str(f.root), 'reason': 'Verify the reviewed synthetic action',
            'availableDecisions': ['accept', 'decline', 'cancel']}})
        approval = next(a for a in self.app.approvals.values() if a['task_id'] == target['id'])
        review = self.app.review_approval(approval['id'])
        self.assertIn('/usr/bin/true', str(review))
        self.app.respond_approval(approval['id'], {'decision': 'accept', 'review_id': review['review_id']})
        self.assertIn((801, {'decision': 'accept'}), self.client.responses)
        with self.assertRaises(ValueError):
            self.app.respond_approval(approval['id'], {'decision': 'accept', 'review_id': review['review_id']})
        f.finish(target)
        self.assertEqual('completed', target['status'])
        self.assertEqual('unknown', self.origin['status'])
        self.assertEqual('recovery_assessment', assessment['task_purpose'])
        self.assertTrue(self.app.conversation(target['id'])['can_send'])

    def test_new_assessment_answer_invalidates_previously_reviewed_plan(self):
        f = self.fixture
        payload = f.continuation()
        assessment = self.app.tasks[f.summary()['assessment']['task_id']]
        self.app.send_message(assessment['id'], {'text': 'Account for an additional unresolved effect.',
            'expected_turn_id': assessment['turn_id']})
        f.wait()
        checked = f.check()
        before = sum(method == 'turn/start' for method, _ in self.client.requests)
        with self.assertRaises(FileAccessError):
            self.app.recovery_continue(self.origin['id'], {**payload, 'receipt_id': checked['receipt_id']})
        self.assertEqual(before, sum(method == 'turn/start' for method, _ in self.client.requests))
        self.assertEqual('unknown', self.origin['status'])

    def test_recovered_native_request_decline_cancel_and_stale_accept_are_distinct(self):
        f = self.fixture
        self.app.recovery_continue(self.origin['id'], f.continuation())
        f.wait()
        target = self.app.tasks[f.summary()['operation']['target_task_id']]
        def request(rpc):
            self.app.on_message({'id': rpc, 'method': 'item/commandExecution/requestApproval', 'params': {
                'threadId': target['thread_id'], 'turnId': target['turn_id'], 'itemId': 'action-' + str(rpc),
                'startedAtMs': 1, 'command': '/usr/bin/true', 'cwd': str(f.root),
                'availableDecisions': ['accept', 'decline', 'cancel']}})
            return list(self.app.approvals.values())[-1]
        declined = request(811)
        self.app.respond_approval(declined['id'], {'decision': 'decline'})
        self.assertIn((811, {'decision': 'decline'}), self.client.responses)
        cancelled = request(812)
        self.app.respond_approval(cancelled['id'], {'decision': 'cancel'})
        self.assertIn((812, {'decision': 'cancel'}), self.client.responses)
        stale = request(813)
        review = self.app.review_approval(stale['id'])
        f.finish(target)
        before = len(self.client.responses)
        with self.assertRaises(ValueError):
            self.app.respond_approval(stale['id'], {'decision': 'accept', 'review_id': review['review_id']})
        self.assertEqual(before, len(self.client.responses))
        self.assertEqual('unknown', self.origin['status'])

    def test_native_disconnection_keeps_restricted_assessment_questions_usable(self):
        f = self.fixture
        self.app.client = None
        self.app.connection['status'] = 'disconnected'
        assessment, _ = f.assess()
        conversation = self.app.conversation(assessment['id'])
        self.assertTrue(conversation['can_send'])
        self.assertEqual('assessment', conversation['send_mode'])
        self.app.send_message(assessment['id'], {'text': 'Which observations are still missing?',
            'expected_turn_id': assessment['turn_id']})
        f.wait()
        self.assertEqual(2, len(f.assessment.calls))
        self.assertEqual('completed', assessment['status'])
        self.assertFalse(self.app.conversation(self.origin['id'])['can_send'])
        self.assertEqual([], self.client.requests)
        self.assertEqual('unknown', self.origin['status'])

    def _bind_disposable_project(self):
        path = self.fixture.root / ('project-' + uuid.uuid4().hex)
        path.mkdir()
        project = self.app.add_project({'name': 'Disposable recovery project', 'path': str(path)})
        self.origin['project_id'] = project['id']
        self.client.project_path = str(path)
        self.app.store.put('task', self.origin)
        return path

    def _assert_broken_directory_assessment_and_plan_boundary(self):
        f = self.fixture
        before = len(self.client.requests)
        checked = f.check()
        self.assertIn('project_binding_unavailable', checked['reason_codes'])
        self.assertEqual('unverified', checked['execution_clearance'])
        assessment, _ = f.assess()
        self.assertEqual('completed', assessment['status'])
        for question in ('What remains uncertain about the old work?', 'What needs human review next?'):
            self.app.send_message(assessment['id'], {'text': question,
                'expected_turn_id': assessment['turn_id']})
            f.wait()
            self.assertEqual('completed', assessment['status'])
            self.assertTrue(self.app.conversation(assessment['id'])['can_send'])
        self.assertEqual(3, len(f.assessment.calls))
        summary = f.summary()
        with self.assertRaises(FileAccessError):
            self.app.recovery_plan(self.origin['id'], {'expected_revision': summary['revision'],
                'assessment_task_id': assessment['id'], 'instruction': 'Review the current directory before any work.',
                'target_strategy': 'new_linked', 'role': 'backend_developer'})
        self.assertEqual(before, len(self.client.requests))
        self.assertEqual('unknown', self.origin['status'])
        self.assertTrue(self.origin['recovery_hold'])

    def test_missing_project_directory_still_allows_repeated_checked_assessment(self):
        path = self._bind_disposable_project()
        path.rename(path.with_name(path.name + '-moved'))
        self._assert_broken_directory_assessment_and_plan_boundary()

    def test_replaced_project_directory_still_allows_repeated_checked_assessment(self):
        path = self._bind_disposable_project()
        path.rename(path.with_name(path.name + '-original'))
        path.mkdir()
        self._assert_broken_directory_assessment_and_plan_boundary()

    def test_directory_loss_after_assessment_does_not_wedge_followup_composer(self):
        path = self._bind_disposable_project()
        assessment, _ = self.fixture.assess()
        path.rename(path.with_name(path.name + '-moved'))
        before = len(self.client.requests)
        for question in ('The directory has moved; explain the limitation.', 'Can we still review checked history?'):
            self.app.send_message(assessment['id'], {'text': question,
                'expected_turn_id': assessment['turn_id']})
            self.fixture.wait()
            self.assertEqual('completed', assessment['status'])
            self.assertTrue(self.app.conversation(assessment['id'])['can_send'])
        self.assertEqual(3, len(self.fixture.assessment.calls))
        self.assertEqual(before, len(self.client.requests))
        self.assertEqual('unknown', self.origin['status'])
        self.assertNotIn(assessment['id'], self.app.message_busy)

    def test_assessment_followup_obeys_active_run_limit_then_succeeds_when_slot_frees(self):
        assessment, _ = self.fixture.assess()
        roots = []
        for _ in range(3):
            task = deepcopy(self.origin)
            task.update(id=uuid.uuid4().hex, title='Synthetic concurrent work', status='running',
                recovery_hold=False, thread_id=None, turn_id=None)
            roots.append(task)
            self.app.tasks[task['id']] = task
            self.app.store.put('task', task)
        conversation = self.app.conversation(assessment['id'])
        self.assertFalse(conversation['can_send'])
        before = deepcopy((self.app.tasks, self.app.recoveries, self.app.recovery_operations, self.app.messages))
        calls = len(self.fixture.assessment.calls)
        with self.assertRaises(ValueError):
            self.app.send_message(assessment['id'], {'text': 'Ask again after capacity becomes available.',
                'expected_turn_id': assessment['turn_id']})
        self.assertEqual(before, (self.app.tasks, self.app.recoveries, self.app.recovery_operations, self.app.messages))
        self.assertEqual(calls, len(self.fixture.assessment.calls))
        self.assertNotIn(assessment['id'], self.app.message_busy)
        roots[0]['status'] = 'completed'
        self.app.store.put('task', roots[0])
        self.assertTrue(self.app.conversation(assessment['id'])['can_send'])
        self.app.send_message(assessment['id'], {'text': 'Continue the restricted assessment question.',
            'expected_turn_id': assessment['turn_id']})
        self.fixture.wait()
        self.assertEqual(calls + 1, len(self.fixture.assessment.calls))
        self.assertEqual('completed', assessment['status'])
        self.assertEqual('unknown', self.origin['status'])

    def _start_synthetic_dashboard_connector(self):
        connected = threading.Event()
        class Client:
            def __init__(self, on_message, on_disconnect):
                self.on_message, self.on_disconnect = on_message, on_disconnect
                self.process = None
                self.closed = False
                self.requests = []
            def connect(self):
                self.process = object()
                self.requests.extend([('initialize', {}), ('initialized', {})])
            def request_readonly(self, method, params, *, timeout=30):
                return self.request(method, params, timeout=timeout)
            def request(self, method, params, timeout=30):
                if method != 'thread/loaded/list':
                    raise AssertionError('Connector attempted execution while recovering')
                self.requests.append((method, params))
                if len(self.requests) == 4:
                    connected.set()
                return {'data': [], 'nextCursor': None}
            def close(self):
                self.closed = True
        provider = RecoveryCapabilities()
        self.app.recovery_capabilities = provider
        self.app.client_factory = Client
        self.app.start()
        self.assertTrue(connected.wait(2))
        deadline = time.monotonic() + 2
        while self.app.connection['status'] != 'connected' and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertEqual('connected', self.app.connection['status'])
        return provider

    def test_dashboard_connector_observes_startup_before_connected_without_replaying_work(self):
        provider = self._start_synthetic_dashboard_connector()
        self.assertEqual(['initialize', 'initialized', 'thread/loaded/list', 'thread/loaded/list'],
            [method for method, _ in self.app.client.requests])
        self.assertEqual(self.app._recovery_connection_generation(self.app.client), provider._startup_generation)
        self.assertEqual('unknown', self.origin['status'])
        self.assertEqual(1, len(self.app.tasks))

    def test_stale_native_client_callbacks_cannot_mutate_current_task_or_disconnect_replacement(self):
        self._start_synthetic_dashboard_connector()
        stale = self.app.client
        current = fixtures.RecoveryClient(str(self.fixture.root))
        self.app.client = current
        self.origin.update(status='running', recovery_hold=False)
        self.app._register_thread(self.origin['thread_id'], self.origin['id'])
        owned = self.app._owned(self.origin['thread_id'])
        owned.update(current_turn=self.origin['turn_id'], turns={self.origin['turn_id']})
        self.app.store.put('task', self.origin)
        before = deepcopy((self.app.tasks, self.app.connection, self.app.recovery_event_revision))
        completed = {'method': 'turn/completed', 'params': {'threadId': self.origin['thread_id'],
            'turn': {'id': self.origin['turn_id'], 'status': 'completed'}}}
        stale.on_message(completed)
        stale.on_disconnect()
        self.assertEqual(before, (self.app.tasks, self.app.connection, self.app.recovery_event_revision))
        self.assertEqual('running', self.origin['status'])
        self.app._client_message(current, completed)
        self.assertEqual('completed', self.origin['status'])
        self.assertEqual('connected', self.app.connection['status'])
        self.app._client_disconnected(current)
        self.assertEqual('disconnected', self.app.connection['status'])
        stale.close()

    def test_current_native_callbacks_after_shutdown_flag_preserve_state(self):
        self.origin.update(status='running', recovery_hold=False)
        self.app._register_thread(self.origin['thread_id'], self.origin['id'])
        self.app._owned(self.origin['thread_id']).update(
            current_turn=self.origin['turn_id'], turns={self.origin['turn_id']})
        self.app.store.put('task', self.origin)
        before = deepcopy((self.app.tasks, self.app.connection, self.app.recovery_event_revision))
        self.app.stop.set()
        self.app._client_message(self.client, {'method': 'turn/completed', 'params': {
            'threadId': self.origin['thread_id'], 'turn': {'id': self.origin['turn_id'], 'status': 'completed'}}})
        self.app._client_disconnected(self.client)
        self.assertEqual(before, (self.app.tasks, self.app.connection, self.app.recovery_event_revision))
        self.assertEqual('running', next(task for task in self.app.store.load('task')
            if task['id'] == self.origin['id'])['status'])

    def _observe_synthetic_postboot_startup(self):
        """Real clearance implementation with fake OS owner and fake native protocol."""
        provider = RecoveryCapabilities()
        self.app.recovery_capabilities = provider
        self.app.runtime_owner = SimpleNamespace(exclusive=True, owner_id=uuid.uuid4().hex, boot_id='b' * 64)
        self.client.on_message = self.app.on_message
        self.client.process = None
        self.client.connect = lambda: setattr(self.client, 'process', object())
        original = self.client.request
        loaded = []
        def request(method, params, timeout=30):
            if method == 'thread/loaded/list':
                self.client.requests.append((method, params))
                return {'data': list(loaded), 'nextCursor': None}
            result = original(method, params, timeout=timeout)
            if method == 'thread/start':
                loaded.append(result['thread']['id'])
            return result
        self.client.request = request
        generation = digest([self.app.recovery_epoch, id(self.client)])
        self.assertTrue(provider.connect_and_observe_startup(self.client, generation))
        self.fixture.summary()
        record = self.app.recoveries[self.origin['id']]
        record['restart'] = {'planned': True, 'pre_boot_id': 'c' * 64}
        self.app.store.put('recovery', record)
        return request

    def test_missing_history_does_not_waive_loaded_conflict_or_arbitrary_protocol_errors(self):
        original = self._observe_synthetic_postboot_startup()
        def conflict(method, params, timeout=30):
            if method == 'thread/read':
                raise RequestRejected(code='thread_history_unavailable')
            if method == 'thread/loaded/list':
                return {'data': ['unknown-current-work'], 'nextCursor': None}
            return original(method, params, timeout=timeout)
        self.client.request = conflict
        checked = self.fixture.check()
        self.assertEqual('unverified', checked['execution_clearance'])
        self.assertTrue(checked['actions']['assess'])
        self.assertFalse(checked['actions']['continue'])
        def arbitrary(method, params, timeout=30):
            if method == 'thread/read':
                raise RequestRejected(code='request_rejected')
            return original(method, params, timeout=timeout)
        self.client.request = arbitrary
        checked = self.fixture.check()
        self.assertEqual('unverified', checked['execution_clearance'])
        self.assertEqual('unknown', self.origin['status'])

    def test_missing_history_after_verified_fence_has_usable_linked_fallback(self):
        original = self._observe_synthetic_postboot_startup()
        def missing(method, params, timeout=30):
            if method == 'thread/read':
                raise RequestRejected(code='thread_history_unavailable')
            return original(method, params, timeout=timeout)
        self.client.request = missing
        checked = self.fixture.check()
        self.assertEqual('quiescent', checked['execution_clearance'], checked['reason_codes'])
        payload = self.fixture.continuation()
        self.app.recovery_continue(self.origin['id'], payload)
        self.fixture.wait()
        self.assertEqual('acknowledged', self.fixture.summary()['operation']['status'])
        self.assertEqual('unknown', self.origin['status'])

    def test_absent_old_turn_after_verified_fence_does_not_require_fabricated_outcome(self):
        original = self._observe_synthetic_postboot_startup()
        def absent(method, params, timeout=30):
            if method == 'thread/turns/list':
                return {'data': [], 'nextCursor': None}
            return original(method, params, timeout=timeout)
        self.client.request = absent
        checked = self.fixture.check()
        self.assertEqual('quiescent', checked['execution_clearance'], checked['reason_codes'])
        self.assertEqual('unknown', self.origin['status'])
        self.assertIsNone(checked['last_turn'])


if __name__ == '__main__':
    unittest.main()
