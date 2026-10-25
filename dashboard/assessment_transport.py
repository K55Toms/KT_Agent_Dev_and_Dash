"""Bounded conversation-only inference with no native runtime or tool executor.

Only scanner-approved strings enter a fixed Responses request. Model text is buffered
until a validated terminal response and a successful output scan; partial replies,
reasoning, remote errors and credentials never escape this transport.
"""
import hashlib
import json
import re
import time

from .recovery_auth import MODELS, RESPONSES, RecoveryAuthError, _json

CONTRACT = {
    'version': 1, 'purpose': 'recovery_assessment',
    'transport': 'chatgpt_plan_public_responses_https_text_only',
    'input': 'bounded_scanner_checked_plain_text_and_history',
    'output': 'completed_scanner_checked_text_and_observed_usage',
    'authority': 'no_local_runtime_no_tools_no_project_mount_no_executor',
    'tokens': 'memory_only_separate_public_oauth_no_native_auth_access',
    'state': 'no_remote_storage_no_continuation_id_no_automatic_retry',
}
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z')
MAX_INPUT = 131072
MAX_OUTPUT = 131072
MAX_STREAM = 2097152
MAX_EVENT = 262144
MAX_SECONDS = 120


class AssessmentError(ValueError):
    def __init__(self, code='request_failed'):
        allowed = {'cancelled', 'auth_changed', 'auth_required', 'plan_unavailable',
                   'request_failed', 'delivery_unknown', 'model_unavailable',
                   'invalid_input', 'content_blocked', 'unsupported_output'}
        self.code = code if code in allowed else 'request_failed'
        super().__init__(self.code)


