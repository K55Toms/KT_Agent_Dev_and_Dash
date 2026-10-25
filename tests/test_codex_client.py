import json
import subprocess
import sys
import threading
import unittest

from dashboard.codex_client import CodexClient, ProtocolError, RequestRejected
from dashboard.diagnostics import classify_error


FAKE_SERVER = r'''
import json,sys
late_id = None
for line in sys.stdin:
    message=json.loads(line)
    method=message.get('method')
    if method=='initialize':
        print(json.dumps({'id':message['id'],'result':{'userAgent':'fake-server'}}),flush=True)
    elif method=='initialized':
        print(json.dumps({'method':'test/ready','params':{}}),flush=True)
    elif method=='test/request':
        if late_id:
            print(json.dumps({'id':late_id,'result':{'late':True}}),flush=True)
            late_id = None
        print(json.dumps({'id':message['id'],'result':{'ok':True}}),flush=True)
        print(json.dumps({'id':19,'method':'item/commandExecution/requestApproval','params':{'threadId':'test'}}),flush=True)
    elif method=='test/error':
        print(json.dumps({'id':message['id'],'error':{'message':'SYNTHETIC_PRIVATE_ERROR'}}),flush=True)
    elif method=='test/reject':
        print(json.dumps({'id':message['id'],'error':{'code':-32602,'message':'SYNTHETIC_PRIVATE_REJECTION'}}),flush=True)
    elif method=='test/config':
        print(json.dumps({'id':message['id'],'error':{'code':-32600,'message':'failed to load config.toml: SYNTHETIC_PRIVATE_CONFIGURATION'}}),flush=True)
    elif method=='test/exit':
        break
    elif method=='thread/read' and message['params']['threadId']=='synthetic-timeout':
        late_id = message['id']
    elif method=='thread/read' and message['params']['threadId']=='synthetic-eof':
        break
    elif method=='thread/read' and message['params']['threadId']=='synthetic-malformed':
        print('malformed JSON',flush=True)
    elif method in {'thread/read','thread/list','thread/turns/list','thread/goal/get',
                    'thread/backgroundTerminals/list','thread/loaded/list'}:
        print(json.dumps({'id':message['id'],'result':{'params':message['params']}}),flush=True)
'''


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.ready = threading.Event()
        self.disconnected = threading.Event()
        self.factory_args = None
        def factory(args, **kwargs):
            self.factory_args = args, kwargs
            return subprocess.Popen([sys.executable, "-u", "-c", FAKE_SERVER], **kwargs)
        def event(message):
            self.events.append(message)
            self.ready.set()
        self.client = CodexClient(event, self.disconnected.set, process_factory=factory)

    def tearDown(self):
        self.client.close()

    def test_closed_or_started_client_cannot_spawn_another_process(self):
        self.client.connect()
        process = self.client.process
        with self.assertRaises(ProtocolError):
            self.client.connect()
        self.assertIs(process, self.client.process)
        self.client.close()
        with self.assertRaises(ProtocolError):
            self.client.connect()
        fresh = CodexClient(lambda _message: None, lambda: None,
                            process_factory=lambda *_args, **_kwargs: self.fail('Closed client spawned a process'))
        fresh.close()
        with self.assertRaises(ProtocolError):
            fresh.connect()

    def test_handshake_requests_events_no_shell_or_inference(self):
        result = self.client.connect()
        self.assertEqual("fake-server", result["userAgent"])
        self.assertTrue(self.ready.wait(2))
        self.assertEqual(["codex", "app-server"], self.factory_args[0])
        self.assertNotIn("shell", self.factory_args[1])
        self.assertEqual(subprocess.DEVNULL, self.factory_args[1]["stderr"])
        self.assertEqual({"ok": True}, self.client.request("test/request", {}))
        self.assertFalse(self.client.closed)

    def test_raw_errors_are_never_in_exception(self):
        self.client.connect()
        with self.assertRaises(ProtocolError) as error:
            self.client.request("test/error", {})
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", str(error.exception))
        self.assertNotIsInstance(error.exception, RequestRejected)

    def test_explicit_json_rpc_rejection_is_payload_free_and_distinct(self):
        self.client.connect()
        with self.assertRaises(RequestRejected) as error:
            self.client.request("test/reject", {})
        self.assertNotIn("SYNTHETIC_PRIVATE_REJECTION", str(error.exception))
        self.assertEqual("invalid_params", error.exception.diagnostic_code)

    def test_configuration_error_retains_only_fixed_diagnostic(self):
        self.client.connect()
        with self.assertRaises(RequestRejected) as error:
            self.client.request("test/config", {})
        self.assertEqual("config_invalid", error.exception.diagnostic_code)
        self.assertNotIn("SYNTHETIC_PRIVATE", repr(error.exception))
        self.assertFalse(self.client.pending)

    def test_error_classification_is_fixed_and_bounded(self):
        cases = [({"codexErrorInfo": "unauthorized", "message": "SYNTHETIC_PRIVATE"}, "authentication_required"),
                 ({"message": "invalid thread-store request: no rollout found for thread id SYNTHETIC_PRIVATE"}, "thread_history_unavailable"),
                 ({"message": "The model is not supported: SYNTHETIC_PRIVATE"}, "model_unavailable"),
                 ({"message": "quota exceeded SYNTHETIC_PRIVATE"}, "usage_limit"),
                 ({"message": "sandbox-exec: operation not permitted SYNTHETIC_PRIVATE"}, "sandbox_initialization"),
                 ({"message": {"raw": "SYNTHETIC_PRIVATE"}}, "request_rejected"),
                 ({"message": "SYNTHETIC_PRIVATE" * 10000}, "request_rejected")]
        for payload, expected in cases:
            self.assertEqual(expected, classify_error(payload))

    def test_mutation_timeout_disconnects_and_wakes_pending_without_replay(self):
        self.client.connect()
        with self.assertRaises(ProtocolError):
            self.client.request("turn/start", {}, timeout=.05)
        self.assertTrue(self.client.closed)
        self.assertTrue(self.disconnected.wait(2))
        self.assertFalse(self.client.pending)

    def test_readonly_timeout_preserves_shared_process_and_ignores_late_reply(self):
        self.client.connect()
        process = self.client.process
        with self.assertRaisesRegex(ProtocolError, 'metadata response timed out'):
            self.client.request_readonly('thread/read', {'threadId': 'synthetic-timeout', 'includeTurns': False}, timeout=.05)
        self.assertFalse(self.client.pending)
        self.assertFalse(self.client.closed)
        self.assertFalse(self.disconnected.is_set())
        self.assertIsNone(process.poll())
        # The fake server first replies to the expired ID, then to this live ID.
        self.assertEqual({'ok': True}, self.client.request('test/request', {}, timeout=1))
        self.assertFalse(self.client.pending)
        self.assertFalse(self.client.closed)

    def test_readonly_whitelist_sends_only_bounded_metadata_shapes(self):
        self.client.connect()
        cases = [
            ('thread/read', {'threadId': 'synthetic-root', 'includeTurns': False}),
            ('thread/list', {'ancestorThreadId': 'synthetic-root', 'archived': True, 'useStateDbOnly': True, 'limit': 100, 'cursor': 'next'}),
            ('thread/turns/list', {'threadId': 'synthetic-root', 'itemsView': 'notLoaded', 'sortDirection': 'desc', 'limit': 100, 'cursor': 'next'}),
            ('thread/goal/get', {'threadId': 'synthetic-root'}),
            ('thread/backgroundTerminals/list', {'threadId': 'synthetic-root', 'limit': 100, 'cursor': 'next'}),
            ('thread/loaded/list', {'limit': 256, 'cursor': 'next'}),
        ]
        for method, params in cases:
            with self.subTest(method=method):
                self.assertEqual({'params': params}, self.client.request_readonly(method, params, timeout=1))

    def test_unsafe_readonly_methods_and_parameters_are_rejected_before_wire(self):
        from unittest.mock import patch
        self.client.connect()
        cases = [
            ('turn/start', {}), ('thread/resume', {}), ('unknown/read', {}),
            ('thread/read', {'threadId': 'synthetic-root'}),
            ('thread/read', {'threadId': 'synthetic-root', 'includeTurns': True}),
            ('thread/read', {'threadId': 'synthetic-root', 'includeTurns': 0}),
            ('thread/read', {'threadId': '', 'includeTurns': False}),
            ('thread/read', {'threadId': 'synthetic-root', 'includeTurns': False, 'extra': True}),
            ('thread/list', {'ancestorThreadId': 'synthetic-root', 'archived': False, 'useStateDbOnly': False, 'limit': 100}),
            ('thread/list', {'archived': False, 'useStateDbOnly': True, 'limit': 100}),
            ('thread/list', {'ancestorThreadId': 'synthetic-root', 'archived': 0, 'useStateDbOnly': True, 'limit': 100}),
            ('thread/turns/list', {'threadId': 'synthetic-root', 'itemsView': 'full', 'sortDirection': 'desc', 'limit': 100}),
            ('thread/turns/list', {'threadId': 'synthetic-root', 'itemsView': 'summary', 'sortDirection': 'desc', 'limit': 100}),
            ('thread/goal/get', {'threadId': 'synthetic-root', 'prompt': 'synthetic'}),
            ('thread/backgroundTerminals/list', {'threadId': 'synthetic-root', 'limit': 101}),
            ('thread/loaded/list', {'limit': True}), ('thread/loaded/list', {'limit': 0}),
            ('thread/loaded/list', {'limit': 257}), ('thread/loaded/list', {'limit': 1, 'cursor': None}),
            ('thread/loaded/list', {'limit': 1, 'cursor': 'x' * 4097}),
        ]
        with patch.object(self.client, '_write') as write:
            for method, params in cases:
                with self.subTest(method=method, params=params):
                    with self.assertRaises(ProtocolError):
                        self.client.request_readonly(method, params)
            write.assert_not_called()
        self.assertFalse(self.client.pending)
        self.assertFalse(self.client.closed)

    def test_readonly_eof_and_malformed_framing_remain_fatal(self):
        for identifier in ('synthetic-eof', 'synthetic-malformed'):
            with self.subTest(identifier=identifier):
                if self.client.process is not None:
                    self.client.close()
                    self.setUp()
                self.client.connect()
                with self.assertRaises(ProtocolError):
                    self.client.request_readonly('thread/read', {'threadId': identifier, 'includeTurns': False}, timeout=1)
                self.assertTrue(self.client.closed)
                self.assertTrue(self.disconnected.wait(1))
                self.assertFalse(self.client.pending)

    def test_response_wait_deducts_time_spent_writing(self):
        from unittest.mock import Mock, patch
        waiter_event = Mock()
        waiter_event.wait.return_value = False
        with patch('dashboard.codex_client.threading.Event', return_value=waiter_event), \
                patch('dashboard.codex_client.time.monotonic', side_effect=[100, 100.75]), \
                patch.object(self.client, '_write'):
            with self.assertRaises(ProtocolError):
                self.client.request_readonly('thread/loaded/list', {'limit': 1}, timeout=1)
        waiter_event.wait.assert_called_once_with(.25)
        self.assertFalse(self.client.closed)
        self.assertFalse(self.client.pending)



