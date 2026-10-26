"""Author delivery checks with disposable Git storage and synthetic native messages."""
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from dashboard.delivery import code_snapshot
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient


class DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.project_root = self.root / 'project'
        self.project_root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project_root)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (self.project_root / 'feature.py').write_text('print("example")\n')
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.project = self.app.add_project({'name': 'Disposable delivery', 'path': str(self.project_root)})
        task = self.app.start_task({'project_id': self.project['id'], 'title': 'Implement feature',
            'instruction': 'Implement the agreed example feature.', 'role': 'backend_developer'})
        self.join()
        self.subject = self.app.tasks[task['id']]
        self.complete(self.subject)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def join(self):
        for worker in self.app.workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())

    def event(self, task, method, **params):
        self.app.on_message({'method': method, 'params': {'threadId': task['thread_id'],
            'turnId': task['turn_id'], **params}})

    def complete(self, task, status='completed'):
        self.event(task, 'turn/completed', turn={'id': task['turn_id'], 'status': status})

    def plan(self, commands=None):
        return self.app.approve_check_plan(self.project['id'], {'expected_version': self.app.check_plan(self.project['id'])['version'],
            'commands': ['python3 -m unittest'] if commands is None else commands, 'confirmed': True})

    def delivery(self):
        return self.app.delivery(self.subject['id'])

    def checks(self):
        current = self.delivery()
        result = self.app.start_delivery_checks(self.subject['id'], {'expected_snapshot': current['snapshot_digest'],
            'expected_plan_version': current['plan_version'], 'operation_id': uuid.uuid4().hex, 'confirmed': True})
        self.join()
        return self.app.tasks[result['check_operation']['task_id']]

    def command(self, task, command='python3 -m unittest', status='completed', exit_code=0, identifier='check-item', started=True):
        item = {'id': identifier, 'type': 'commandExecution', 'command': command,
            'cwd': self.project['path'], 'status': 'inProgress'}
        if started:
            self.event(task, 'item/started', item=deepcopy(item))
        item.update(status=status, exitCode=exit_code, aggregatedOutput='SYNTHETIC_PRIVATE_TOOL_OUTPUT')
        self.event(task, 'item/completed', item=item)

    def checked(self):
        self.plan()
        task = self.checks()
        self.command(task)
        self.complete(task)
        return self.delivery()

    def reviewed(self):
        current = self.checked()
        result = self.app.start_delivery_review(self.subject['id'], {'expected_snapshot': current['snapshot_digest'],
            'check_operation_id': current['check_operation']['id'], 'operation_id': uuid.uuid4().hex, 'confirmed': True})
        self.join()
        task = self.app.tasks[result['review_operation']['task_id']]
        self.event(task, 'item/completed', item={'id': 'review-message', 'type': 'agentMessage',
            'text': 'Reviewed current changes. No findings in the agreed scope.'})
        self.app.wait_conversations()
        self.complete(task)
        return self.app.delivery_review(self.subject['id'], result['review_operation']['id'])

    def accept(self, preview, decision='accept'):
        return self.app.delivery_review_decision(self.subject['id'], {'review_id': preview['review_id'],
            'receipt_id': preview['receipt_id'], 'review_digest': preview['review_digest'],
            'expected_snapshot': preview['snapshot_digest'], 'decision': decision, 'confirmed': True})


