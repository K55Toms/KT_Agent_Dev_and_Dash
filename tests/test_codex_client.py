import json
import subprocess
import sys
import threading
import unittest

from dashboard.codex_client import CodexClient, ProtocolError, RequestRejected
from dashboard.diagnostics import classify_error


FAKE_SERVER = r'''
import json,sys
for line in sys.stdin:
    message=json.loads(line)
    method=message.get('method')
    if method=='initialize':
        print(json.dumps({'id':message['id'],'result':{'userAgent':'fake-server'}}),flush=True)
    elif method=='initialized':
        print(json.dumps({'method':'test/ready','params':{}}),flush=True)
    elif method=='test/request':
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
                 ({"message": "The model is not supported: SYNTHETIC_PRIVATE"}, "model_unavailable"),
                 ({"message": "quota exceeded SYNTHETIC_PRIVATE"}, "usage_limit"),
                 ({"message": "sandbox-exec: operation not permitted SYNTHETIC_PRIVATE"}, "sandbox_initialization"),
                 ({"message": {"raw": "SYNTHETIC_PRIVATE"}}, "request_rejected"),
                 ({"message": "SYNTHETIC_PRIVATE" * 10000}, "request_rejected")]
        for payload, expected in cases:
            self.assertEqual(expected, classify_error(payload))

    def test_disconnect_and_timeout_wake_pending_without_replay(self):
        self.client.connect()
        with self.assertRaises(ProtocolError):
            self.client.request("test/no-response", {}, timeout=.05)
        self.assertTrue(self.client.closed)
        self.assertTrue(self.disconnected.wait(2))
        self.assertFalse(self.client.pending)


if __name__ == "__main__":
    unittest.main()