class GuardedRequestTests(unittest.TestCase):
    """Real client framing over POSIX pipes; no native server, account, or network."""
    def setUp(self):
        import os
        from io import StringIO
        self.os = os
        self.read_fd, self.write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        self.held = threading.Event()
        self.released = threading.Event()
        self.written = threading.Event()
        self.disconnected = threading.Event()
        self.dashboard_lock = threading.Lock()
        self.validations = 0
        self.results, self.errors = [], []
        owner = self
        class Input:
            closed = False
            def fileno(self):
                return owner.write_fd
            def write(self, _value):
                raise AssertionError('TextIO writes cannot enforce the IPC deadline')
            def flush(self):
                raise AssertionError('Raw bounded frames require no buffered flush')
            def close(self):
                if not self.closed:
                    self.closed = True
                    os.close(owner.write_fd)
        class Process:
            def __init__(self):
                self.stdin, self.stdout = Input(), StringIO()
            def terminate(self):
                pass
            def wait(self, timeout=None):
                return 0
            def kill(self):
                pass
        self.client = CodexClient(lambda _: None, self.disconnected.set)
        self.client.process = Process()

    def tearDown(self):
        self.client.close()
        if self.read_fd is not None:
            self.os.close(self.read_fd)

    def guard(self):
        from contextlib import contextmanager
        @contextmanager
        def managed():
            with self.dashboard_lock:
                self.held.set()
                try:
                    def validate():
                        self.assertTrue(self.client.write_lock.locked())
                        self.validations += 1
                    yield validate
                finally:
                    self.held.clear()
                    self.released.set()
        return managed()

    def run_request(self, guard=None):
        try:
            self.results.append(self.client.request_guarded('test/guarded', {}, guard or self.guard, timeout=2))
        except Exception as error:
            self.errors.append(error)

    def read_bytes(self):
        data = bytearray()
        while True:
            try:
                chunk = self.os.read(self.read_fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)

    def reply(self, key):
        with self.client.lock:
            waiter = self.client.pending[key]
            waiter['result'] = {'ok': True}
            waiter['event'].set()

    def checked_write(self, real_write):
        def write(fd, data):
            self.assertTrue(self.held.is_set())
            self.assertTrue(self.dashboard_lock.locked())
            self.assertTrue(self.client.write_lock.locked())
            self.assertGreater(self.validations, 0)
            result = real_write(fd, data)
            if bytes(data[:result]).endswith(b'\n'):
                self.written.set()
            return result
        return write

    def test_guard_covers_actual_raw_write_released_before_response_wait(self):
        from unittest.mock import patch
        real_write = self.os.write
        with patch('dashboard.codex_client.os.write', side_effect=self.checked_write(real_write)):
            worker = threading.Thread(target=self.run_request)
            worker.start()
            self.assertTrue(self.written.wait(1))
            self.assertTrue(self.released.wait(1))
            self.assertTrue(worker.is_alive())
            self.assertTrue(self.dashboard_lock.acquire(timeout=1))
            self.dashboard_lock.release()
            self.assertFalse(self.client.write_lock.locked())
            self.assertTrue(self.os.get_blocking(self.write_fd))
            frame = json.loads(self.read_bytes())
            self.reply(frame['id'])
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], self.errors)
        self.assertEqual([{'ok': True}], self.results)
        self.assertFalse(self.client.pending)

    def test_guard_entry_and_final_validation_errors_send_zero_bytes(self):
        from contextlib import contextmanager
        error = ValueError('synthetic revoked authority')
        @contextmanager
        def entry_failure():
            raise error
            yield
        with self.assertRaises(ValueError) as caught:
            self.client.request_guarded('test/guarded', {}, entry_failure)
        self.assertIs(error, caught.exception)
        @contextmanager
        def validation_failure():
            def validate():
                self.assertTrue(self.client.write_lock.locked())
                raise error
            yield validate
        with self.assertRaises(ValueError) as caught:
            self.client.request_guarded('test/guarded', {}, validation_failure)
        self.assertIs(error, caught.exception)
        self.assertEqual(b'', self.read_bytes())
        self.assertFalse(self.client.pending)
        self.assertFalse(self.client.write_lock.locked())
        self.assertFalse(self.client.closed)

    def test_writer_contention_releases_guard_and_validates_after_reacquisition(self):
        from contextlib import contextmanager
        entered = threading.Event()
        allowed = {'value': True}
        @contextmanager
        def authority():
            with self.guard() as validate:
                entered.set()
                def final():
                    validate()
                    if not allowed['value']:
                        raise ValueError('synthetic revoked authority')
                yield final
        self.client.write_lock.acquire()
        worker = threading.Thread(target=lambda: self.run_request(authority), daemon=True)
        try:
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.released.wait(1))
            self.assertEqual(0, self.validations)
            self.assertTrue(self.dashboard_lock.acquire(timeout=1))
            allowed['value'] = False
            self.dashboard_lock.release()
        finally:
            self.client.write_lock.release()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(self.errors))
        self.assertIsInstance(self.errors[0], ValueError)
        self.assertEqual(b'', self.read_bytes())
        self.assertFalse(self.client.pending)

    def test_callback_dashboard_to_writer_order_does_not_deadlock_guarded_request(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        callback_holds_dashboard, allow_callback, guard_called = threading.Event(), threading.Event(), threading.Event()
        callback_done = threading.Event()
        @contextmanager
        def authority():
            guard_called.set()
            with self.guard() as validate:
                yield validate
        def callback():
            with self.dashboard_lock:
                callback_holds_dashboard.set()
                allow_callback.wait(1)
                self.client.respond('native-request', {'decision': 'decline'})
            callback_done.set()
        real_write = self.os.write
        def observed_write(fd, data):
            result = real_write(fd, data)
            if b'test/guarded' in bytes(data):
                self.assertTrue(self.held.is_set())
                self.written.set()
            return result
        with patch('dashboard.codex_client.os.write', side_effect=observed_write):
            callback_worker = threading.Thread(target=callback, daemon=True)
            callback_worker.start()
            self.assertTrue(callback_holds_dashboard.wait(1))
            worker = threading.Thread(target=lambda: self.run_request(authority), daemon=True)
            worker.start()
            self.assertTrue(guard_called.wait(1))
            allow_callback.set()
            self.assertTrue(callback_done.wait(1))
            self.assertTrue(self.written.wait(1))
            frames = [json.loads(line) for line in self.read_bytes().splitlines()]
            own = next(frame for frame in frames if frame.get('method') == 'test/guarded')
            self.reply(own['id'])
            worker.join(2)
            callback_worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(callback_worker.is_alive())
        self.assertEqual([], self.errors)

    def test_response_arriving_inside_send_is_not_lost(self):
        from unittest.mock import patch
        real_write = self.os.write
        def immediate_reply(fd, data):
            result = self.checked_write(real_write)(fd, data)
            self.reply(json.loads(bytes(data))['id'])
            return result
        with patch('dashboard.codex_client.os.write', side_effect=immediate_reply):
            result = self.client.request_guarded('test/guarded', {}, self.guard)
        self.assertEqual({'ok': True}, result)
        self.assertTrue(self.released.is_set())
        self.assertFalse(self.client.pending)

    def test_interrupted_and_short_writes_form_one_frame_without_replay(self):
        import errno
        from unittest.mock import patch
        real_write = self.os.write
        calls = []
        def short_write(fd, data):
            calls.append(1)
            if len(calls) == 1:
                raise InterruptedError(errno.EINTR, 'synthetic interruption')
            result = self.checked_write(real_write)(fd, data[:3] if len(calls) == 2 else data)
            if len(calls) > 2:
                frame = json.loads(self.read_bytes())
                self.reply(frame['id'])
            return result
        with patch('dashboard.codex_client.os.write', side_effect=short_write):
            result = self.client.request_guarded('test/guarded', {}, self.guard)
        self.assertEqual({'ok': True}, result)
        self.assertEqual(3, len(calls))
        self.assertTrue(self.os.get_blocking(self.write_fd))
        self.assertFalse(self.client.pending)

    def test_partial_frame_timeout_revokes_connection_after_both_locks_release(self):
        import time
        from unittest.mock import patch
        observed = threading.Event()
        def disconnected():
            # Cleanup may legitimately acquire the writer after failed dispatch.
            # Prove the callback can progress rather than assert global ownership.
            for lock in (self.dashboard_lock, self.client.write_lock):
                self.assertTrue(lock.acquire(timeout=1))
                lock.release()
            observed.set()
        self.client.on_disconnect = disconnected
        original_close = self.client.close
        close_calls = []
        def checked_close(*args, **kwargs):
            self.assertFalse(self.dashboard_lock.locked())
            self.assertFalse(self.client.write_lock.locked())
            close_calls.append(True)
            return original_close(*args, **kwargs)
        started = time.monotonic()
        with patch('dashboard.codex_client.WRITE_TIMEOUT', .05), patch.object(self.client, 'close', side_effect=checked_close):
            with self.assertRaises(ProtocolError):
                self.client.request_guarded('test/guarded', {'text': 'x' * 1000000}, self.guard)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(close_calls)
        self.assertTrue(self.client.closed)
        self.assertTrue(observed.wait(1))
        partial = self.read_bytes()
        self.assertGreater(len(partial), 0)
        self.assertFalse(partial.endswith(b'\n'))
        self.assertFalse(self.client.pending)

    def test_readonly_partial_write_remains_fatal_without_retry(self):
        import errno
        from unittest.mock import patch
        real_write = self.os.write
        calls = []
        def partial_then_broken(fd, data):
            calls.append(True)
            if len(calls) == 1:
                return real_write(fd, data[:1])
            raise BrokenPipeError(errno.EPIPE, 'synthetic broken pipe')
        with patch('dashboard.codex_client.os.write', side_effect=partial_then_broken):
            with self.assertRaisesRegex(ProtocolError, 'delivery is unknown'):
                self.client.request_readonly('thread/loaded/list', {'limit': 1}, timeout=1)
        self.assertEqual(2, len(calls))
        self.assertEqual(b'{', self.read_bytes())
        self.assertTrue(self.client.closed)
        self.assertTrue(self.disconnected.wait(1))
        self.assertFalse(self.client.pending)

    def test_ordinary_callback_write_failure_never_waits_for_dashboard_callback(self):
        import time
        from unittest.mock import patch
        observed = threading.Event()
        def disconnected():
            with self.dashboard_lock:
                observed.set()
        self.client.on_disconnect = disconnected
        self.os.close(self.read_fd)
        self.read_fd = None
        started = time.monotonic()
        with self.dashboard_lock:
            with self.assertRaises(ProtocolError):
                self.client.respond('native-request', {'decision': 'decline'})
            self.assertTrue(self.client.closed)
            self.assertFalse(observed.is_set())
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(observed.wait(1))
        self.client.close()
        self.assertTrue(self.client.cleanup_complete.is_set())

    def test_zero_deadline_and_oversized_frame_never_enter_guard_or_write(self):
        from unittest.mock import patch
        called = []
        def unexpected_guard():
            called.append(True)
            return self.guard()
        with patch('dashboard.codex_client.WRITE_TIMEOUT', 0):
            with self.assertRaises(ProtocolError):
                self.client.request_guarded('test/guarded', {}, unexpected_guard)
        with patch('dashboard.codex_client.MAX_WRITE_BYTES', 8):
            with self.assertRaises(ProtocolError):
                self.client.request_guarded('test/guarded', {}, unexpected_guard)
        self.assertEqual([], called)
        self.assertEqual(b'', self.read_bytes())
        self.assertFalse(self.client.pending)

    def test_busy_writer_has_one_deadline_without_validation_or_authority_lock_wait(self):
        from unittest.mock import patch
        self.client.write_lock.acquire()
        worker = threading.Thread(target=self.run_request, daemon=True)
        try:
            with patch('dashboard.codex_client.WRITE_TIMEOUT', .05):
                worker.start()
                self.assertTrue(self.released.wait(1))
                self.assertTrue(self.dashboard_lock.acquire(timeout=1))
                self.dashboard_lock.release()
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(0, self.validations)
            self.assertEqual(1, len(self.errors))
            self.assertIsInstance(self.errors[0], ProtocolError)
            self.assertFalse(self.client.closed)
            self.assertEqual(b'', self.read_bytes())
            self.assertFalse(self.client.pending)
        finally:
            self.client.write_lock.release()

    def test_cleanup_cannot_close_stdin_until_active_writer_exits(self):
        from contextlib import contextmanager
        validated, release_validator, terminated = threading.Event(), threading.Event(), threading.Event()
        self.client.process.terminate = terminated.set
        @contextmanager
        def authority():
            with self.guard() as validate:
                def pause():
                    validate()
                    validated.set()
                    release_validator.wait(1)
                yield pause
        worker = threading.Thread(target=lambda: self.run_request(authority), daemon=True)
        worker.start()
        self.assertTrue(validated.wait(1))
        self.client.close(wait=False)
        self.assertTrue(terminated.wait(1))
        self.assertFalse(self.client.process.stdin.closed)
        release_validator.set()
        worker.join(2)
        self.client.close()
        self.assertTrue(self.client.cleanup_complete.is_set())
        self.assertTrue(self.client.process.stdin.closed)
        self.assertEqual(1, len(self.errors))
        self.assertIsInstance(self.errors[0], ProtocolError)
        self.assertEqual(b'', self.read_bytes())

    def test_explicit_close_waits_existing_async_cleanup_without_closing_live_reader(self):
        from unittest.mock import Mock
        started, release_cleanup, explicit_finished = threading.Event(), threading.Event(), threading.Event()
        def wait(timeout=None):
            started.set()
            release_cleanup.wait(1)
            return 0
        self.client.process.wait = wait
        self.client.reader = Mock()
        self.client.reader.is_alive.return_value = True
        self.client.close(wait=False)
        self.assertTrue(started.wait(1))
        worker = threading.Thread(target=lambda: (self.client.close(), explicit_finished.set()), daemon=True)
        worker.start()
        self.assertFalse(explicit_finished.wait(.05))
        release_cleanup.set()
        worker.join(2)
        self.assertTrue(explicit_finished.is_set())
        self.assertTrue(self.client.cleanup_complete.is_set())
        self.assertFalse(self.client.process.stdout.closed)

    def test_payload_is_frozen_before_guard_entry(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        params = {'text': 'reviewed instruction'}
        @contextmanager
        def mutate():
            params['text'] = 'later mutation'
            with self.guard() as validate:
                yield validate
        real_write = self.os.write
        def immediate_reply(fd, data):
            result = self.checked_write(real_write)(fd, data)
            frame = json.loads(bytes(data))
            self.assertEqual('reviewed instruction', frame['params']['text'])
            self.reply(frame['id'])
            return result
        with patch('dashboard.codex_client.os.write', side_effect=immediate_reply):
            self.assertEqual({'ok': True}, self.client.request_guarded('test/guarded', params, mutate))


if __name__ == '__main__':
    unittest.main()
