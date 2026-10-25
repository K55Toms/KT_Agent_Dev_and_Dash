"""Deterministic recovery protocol tests. Capabilities are injected fakes, not native proof."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from dashboard.codex_client import ProtocolError
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard
from tests.test_dashboard_backend import FakeClient


class FakeRecoveryCapabilities:
    """Explicit test double: never installed into a production Dashboard."""
    def __init__(self):
        self.contract_digest = 'a' * 64
        self.cleared = True
        self.assessment = True
        self.checks = 0

    def describe(self):
        return {'assessment': self.assessment, 'same_thread': False, 'new_linked': True}

    def clearance(self, **_kwargs):
        self.checks += 1
        return {'cleared': self.cleared, 'reason_codes': [] if self.cleared else ['activity_unverified']}

    def assessment_options(self, task, project, role):
        return {'cwd': project['path'], 'model': role['model'], 'approvalPolicy': 'never',
                'approvalsReviewer': 'user', 'permissions': 'assessment-' + task['id'],
                'runtimeWorkspaceRoots': [project['path']], 'ephemeral': False,
                'config': {'test_only_capability': True}}

    def validate_assessment(self, response, task, project):
        return response.get('approvalPolicy') == 'never' and response.get('cwd') == project['path']


class RecoveryClient(FakeClient):
    def __init__(self, project_path):
        super().__init__()
        self.project_path = project_path
        self.lose_start = False
        self.metadata_marker = 'PRIVATE_NATIVE_TRANSCRIPT_MUST_NOT_PERSIST'
        self.turn_counter = 0

    def request(self, method, params, timeout=30):
        if method == 'thread/read':
            self.requests.append((method, deepcopy(params)))
            return {'thread': {'id': params['threadId'], 'cwd': self.project_path, 'ephemeral': False,
                               'parentThreadId': None, 'status': {'type': 'idle'},
                               'preview': self.metadata_marker, 'path': self.metadata_marker}}
        if method == 'thread/turns/list':
            self.requests.append((method, deepcopy(params)))
            return {'data': [{'id': 'old-turn', 'status': 'completed', 'items': []}], 'nextCursor': None}
        if method in {'thread/list', 'thread/backgroundTerminals/list'}:
            self.requests.append((method, deepcopy(params)))
            return {'data': [], 'nextCursor': None}
        if method == 'thread/goal/get':
            self.requests.append((method, deepcopy(params)))
            return {'goal': None}
        if method == 'thread/start':
            if self.lose_start:
                self.requests.append((method, deepcopy(params)))
                raise ProtocolError('Synthetic lost acknowledgement')
            result = super().request(method, params)
            result['approvalPolicy'] = params.get('approvalPolicy')
            return result
        if method == 'turn/start':
            self.requests.append((method, deepcopy(params)))
            self.turn_counter += 1
            return {'turn': {'id': 'new-turn-' + str(self.turn_counter), 'status': 'inProgress'}}
        return super().request(method, params)


class FakeAssessmentError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class FakeAssessmentTransport:
    """Synthetic effects-free transport; never an App Server or real model call."""
    contract_digest = 'b' * 64

    def __init__(self):
        self.generation = 1
        self.authenticated = True
        self.plan_enabled = True
        self.calls = []
        self.fail_code = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def status(self):
        return {'state': 'authenticated' if self.authenticated else 'signed_out',
            'authenticated': self.authenticated, 'plan_enabled': self.plan_enabled,
            'generation': self.generation, 'error_code': None, 'registration': None,
            'remote_revocation_confirmed': None}

    def assess(self, task, history, instruction, cancel):
        generation = self.generation
        self.calls.append({'task': deepcopy(task), 'history': deepcopy(history), 'instruction': instruction})
        self.entered.set()
        while not self.release.wait(.01):
            if cancel.is_set():
                raise FakeAssessmentError('cancelled')
            if generation != self.generation:
                raise FakeAssessmentError('auth_changed')
        if cancel.is_set():
            raise FakeAssessmentError('cancelled')
        if self.fail_code:
            raise FakeAssessmentError(self.fail_code)
        return {'text': 'Observed local result; external effects remain unknown.', 'usage': None,
                'model': task['model'], 'auth_generation': generation}

    def commit_if_current(self, generation, callback):
        if generation != self.generation or not self.authenticated or not self.plan_enabled:
            raise FakeAssessmentError('auth_changed')
        return callback()

    def start_auth(self):
        self.generation += 1
        self.authenticated = False
        return {'authorization_url': 'https://auth.openai.com/api/accounts/authorize', 'expires_in': 60}

    def cancel_auth(self):
        self.generation += 1

    def sign_out(self):
        self.generation += 1
        self.authenticated = False
        return self.status()

    def close(self):
        self.generation += 1
        self.authenticated = False
        self.release.set()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.caps = FakeRecoveryCapabilities()
        self.assessment = FakeAssessmentTransport()
        self.app = Dashboard(self.root / 'state', recovery_capabilities=self.caps, assessment_transport=self.assessment)
        self.client = RecoveryClient(str(self.root))
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.project = self.app.add_project({'name': 'Recovery fixture', 'path': str(self.root)})
        self.scan = patch('dashboard.conversation.scan_preview', lambda _data: None)
        self.scan.start()
        self.origin = {'id': uuid.uuid4().hex, 'project_id': self.project['id'], 'title': 'Unknown task',
            'role': 'backend_developer', 'model': 'gpt-6.1-sol', 'reasoning': 'high', 'status': 'unknown',
            'thread_id': 'old-thread', 'turn_id': 'old-turn', 'plan': [], 'created_at': '2026-10-19',
            'updated_at': '2026-10-19', 'error': None, 'diagnostics': [], 'usage': None,
            'cost': {'basis': 'unknown', 'credits': None}, 'task_purpose': 'development', 'recovery_hold': True}
        self.app.tasks[self.origin['id']] = self.origin
        self.app.store.put('task', self.origin)

    def tearDown(self):
        self.app.close()
        self.scan.stop()
        self.temp.cleanup()

    def summary(self):
        return self.app.recovery(self.origin['id'])

    def check(self):
        return self.app.recovery_check(self.origin['id'], {'expected_revision': self.summary()['revision']})

    def wait(self):
        for worker in list(self.app.workers):
            worker.join(3)
            self.assertFalse(worker.is_alive())

    def assess(self):
        checked = self.check()
        payload = {'receipt_id': checked['receipt_id'], 'operation_id': uuid.uuid4().hex,
                   'selected_message_ids': [], 'text': 'Explain the observed changes and what remains unknown.', 'confirmed': True}
        self.app.recovery_assess(self.origin['id'], payload)
        self.wait()
        task = self.app.tasks[self.summary()['assessment']['task_id']]
        return task, payload

    def finish(self, task, text='Observed local result; external outcome remains unknown.'):
        if task.get('task_purpose') == 'recovery_assessment':
            self.wait()
            return
        self.app.on_message({'method': 'item/completed', 'params': {'threadId': task['thread_id'],
            'turnId': task['turn_id'], 'item': {'id': uuid.uuid4().hex, 'type': 'agentMessage', 'text': text}}})
        self.app.wait_conversations()
        self.app.on_message({'method': 'turn/completed', 'params': {'threadId': task['thread_id'],
            'turn': {'id': task['turn_id'], 'status': 'completed'}}})

    def plan(self):
        task, _ = self.assess()
        self.finish(task)
        summary = self.summary()
        return self.app.recovery_plan(self.origin['id'], {'assessment_task_id': task['id'],
            'expected_revision': summary['revision'], 'instruction': 'Inspect existing changes, then implement only the missing behavior.',
            'target_strategy': 'new_linked', 'role': 'backend_developer'})

    def continuation(self):
        summary = self.plan()
        checked = self.check()
        return {'receipt_id': checked['receipt_id'], 'operation_id': uuid.uuid4().hex,
                'assessment_task_id': summary['assessment']['task_id'], 'plan_id': summary['plan']['id'],
                'plan_digest': summary['plan']['digest'], 'confirmed': True}

    def test_metadata_check_no_inference_no_transcripts_no_status_relabel(self):
        summary = self.check()
        self.assertEqual('quiescent', summary['execution_clearance'])
        self.assertEqual('unknown', self.origin['status'])
        self.assertEqual(['thread/read', 'thread/turns/list', 'thread/list', 'thread/list',
                          'thread/goal/get', 'thread/backgroundTerminals/list'], [m for m, _ in self.client.requests])
        self.assertNotIn(self.client.metadata_marker, json.dumps(summary))
        self.assertNotIn(self.client.metadata_marker.encode(), (self.root / 'state/dashboard.sqlite3').read_bytes())
        self.assertEqual('notLoaded', self.client.requests[1][1]['itemsView'])

    def test_unknown_hold_blocks_new_start_publication_and_generic_message(self):
        with self.assertRaises(ValueError):
            self.app.start_task({'project_id': self.project['id'], 'title': 'Other work', 'instruction': 'New development', 'role': 'backend_developer'})
        self.assertIsNone(self.app._send_state(self.origin)[0])
        self.app._register_thread('old-thread', self.origin['id'])
        self.assertIsNone(self.app._send_state(self.origin)[0])
        self.assertIn(self.root, self.app.active_project_roots())

    def test_assessment_repeated_followups_while_original_stays_unknown(self):
        task, _ = self.assess()
        self.assertEqual('recovery_assessment', task['task_purpose'])
        self.finish(task)
        self.assertEqual('reviewable', self.summary()['assessment']['status'])
        for question in ('What is directly observed?', 'What needs checking next?'):
            response = self.app.send_message(task['id'], {'text': question, 'expected_turn_id': task['turn_id']})
            self.assertEqual('queued', response['status'])
            self.finish(task)
        self.assertEqual('unknown', self.origin['status'])
        self.assertTrue(self.origin['recovery_hold'])
        with self.assertRaises(FileAccessError):
            self.app.recovery(task['id'])

    def test_duplicate_assessment_operation_and_changed_payload(self):
        _, payload = self.assess()
        count = len(self.assessment.calls)
        self.app.recovery_assess(self.origin['id'], payload)
        self.assertEqual(count, len(self.assessment.calls))
        with self.assertRaises(FileAccessError):
            self.app.recovery_assess(self.origin['id'], {**payload, 'text': 'Different instruction'})

    def test_human_approval_exact_plan_fresh_check_then_new_linked_execution(self):
        payload = self.continuation()
        checks = self.caps.checks
        self.app.recovery_continue(self.origin['id'], payload)
        self.wait()
        summary = self.summary()
        self.assertGreater(self.caps.checks, checks)
        self.assertEqual('acknowledged', summary['operation']['status'])
        target = self.app.tasks[summary['operation']['target_task_id']]
        self.assertEqual('development', target['task_purpose'])
        self.assertEqual(self.origin['id'], target['origin_task_id'])
        self.assertTrue(target['recovery_manual'])
        self.assertEqual('unknown', self.origin['status'])
        self.assertNotEqual('old-thread', target['thread_id'])
        starts = [p for m, p in self.client.requests if m == 'turn/start']
        self.assertIn('reviewed fresh plan', starts[-1]['input'][0]['text'])
        before = len(starts)
        self.app.recovery_continue(self.origin['id'], payload)
        self.assertEqual(before, sum(m == 'turn/start' for m, _ in self.client.requests))
        self.finish(target)
        self.assertEqual('completed', target['status'])

    def test_plan_edit_invalidates_prior_receipt_and_digest(self):
        payload = self.continuation()
        summary = self.summary()
        updated = self.app.recovery_plan(self.origin['id'], {'expected_revision': summary['revision'],
            'expected_plan_version': summary['plan']['version'], 'instruction': 'A materially different safe instruction.',
            'target_strategy': 'new_linked', 'role': 'backend_developer'}, summary['plan']['id'])
        self.assertEqual(2, updated['plan']['version'])
        self.assertNotEqual(payload['plan_digest'], updated['plan']['digest'])
        with self.assertRaises(FileAccessError):
            self.app.recovery_continue(self.origin['id'], payload)

    def test_unproven_capability_blocks_inference_but_allows_checked_evidence(self):
        self.assessment.authenticated = False
        summary = self.check()
        with self.assertRaises(FileAccessError):
            self.app.recovery_assess(self.origin['id'], {'receipt_id': summary['receipt_id'], 'operation_id': uuid.uuid4().hex,
                'selected_message_ids': [], 'text': 'Assess the evidence.', 'confirmed': True})
        self.assertFalse(any(m == 'thread/start' for m, _ in self.client.requests))

    def test_clearance_revoked_after_review_blocks_continuation(self):
        payload = self.continuation()
        self.caps.cleared = False
        before = sum(m == 'thread/start' for m, _ in self.client.requests)
        with self.assertRaises(FileAccessError):
            self.app.recovery_continue(self.origin['id'], payload)
        self.assertEqual(before, sum(m == 'thread/start' for m, _ in self.client.requests))

    def test_assessment_callbacks_and_rewards_cannot_grant_writes(self):
        task, _ = self.assess()
        self.app.on_message({'id': 441, 'method': 'item/fileChange/requestApproval', 'params': {
            'threadId': task['thread_id'], 'turnId': task['turn_id'], 'itemId': 'write'}})
        self.assertIn(441, self.client.rejections)
        self.assertFalse(any(a['task_id'] == task['id'] for a in self.app.approvals.values()))
        owned = self.app._owned(task['thread_id'])
        self.assertFalse(self.app._delegation_parent_live(owned))

    def test_lost_start_ack_persists_unknown_and_never_retries(self):
        checked = self.check()
        self.assessment.fail_code = 'delivery_unknown'
        payload = {'receipt_id': checked['receipt_id'], 'operation_id': uuid.uuid4().hex,
                   'selected_message_ids': [], 'text': 'Assess the current state.', 'confirmed': True}
        self.app.recovery_assess(self.origin['id'], payload)
        self.wait()
        self.assertEqual('delivery_unknown', self.summary()['operation']['status'])
        before = len(self.client.requests)
        self.app.recovery_assess(self.origin['id'], payload)
        self.assertEqual(before, len(self.client.requests))
        self.app.recovery_check(self.origin['id'], {'expected_revision': self.summary()['revision']})
        self.assertEqual('delivery_unknown', self.summary()['operation']['status'])

    def test_cancel_before_dispatch_prevents_native_requests(self):
        checked = self.check()
        with patch.object(self.app, '_start_recovery_worker'):
            summary = self.app.recovery_assess(self.origin['id'], {'receipt_id': checked['receipt_id'], 'operation_id': uuid.uuid4().hex,
                'selected_message_ids': [], 'text': 'Assess the evidence.', 'confirmed': True})
        op = summary['operation']
        result = self.app.recovery_cancel(self.origin['id'], op['id'], {'expected_revision': summary['revision'], 'confirmed': True})
        self.assertEqual('cancelled_before_dispatch', result['operation']['status'])
        task = self.app.tasks[op['target_task_id']]
        self.app._recovery_launch(self.client, task['id'], self.project, self.app.roles[task['role']], 'Assess only.')
        self.assertFalse(any(m == 'thread/start' for m, _ in self.client.requests))

    def test_annotation_never_clears_hold_or_changes_historical_outcome(self):
        result = self.app.recovery_disposition(self.origin['id'], {'expected_revision': self.summary()['revision'],
            'disposition': 'abandoned', 'note': 'Human reviewed effects independently.', 'confirmed': True})
        self.assertEqual('unknown', self.origin['status'])
        self.assertTrue(self.origin['recovery_hold'])
        self.assertEqual('unverified', result['execution_clearance'])

    def test_restart_migrates_unopened_unknown_children_and_never_installs_ownership(self):
        self.origin.pop('recovery_hold')
        self.origin['status'] = 'completed'
        self.app.store.put('task', self.origin)
        self.app.store.put('team_activity', {'id': 'unknown-child', 'parent_task_id': self.origin['id'],
            'project_id': self.project['id'], 'thread_id': 'lost-child', 'role': 'backend_developer',
            'title': 'Delegated work', 'status': 'unknown', 'updated_at': '2026-10-19'})
        self.app.close()
        self.app = Dashboard(self.root / 'state', recovery_capabilities=self.caps)
        self.assertTrue(self.app.tasks[self.origin['id']]['recovery_hold'])
        self.assertEqual({}, self.app.owned_threads)
        self.assertIn(self.root, self.app.active_project_roots())
        self.assertEqual({}, self.app.recoveries)

    def test_assessment_without_native_history_remains_useful(self):
        original = self.client.request
        def missing(method, params, timeout=30):
            if method == 'thread/read':
                raise ProtocolError('Synthetic missing native history')
            return original(method, params)
        self.client.request = missing
        task, _ = self.assess()
        self.assertEqual('completed', task['status'])
        self.assertEqual('unavailable', self.summary()['coverage'])
        self.finish(task, 'Native history is unavailable. These are the remaining questions.')
        self.assertEqual('reviewable', self.summary()['assessment']['status'])

    def test_receipt_expires_and_material_event_invalidates_it(self):
        summary = self.check()
        self.app.recovery_receipts[self.origin['id']]['created'] -= 61
        self.assertIsNone(self.summary()['receipt_id'])
        summary = self.check()
        self.app.on_message({'method': 'thread/started', 'params': {'thread': {'id': 'unrelated-metadata'}}})
        self.assertIsNone(self.summary()['receipt_id'])

    def test_cancel_during_attach_prevents_turn_dispatch_and_reports_attachment_only(self):
        payload = self.continuation()
        entered, release = threading.Event(), threading.Event()
        original = self.client.request
        def blocked(method, params, timeout=30):
            if method == 'thread/start':
                entered.set()
                release.wait(3)
            return original(method, params)
        self.client.request = blocked
        before = sum(m == 'turn/start' for m, _ in self.client.requests)
        self.app.recovery_continue(self.origin['id'], payload)
        self.assertTrue(entered.wait(2))
        summary = self.summary()
        try:
            cancelled = self.app.recovery_cancel(self.origin['id'], summary['operation']['id'],
                {'expected_revision': summary['revision'], 'confirmed': True})
            self.assertEqual('stop_requested', cancelled['operation']['status'])
        finally:
            release.set()
        self.wait()
        self.assertEqual(before, sum(m == 'turn/start' for m, _ in self.client.requests))
        self.assertEqual('cancelled_after_attach', self.summary()['operation']['status'])

    def test_hydrated_native_items_block_clearance_and_are_never_saved(self):
        original = self.client.request
        def hydrated(method, params, timeout=30):
            if method == 'thread/turns/list':
                return {'data': [{'id': 'old-turn', 'status': 'completed',
                    'items': [{'text': 'PRIVATE_TOOL_TRANSCRIPT'}]}], 'nextCursor': None}
            return original(method, params)
        self.client.request = hydrated
        result = self.check()
        self.assertEqual('unverified', result['execution_clearance'])
        self.assertIn('unexpected_hydrated_items', result['reason_codes'])
        self.assertNotIn(b'PRIVATE_TOOL_TRANSCRIPT', (self.root / 'state/dashboard.sqlite3').read_bytes())

    def test_source_activity_during_attach_blocks_actual_turn_dispatch(self):
        payload = self.continuation()
        original = self.client.request
        def changed(method, params, timeout=30):
            result = original(method, params, timeout=timeout)
            if method == 'thread/start':
                self.app.observed_tasks['late-child'] = {'id': 'late-child', 'parent_task_id': self.origin['id'],
                    'project_id': self.project['id'], 'thread_id': 'late-child-thread', 'role': 'backend_developer',
                    'status': 'running', 'title': 'Observed work', 'updated_at': '2026-10-22'}
                self.app._recovery_changed()
            return result
        self.client.request = changed
        before = sum(m == 'turn/start' for m, _ in self.client.requests)
        self.app.recovery_continue(self.origin['id'], payload)
        self.wait()
        self.assertEqual(before, sum(m == 'turn/start' for m, _ in self.client.requests))
        self.assertNotEqual('acknowledged', self.summary()['operation']['status'])
        self.assertTrue(self.app.tasks[self.origin['id']]['recovery_hold'])
        self.assertIn(self.root, self.app.active_project_roots())

    def test_own_verified_attach_notification_allows_fresh_final_clearance(self):
        payload = self.continuation()
        original = self.client.request
        def own_event(method, params, timeout=30):
            result = original(method, params, timeout=timeout)
            if method == 'thread/start':
                self.app.on_message({'method': 'thread/started', 'params': {'thread': {
                    'id': result['thread']['id'], 'parentThreadId': None}}})
            return result
        self.client.request = own_event
        self.app.recovery_continue(self.origin['id'], payload)
        self.wait()
        self.assertEqual('acknowledged', self.summary()['operation']['status'])

    def test_native_activity_in_final_check_blocks_turn_after_attachment(self):
        payload = self.continuation()
        original = self.client.request
        attached = False
        def active_on_final(method, params, timeout=30):
            nonlocal attached
            result = original(method, params, timeout=timeout)
            if method == 'thread/start':
                attached = True
            if method == 'thread/read' and attached:
                result['thread']['status'] = {'type': 'active'}
            return result
        self.client.request = active_on_final
        before = sum(m == 'turn/start' for m, _ in self.client.requests)
        self.app.recovery_continue(self.origin['id'], payload)
        self.wait()
        self.assertEqual(before, sum(m == 'turn/start' for m, _ in self.client.requests))
        self.assertTrue(self.app.tasks[self.origin['id']]['recovery_hold'])

    def test_failed_prepare_transaction_restores_memory_receipt_and_retry(self):
        self._assert_failed_prepare_retries('recovery_operation')

    def test_failed_prepared_message_transaction_leaves_no_phantom_operation(self):
        self._assert_failed_prepare_retries('conversation')

    def _assert_failed_prepare_retries(self, failed_kind):
        checked = self.check()
        payload = {'receipt_id': checked['receipt_id'], 'operation_id': uuid.uuid4().hex,
            'selected_message_ids': [], 'text': 'Assess current evidence.', 'confirmed': True}
        before_tasks = set(self.app.tasks)
        before_record = deepcopy(self.app.recoveries[self.origin['id']])
        self.app.store.db.execute("CREATE TRIGGER recovery_prepare_failure BEFORE INSERT ON records WHEN NEW.kind='" + failed_kind + "' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        self.app.store.db.commit()
        try:
            with self.assertRaises(FileAccessError) as error:
                self.app.recovery_assess(self.origin['id'], payload)
            self.assertEqual(503, error.exception.status)
            self.assertEqual(before_tasks, set(self.app.tasks))
            self.assertEqual(before_record, self.app.recoveries[self.origin['id']])
            self.assertNotIn(payload['operation_id'], self.app.recovery_operations)
            self.assertEqual(checked['receipt_id'], self.summary()['receipt_id'])
            self.assertFalse(any(m == 'thread/start' for m, _ in self.client.requests))
        finally:
            self.app.store.db.execute('DROP TRIGGER recovery_prepare_failure')
            self.app.store.db.commit()
        self.app.recovery_assess(self.origin['id'], payload)
        self.wait()
        self.assertEqual('acknowledged', self.summary()['operation']['status'])

    def test_terminal_and_old_operation_cancellation_cannot_poison_recovery(self):
        task, _ = self.assess()
        self.finish(task)
        before = self.summary()
        with self.assertRaises(FileAccessError):
            self.app.recovery_cancel(self.origin['id'], before['operation']['id'],
                {'expected_revision': before['revision'], 'confirmed': True})
        self.assertEqual(before, self.summary())
        self.assertTrue(self.summary()['actions']['review_plan'])
        old_op = before['operation']['id']
        self.assess()
        current = self.summary()
        with self.assertRaises(FileAccessError):
            self.app.recovery_cancel(self.origin['id'], old_op,
                {'expected_revision': current['revision'], 'confirmed': True})
        self.assertEqual(current, self.summary())

    def test_unknown_child_event_blocks_generic_composer_after_root_completes(self):
        self.origin.update(status='running', recovery_hold=False)
        self.app._register_thread('old-thread', self.origin['id'])
        owned = self.app._owned('old-thread')
        owned.update(current_turn='old-turn', turns={'old-turn'})
        self.app.on_message({'method': 'thread/started', 'params': {'thread': {'id': 'unknown-child-thread',
            'parentThreadId': 'old-thread', 'agentRole': 'backend_developer'}}})
        self.app.on_message({'method': 'item/completed', 'params': {'threadId': 'old-thread', 'turnId': 'old-turn',
            'item': {'id': 'child-event', 'type': 'collabAgentToolCall', 'status': 'completed',
                'senderThreadId': 'old-thread', 'receiverThreadIds': ['unknown-child-thread'],
                'agentsStates': {'unknown-child-thread': {'status': 'notFound'}}}}})
        self.app.wait_conversations()
        self.app.on_message({'method': 'turn/completed', 'params': {'threadId': 'old-thread',
            'turn': {'id': 'old-turn', 'status': 'completed'}}})
        self.assertEqual('completed', self.origin['status'])
        self.assertIn('unknown', [c['status'] for c in self.app.observed_tasks.values()])
        self.assertFalse(self.app.conversation(self.origin['id'])['can_send'])
        before = sum(m == 'turn/start' for m, _ in self.client.requests)
        with self.assertRaises(ValueError):
            self.app.send_message(self.origin['id'], {'text': 'Continue the work.', 'expected_turn_id': 'old-turn'})
        self.assertEqual(before, sum(m == 'turn/start' for m, _ in self.client.requests))

    def test_healthy_running_root_can_steer_while_known_child_runs(self):
        self.origin.update(status='running', recovery_hold=False)
        self.app._register_thread('old-thread', self.origin['id'])
        self.app._owned('old-thread').update(current_turn='old-turn', turns={'old-turn'})
        self.app.on_message({'method': 'thread/started', 'params': {'thread': {'id': 'healthy-child',
            'parentThreadId': 'old-thread', 'agentRole': 'backend_developer'}}})
        self.assertEqual(('steer', None), self.app._send_state(self.origin))
        self.app.on_message({'method': 'turn/completed', 'params': {'threadId': 'old-thread',
            'turn': {'id': 'old-turn', 'status': 'completed'}}})
        self.assertIsNone(self.app._send_state(self.origin)[0])

    def test_failed_check_closeout_keeps_recheck_available_without_receipt(self):
        self.summary()
        self.app.store.db.execute("CREATE TRIGGER check_closeout_failure BEFORE INSERT ON records WHEN NEW.kind='recovery' AND json_extract(NEW.body, '$.state')='needs_review' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        self.app.store.db.commit()
        try:
            with self.assertRaises(FileAccessError):
                self.check()
            summary = self.summary()
            self.assertEqual('blocked', summary['state'])
            self.assertTrue(summary['actions']['check'])
            self.assertIsNone(summary['receipt_id'])
        finally:
            self.app.store.db.execute('DROP TRIGGER check_closeout_failure')
            self.app.store.db.commit()
        self.assertEqual('quiescent', self.check()['execution_clearance'])

    def test_failed_dispatch_journal_write_keeps_provable_cancellation_path(self):
        checked = self.check()
        with patch.object(self.app, '_start_recovery_worker'):
            prepared = self.app.recovery_assess(self.origin['id'], {'receipt_id': checked['receipt_id'],
                'operation_id': uuid.uuid4().hex, 'selected_message_ids': [], 'text': 'Assess evidence.', 'confirmed': True})
        target = self.app.tasks[prepared['operation']['target_task_id']]
        self.app.store.db.execute("CREATE TRIGGER dispatch_stage_failure BEFORE INSERT ON records WHEN NEW.kind='recovery_operation' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        self.app.store.db.commit()
        try:
            self.app._recovery_launch(self.client, target['id'], self.project, self.app.roles[target['role']], 'Assess only.')
            op = self.app.recovery_operations[prepared['operation']['id']]
            self.assertEqual('prepared', op['status'])
            self.assertFalse(op['dispatched'])
            self.assertIn(self.root, self.app.active_project_roots())
            self.assertFalse(any(m == 'thread/start' for m, _ in self.client.requests))
        finally:
            self.app.store.db.execute('DROP TRIGGER dispatch_stage_failure')
            self.app.store.db.commit()
        summary = self.summary()
        cancelled = self.app.recovery_cancel(self.origin['id'], prepared['operation']['id'],
            {'expected_revision': summary['revision'], 'confirmed': True})
        self.assertEqual('cancelled_before_dispatch', cancelled['operation']['status'])

    def test_assessment_stop_blocks_all_guidance_until_transport_ends(self):
        self.assessment.release.clear()
        checked = self.check()
        self.app.recovery_assess(self.origin['id'], {'receipt_id': checked['receipt_id'],
            'operation_id': uuid.uuid4().hex, 'selected_message_ids': [], 'text': 'Assess evidence.', 'confirmed': True})
        self.assertTrue(self.assessment.entered.wait(2))
        task = self.app.tasks[self.summary()['assessment']['task_id']]
        self.assertIsNone(task['thread_id'])
        self.assertEqual('interrupt_requested', self.app.interrupt(task['id'], {})['status'])
        with self.assertRaises(ValueError):
            self.app.send_message(task['id'], {'text': 'Followup question.', 'expected_turn_id': task['turn_id']})
        self.wait()
        self.assertEqual('interrupted', task['status'])
        self.assertTrue(self.app.conversation(task['id'])['can_send'])
        self.assertFalse(any(m in {'model/list', 'thread/start', 'turn/start', 'turn/steer', 'turn/interrupt'}
                             for m, _ in self.client.requests))

    def test_attachment_journal_failure_preserves_no_turn_cancellation(self):
        payload = self.continuation()
        original = self.client.request
        def fail_after_attach(method, params, timeout=30):
            result = original(method, params, timeout=timeout)
            if method == 'thread/start':
                self.app.store.db.execute("CREATE TRIGGER attachment_failure BEFORE INSERT ON records WHEN NEW.kind='recovery_operation' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
                self.app.store.db.commit()
            return result
        self.client.request = fail_after_attach
        before = sum(m == 'turn/start' for m, _ in self.client.requests)
        self.app.recovery_continue(self.origin['id'], payload)
        self.wait()
        self.assertEqual(before, sum(m == 'turn/start' for m, _ in self.client.requests))
        self.assertIn(self.root, self.app.active_project_roots())
        self.app.store.db.execute('DROP TRIGGER attachment_failure')
        self.app.store.db.commit()
        summary = self.summary()
        result = self.app.recovery_cancel(self.origin['id'], summary['operation']['id'],
            {'expected_revision': summary['revision'], 'confirmed': True})
        self.assertEqual('cancelled_after_attach', result['operation']['status'])

    def test_initial_recovery_record_save_failure_returns_safe_retryable_state(self):
        self.app.store.db.execute("CREATE TRIGGER recovery_record_failure BEFORE INSERT ON records WHEN NEW.kind='recovery' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        self.app.store.db.commit()
        try:
            with self.assertRaises(FileAccessError) as error:
                self.summary()
            self.assertEqual(503, error.exception.status)
            self.assertNotIn(self.origin['id'], self.app.recoveries)
        finally:
            self.app.store.db.execute('DROP TRIGGER recovery_record_failure')
            self.app.store.db.commit()
        self.assertEqual('unchecked', self.summary()['state'])
