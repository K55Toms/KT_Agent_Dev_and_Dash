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

from dashboard.approval_review import ApprovalReviews, MAX_CONTEXT
from dashboard.codex_client import ProtocolError
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard, make_server, now, unknown_cost
from tests.test_dashboard_backend import FakeClient


class ApprovalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.app = Dashboard(self.root / 'state')
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

    def approval(self, kind='command', **params):
        self.rpc += 1
        defaults = {'threadId': 'native-root', 'turnId': 'native-turn', 'itemId': 'item-' + str(self.rpc),
                    'startedAtMs': 1, 'reason': 'Run the checked synthetic command'}
        if kind == 'command':
            defaults.update(command='/usr/bin/true', cwd=str(self.root),
                            availableDecisions=['accept', 'acceptForSession', 'decline', 'cancel'])
        defaults.update(params)
        method = 'item/commandExecution/requestApproval' if kind == 'command' else 'item/fileChange/requestApproval'
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
        approval = self.approval(kind='file_change', itemId=item, **params)
        return approval, changes

    def test_complete_command_review_and_exact_native_one_request_response(self):
        approval = self.approval(additionalPermissions={'network': {'enabled': True}, 'fileSystem': {'write': ['/private/tmp/review-target']}},
                                 approvalId='callback-one')
        self.assertEqual(['decline'], approval['available_decisions'])
        review = self.review(approval)
        self.assertEqual('/usr/bin/true', review['context']['command'])
        self.assertEqual(str(self.root), review['context']['cwd'])
        self.assertEqual('callback-one', review['context']['approvalId'])
        self.assertEqual(True, review['context']['additionalPermissions']['network']['enabled'])
        self.assertIsNone(review['context']['networkApprovalContext'])
        self.assertEqual(['decline', 'accept'], approval['available_decisions'])
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

    def test_missing_unknown_or_broader_scope_blocks_grants_but_decline_works(self):
        variants = [dict(command=None), dict(cwd=None), dict(availableDecisions=None),
                    dict(availableDecisions=['decline', 'acceptForSession']), dict(kind='writeStdin'),
                    dict(kind='future-kind'), dict(environmentId='remote-one'), dict(futureScope=True),
                    dict(additionalPermissions={'network': {'enabled': True, 'futureGrant': True}}),
                    dict(additionalPermissions={'fileSystem': {'futureScope': '/'}}),
                    dict(networkApprovalContext={'host': 'example.com', 'protocol': 'newProtocol'}),
                    dict(networkApprovalContext={'host': 'example.com', 'protocol': 'https'}),
                    dict(availableDecisions=['accept', {'futureDecision': {}}])]
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
        no_item = self.approval(kind='file_change')
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
        approval = self.approval(kind='file_change', itemId='truncated')
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
        self.app = Dashboard(self.root / 'state')
        self.assertEqual('unavailable', self.app.approvals[approval['id']]['status'])
        self.assertEqual({}, self.app.pending)
        self.assertEqual(0, self.app.approval_reviews.size)

    def test_http_same_origin_and_exact_review_response_boundary(self):
        approval = self.approval()
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
            payload = {'decision': 'accept', 'review_id': review['review_id']}
            self.assertEqual(403, call('POST', route + '/respond', payload, origin='https://evil.example')[0])
            self.assertEqual([], self.fake.responses)
            self.assertEqual(200, call('POST', route + '/respond', payload, origin='http://127.0.0.1:' + str(port))[0])
            self.assertEqual(409, call('GET', route + '/review')[0])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
