import json
import subprocess
import sys
import threading
import unittest

from dashboard.codex_client import CodexClient, ProtocolError, RequestRejected


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

    def test_disconnect_and_timeout_wake_pending_without_replay(self):
        self.client.connect()
        with self.assertRaises(ProtocolError):
            self.client.request("test/no-response", {}, timeout=.05)
        self.assertTrue(self.client.closed)
        self.assertTrue(self.disconnected.wait(2))
        self.assertFalse(self.client.pending)


if __name__ == "__main__":
    unittest.main()
