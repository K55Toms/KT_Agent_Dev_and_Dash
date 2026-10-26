"""Independent acceptance: production gates with disposable Git/SQLite and synthetic native RPC.

No native model is started. Successful command events are synthetic protocol evidence,
not proof that a live Codex installation can execute the workflow.
"""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from dashboard.delivery import code_snapshot
from dashboard.ponytail_policy import PolicyError
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard, make_server
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient


class DeliveryAcceptance(unittest.TestCase):
    command = 'python3 -m unittest discover -s tests'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='delivery-acceptance-', dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.project_root = self.root / 'project'
        self.project_root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project_root)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.source = self.project_root / 'example.py'
        self.source.write_text('VALUE = 1\n')
        self.asset = self.project_root / 'asset.bin'
        self.asset.write_bytes(b'\x00SYNTHETIC_OPAQUE_ASSET\x01')
        subprocess.run(['git', '-C', str(self.project_root), 'add', 'example.py', 'asset.bin'], check=True)
        self.source.write_text('VALUE = 2\n')
        self.state = self.root / 'state'
        self.app = Dashboard(self.state, policy_provider=SyntheticPolicy())
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.project = self.app.add_project({'name': 'Isolated delivery acceptance', 'path': str(self.project_root)})
        self.http_server = self.http_thread = None

    def tearDown(self):
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
            self.http_thread.join(3)
        self.app.close()
        self.temp.cleanup()

    def wait_worker(self):
        # Launch performs bounded scanner subprocesses (12s each); four seconds
        # was shorter than one permitted scan under concurrent regression load.
        for worker in list(self.app.workers):
            worker.join(30)
            self.assertFalse(worker.is_alive(), "Synthetic launch did not finish within the scanner-aware test budget")

    def emit(self, task, method, **params):
        self.app.on_message({'method': method, 'params': {
            'threadId': task['thread_id'], 'turnId': task['turn_id'], **params}})

    def complete(self, task):
        self.emit(task, 'turn/completed', turn={'id': task['turn_id'], 'status': 'completed'})
        self.assertEqual('completed', task['status'])

    def approve_plan(self):
        return self.app.approve_check_plan(self.project['id'], {
            'expected_version': self.app.check_plan(self.project['id'])['version'],
            'commands': [self.command], 'confirmed': True})

    def subject(self, role='backend_developer'):
        self.approve_plan()
        row = self.app.start_task({'project_id': self.project['id'], 'title': 'Implement an isolated feature',
            'instruction': 'Implement the agreed isolated feature and preserve its acceptance criteria.', 'role': role})
        self.wait_worker()
        task = self.app.tasks[row['id']]
        self.assertEqual('running', task['status'], task.get('error'))
        self.complete(task)
        return task

    def checks(self, subject, *, approve=False, record=True, exit_code=0, forged=False):
        current = self.app.delivery(subject['id'])
        operation_id = uuid.uuid4().hex
        payload = {'expected_snapshot': current['snapshot_digest'], 'expected_plan_version': current['plan_version'],
            'operation_id': operation_id, 'confirmed': True}
        self.app.start_delivery_checks(subject['id'], payload)
        self.wait_worker()
        operation = self.app.delivery_operations[operation_id]
        runner = self.app.tasks[operation['task_id']]
        self.assertEqual('qa_engineer', runner['role'])
        self.assertNotEqual(subject['id'], runner['id'])
        item = {'type': 'commandExecution', 'id': 'check-item', 'command': self.command,
            'cwd': str(self.project_root), 'status': 'inProgress'}
        if record:
            if not forged:
                self.emit(runner, 'item/started', item=deepcopy(item))
            if approve:
                self.app.on_message({'id': 901, 'method': 'item/commandExecution/requestApproval', 'params': {
                    'threadId': runner['thread_id'], 'turnId': runner['turn_id'], 'itemId': item['id'],
                    'startedAtMs': 1, 'reason': 'Run the explicitly approved isolated check',
                    'command': self.command, 'cwd': str(self.project_root),
                    'availableDecisions': ['accept', 'decline', 'cancel']}})
                approval = next(row for row in self.app.approvals.values() if row['status'] == 'pending')
                self.assertEqual([], self.client.responses)
                context = self.app.review_approval(approval['id'])
                self.assertEqual(self.command, context['context']['command'])
                self.app.respond_approval(approval['id'], {'decision': 'accept', 'review_id': context['review_id']})
                self.assertEqual(901, self.client.responses[-1][0])
            item.update(status='completed', exitCode=exit_code, aggregatedOutput='SYNTHETIC_NATIVE_OUTPUT_MUST_NOT_PERSIST')
            self.emit(runner, 'item/completed', item=item)
        else:
            self.emit(runner, 'item/completed', item={'type': 'agentMessage', 'id': 'claimed-results',
                'text': 'All checks passed.'})
        self.app.wait_conversations()
        self.complete(runner)
        return payload, runner

    def review(self, subject):
        current = self.app.delivery(subject['id'])
        operation_id = uuid.uuid4().hex
        self.app.start_delivery_review(subject['id'], {'expected_snapshot': current['snapshot_digest'],
            'check_operation_id': current['check_operation']['id'], 'operation_id': operation_id, 'confirmed': True})
        self.wait_worker()
        runner = self.app.tasks[self.app.delivery_operations[operation_id]['task_id']]
        self.assertEqual('code_quality_reviewer', runner['role'])
        self.assertNotEqual(subject['id'], runner['id'])
        self.emit(runner, 'item/completed', item={'type': 'agentMessage', 'id': 'independent-review',
            'phase': 'final_answer', 'text': 'Reviewed current implementation. No findings. <script>Literal text.</script>'})
        self.app.wait_conversations()
        self.complete(runner)
        preview = self.app.delivery_review(subject['id'], operation_id)
        return preview, runner

    def decision(self, preview, choice='accept'):
        return {'review_id': preview['review_id'], 'receipt_id': preview['receipt_id'],
            'review_digest': preview['review_digest'], 'expected_snapshot': preview['snapshot_digest'],
            'decision': choice, 'confirmed': True}

    def ready(self):
        subject = self.subject()
        self.checks(subject)
        preview, _runner = self.review(subject)
        result = self.app.delivery_review_decision(subject['id'], self.decision(preview))
        self.assertEqual('ready', result['status'])
        return subject, preview

    def test_dirty_project_and_opaque_asset_complete_full_human_approved_journey(self):
        subject = self.subject()
        self.assertEqual('completed', subject['status'])
        self.assertEqual('awaiting_checks', self.app.delivery(subject['id'])['status'])
        self.checks(subject, approve=True)
        self.assertEqual('awaiting_review', self.app.delivery(subject['id'])['status'])
        preview, _ = self.review(subject)
        self.assertIn('<script>Literal text.</script>', preview['messages'][0]['text'])
        self.assertNotEqual('ready', self.app.delivery(subject['id'])['status'])
        result = self.app.delivery_review_decision(subject['id'], self.decision(preview))
        self.assertEqual('ready', result['status'])
        self.assertEqual('completed', subject['status'])
        self.assertNotIn(b'SYNTHETIC_NATIVE_OUTPUT_MUST_NOT_PERSIST', (self.state / 'dashboard.sqlite3').read_bytes())

    def test_agent_claim_or_completion_without_started_native_item_cannot_pass_checks(self):
        for record, forged in ((False, False), (True, True)):
            with self.subTest(record=record, forged=forged):
                subject = self.subject()
                self.checks(subject, record=record, forged=forged)
                current = self.app.delivery(subject['id'])
                self.assertEqual('checks_failed', current['status'])
                self.assertFalse(current['actions']['start_review'])

    def test_failed_native_check_cannot_be_replaced_with_claimed_pass(self):
        subject = self.subject()
        self.checks(subject, exit_code=1)
        self.assertEqual('checks_failed', self.app.delivery(subject['id'])['status'])

    def test_replayed_operation_is_idempotent_and_rebound_payload_rejected(self):
        subject = self.subject()
        payload, _ = self.checks(subject)
        count = len(self.app.tasks)
        self.app.start_delivery_checks(subject['id'], deepcopy(payload))
        self.assertEqual(count, len(self.app.tasks))
        altered = {**payload, 'expected_snapshot': '0' * 64}
        with self.assertRaises(FileAccessError):
            self.app.start_delivery_checks(subject['id'], altered)
        self.assertEqual(count, len(self.app.tasks))

    def test_explicit_rejection_and_forged_or_consumed_receipts_never_authorize_ready(self):
        subject = self.subject()
        self.checks(subject)
        preview, _ = self.review(subject)
        forged = {**self.decision(preview), 'receipt_id': 'f' * 32}
        with self.assertRaises(FileAccessError):
            self.app.delivery_review_decision(subject['id'], forged)
        result = self.app.delivery_review_decision(subject['id'], self.decision(preview, 'reject'))
        self.assertEqual('changes_requested', result['status'])
        with self.assertRaises(FileAccessError):
            self.app.delivery_review_decision(subject['id'], self.decision(preview))

    def test_source_asset_path_mode_and_plan_changes_invalidate_evidence(self):
        subject, _ = self.ready()
        initial = self.app.delivery(subject['id'])['snapshot_digest']
        self.source.write_text('VALUE = 3\n')
        self.assertEqual('stale', self.app.delivery(subject['id'])['status'])
        self.source.write_text('VALUE = 2\n')
        self.asset.write_bytes(b'\x00CHANGED_OPAQUE_ASSET\x01')
        self.assertEqual('stale', self.app.delivery(subject['id'])['status'])
        self.asset.write_bytes(b'\x00SYNTHETIC_OPAQUE_ASSET\x01')
        extra = self.project_root / 'new.py'
        extra.write_text('NEW = True\n')
        self.assertEqual('stale', self.app.delivery(subject['id'])['status'])
        extra.unlink()
        self.source.chmod(0o755)
        self.assertNotEqual(initial, self.app.delivery(subject['id'])['snapshot_digest'])
        self.assertEqual('stale', self.app.delivery(subject['id'])['status'])
        self.source.chmod(0o644)
        self.approve_plan()
        self.assertEqual('stale', self.app.delivery(subject['id'])['status'])

    def test_policy_unavailability_unknown_child_and_connection_change_block_readiness(self):
        subject, _ = self.ready()
        with patch.object(self.app.policy_provider, 'load', side_effect=PolicyError('Unavailable approved source.')):
            self.assertEqual('unverified', self.app.delivery(subject['id'])['status'])
        child = {'id': 'unknown-child', 'parent_task_id': subject['id'], 'role': None, 'status': 'completed'}
        self.app.observed_tasks[child['id']] = child
        self.assertEqual('unverified', self.app.delivery(subject['id'])['status'])
        self.app.observed_tasks.clear()
        self.app.client = FakeClient()
        self.assertEqual('stale', self.app.delivery(subject['id'])['status'])

    def test_role_spoof_and_changed_code_between_preview_and_accept_reject(self):
        subject = self.subject()
        self.checks(subject)
        preview, reviewer = self.review(subject)
        reviewer['role'] = 'backend_developer'
        self.assertNotEqual('ready', self.app.delivery(subject['id'])['status'])
        with self.assertRaises(FileAccessError):
            self.app.delivery_review_decision(subject['id'], self.decision(preview))
        reviewer['role'] = 'code_quality_reviewer'
        preview = self.app.delivery_review(subject['id'], preview['review_id'])
        self.source.write_text('VALUE = 99\n')
        with self.assertRaises(FileAccessError):
            self.app.delivery_review_decision(subject['id'], self.decision(preview))

    def test_restart_retains_check_plan_but_cannot_restore_delivery_authority(self):
        subject, _ = self.ready()
        self.app.close()
        self.app = Dashboard(self.state, policy_provider=SyntheticPolicy())
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.assertEqual([self.command], [row['command'] for row in self.app.check_plan(self.project['id'])['commands']])
        self.assertNotEqual('ready', self.app.delivery(subject['id'])['status'])

    def test_legacy_task_stays_explicitly_unenforced(self):
        subject = self.subject()
        subject.pop('compliance_policy')
        self.assertEqual('not_enforced', self.app.delivery(subject['id'])['status'])
        self.assertFalse(self.app.delivery(subject['id'])['actions']['run_checks'])

    def test_tracked_file_is_not_hidden_by_ignore_rule_and_links_fail_closed(self):
        before = code_snapshot(self.project)
        (self.project_root / '.gitignore').write_text('example.py\n')
        one = code_snapshot(self.project)
        self.source.write_text('VALUE = 4\n')
        two = code_snapshot(self.project)
        self.assertNotEqual(before, one)
        self.assertNotEqual(one, two)
        self.source.unlink()
        self.source.symlink_to(self.asset)
        with self.assertRaises(FileAccessError):
            code_snapshot(self.project)

    def test_scanner_failure_withholds_current_snapshot_and_complete_review(self):
        subject = self.subject()
        self.checks(subject)
        preview, _ = self.review(subject)
        with patch('dashboard.delivery.scan_preview', side_effect=FileAccessError(503, 'SYNTHETIC_PRIVATE_ERROR')):
            current = self.app.delivery(subject['id'])
            self.assertEqual('unverified', current['status'])
            self.assertNotIn('SYNTHETIC_PRIVATE_ERROR', json.dumps(current))
            with self.assertRaises(FileAccessError):
                self.app.delivery_review(subject['id'], preview['review_id'])

    def test_http_origin_schema_and_server_only_role_context_are_enforced(self):
        self.http_server = make_server(self.app, 0)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()
        port = self.http_server.server_port
        path = '/api/projects/' + self.project['id'] + '/check-plan'
        def request(data, origin):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            connection.request('POST', path, body=json.dumps(data), headers={
                'Content-Type': 'application/json', 'Origin': origin})
            response = connection.getresponse()
            status = response.status
            response.read()
            connection.close()
            return status
        valid = {'expected_version': 0, 'commands': [self.command], 'confirmed': True}
        self.assertEqual(403, request(valid, 'https://example.invalid'))
        self.assertEqual(0, self.app.check_plan(self.project['id'])['version'])
        self.assertEqual(400, request({**valid, 'delivery_context': {}}, 'http://127.0.0.1:' + str(port)))
        self.assertEqual(200, request(valid, 'http://127.0.0.1:' + str(port)))
