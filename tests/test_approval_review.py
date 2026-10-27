"""Native approval grants require complete checked, exact, current context."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from dashboard.approval_review import ApprovalReviews, MAX_CONTEXT, REVIEW_FAILURES, ReviewError
from dashboard.codex_client import ProtocolError
from dashboard.project_files import FileAccessError, SensitiveContentError
from dashboard.server import Dashboard, SAFETY_INSTRUCTIONS, make_server, now, unknown_cost
from dashboard.settings import SettingsStore
from tests.test_dashboard_backend import FakeClient
from tests.policy_fixtures import SyntheticPolicy


class ApprovalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.app.settings = SettingsStore(self.root, config_path=self.root / 'settings.toml')
        self.fake = FakeClient()
        self.app.client = self.fake
        self.app.connection['status'] = 'connected'
        project = self.app.add_project({'name': 'Approval fixture', 'path': str(self.root)})
        self.task = {'id': 'a' * 32, 'project_id': project['id'], 'title': 'Native approval test',
                     'role': 'backend_developer', 'model': 'gpt-6.1-sol', 'reasoning': 'high',
                     'status': 'running', 'thread_id': 'native-root', 'turn_id': 'native-turn',
                     'plan': [], 'usage': None, 'cost': unknown_cost(), 'error': None,
                     'created_at': now(), 'updated_at': now()}
        self.app.tasks[self.task['id']] = self.task
        self.app.store.put('task', self.task)
        self.app._register_thread('native-root', self.task['id'])
        self.app.owned_threads['native-root'].update(current_turn='native-turn', turns={'native-turn'})
        self.rpc = 0

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def event(self, method, **params):
        self.app.on_message({'method': method, 'params': {
            'threadId': 'native-root', 'turnId': 'native-turn', **params}})

    def approval(self, request_kind='command', **params):
        self.rpc += 1
        defaults = {'threadId': 'native-root', 'turnId': 'native-turn', 'itemId': 'item-' + str(self.rpc),
                    'startedAtMs': 1, 'reason': 'Run the checked synthetic command'}
        if request_kind == 'command':
            defaults.update(command='/usr/bin/true', cwd=str(self.root),
                            availableDecisions=['accept', 'acceptForSession', 'decline', 'cancel'])
        defaults.update(params)
        method = 'item/commandExecution/requestApproval' if request_kind == 'command' else 'item/fileChange/requestApproval'
        self.app.on_message({'id': self.rpc, 'method': method, 'params': defaults})
        return list(self.app.approvals.values())[-1]

    def review(self, approval):
        return self.app.review_approval(approval['id'])

    def accept(self, approval, review):
        return self.app.respond_approval(approval['id'], {'decision': 'accept', 'review_id': review['review_id']})

    def file_approval(self, **params):
        item = 'file-item-' + str(self.rpc + 1)
        changes = [{'path': 'example.txt', 'kind': {'type': 'update', 'move_path': 'renamed.txt'},
                    'diff': '--- example.txt\n+++ renamed.txt\n@@ -1 +1 @@\n-old\n+new\n'}]
        self.event('item/started', item={'type': 'fileChange', 'id': item, 'status': 'inProgress', 'changes': changes})
        approval = self.approval(request_kind='file_change', itemId=item, **params)
        return approval, changes

    def sensitive_review(self, approval):
        return self.app.sensitive_review_approval(approval['id'], {'confirmed': True})

    def sensitive_accept(self, approval, review):
        return self.app.respond_approval(approval['id'], {
            'decision': 'accept', 'review_id': review['review_id'], 'sensitive_confirmed': True})

    def test_sensitive_findings_require_explicit_reveal_and_separate_one_time_grant(self):
        approval = self.approval()
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            with self.assertRaises(ReviewError) as caught:
                self.review(approval)
            public = self.app.record_review_failure(approval['id'], caught.exception)
            self.assertTrue(public['can_sensitive_review'])
            with self.assertRaises(ValueError):
                self.app.sensitive_review_approval(approval['id'], {})
            with self.assertRaises(ReviewError):
                self.app.sensitive_review_approval(approval['id'], {'confirmed': 1})
            review = self.sensitive_review(approval)
            self.assertTrue(review['sensitive_review'])
            self.assertEqual('/usr/bin/true', review['context']['command'])
            self.assertEqual([], self.fake.responses)
            with self.assertRaises(ReviewError) as caught:
                self.accept(approval, review)
            self.assertEqual('sensitive_confirmation_required', caught.exception.code)
            with self.assertRaises(ReviewError):
                self.app.respond_approval(approval['id'], {
                    'decision': 'accept', 'review_id': review['review_id'], 'sensitive_confirmed': True},
                    _source='project_policy')
            self.sensitive_accept(approval, review)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)
        self.assertEqual('human_sensitive_review', approval['decision']['source'])
        persisted = (self.root / 'state/dashboard.sqlite3').read_bytes()
        for withheld in (review['review_id'], '/usr/bin/true'):
            self.assertNotIn(withheld.encode(), persisted)
            self.assertNotIn(withheld, json.dumps(self.app.snapshot()))
        with self.assertRaises(ReviewError):
            self.sensitive_accept(approval, review)

    def test_sensitive_reveal_only_overrides_typed_completed_findings(self):
        for failure in (FileAccessError(403, 'private scanner detail'),
                        FileAccessError(503, 'private scanner detail'), RuntimeError('private scanner detail')):
            approval = self.approval()
            with patch('dashboard.server.scan_preview', side_effect=failure):
                with self.assertRaises(ReviewError) as caught:
                    self.sensitive_review(approval)
            self.assertFalse(self.app.record_review_failure(approval['id'], caught.exception)['can_sensitive_review'])
            self.assertNotIn('receipt', self.app.pending[approval['id']])
        approval = self.approval()
        with patch('dashboard.server.scan_preview'):
            with self.assertRaises(ReviewError) as caught:
                self.sensitive_review(approval)
        self.assertEqual('sensitive_review_not_needed', caught.exception.code)
        self.assertNotIn('receipt', self.app.pending[approval['id']])
        self.assertEqual([], self.fake.responses)

    def test_sensitive_file_review_preserves_complete_patch_and_scoped_native_grant(self):
        approval, changes = self.file_approval()
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            review = self.sensitive_review(approval)
            self.assertEqual(changes, review['context']['changes'])
            self.sensitive_accept(approval, review)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)
        self.assertEqual('human_sensitive_review', approval['decision']['source'])
        persisted = (self.root / 'state/dashboard.sqlite3').read_bytes()
        self.assertNotIn(changes[0]['diff'].encode(), persisted)

    def test_sensitive_review_keeps_all_native_shape_and_scope_guards(self):
        for params in ({'command': None}, {'cwd': None}, {'futureField': True},
                       {'command': '/usr/bin/true\u202e'}, {'environmentId': 'remote'},
                       {'networkApprovalContext': {'host': 'example.com', 'protocol': 'https'}}):
            approval = self.approval(**params)
            with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()) as scanner:
                with self.assertRaises(ReviewError):
                    self.sensitive_review(approval)
            scanner.assert_not_called()
        self.assertEqual([], self.fake.responses)

    def test_sensitive_receipt_cannot_be_created_by_plain_confirmation_or_normal_review(self):
        approval = self.approval()
        review = self.review(approval)
        with self.assertRaises(ReviewError):
            self.sensitive_accept(approval, review)
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            with self.assertRaises(ReviewError):
                self.accept(approval, review)
        self.assertEqual([], self.fake.responses)

    def test_sensitive_receipt_expiry_change_and_scanner_failure_block_grant(self):
        approval = self.approval()
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            review = self.sensitive_review(approval)
            self.app.pending[approval['id']]['receipt']['created'] -= 601
            with self.assertRaises(ReviewError):
                self.sensitive_accept(approval, review)
            review = self.sensitive_review(approval)
            self.app.pending[approval['id']]['params']['command'] = '/usr/bin/false'
            with self.assertRaises(ReviewError):
                self.sensitive_accept(approval, review)
            review = self.sensitive_review(approval)
        with patch('dashboard.server.scan_preview', side_effect=FileAccessError(503, 'private error')):
            with self.assertRaises(ReviewError):
                self.sensitive_accept(approval, review)
        self.assertEqual([], self.fake.responses)

    def test_sensitive_setting_revocation_reenable_invalidates_receipts_and_scans(self):
        approval = self.approval()
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            review = self.sensitive_review(approval)
        config = self.app.settings.load()
        config['sensitive_review_enabled'] = False
        self.app.save_settings(config)
        with self.assertRaises(ReviewError):
            self.sensitive_review(approval)
        config['sensitive_review_enabled'] = True
        self.app.save_settings(config)
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            with self.assertRaises(ReviewError):
                self.sensitive_accept(approval, review)
        def revoke_during_scan(_):
            config['sensitive_review_enabled'] = False
            self.app.save_settings(config)
            config['sensitive_review_enabled'] = True
            self.app.save_settings(config)
            raise SensitiveContentError()
        with patch('dashboard.server.scan_preview', side_effect=revoke_during_scan):
            with self.assertRaises(ReviewError):
                self.sensitive_review(approval)
        self.assertEqual([], self.fake.responses)

    def test_sensitive_setting_revoked_during_final_scan_blocks_native_write(self):
        approval = self.approval()
        with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
            review = self.sensitive_review(approval)
        def revoke(_):
            config = self.app.settings.load()
            config['sensitive_review_enabled'] = False
            self.app.save_settings(config)
            raise SensitiveContentError()
        with patch('dashboard.server.scan_preview', side_effect=revoke):
            with self.assertRaises(ReviewError):
                self.sensitive_accept(approval, review)
        self.assertEqual([], self.fake.responses)

    def test_sensitive_disconnect_during_reveal_never_returns_context(self):
        approval = self.approval()
        def disconnect(_):
            self.app.disconnected()
            raise SensitiveContentError()
        with patch('dashboard.server.scan_preview', side_effect=disconnect):
            with self.assertRaises(ReviewError) as caught:
                self.sensitive_review(approval)
        self.assertEqual('request_unavailable', caught.exception.code)
        self.assertEqual([], self.fake.responses)

    def test_sensitive_http_reveal_and_grant_are_separate_same_origin_no_store_actions(self):
        approval = self.approval()
        server = make_server(self.app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        port = server.server_address[1]
        route = '/api/approvals/' + approval['id']
        origin = 'http://127.0.0.1:' + str(port)
        def call(path, data, selected_origin=origin):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            conn.request('POST', path, json.dumps(data), {'Content-Type': 'application/json',
                         'Host': '127.0.0.1:' + str(port), 'Origin': selected_origin})
            response = conn.getresponse()
            result = response.status, json.loads(response.read()), response.getheader('Cache-Control')
            conn.close()
            return result
        try:
            with patch('dashboard.server.scan_preview', side_effect=SensitiveContentError()):
                self.assertEqual(403, call(route + '/sensitive-review', {'confirmed': True}, 'https://evil.example')[0])
                self.assertEqual(409, call(route + '/sensitive-review', {'confirmed': False})[0])
                status, review, caching = call(route + '/sensitive-review', {'confirmed': True})
                self.assertEqual(200, status)
                self.assertEqual('no-store', caching)
                self.assertTrue(review['sensitive_review'])
                self.assertEqual('/usr/bin/true', review['context']['command'])
                self.assertEqual([], self.fake.responses)
                payload = {'decision': 'accept', 'review_id': review['review_id']}
                self.assertEqual(409, call(route + '/respond', payload)[0])
                # A rejected attempt burns the prior review through the HTTP error adapter.
                _, review, _ = call(route + '/sensitive-review', {'confirmed': True})
                payload.update(review_id=review['review_id'], sensitive_confirmed=True)
                self.assertEqual(403, call(route + '/respond', payload, 'https://evil.example')[0])
                self.assertEqual(200, call(route + '/respond', payload)[0])
            self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_complete_command_review_and_exact_native_one_request_response(self):
        approval = self.approval(additionalPermissions={'network': {'enabled': True}, 'fileSystem': {'write': ['/private/tmp/review-target']}},
                                 approvalId='callback-one')
        self.assertEqual(['decline', 'cancel'], approval['available_decisions'])
        review = self.review(approval)
        self.assertEqual('/usr/bin/true', review['context']['command'])
        self.assertEqual(str(self.root), review['context']['cwd'])
        self.assertEqual('callback-one', review['context']['approvalId'])
        self.assertEqual(True, review['context']['additionalPermissions']['network']['enabled'])
        self.assertIsNone(review['context']['networkApprovalContext'])
        self.assertEqual(['decline', 'cancel', 'accept'], approval['available_decisions'])
        encoded = json.dumps(self.app.snapshot())
        persisted = (self.root / 'state/dashboard.sqlite3').read_bytes()
        for private in ('/usr/bin/true', 'callback-one', '/private/tmp/review-target', review['review_id']):
            self.assertNotIn(private, encoded)
            self.assertNotIn(private.encode(), persisted)
        self.accept(approval, review)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)
        self.assertEqual('resolved', approval['status'])
        with self.assertRaises(ValueError):
            self.accept(approval, review)

    def test_file_changes_require_complete_exact_matching_started_item(self):
        approval, changes = self.file_approval()
        review = self.review(approval)
        self.assertEqual(changes, review['context']['changes'])
        self.assertIsNone(review['context']['grantRoot'])
        self.accept(approval, review)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)

    def test_native_local_environment_marker_is_preserved_and_approved_once(self):
        approval = self.approval(environmentId='local', kind='command', startedAtMs=1792328400000,
                                 availableDecisions=['accept', 'decline'])
        review = self.review(approval)
        self.assertEqual('local', review['context']['environmentId'])
        self.assertEqual(1792328400000, review['context']['startedAtMs'])
        self.accept(approval, review)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)

    def test_wrong_or_missing_receipt_cross_request_and_extra_payload_denied(self):
        first = self.approval()
        first_review = self.review(first)
        second = self.approval()
        for data in ({'decision': 'accept'}, {'decision': 'accept', 'review_id': first_review['review_id']},
                     {'decision': 'acceptForSession'}, {'decision': {'acceptWithExecpolicyAmendment': {}}},
                     {'decision': ['accept']}, {'decision': 'accept', 'review_id': 'wrong'},
                     {'decision': 'decline', 'command': '/usr/bin/false'}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.app.respond_approval(second['id'], data)
        self.assertEqual([], self.fake.responses)
        self.app.respond_approval(second['id'], {'decision': 'decline'})
        self.assertEqual([(2, {'decision': 'decline'})], self.fake.responses)

    def test_cached_command_fallback_requires_exact_item_and_consistent_values(self):
        self.event('item/started', item={'type': 'commandExecution', 'id': 'cache-item',
                                        'command': '/usr/bin/true', 'cwd': str(self.root), 'status': 'inProgress'})
        valid = self.approval(itemId='cache-item', command=None, cwd=None)
        self.assertEqual('/usr/bin/true', self.review(valid)['context']['command'])
        missing = self.approval(itemId='other-item', command=None, cwd=None)
        mismatch = self.approval(itemId='cache-item', command='/usr/bin/false')
        for approval in (missing, mismatch):
            with self.assertRaises(ValueError):
                self.review(approval)
            self.app.respond_approval(approval['id'], {'decision': 'decline'})

    def test_subcommand_callback_reviews_exact_command_and_parent_separately(self):
        parent = "printf 'first\\n' && printf 'second\\n'"
        self.event('item/started', item={'type': 'commandExecution', 'id': 'compound-item',
                                        'command': parent, 'cwd': str(self.root), 'status': 'inProgress'})
        first = self.approval(itemId='compound-item', approvalId='callback-first',
                              command="printf 'first\\n'", cwd=str(self.root))
        first_review = self.review(first)
        self.assertEqual("printf 'first\\n'", first_review['context']['command'])
        self.assertEqual(parent, first_review['context']['parentItemContext']['command'])
        second = self.approval(itemId='compound-item', approvalId='callback-second',
                               command="printf 'second\\n'", cwd=str(self.root))
        second_review = self.review(second)
        with self.assertRaises(ValueError):
            self.accept(second, first_review)
        self.accept(first, first_review)
        self.accept(second, second_review)
        self.assertEqual([(1, {'decision': 'accept'}), (2, {'decision': 'accept'})], self.fake.responses)
        for missing in ('command', 'cwd'):
            params = {'itemId': 'compound-item', 'approvalId': 'callback-missing', missing: None}
            approval = self.approval(**params)
            with self.assertRaises(ReviewError) as caught:
                self.review(approval)
            self.assertEqual(missing + '_missing', caught.exception.code)

    def test_native_empty_optional_text_and_empty_file_diff_are_valid(self):
        approval = self.approval(reason='', commandActions=[{'type': 'search', 'command': 'rg', 'path': '', 'query': ''}])
        review = self.review(approval)
        self.assertEqual('', review['context']['reason'])
        self.assertEqual('', review['context']['commandActions'][0]['query'])
        self.accept(approval, review)
        self.event('item/started', item={'type': 'fileChange', 'id': 'empty-file', 'status': 'inProgress',
                   'changes': [{'path': 'empty.txt', 'kind': {'type': 'add'}, 'diff': ''}]})
        approval = self.approval(request_kind='file_change', itemId='empty-file', reason='')
        review = self.review(approval)
        self.assertEqual('', review['context']['changes'][0]['diff'])
        self.accept(approval, review)

    def test_full_multiline_mvp_command_roundtrip_scans_without_excerpting(self):
        command = "python3 - <<'PY'\nfrom pathlib import Path\nroot = Path('mvp')\nroot.mkdir(exist_ok=True)\n(root / 'index.html').write_text('<main>Profile preview</main>\\n')\n(root / 'app.py').write_text('print(42)\\n')\nPY"
        approval = self.approval(command=command, reason='', environmentId='local',
                                 commandActions=[{'type': 'unknown', 'command': command}],
                                 proposedExecpolicyAmendment=['python3', '-'],
                                 availableDecisions=['accept', 'decline', {'acceptWithExecpolicyAmendment': {'execpolicy_amendment': ['python3', '-']}}])
        review = self.review(approval)
        self.assertEqual(command, review['context']['command'])
        self.assertEqual(command, review['context']['commandActions'][0]['command'])
        self.accept(approval, review)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)

    def test_fixed_diagnostics_distinguish_schema_scope_and_content_failures(self):
        variants = [(dict(command=None), 'command_missing'), (dict(cwd=None), 'cwd_missing'),
                    (dict(environmentId='remote'), 'unsupported_environment'),
                    (dict(kind='writeStdin'), 'unsupported_action'),
                    (dict(availableDecisions=None), 'accept_not_offered'),
                    (dict(networkApprovalContext={'host': 'example.com', 'protocol': 'https'}), 'managed_network_scope'),
                    (dict(additionalPermissions={'newScope': True}), 'unsupported_permissions'),
                    (dict(futureField=True), 'unsupported_shape'),
                    (dict(command='x' * MAX_CONTEXT), 'context_too_large')]
        for params, code in variants:
            approval = self.approval(**params)
            with self.subTest(code=code), self.assertRaises(ReviewError) as caught:
                self.review(approval)
            self.assertEqual(code, caught.exception.code)
            public = self.app.record_review_failure(approval['id'], caught.exception)
            self.assertEqual(code, public['code'])
            self.assertEqual(REVIEW_FAILURES[code][0], public['error'])
            self.assertEqual(code, self.app.snapshot()['approvals'][-1]['review_failure']['code'])
            self.assertNotIn('params', json.dumps(public))
        self.assertEqual([], self.fake.responses)

    def test_scoped_guidance_acknowledged_before_exact_request_decline(self):
        approval = self.approval()
        other = self.approval()
        calls = []
        def request(method, params):
            calls.append((method, params))
            self.assertEqual([], self.fake.responses)
            with self.assertRaises(ReviewError):
                self.review(approval)
            return {'turnId': 'native-turn'}
        self.fake.request = request
        self.assertTrue(self.app.snapshot()['approvals'][0]['can_request_alternative'])
        result = self.app.request_approval_alternative(approval['id'], {'text': 'Please split this into smaller local steps.'})
        self.assertEqual({'guidance_sent': True, 'request_declined': True}, result)
        self.assertEqual('turn/steer', calls[0][0])
        self.assertEqual('native-turn', calls[0][1]['expectedTurnId'])
        self.assertEqual('native-root', calls[0][1]['threadId'])
        self.assertEqual([(1, {'decision': 'decline'})], self.fake.responses)
        self.assertIn(other['id'], self.app.pending)
        self.assertNotIn('/usr/bin/true', calls[0][1]['input'][0]['text'])
        self.assertIn('Please split', self.app.messages[-1]['text'])

    def test_guidance_rejection_or_scanner_block_keeps_request_pending(self):
        from dashboard.codex_client import RequestRejected
        approval = self.approval()
        self.fake.request = lambda *_: (_ for _ in ()).throw(RequestRejected())
        with self.assertRaises(ReviewError) as caught:
            self.app.request_approval_alternative(approval['id'], {'text': ''})
        self.assertEqual('guidance_rejected', caught.exception.code)
        self.assertIn(approval['id'], self.app.pending)
        self.assertNotIn('busy', self.app.pending[approval['id']])
        with patch('dashboard.server.safe_text', side_effect=ValueError('SYNTHETIC_PRIVATE')):
            with self.assertRaises(ReviewError) as caught:
                self.app.request_approval_alternative(approval['id'], {'text': 'safe guidance'})
        self.assertEqual('guidance_invalid', caught.exception.code)
        self.assertEqual([], self.fake.responses)

    def test_recovery_explains_when_native_offers_cancel_but_not_continuing_decline(self):
        approval = self.approval(availableDecisions=['accept', 'acceptForSession', 'cancel'])
        projected = self.app.snapshot()['approvals'][-1]
        self.assertTrue(projected['can_request_alternative'])
        self.assertEqual('cancel', projected['resolution_mode'])
        self.assertEqual(['cancel'], projected['available_decisions'])
        with self.assertRaises(ReviewError) as caught:
            self.app.request_approval_alternative(approval['id'], {'text': 'Propose a smaller command.'})
        self.assertEqual('decline_not_offered', caught.exception.code)
        self.assertEqual([], self.fake.requests)
        self.assertEqual([], self.fake.responses)
        self.assertEqual('pending', approval['status'])
        with self.assertRaises(ReviewError):
            self.app.respond_approval(approval['id'], {'decision': 'decline'})
        review = self.review(approval)
        self.assertEqual('/usr/bin/true', review['context']['command'])

    def test_explicit_cancel_then_observed_interruption_then_separate_followup(self):
        self.app.policy_provider = SyntheticPolicy()
        policy = self.app.policy_provider.load()
        self.app.native_roles.config(self.app.roles, SAFETY_INSTRUCTIONS, policy=policy)
        self.task.update(compliance_policy=policy.metadata,
                         compliance_role_digest=self.app.native_roles.fingerprint)
        self.app.store.put('task', self.task)
        approval = self.approval(availableDecisions=['accept', 'cancel'])
        def request(method, params):
            self.fake.requests.append((method, params))
            return {'turnId': 'native-turn'} if method == 'turn/steer' else {'turn': {'id': 'revised-turn'}}
        self.fake.request = request
        result = self.app.request_approval_alternative(approval['id'], {'text': 'Propose one smaller operation.', 'mode': 'cancel'})
        self.assertEqual({'guidance_sent': True, 'request_declined': False, 'cancel_sent': True,
                          'origin_thread_id': 'native-root', 'origin_turn_id': 'native-turn', 'root_task': True}, result)
        self.assertEqual([(1, {'decision': 'cancel'})], self.fake.responses)
        self.assertEqual('cancel', approval['decision']['value'])
        self.assertNotEqual('interrupted', self.task['status'])
        self.assertEqual(['turn/steer'], [call[0] for call in self.fake.requests])
        self.event('turn/completed', turn={'id': 'native-turn', 'status': 'interrupted'})
        self.assertEqual('interrupted', self.task['status'])
        self.assertEqual(['turn/steer'], [call[0] for call in self.fake.requests])
        self.app.send_message(self.task['id'], {'text': 'Propose one smaller operation.', 'expected_turn_id': 'native-turn'})
        self.assertEqual(['turn/steer', 'turn/start'], [call[0] for call in self.fake.requests])
        self.assertEqual('revised-turn', self.task['turn_id'])
        self.assertEqual('Propose one smaller operation.', self.fake.requests[-1][1]['input'][0]['text'])

    def test_cancel_mode_requires_offered_choice_and_partial_ack_does_not_cancel_others(self):
        no_cancel = self.approval(availableDecisions=['accept', 'decline'])
        with self.assertRaises(ReviewError) as caught:
            self.app.request_approval_alternative(no_cancel['id'], {'text': '', 'mode': 'cancel'})
        self.assertEqual('cancel_not_offered', caught.exception.code)
        approval = self.approval(availableDecisions=['accept', 'cancel'])
        def request(*_):
            self.event('serverRequest/resolved', requestId=2)
            return {'turnId': 'native-turn'}
        self.fake.request = request
        result = self.app.request_approval_alternative(approval['id'], {'text': '', 'mode': 'cancel'})
        self.assertTrue(result['guidance_sent'])
        self.assertFalse(result['cancel_sent'])
        self.assertFalse(result['request_declined'])
        self.assertEqual([], self.fake.responses)
        self.assertIn(no_cancel['id'], self.app.pending)

    def test_child_cancel_marks_origin_and_never_starts_root_followup(self):
        self.app._register_thread('native-child', self.task['id'], 'native-root')
        self.event('turn/started', threadId='native-child', turn={'id': 'child-turn'})
        approval = self.approval(threadId='native-child', turnId='child-turn', availableDecisions=['accept', 'cancel'])
        self.fake.request = lambda *_: {'turnId': 'child-turn'}
        result = self.app.request_approval_alternative(approval['id'], {'text': 'Smaller operation please.', 'mode': 'cancel'})
        self.assertFalse(result['root_task'])
        self.assertEqual('native-child', result['origin_thread_id'])
        self.assertEqual('child-turn', result['origin_turn_id'])
        self.assertEqual('native-turn', self.task['turn_id'])
        self.assertEqual([(1, {'decision': 'cancel'})], self.fake.responses)

    def test_manual_negative_choices_match_native_explicit_offers(self):
        approval = self.approval(availableDecisions=['accept', 'cancel'])
        self.assertEqual(['cancel'], approval['available_decisions'])
        with self.assertRaises(ReviewError):
            self.app.respond_approval(approval['id'], {'decision': 'decline'})
        self.app.respond_approval(approval['id'], {'decision': 'cancel'})
        self.assertEqual([(1, {'decision': 'cancel'})], self.fake.responses)

    def test_approval_requester_uses_verified_human_role_identity(self):
        root = self.approval()
        self.assertEqual('Kira Voss (Backend Developer) via Codex App Server', root['requester'])
        self.event('thread/started', thread={'id': 'known-child', 'parentThreadId': 'native-root', 'agentRole': 'security_reviewer'})
        self.event('turn/started', threadId='known-child', turn={'id': 'known-child-turn'})
        known = self.approval(threadId='known-child', turnId='known-child-turn')
        self.assertEqual('Dax Corven (Security Reviewer) via Codex App Server', known['requester'])
        self.app._register_thread('unknown-child', self.task['id'], 'native-root')
        self.event('turn/started', threadId='unknown-child', turn={'id': 'unknown-child-turn'})
        unknown = self.approval(threadId='unknown-child', turnId='unknown-child-turn')
        self.assertEqual('Unknown agent via Codex App Server', unknown['requester'])

    def test_guidance_resolution_during_ack_reports_sent_without_second_decline(self):
        approval = self.approval()
        def request(*_):
            self.event('serverRequest/resolved', requestId=1)
            return {'turnId': 'native-turn'}
        self.fake.request = request
        result = self.app.request_approval_alternative(approval['id'], {'text': 'Suggest a smaller alternative.'})
        self.assertEqual({'guidance_sent': True, 'request_declined': False}, result)
        self.assertEqual([], self.fake.responses)
        self.assertIn('Suggest a smaller', self.app.messages[-1]['text'])

    def test_uncertain_guidance_delivery_does_not_decline_or_replay(self):
        approval = self.approval()
        self.fake.request = lambda *_: (_ for _ in ()).throw(ProtocolError('Synthetic lost ack'))
        with self.assertRaises(ProtocolError):
            self.app.request_approval_alternative(approval['id'], {'text': ''})
        self.assertEqual([], self.fake.responses)
        self.assertEqual('unknown', self.task['status'])
        self.assertEqual('unavailable', approval['status'])
        with self.assertRaises(ReviewError):
            self.app.request_approval_alternative(approval['id'], {'text': ''})

    def test_recovery_remains_available_for_oversized_withheld_context(self):
        approval = self.approval(command='x' * MAX_CONTEXT)
        self.assertIsNone(self.app.pending[approval['id']]['params'])
        self.assertTrue(self.app.snapshot()['approvals'][-1]['can_request_alternative'])
        self.fake.request = lambda *_: {'turnId': 'native-turn'}
        result = self.app.request_approval_alternative(approval['id'], {'text': 'Split into smaller operations.'})
        self.assertTrue(result['request_declined'])
        self.assertEqual([(1, {'decision': 'decline'})], self.fake.responses)

    def test_recovery_revalidates_after_scanning_and_targets_exact_child(self):
        approval = self.approval()
        count = 0
        def scan(text, *_):
            nonlocal count
            count += 1
            if count == 2:
                self.event('serverRequest/resolved', requestId=1)
            return text
        with patch('dashboard.server.safe_text', side_effect=scan):
            with self.assertRaises(ReviewError):
                self.app.request_approval_alternative(approval['id'], {'text': 'Simplify the operation.'})
        self.assertEqual([], self.fake.requests)
        self.app._register_thread('native-child', self.task['id'], 'native-root')
        self.event('turn/started', threadId='native-child', turn={'id': 'child-turn'})
        child = self.approval(threadId='native-child', turnId='child-turn')
        self.event('turn/completed', turn={'id': 'native-turn', 'status': 'completed'})
        def request(method, params):
            self.assertEqual('native-child', params['threadId'])
            self.assertEqual('child-turn', params['expectedTurnId'])
            return {'turnId': 'child-turn'}
        self.fake.request = request
        self.app.request_approval_alternative(child['id'], {'text': ''})
        self.assertEqual('completed', self.task['status'])

    def mode(self, value):
        config = self.app.settings.load()
        config['project_approval_modes'] = {self.task['project_id']: value}
        self.app.save_settings(config)

    def wait_automatic(self, approval):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.app.lock:
                if approval['status'] != 'pending' or approval.get('review_failure'):
                    return
            time.sleep(.01)
        self.fail('Automatic review did not settle')

    def test_project_automatic_applies_only_to_future_callbacks_with_audit(self):
        pending = self.approval()
        self.mode('automatic')
        self.assertNotIn('automatic_eligible', self.app.pending[pending['id']])
        later = self.approval()
        self.wait_automatic(later)
        self.assertEqual([(2, {'decision': 'accept'})], self.fake.responses)
        self.assertEqual('project_policy', later['decision']['source'])
        self.assertEqual('pending', pending['status'])
        self.assertIn(pending['id'], self.app.pending)
        self.assertNotIn('/usr/bin/true', json.dumps(self.app.snapshot()))

    def test_automatic_revocation_during_scan_prevents_native_write(self):
        self.mode('automatic')
        entered, release = threading.Event(), threading.Event()
        def scan(_):
            entered.set()
            self.assertTrue(release.wait(30))
        with patch('dashboard.server.scan_preview', side_effect=scan):
            approval = self.approval()
            self.assertTrue(entered.wait(30))
            self.mode('manual')
            self.mode('automatic')  # A later enable must not revive the revoked callback.
            release.set()
            self.wait_automatic(approval)
        self.assertEqual([], self.fake.responses)
        self.assertEqual('pending', approval['status'])
        self.assertEqual('project_policy_changed', approval['review_failure']['code'])
        self.assertNotIn('busy', self.app.pending[approval['id']])

    def test_automatic_unsupported_content_and_queue_failure_stay_manual(self):
        self.mode('automatic')
        approval = self.approval(networkApprovalContext={'host': 'example.com', 'protocol': 'https'})
        self.wait_automatic(approval)
        self.assertEqual('managed_network_scope', approval['review_failure']['code'])
        self.assertEqual([], self.fake.responses)
        self.assertEqual('pending', approval['status'])
        # Inject queue saturation without replacing a queue owned by the worker.
        import queue
        with patch.object(self.app.automatic_queue, 'put_nowait', side_effect=queue.Full):
            saturated = self.approval()
            self.assertEqual('automatic_queue_full', saturated['review_failure']['code'])
            self.assertEqual('pending', saturated['status'])

    def test_automatic_child_uses_owned_root_project_policy_only(self):
        self.mode('automatic')
        self.app._register_thread('native-child', self.task['id'], 'native-root')
        self.event('turn/started', threadId='native-child', turn={'id': 'child-turn'})
        self.event('turn/completed', turn={'id': 'native-turn', 'status': 'completed'})
        approval = self.approval(threadId='native-child', turnId='child-turn')
        self.wait_automatic(approval)
        self.assertEqual([(1, {'decision': 'accept'})], self.fake.responses)
        self.assertEqual('project_policy', approval['decision']['source'])
        self.assertEqual('completed', self.task['status'])

    def test_automatic_does_not_cross_project_boundary(self):
        self.mode('automatic')
        other_path = self.root / 'other-project'
        other_path.mkdir()
        project = self.app.add_project({'name': 'Manual project', 'path': str(other_path)})
        task = deepcopy(self.task)
        task.update(id='b' * 32, project_id=project['id'], thread_id='other-thread', turn_id='other-turn')
        self.app.tasks[task['id']] = task
        self.app._register_thread('other-thread', task['id'])
        self.app.owned_threads['other-thread'].update(current_turn='other-turn', turns={'other-turn'})
        approval = self.approval(threadId='other-thread', turnId='other-turn')
        self.assertNotIn('automatic_eligible', self.app.pending[approval['id']])
        self.assertEqual('pending', approval['status'])
        self.assertEqual([], self.fake.responses)

    def test_automatic_scanner_and_unknown_context_fail_closed(self):
        self.mode('automatic')
        with patch('dashboard.server.scan_preview', side_effect=FileAccessError(403, 'SYNTHETIC_PRIVATE')):
            approval = self.approval()
            self.wait_automatic(approval)
        self.assertEqual('scanner_blocked', approval['review_failure']['code'])
        self.assertEqual('pending', approval['status'])
        unknown = self.approval(futureField=True)
        self.wait_automatic(unknown)
        self.assertEqual('unsupported_shape', unknown['review_failure']['code'])
        self.assertEqual([], self.fake.responses)
        self.assertNotIn(b'SYNTHETIC_PRIVATE', (self.root / 'state/dashboard.sqlite3').read_bytes())

    def test_disconnect_during_automatic_scan_never_writes_native_decision(self):
        self.mode('automatic')
        entered, release = threading.Event(), threading.Event()
        def scan(_):
            entered.set()
            self.assertTrue(release.wait(30))
        with patch('dashboard.server.scan_preview', side_effect=scan):
            approval = self.approval()
            self.assertTrue(entered.wait(30))
            self.app.disconnected()
            release.set()
            self.app.automatic_queue.join()
        self.assertEqual([], self.fake.responses)
        self.assertEqual('unavailable', approval['status'])
        self.assertEqual({}, self.app.pending)

    def test_failed_review_diagnostic_is_safe_persisted_and_cleared_on_retry(self):
        approval = self.approval()
        with patch('dashboard.server.scan_preview', side_effect=FileAccessError(503, 'SYNTHETIC_PRIVATE_SCANNER_DETAIL')):
            with self.assertRaises(ReviewError) as caught:
                self.review(approval)
        public = self.app.record_review_failure(approval['id'], caught.exception)
        self.assertEqual('scanner_unavailable', public['code'])
        self.assertTrue(public['retryable'])
        persisted = (self.root / 'state/dashboard.sqlite3').read_bytes()
        self.assertNotIn(b'SYNTHETIC_PRIVATE_SCANNER_DETAIL', persisted)
        self.assertNotIn(b'/usr/bin/true', persisted)
        review = self.review(approval)
        self.assertNotIn('review_failure', approval)
        self.assertNotIn('review_failure', self.app.store.load('approval')[-1])
        self.assertEqual(['decline', 'cancel'], self.app.store.load('approval')[-1]['available_decisions'])
        self.accept(approval, review)

    def test_missing_unknown_or_broader_scope_blocks_grants_but_decline_works(self):
        variants = [dict(command=None), dict(cwd=None), dict(availableDecisions=None),
                    dict(availableDecisions=['decline', 'acceptForSession']), dict(kind='writeStdin'),
                    dict(kind='future-kind'), dict(environmentId='remote-one'), dict(futureScope=True),
                    dict(additionalPermissions={'network': {'enabled': True, 'futureGrant': True}}),
                    dict(additionalPermissions={'fileSystem': {'futureScope': '/'}}),
                    dict(networkApprovalContext={'host': 'example.com', 'protocol': 'newProtocol'}),
                    dict(networkApprovalContext={'host': 'example.com', 'protocol': 'https'}),
                    dict(availableDecisions=['accept', 'decline', {'futureDecision': {}}])]
        for params in variants:
            with self.subTest(params=params):
                approval = self.approval(**params)
                with self.assertRaises(ValueError):
                    self.review(approval)
                self.app.respond_approval(approval['id'], {'decision': 'decline'})
        approval, _ = self.file_approval(grantRoot='/private/tmp')
        with self.assertRaises(ValueError):
            self.review(approval)
        self.app.respond_approval(approval['id'], {'decision': 'decline'})
        no_item = self.approval(request_kind='file_change')
        with self.assertRaises(ValueError):
            self.review(no_item)

    def test_oversized_controls_and_truncation_markers_cannot_create_receipt(self):
        for command in ('x' * MAX_CONTEXT, 'echo safe\u202eunsafe', 'echo\x00bad'):
            approval = self.approval(command=command)
            with self.assertRaises(ValueError):
                self.review(approval)
            self.app.respond_approval(approval['id'], {'decision': 'decline'})
        self.event('item/started', item={'type': 'fileChange', 'id': 'truncated',
                   'changes': [{'path': 'test.txt', 'kind': {'type': 'add'}, 'diff': '+safe complete-looking text'}],
                   'truncated': True})
        approval = self.approval(request_kind='file_change', itemId='truncated')
        with self.assertRaises(ValueError):
            self.review(approval)

    def test_changed_duplicate_rpc_invalidates_receipt_but_identical_is_ignored(self):
        approval = self.approval()
        review = self.review(approval)
        params = deepcopy(self.app.pending[approval['id']]['params'])
        message = {'id': 1, 'method': 'item/commandExecution/requestApproval', 'params': params}
        self.app.on_message(message)
        self.assertEqual(1, len(self.app.pending))
        self.assertEqual(review['review_id'], self.app.pending[approval['id']]['receipt']['id'])
        message['params']['command'] = '/usr/bin/false'
        self.app.on_message(message)
        self.assertEqual('unavailable', approval['status'])
        self.assertEqual({}, self.app.pending)
        with self.assertRaises(ValueError):
            self.accept(approval, review)
        self.assertEqual([], self.fake.responses)

    def test_real_scanner_withholds_synthetic_secret_without_persistence(self):
        value = 'synthetic' + '-not-a-real-credential-' + 'fixture'
        command = 'echo api_' + "key='" + value + "'"
        approval = self.approval(command=command)
        with self.assertRaises(ValueError) as caught:
            self.review(approval)
        self.assertNotIn(value, str(caught.exception))
        self.assertNotIn(value.encode(), (self.root / 'state/dashboard.sqlite3').read_bytes())
        self.assertNotIn('receipt', self.app.pending[approval['id']])

    def test_scanner_unavailable_unexpected_failure_and_recheck_at_accept(self):
        approval = self.approval()
        for failure in (FileAccessError(503, 'scanner unavailable'), RuntimeError('SYNTHETIC_PRIVATE')):
            with patch('dashboard.server.scan_preview', side_effect=failure):
                with self.assertRaises(ValueError) as caught:
                    self.review(approval)
                self.assertNotIn('SYNTHETIC_PRIVATE', str(caught.exception))
        review = self.review(approval)
        with patch('dashboard.server.scan_preview', side_effect=FileAccessError(503, 'scanner changed')):
            with self.assertRaises(ValueError):
                self.accept(approval, review)
        self.assertEqual([], self.fake.responses)

    def test_completion_resolution_and_disconnect_invalidate_receipts(self):
        cases = [('item/completed', {'item': {'type': 'commandExecution', 'id': 'item-1'}}),
                 ('turn/completed', {'turn': {'id': 'native-turn', 'status': 'completed'}}),
                 ('serverRequest/resolved', {'requestId': 1}), ('disconnect', {})]
        for method, params in cases:
            with self.subTest(method=method):
                # Independent runtime for each lifecycle path.
                self.rpc = 0
                self.fake.closed = False
                self.app.connection['status'] = 'connected'
                self.task.update(status='running', turn_id='native-turn')
                self.app.owned_threads.setdefault('native-root', {'task_id': self.task['id'], 'parent': None, 'turns': {'native-turn'}}).update(active=True, current_turn='native-turn')
                self.app.resolved_requests.clear()
                approval = self.approval()
                review = self.review(approval)
                self.app.disconnected() if method == 'disconnect' else self.event(method, **params)
                with self.assertRaises(ValueError):
                    self.accept(approval, review)
                self.assertNotIn(approval['id'], self.app.pending)
        self.assertEqual([], self.fake.responses)

    def test_scanner_race_cannot_mint_or_use_stale_receipt(self):
        approval = self.approval()
        def complete(_):
            self.event('serverRequest/resolved', requestId=1)
        with patch('dashboard.server.scan_preview', side_effect=complete):
            with self.assertRaises(ValueError):
                self.review(approval)
        approval = self.approval()
        review = self.review(approval)
        def resolve_second(_):
            self.event('serverRequest/resolved', requestId=2)
        with patch('dashboard.server.scan_preview', side_effect=resolve_second):
            with self.assertRaises(ValueError):
                self.accept(approval, review)
        self.assertEqual([], self.fake.responses)

    def test_partial_native_write_consumes_authority_and_marks_unknown(self):
        approval = self.approval()
        review = self.review(approval)
        def uncertain(request_id, result):
            self.fake.responses.append((request_id, result))
            raise ProtocolError('Synthetic partial write')
        self.fake.respond = uncertain
        with self.assertRaises(ProtocolError):
            self.accept(approval, review)
        self.assertEqual('unavailable', approval['status'])
        self.assertEqual('unknown', self.task['status'])
        self.assertNotIn(approval['id'], self.app.pending)
        for action in (lambda: self.review(approval), lambda: self.accept(approval, review)):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(1, len(self.fake.responses))

    def test_child_request_survives_parent_completion_but_not_own_completion(self):
        self.app._register_thread('native-child', self.task['id'], 'native-root')
        self.event('turn/started', threadId='native-child', turn={'id': 'child-turn'})
        approval = self.approval(threadId='native-child', turnId='child-turn')
        self.event('turn/completed', turn={'id': 'native-turn', 'status': 'completed'})
        self.assertEqual('completed', self.task['status'])
        review = self.review(approval)
        self.assertEqual('native-child', review['context']['threadId'])
        self.accept(approval, review)
        self.assertEqual('completed', self.task['status'])
        second = self.approval(threadId='native-child', turnId='child-turn')
        second_review = self.review(second)
        self.event('turn/completed', threadId='native-child', turn={'id': 'child-turn', 'status': 'completed'})
        with self.assertRaises(ValueError):
            self.accept(second, second_review)

    def test_context_and_receipt_expiry_or_client_change_fail_closed(self):
        approval = self.approval()
        review = self.review(approval)
        self.app.pending[approval['id']]['receipt']['created'] = time.monotonic() - 601
        with self.assertRaises(ValueError):
            self.accept(approval, review)
        review = self.review(approval)
        self.app.pending[approval['id']]['params']['command'] = '/usr/bin/false'
        with self.assertRaises(ValueError):
            self.accept(approval, review)
        self.app.client = FakeClient()
        with self.assertRaises(ValueError):
            self.review(approval)

    def test_cache_bounds_and_restart_do_not_restore_grants(self):
        for index in range(100):
            self.event('item/started', item={'id': 'bounded-' + str(index), 'type': 'fileChange',
                       'changes': [{'path': 'test.txt', 'kind': {'type': 'add'}, 'diff': 'x' * 16000}]})
        self.assertLessEqual(len(self.app.approval_reviews.items), 64)
        self.assertLessEqual(self.app.approval_reviews.size, 524288)
        approval = self.approval()
        self.review(approval)
        self.app.close()
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.assertEqual('unavailable', self.app.approvals[approval['id']]['status'])
        self.assertEqual({}, self.app.pending)
        self.assertEqual(0, self.app.approval_reviews.size)

    def test_http_same_origin_and_exact_review_response_boundary(self):
        command = "python3 - <<'PY'\nfrom pathlib import Path\nPath('preview.html').write_text('<main>Profile preview</main>\\n')\nPY"
        approval = self.approval(command=command, reason='', environmentId='local')
        server = make_server(self.app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        port = server.server_address[1]
        def call(method, path, data=None, origin=None, host=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            headers = {'Content-Type': 'application/json', 'Host': host or '127.0.0.1:' + str(port)}
            if origin:
                headers['Origin'] = origin
            conn.request(method, path, json.dumps(data) if data is not None else None, headers)
            response = conn.getresponse()
            result = (response.status, json.loads(response.read()))
            conn.close()
            return result
        try:
            route = '/api/approvals/' + approval['id']
            self.assertEqual(403, call('GET', route + '/review', host='evil.example')[0])
            status, review = call('GET', route + '/review')
            self.assertEqual(200, status)
            self.assertEqual(command, review['context']['command'])
            payload = {'decision': 'accept', 'review_id': review['review_id']}
            self.assertEqual(403, call('POST', route + '/respond', payload, origin='https://evil.example')[0])
            self.assertEqual([], self.fake.responses)
            self.assertEqual(200, call('POST', route + '/respond', payload, origin='http://127.0.0.1:' + str(port))[0])
            status, error = call('GET', route + '/review')
            self.assertEqual(409, status)
            self.assertEqual('request_unavailable', error['code'])
            self.assertFalse(error['retryable'])
            self.assertIn('action', error)
            second = self.approval()
            second_route = '/api/approvals/' + second['id'] + '/alternative'
            self.fake.request = lambda *_: {'turnId': 'native-turn'}
            self.assertEqual(403, call('POST', second_route, {'text': 'Split this step.'}, origin='https://evil.example')[0])
            status, result = call('POST', second_route, {'text': 'Split this step.'}, origin='http://127.0.0.1:' + str(port))
            self.assertEqual(200, status)
            self.assertEqual({'guidance_sent': True, 'request_declined': True}, result)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
