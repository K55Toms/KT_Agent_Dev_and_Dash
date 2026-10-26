"""Independent new-native-approval HTTP journeys using a simulated native client.

The wire response assertions derive from the installed App Server schema, not
the dashboard's implementation. No native model or external action is executed.
"""
import unittest

from tests.test_ui_review_acceptance import IsolatedUIFixture


class NativeApprovalHTTPAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixture = IsolatedUIFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.start_http()
        self.task = self.fixture.task()
        self.rpc = 200

    def native(self, method, params, task=None):
        task = self.task if task is None else task
        self.rpc += 1
        request = {'threadId': task['thread_id'], 'turnId': task['turn_id'], **params}
        self.fixture.app.on_message({'id': self.rpc, 'method': method, 'params': request})
        self.fixture.app.wait_conversations()
        approvals = [row for row in self.fixture.app.approvals.values() if row['task_id'] == task['id']]
        self.assertTrue(approvals, 'Native decision must appear in the dashboard approval queue')
        return approvals[-1]

    def permission(self, task=None):
        return self.native('item/permissions/requestApproval', {
            'itemId': 'synthetic-permission', 'startedAtMs': 1,
            'cwd': str(self.fixture.project_root), 'permissions': {'network': {'enabled': True}},
            'reason': 'Synthetic network permission request for this turn.'}, task)

    def review(self, approval):
        status, result = self.fixture.request(f'/api/approvals/{approval["id"]}/review')
        self.assertEqual(200, status, result)
        return result

    def respond(self, approval, body):
        return self.fixture.request(f'/api/approvals/{approval["id"]}/respond', body)

    def test_permission_review_turn_scoped_grant_then_observed_completion(self):
        approval = self.permission()
        review = self.review(approval)
        self.assertEqual({'network': {'enabled': True}}, review['context']['permissions'])
        self.assertEqual(str(self.fixture.project_root), review['context']['cwd'])
        self.assertEqual(200, self.respond(approval, {'decision': 'accept', 'review_id': review['review_id']})[0])
        self.assertEqual((self.rpc, {'permissions': {'network': {'enabled': True}}, 'scope': 'turn'}),
                         self.fixture.client.responses[-1])
        self.assertEqual('running', self.fixture.app.tasks[self.task['id']]['status'])
        self.fixture.emit(self.task, 'turn/completed', turn={'id': self.task['turn_id'], 'status': 'completed'})
        self.assertEqual('completed', self.fixture.app.tasks[self.task['id']]['status'])
        self.assertEqual(409, self.respond(approval, {'decision': 'accept', 'review_id': review['review_id']})[0])
        self.assertEqual(1, len(self.fixture.client.responses))

    def test_permission_rejection_sends_empty_overlay_never_a_grant(self):
        approval = self.permission()
        status, result = self.respond(approval, {'decision': 'decline'})
        self.assertEqual(200, status, result)
        self.assertEqual((self.rpc, {'permissions': {}, 'scope': 'turn'}), self.fixture.client.responses[-1])
        self.assertEqual('running', self.fixture.app.tasks[self.task['id']]['status'])

    def test_permission_receipt_cannot_cross_request_or_survive_turn_change(self):
        first = self.permission()
        review = self.review(first)
        other_task = self.fixture.task('Synthetic unrelated permission request')
        second = self.permission(other_task)
        self.assertEqual(409, self.respond(second, {'decision': 'accept', 'review_id': review['review_id']})[0])
        self.fixture.app.owned_threads[self.task['thread_id']]['current_turn'] = 'synthetic-new-turn'
        self.assertEqual(409, self.respond(first, {'decision': 'accept', 'review_id': review['review_id']})[0])
        self.assertEqual([], self.fixture.client.responses)

    def test_mcp_form_reject_and_cancel_have_native_response_shape(self):
        for decision in ('decline', 'cancel'):
            task = self.fixture.task('Synthetic MCP ' + decision)
            approval = self.native('mcpServer/elicitation/request', {
                'serverName': 'synthetic_connector', 'mode': 'form',
                'message': 'Synthetic request; no external operation will occur.',
                'requestedSchema': {'type': 'object', 'properties': {
                    'confirm': {'type': 'boolean', 'title': 'Synthetic confirmation'}}, 'required': ['confirm']}}, task)
            status, result = self.respond(approval, {'decision': decision})
            self.assertEqual(200, status, result)
            self.assertEqual((self.rpc, {'action': decision, 'content': None}), self.fixture.client.responses[-1])

    def test_permission_context_and_receipts_are_not_saved_in_history(self):
        approval = self.permission()
        review = self.review(approval)
        persisted = next(row for row in self.fixture.app.store.load('approval') if row['id'] == approval['id'])
        self.assertNotIn('context', persisted)
        self.assertNotIn('permissions', persisted)
        self.assertNotIn('review_id', persisted)
        self.assertNotIn(review['review_id'], str(persisted))

    def test_native_approval_question_sends_exact_selected_option_then_completes(self):
        approval = self.native('item/tool/requestUserInput', {
            'itemId': 'synthetic-native-question', 'isBlocking': True, 'autoResolutionMs': None,
            'questions': [{'id': 'synthetic-decision', 'header': 'Synthetic approval',
                'question': 'Approve the synthetic connector action?', 'isOther': False, 'isSecret': False,
                'options': [{'label': 'Accept', 'description': 'Allow this synthetic action'},
                            {'label': 'Decline', 'description': 'Reject this synthetic action'}]}]})
        review = self.review(approval)
        self.assertEqual('Accept', review['context']['questions'][0]['options'][0]['label'])
        body = {'decision': 'accept', 'review_id': review['review_id'],
                'answers': {'synthetic-decision': ['Not an offered option']}}
        self.assertEqual(409, self.respond(approval, body)[0])
        self.assertEqual([], self.fixture.client.responses)
        review = self.review(approval)
        body.update(review_id=review['review_id'], answers={'synthetic-decision': ['Accept']})
        self.assertEqual(200, self.respond(approval, body)[0])
        self.assertEqual((self.rpc, {'answers': {'synthetic-decision': {'answers': ['Accept']}}}),
                         self.fixture.client.responses[-1])
        self.fixture.emit(self.task, 'turn/completed', turn={'id': self.task['turn_id'], 'status': 'completed'})
        self.assertEqual('completed', self.fixture.app.tasks[self.task['id']]['status'])

    def form(self, **updates):
        return self.native('mcpServer/elicitation/request', {
            'serverName': 'synthetic_connector', 'mode': 'form',
            'message': 'Synthetic typed confirmation; no real external action.',
            'requestedSchema': {'type': 'object', 'properties': {
                'choice': {'type': 'string', 'enum': ['Review', 'Confirm']},
                'confirmed': {'type': 'boolean'}, 'count': {'type': 'integer', 'minimum': 1, 'maximum': 3}},
                'required': ['choice', 'confirmed', 'count']}, **updates})

    def test_mcp_form_accept_returns_exact_typed_native_content(self):
        approval = self.form()
        review = self.review(approval)
        content = {'choice': 'Review', 'confirmed': False, 'count': 2}
        status, result = self.respond(approval, {'decision': 'accept', 'review_id': review['review_id'], 'content': content})
        self.assertEqual(200, status, result)
        self.assertEqual((self.rpc, {'action': 'accept', 'content': content}), self.fixture.client.responses[-1])
        self.assertEqual('running', self.fixture.app.tasks[self.task['id']]['status'])

    def test_mcp_form_declared_enum_and_bounds_cannot_be_bypassed_in_post(self):
        for content in ({'choice': 'Unoffered', 'confirmed': True, 'count': 2},
                        {'choice': 'Review', 'confirmed': True, 'count': 100}):
            with self.subTest(content=content):
                task = self.fixture.task('Synthetic schema validation')
                self.task = task
                approval = self.form()
                review = self.review(approval)
                status, _ = self.respond(approval, {'decision': 'accept', 'review_id': review['review_id'], 'content': content})
                self.assertIn(status, (400, 409))
        self.assertEqual([], self.fixture.client.responses)

    def test_mcp_form_protected_or_unenforced_schema_cannot_be_approved(self):
        unsafe_properties = (
            {'credential': {'type': 'string', 'format': 'password'}},
            {'credential': {'type': 'string', 'writeOnly': True}},
            {'code': {'type': 'string', 'pattern': '^[A-Z]+$'}},
            {'choices': {'type': 'array', 'items': {'type': 'string', 'enum': ['A', 'B']}}},
        )
        for properties in unsafe_properties:
            with self.subTest(properties=properties):
                task = self.fixture.task('Synthetic protected form')
                self.task = task
                approval = self.form(requestedSchema={
                    'type': 'object', 'properties': properties, 'required': list(properties)})
                status, _ = self.fixture.request(f'/api/approvals/{approval["id"]}/review')
                self.assertEqual(409, status)
                self.assertEqual([], self.fixture.client.responses)

    def test_mcp_url_requires_explicit_human_acknowledgement(self):
        approval = self.native('mcpServer/elicitation/request', {
            'serverName': 'synthetic_connector', 'mode': 'url', 'elicitationId': 'synthetic-external-step',
            'message': 'Synthetic external verification acknowledgement.',
            'url': 'https://example.com/synthetic-verification'})
        review = self.review(approval)
        self.assertEqual(409, self.respond(approval, {'decision': 'accept', 'review_id': review['review_id'],
                                                    'external_completed': False})[0])
        self.assertEqual([], self.fixture.client.responses)
        review = self.review(approval)
        self.assertEqual(200, self.respond(approval, {'decision': 'accept', 'review_id': review['review_id'],
                                                    'external_completed': True})[0])
        self.assertEqual((self.rpc, {'action': 'accept', 'content': {}}), self.fixture.client.responses[-1])

    def test_missing_turn_mcp_uses_owned_turn_without_fabricating_native_identity(self):
        approval = self.form(turnId=None)
        review = self.review(approval)
        self.assertIsNone(review['context']['turnId'])
        self.assertNotIn('itemId', review['context'])
        body = {'decision': 'accept', 'review_id': review['review_id'],
                'content': {'choice': 'Confirm', 'confirmed': True, 'count': 1}}
        self.assertEqual(200, self.respond(approval, body)[0])
        self.assertEqual(409, self.respond(approval, body)[0])
        self.assertEqual(1, len(self.fixture.client.responses))

    def test_missing_turn_mcp_is_invalid_after_owned_turn_changes(self):
        approval = self.form(turnId=None)
        review = self.review(approval)
        self.fixture.app.owned_threads[self.task['thread_id']]['current_turn'] = 'synthetic-follow-up-turn'
        status, _ = self.respond(approval, {'decision': 'accept', 'review_id': review['review_id'],
            'content': {'choice': 'Confirm', 'confirmed': True, 'count': 1}})
        self.assertEqual(409, status)
        self.assertEqual([], self.fixture.client.responses)
