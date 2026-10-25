"""Synthetic text-only wire tests; neither real sign-in nor inference is executed."""
from contextlib import contextmanager
import io
import json
import threading
import unittest

from dashboard.assessment_transport import AssessmentError, AssessmentTransport, MAX_OUTPUT
from dashboard.recovery_auth import MODELS, RESPONSES, RecoveryAuthError


def event(kind, **values):
    return ('event: ' + kind + '\ndata: ' + json.dumps({'type': kind, **values}) + '\n\n').encode()


def completed(text='Inspected facts remain uncertain.', model='gpt-6.1-sol', output=None, usage=None):
    output = output if output is not None else [
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}]
    return event('response.completed', response={'status': 'completed', 'model': model,
                                                'output': output, 'usage': usage})


class Stream(io.BytesIO):
    def __init__(self, data, hook=None, content_type='text/event-stream'):
        super().__init__(data)
        self.headers = {'Content-Type': content_type}
        self.hook = hook

    def readline(self, size=-1):
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        return super().readline(size)


class Auth:
    def __init__(self):
        self._lock = threading.RLock()
        self.generation = 1
        self.authenticated = self.plan = True
        self.catalog = {'models': [{'slug': 'gpt-6.1-sol', 'visibility': 'list'}]}
        self.data = completed()
        self.requests = []
        self.error = None
        self.hook = None
        self.content_type = 'text/event-stream'

    def status(self):
        return {'generation': self.generation, 'authenticated': self.authenticated,
                'plan_enabled': self.plan}

    def start(self):
        return {'authorization_url': 'https://auth.openai.com/api/accounts/authorize'}

    def cancel(self):
        self.generation += 1
        return self.status()

    def sign_out(self):
        self.generation += 1
        self.authenticated = self.plan = False
        return self.status()

    def close(self):
        self.sign_out()

    @contextmanager
    def authorized_open(self, url, *, body=None, cancel=None, generation=None):
        self.requests.append((url, json.loads(body) if body else None))
        if self.error:
            raise RecoveryAuthError(self.error)
        response = Stream(json.dumps(self.catalog).encode() if url == MODELS else self.data,
                          hook=self.hook if url == RESPONSES else None,
                          content_type=self.content_type)
        try:
            yield response
        finally:
            response.close()