class AssessmentTransport:
    contract_digest = hashlib.sha256(json.dumps(CONTRACT, sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()

    def __init__(self, auth, check_text):
        if not callable(check_text):
            raise ValueError('Assessment requires a mandatory content checker')
        self.auth = auth
        self._check_text = check_text

    def status(self):
        return self.auth.status()

    def start_auth(self):
        return self.auth.start()

    def cancel_auth(self):
        return self.auth.cancel()

    def sign_out(self):
        return self.auth.sign_out()

    def close(self):
        self.auth.close()

    def commit_if_current(self, expected_generation, callback):
        """Bind a short local commit to the unchanged authenticated session.

        The callback must not perform network operations. Auth metadata persistence
        must not acquire the dashboard lock, which the caller may already hold.
        """
        with self.auth._lock:
            status = self.auth.status()
            if (status['generation'] != expected_generation or not status['authenticated']
                    or not status['plan_enabled']):
                raise AssessmentError('auth_changed')
            return callback()

    def _checked(self, value):
        if (not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > MAX_INPUT
                or any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in value)):
            raise AssessmentError('invalid_input')
        try:
            checked = self._check_text(value)
            # Checker must return checked text; boolean/None cannot authorize bytes.
            if not isinstance(checked, str) or not checked.strip():
                raise ValueError()
            return checked
        except Exception:
            raise AssessmentError('content_blocked') from None

    def _guard(self, generation, cancel):
        if cancel is not None and cancel.is_set():
            raise AssessmentError('cancelled')
        if self.auth.status()['generation'] != generation:
            raise AssessmentError('auth_changed')

    def assess(self, task, history, instruction, cancel=None):
        if not isinstance(task, dict) or not isinstance(history, list) or len(history) > 64:
            raise AssessmentError('invalid_input')
        model = task.get('model')
        if not isinstance(model, str) or not MODEL.fullmatch(model):
            raise AssessmentError('invalid_input')
        instructions = self._checked(instruction)
        inputs = []
        for message in history:
            if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                    or message['role'] not in {'user', 'assistant'}):
                raise AssessmentError('invalid_input')
            # Only text strings, never file references, structured items or tools.
            inputs.append({'role': message['role'], 'content': self._checked(message['content'])})
        if not inputs or len(json.dumps(inputs).encode()) + len(instructions.encode()) > MAX_INPUT:
            raise AssessmentError('invalid_input')
        status = self.auth.status()
        generation = status['generation']
        if not status['authenticated']:
            raise AssessmentError('auth_required')
        if not status['plan_enabled']:
            raise AssessmentError('plan_unavailable')
        self._guard(generation, cancel)
        dispatched = False
        try:
            with self.auth.authorized_open(MODELS, cancel=cancel, generation=generation) as response:
                catalog = _json(response)
            self._guard(generation, cancel)
            models = catalog.get('models')
            if not isinstance(models, list) or len(models) > 1000:
                raise AssessmentError('request_failed')
            if not any(isinstance(entry, dict) and entry.get('slug') == model for entry in models):
                raise AssessmentError('model_unavailable')
            payload = {'model': model, 'instructions': instructions, 'input': inputs,
                       'tools': [], 'tool_choice': 'none', 'store': False, 'stream': True}
            reasoning = task.get('reasoning')
            if reasoning is not None:
                if reasoning not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
                    raise AssessmentError('invalid_input')
                payload['reasoning'] = {'effort': reasoning}
            self._guard(generation, cancel)
            dispatched = True
            with self.auth.authorized_open(RESPONSES, body=json.dumps(payload).encode(),
                                           cancel=cancel, generation=generation) as response:
                result = self._read_stream(response, model, generation, cancel)
            self._guard(generation, cancel)
            result['text'] = self._checked(result['text'])
            self._guard(generation, cancel)
            return {**result, 'auth_generation': generation}
        except AssessmentError:
            raise
        except RecoveryAuthError as error:
            self._guard(generation, cancel)
            code = ('auth_required' if error.code in {'sign_in_required', 'dependency_unavailable'} else
                    'plan_unavailable' if error.code == 'plan_unavailable' else
                    'delivery_unknown' if dispatched else 'request_failed')
            raise AssessmentError(code) from None
        except Exception:
            self._guard(generation, cancel)
            raise AssessmentError('delivery_unknown' if dispatched else 'request_failed') from None

    @staticmethod
    def _item(item):
        if not isinstance(item, dict):
            raise AssessmentError('unsupported_output')
        if item.get('type') == 'reasoning':
            return
        if item.get('type') != 'message' or item.get('role') != 'assistant':
            raise AssessmentError('unsupported_output')
        content = item.get('content')
        if not isinstance(content, list):
            raise AssessmentError('unsupported_output')
        for part in content:
            if not isinstance(part, dict) or part.get('type') != 'output_text' or not isinstance(part.get('text'), str):
                raise AssessmentError('unsupported_output')

    @staticmethod
    def _usage(value):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise AssessmentError('unsupported_output')
        result = {}
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            number = value.get(key)
            if type(number) is not int or not 0 <= number <= 1000000000:
                raise AssessmentError('unsupported_output')
            result[key] = number
        for source, key, target in (('input_tokens_details', 'cached_tokens', 'cached_input_tokens'),
                                    ('output_tokens_details', 'reasoning_tokens', 'reasoning_output_tokens')):
            details = value.get(source)
            if details is not None:
                number = details.get(key) if isinstance(details, dict) else None
                if type(number) is not int or not 0 <= number <= 1000000000:
                    raise AssessmentError('unsupported_output')
                result[target] = number
        return result

    def _read_stream(self, response, model, generation, cancel):
        header = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if header != 'text/event-stream':
            raise AssessmentError('unsupported_output')
        start, total, events, chunk_size = time.monotonic(), 0, 0, 0
        data, event_name, texts = [], None, {}
        while True:
            self._guard(generation, cancel)
            if time.monotonic() - start > MAX_SECONDS:
                raise AssessmentError('delivery_unknown')
            raw = response.readline(65537)
            self._guard(generation, cancel)
            total += len(raw)
            if total > MAX_STREAM or len(raw) > 65536:
                raise AssessmentError('unsupported_output')
            if not raw:
                raise AssessmentError('delivery_unknown')
            try:
                line = raw.decode('utf-8').rstrip('\r\n')
            except UnicodeError:
                raise AssessmentError('unsupported_output') from None
            if line.startswith(':'):
                continue
            if line.startswith('event:'):
                if event_name is not None:
                    raise AssessmentError('unsupported_output')
                event_name = line[6:].strip()
            elif line.startswith('data:'):
                chunk_size += len(raw)
                if chunk_size > MAX_EVENT:
                    raise AssessmentError('unsupported_output')
                data.append(line[5:].lstrip(' '))
            elif line:
                # Only SSE event/data/comments; no unknown retry/redirect semantics.
                raise AssessmentError('unsupported_output')
            elif data:
                events += 1
                if events > 10000:
                    raise AssessmentError('unsupported_output')
                try:
                    event = json.loads('\n'.join(data))
                except (ValueError, TypeError):
                    raise AssessmentError('unsupported_output') from None
                data, chunk_size = [], 0
                if not isinstance(event, dict) or event_name is not None and event_name != event.get('type'):
                    raise AssessmentError('unsupported_output')
                event_name = None
                kind = event.get('type')
                if kind in {'response.failed', 'response.incomplete', 'error'}:
                    raise AssessmentError('delivery_unknown')
                if kind == 'response.output_text.delta':
                    delta = event.get('delta')
                    index = (event.get('output_index'), event.get('content_index'))
                    if (not isinstance(delta, str) or any(type(v) is not int or v < 0 or v > 128 for v in index)):
                        raise AssessmentError('unsupported_output')
                    texts[index] = texts.get(index, '') + delta
                    if sum(len(text.encode()) for text in texts.values()) > MAX_OUTPUT:
                        raise AssessmentError('unsupported_output')
                elif kind in {'response.output_item.added', 'response.output_item.done'}:
                    self._item(event.get('item'))
                elif kind in {'response.content_part.added', 'response.content_part.done'}:
                    part = event.get('part')
                    if not isinstance(part, dict) or part.get('type') != 'output_text':
                        raise AssessmentError('unsupported_output')
                elif kind == 'response.completed':
                    result = event.get('response')
                    if (not isinstance(result, dict) or result.get('status') != 'completed'
                            or result.get('model') != model or not isinstance(result.get('output'), list)):
                        raise AssessmentError('unsupported_output')
                    final = {}
                    for item_index, item in enumerate(result['output']):
                        self._item(item)
                        if item['type'] == 'message':
                            for content_index, part in enumerate(item['content']):
                                final[(item_index, content_index)] = part['text']
                    if not final or texts and texts != final:
                        raise AssessmentError('unsupported_output')
                    text = '\n'.join(final[index] for index in sorted(final))
                    if not text.strip() or len(text.encode()) > MAX_OUTPUT:
                        raise AssessmentError('unsupported_output')
                    return {'text': text, 'usage': self._usage(result.get('usage')), 'model': model}
                elif kind not in {'response.created', 'response.in_progress', 'response.queued',
                                  'response.output_text.done', 'response.reasoning_summary_part.added',
                                  'response.reasoning_summary_part.done', 'response.reasoning_summary_text.delta',
                                  'response.reasoning_summary_text.done', 'response.reasoning_text.delta',
                                  'response.reasoning_text.done', 'response.reasoning_part.added',
                                  'response.reasoning_part.done'}:
                    raise AssessmentError('unsupported_output')