class DeliveryBackendTests(DeliveryFixture):
    def test_complete_positive_journey_is_separate_from_execution(self):
        self.assertEqual('completed', self.subject['status'])
        self.assertEqual('awaiting_checks', self.delivery()['status'])
        preview = self.reviewed()
        self.assertEqual('ready', self.accept(preview)['status'])
        self.assertEqual('completed', self.subject['status'])
        self.assertNotIn('SYNTHETIC_PRIVATE_TOOL_OUTPUT', json.dumps(self.app.snapshot()))
        self.assertNotIn(b'SYNTHETIC_PRIVATE_TOOL_OUTPUT', (self.root / 'state/dashboard.sqlite3').read_bytes())

    def test_failed_unstarted_wrong_or_claimed_checks_never_pass(self):
        self.plan()
        for arguments in ({'started': False}, {'command': 'echo passed'}, {'exit_code': 1}, {'exit_code': False}):
            with self.subTest(arguments=arguments):
                task = self.checks()
                self.command(task, **arguments)
                self.complete(task)
                self.assertEqual('checks_failed', self.delivery()['status'])

    def test_edit_modes_deletions_and_opaque_assets_change_snapshot(self):
        before = code_snapshot(self.project)
        path = self.project_root / 'feature.py'
        path.chmod(0o755)
        self.assertNotEqual(before, code_snapshot(self.project))
        before = code_snapshot(self.project)
        path.unlink()
        self.assertNotEqual(before, code_snapshot(self.project))
        (self.project_root / 'asset.png').write_bytes(b'\x89PNG\r\n\x1a\nasset')
        self.assertNotEqual(before, code_snapshot(self.project))

    def test_tracked_ignored_files_remain_covered(self):
        path = self.project_root / 'feature.py'
        subprocess.run(['git', '-C', str(self.project_root), 'add', 'feature.py'], check=True)
        (self.project_root / '.gitignore').write_text('feature.py\n')
        before = code_snapshot(self.project)
        path.write_text('print("changed")\n')
        self.assertNotEqual(before, code_snapshot(self.project))

    def test_current_code_plan_and_preview_receipts_cannot_be_replayed(self):
        preview = self.reviewed()
        self.accept(preview)
        with self.assertRaises(FileAccessError):
            self.accept(preview)
        (self.project_root / 'feature.py').write_text('print("next")\n')
        self.assertEqual('stale', self.delivery()['status'])
        with self.assertRaises(FileAccessError):
            self.accept(preview)

    def test_unknown_child_and_role_spoof_prevent_readiness(self):
        self.checked()
        self.app.observed_tasks['unknown'] = {'parent_task_id': self.subject['id'], 'role': None, 'status': 'completed'}
        self.assertEqual('unverified', self.delivery()['status'])
        del self.app.observed_tasks['unknown']
        operation = self.app.delivery_operations[self.delivery()['check_operation']['id']]
        self.app.tasks[operation['task_id']]['role'] = 'backend_developer'
        self.assertEqual('stale', self.delivery()['status'])

    def test_new_review_content_invalidates_human_acceptance(self):
        preview = self.reviewed()
        self.accept(preview)
        review = self.app.delivery_operations[preview['review_id']]
        task = self.app.tasks[review['task_id']]
        self.event(task, 'item/completed', item={'id': 'late-review-message', 'type': 'agentMessage', 'text': 'Additional finding.'})
        self.app.wait_conversations()
        self.assertEqual('stale', self.delivery()['status'])

    def test_check_plan_limits_and_missing_fields_are_rejected(self):
        for commands in ([], ['echo\nunsafe'], ['x' * 2000] * 8, ['same', 'same']):
            with self.subTest(commands=len(commands)):
                with self.assertRaises(ValueError):
                    self.plan(commands)

    def test_pending_operation_is_idempotent_and_persisted_with_runner(self):
        self.plan()
        current = self.delivery()
        payload = {'expected_snapshot': current['snapshot_digest'], 'expected_plan_version': current['plan_version'],
            'operation_id': uuid.uuid4().hex, 'confirmed': True}
        first = self.app.start_delivery_checks(self.subject['id'], payload)
        second = self.app.start_delivery_checks(self.subject['id'], payload)
        self.assertEqual(first['check_operation']['id'], second['check_operation']['id'])
        self.assertEqual(2, len(self.app.tasks))
        self.assertEqual(1, len(self.app.store.load('delivery_operation')))
        self.join()

    def test_withheld_final_review_cannot_use_earlier_safe_message(self):
        preview = self.reviewed()
        review = self.app.delivery_operations[preview['review_id']]
        task = self.app.tasks[review['task_id']]
        with patch('dashboard.conversation.safe_text', side_effect=ValueError('Withheld')):
            self.event(task, 'item/completed', item={'id': 'withheld-final', 'type': 'agentMessage',
                'text': 'Synthetic withheld report.', 'phase': 'final_answer'})
            self.app.wait_conversations()
        self.assertNotEqual('ready', self.delivery()['status'])
        with self.assertRaises(FileAccessError):
            self.accept(preview)
        self.assertTrue(self.app.delivery_operations[preview['review_id']]['failed'])

    def test_plan_changed_after_projection_cannot_publish_a_runner(self):
        self.plan()
        current = self.delivery()
        original = self.app.delivery
        changed = False
        def update_plan(task_id):
            nonlocal changed
            result = original(task_id)
            if not changed:
                changed = True
                self.plan(['python3 -m unittest discover'])
            return result
        before = len(self.app.tasks)
        with patch.object(self.app, 'delivery', side_effect=update_plan):
            with self.assertRaises(FileAccessError):
                self.app.start_delivery_checks(self.subject['id'], {'expected_snapshot': current['snapshot_digest'],
                    'expected_plan_version': current['plan_version'], 'operation_id': uuid.uuid4().hex, 'confirmed': True})
        self.assertEqual(before, len(self.app.tasks))
        self.assertEqual([], self.app.store.load('delivery_operation'))

    def test_source_edit_during_content_scan_cannot_report_ready(self):
        self.accept(self.reviewed())
        with patch('dashboard.delivery.scan_preview', side_effect=lambda _: (self.project_root / 'feature.py').write_text('changed during scan\n')):
            self.assertEqual('unverified', self.delivery()['status'])

    def test_malformed_decision_type_is_a_validation_failure(self):
        preview = self.reviewed()
        with self.assertRaises(ValueError):
            self.accept(preview, decision=[])

    def test_coordinator_with_registered_implementation_child_has_delivery_gate(self):
        self.subject['role'] = 'chief_of_staff'
        self.assertFalse(self.app.delivery_available(self.subject))
        self.app.observed_tasks['child'] = {'parent_task_id': self.subject['id'],
            'role': 'backend_developer', 'status': 'completed'}
        self.assertTrue(self.app.delivery_available(self.subject))
        self.assertEqual('awaiting_checks', self.delivery()['status'])
        self.app.observed_tasks['child']['role'] = None
        self.assertTrue(self.app.delivery_available(self.subject))
        self.assertEqual('unverified', self.delivery()['status'])

    def test_saved_decision_ack_survives_code_change_without_restoring_ready(self):
        preview = self.reviewed()
        self.accept(preview)
        (self.project_root / 'feature.py').write_text('changed after decision\n')
        current = self.delivery()
        self.assertEqual('stale', current['status'])
        self.assertEqual({'decision': 'accept', 'receipt_id': preview['receipt_id'],
            'review_digest': preview['review_digest'], 'expected_snapshot': preview['snapshot_digest']},
            current['review_operation']['decision_ack'])

    def test_failed_decision_storage_publishes_no_acceptance_or_ack(self):
        preview = self.reviewed()
        with patch.object(self.app.store, 'put', side_effect=sqlite3.OperationalError('Synthetic storage failure')):
            with self.assertRaises(FileAccessError):
                self.accept(preview)
        review = self.app.delivery_operations[preview['review_id']]
        self.assertNotIn('decision_ack', review)
        self.assertNotIn('decision', review)
        self.assertTrue(self.app.runtime_tracking_lost)
        self.assertNotEqual('ready', self.delivery()['status'])
        saved = next(row for row in self.app.store.load('delivery_operation') if row['id'] == preview['review_id'])
        self.assertNotIn('decision_ack', saved)