class AssessmentTransportTests(unittest.TestCase):
    def setUp(self):
        self.auth = Auth()
        self.checked = []
        self.transport = AssessmentTransport(self.auth, self.check)
        self.task = {'model': 'gpt-6.1-sol', 'reasoning': 'high'}
        self.history = [{'role': 'user', 'content': 'Assess these checked observations.'}]
        self.instruction = 'Report facts, uncertainty and proposed next steps. Do not execute actions.'
        self.cancel = threading.Event()

    def check(self, text):
        self.checked.append(text)
        return text

    def assess(self):
        return self.transport.assess(self.task, self.history, self.instruction, self.cancel)

    def expect(self, code):
        with self.assertRaises(AssessmentError) as caught:
            self.assess()
        self.assertEqual(caught.exception.code, code)

    def test_constructor_and_status_never_send_requests(self):
        self.transport.status()
        self.assertEqual(self.auth.requests, [])
        self.assertRegex(self.transport.contract_digest, r'^[a-f0-9]{64}$')

    def test_completed_text_only_payload_has_no_tools_storage_or_continuation(self):
        result = self.assess()
        self.assertEqual(result['text'], 'Inspected facts remain uncertain.')
        self.assertEqual(result['model'], self.task['model'])
        self.assertEqual(result['auth_generation'], 1)
        self.assertIsNone(result['usage'])
        self.assertEqual(len(self.auth.requests), 2)
        url, payload = self.auth.requests[-1]
        self.assertEqual(url, RESPONSES)
        self.assertEqual(payload['tools'], [])
        self.assertEqual(payload['tool_choice'], 'none')
        self.assertIs(payload['store'], False)
        self.assertIs(payload['stream'], True)
        self.assertEqual(payload['reasoning'], {'effort': 'high'})
        self.assertEqual(set(payload), {'model', 'instructions', 'input', 'tools', 'tool_choice', 'store', 'stream', 'reasoning'})
        self.assertEqual(self.checked, [self.instruction, self.history[0]['content'], result['text']])

    def test_history_followups_reconstruct_checked_text_without_remote_response_ids(self):
        self.history += [{'role': 'assistant', 'content': 'An earlier checked reply.'},
                         {'role': 'user', 'content': 'Explain the next safe step.'}]
        self.assess()
        self.assertEqual(self.auth.requests[-1][1]['input'], self.history)
        self.assertNotIn('previous_response_id', self.auth.requests[-1][1])

    def test_streamed_deltas_must_match_completed_output(self):
        text = 'A checked reply.'
        self.auth.data = (event('response.output_text.delta', output_index=0, content_index=0, delta='A checked ')
                          + event('response.output_text.delta', output_index=0, content_index=0, delta='reply.')
                          + completed(text))
        self.assertEqual(self.assess()['text'], text)

    def test_inconsistent_deltas_fail_closed_without_partial_reply(self):
        self.auth.data = event('response.output_text.delta', output_index=0, content_index=0, delta='partial') + completed('different')
        self.expect('unsupported_output')
        self.assertEqual(self.checked, [self.instruction, self.history[0]['content']])

    def test_reasoning_is_not_returned_or_scanned_as_visible_output(self):
        self.auth.data = event('response.reasoning_summary_text.delta', delta='hidden reasoning') + completed(output=[
            {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': 'hidden reasoning'}]},
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Visible checked reply.'}]}])
        result = self.assess()
        self.assertEqual(result['text'], 'Visible checked reply.')
        self.assertNotIn('hidden reasoning', json.dumps(result))
        self.assertNotIn('hidden reasoning', self.checked)

    def test_tool_output_event_is_rejected_with_no_executor(self):
        self.auth.data = event('response.output_item.added', item={'type': 'function_call', 'name': 'shell'}) + completed()
        self.expect('unsupported_output')
        self.assertEqual(len(self.auth.requests), 2)

    def test_tool_output_at_terminal_event_is_rejected(self):
        for kind in ('function_call', 'custom_tool_call', 'web_search_call', 'mcp_call', 'computer_call'):
            with self.subTest(kind=kind):
                self.auth.data = completed(output=[{'type': kind}])
                self.expect('unsupported_output')

    def test_multimodal_content_and_refusals_fail_closed(self):
        self.auth.data = completed(output=[{'type': 'message', 'role': 'assistant',
                                            'content': [{'type': 'refusal', 'refusal': 'unsupported'}]}])
        self.expect('unsupported_output')

    def test_missing_completed_event_never_counts_as_success(self):
        self.auth.data = event('response.output_text.delta', output_index=0, content_index=0, delta='unconfirmed')
        self.expect('delivery_unknown')

    def test_stream_error_and_incomplete_never_retry_or_echo_remote_error(self):
        for kind in ('response.failed', 'response.incomplete', 'error'):
            with self.subTest(kind=kind):
                self.auth.requests.clear()
                self.auth.data = event(kind, message='Do not expose remote detail.')
                self.expect('delivery_unknown')
                self.assertEqual(len(self.auth.requests), 2)

    def test_scanner_failure_on_outbound_prevents_all_remote_requests(self):
        def blocked(_value):
            raise RuntimeError('raw scanner content is not safe to propagate')
        self.transport._check_text = blocked
        self.expect('content_blocked')
        self.assertEqual(self.auth.requests, [])

    def test_scanner_failure_on_completed_output_prevents_result(self):
        def checked(value):
            if value == 'Inspected facts remain uncertain.':
                raise RuntimeError('remote content withheld')
            return value
        self.transport._check_text = checked
        self.expect('content_blocked')

    def test_nontext_history_and_system_input_are_rejected(self):
        for message in ({'role': 'system', 'content': 'not allowed'},
                        {'role': 'user', 'content': [{'type': 'input_file', 'file_id': 'not allowed'}]},
                        {'role': 'user', 'content': 'ok', 'tools': []}):
            with self.subTest(kind=message['role']):
                self.history = [message]
                self.expect('invalid_input')
        self.assertEqual(self.auth.requests, [])

    def test_unavailable_exact_model_does_not_substitute(self):
        self.auth.catalog = {'models': [{'slug': 'gpt-6-luna'}]}
        self.expect('model_unavailable')
        self.assertEqual(len(self.auth.requests), 1)

    def test_actual_returned_model_must_match_requested_model(self):
        self.auth.data = completed(model='different-model')
        self.expect('unsupported_output')

    def test_missing_auth_or_plan_never_sends_requests(self):
        self.auth.authenticated = False
        self.expect('auth_required')
        self.auth.authenticated, self.auth.plan = True, False
        self.expect('plan_unavailable')
        self.assertEqual(self.auth.requests, [])

    def test_cancel_before_start_sends_nothing(self):
        self.cancel.set()
        self.expect('cancelled')
        self.assertEqual(self.auth.requests, [])

    def test_cancel_during_stream_discards_late_reply(self):
        self.auth.hook = self.cancel.set
        self.expect('cancelled')

    def test_signout_during_stream_discards_late_reply(self):
        self.auth.hook = self.auth.sign_out
        self.expect('auth_changed')

    def test_signout_during_output_scan_discards_checked_reply(self):
        def checker(text):
            if text == 'Inspected facts remain uncertain.':
                self.auth.sign_out()
            return text
        self.transport._check_text = checker
        self.expect('auth_changed')

    def test_atomic_commit_gate_rejects_changed_session(self):
        self.auth.sign_out()
        called = []
        with self.assertRaises(AssessmentError) as caught:
            self.transport.commit_if_current(1, lambda: called.append(True))
        self.assertEqual(caught.exception.code, 'auth_changed')
        self.assertEqual(called, [])

    def test_atomic_commit_gate_accepts_current_session(self):
        self.assertEqual(self.transport.commit_if_current(1, lambda: 'saved'), 'saved')

    def test_network_error_before_dispatch_has_safe_code(self):
        self.auth.error = 'connection_failed'
        self.expect('request_failed')

    def test_usage_preserves_observed_units_and_unknown_cost(self):
        self.auth.data = completed(usage={'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17,
                                         'input_tokens_details': {'cached_tokens': 4},
                                         'output_tokens_details': {'reasoning_tokens': 2},
                                         'untrusted_extra': 'never forwarded'})
        self.assertEqual(self.assess()['usage'], {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17,
                                                'cached_input_tokens': 4, 'reasoning_output_tokens': 2})

    def test_invalid_usage_cannot_be_claimed_as_observed(self):
        self.auth.data = completed(usage={'input_tokens': -1, 'output_tokens': 5, 'total_tokens': 4})
        self.expect('unsupported_output')

    def test_non_sse_malformed_and_oversized_lines_are_rejected(self):
        for data in (b'data: not-json\n\n', b'data: ' + b'a' * 65537 + b'\n\n',
                     b'event: wrong\ndata: {"type":"response.created"}\n\n'):
            with self.subTest(case=len(data)):
                self.auth.data = data
                self.expect('unsupported_output')
        self.auth.content_type = 'application/json'
        self.expect('unsupported_output')

    def test_auth_lifecycle_delegates_without_background_requests(self):
        self.assertIn('authorization_url', self.transport.start_auth())
        self.transport.cancel_auth()
        self.transport.sign_out()
        self.transport.close()
        self.assertEqual(self.auth.requests, [])


if __name__ == '__main__':
    unittest.main()
