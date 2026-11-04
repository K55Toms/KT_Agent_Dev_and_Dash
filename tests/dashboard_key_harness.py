"""Test harness for the dashboard key: existing HTTP tests run against an enforcing server.

`make_test_server` builds the real server with a synthetic key and a handler that supplies that key on any request
which arrives without the header, standing in for the browser page. The real check (`Handler._keyed`) still runs on
every request. Tests of the key itself (tests/test_dashboard_key.py) use `make_server` directly instead.
"""
from dashboard.server import DASHBOARD_KEY_HEADER, Handler, make_server

TEST_DASHBOARD_KEY = "Synthetic_harness_dashboard_key_0123456789abcdef"  # Test value, not a secret.


class KeySupplyingHandler(Handler):
    def parse_request(self):
        ok = super().parse_request()
        if ok and DASHBOARD_KEY_HEADER not in self.headers:
            self.headers[DASHBOARD_KEY_HEADER] = TEST_DASHBOARD_KEY
        return ok


def make_test_server(app, port=0):
    server = make_server(app, port, dashboard_key=TEST_DASHBOARD_KEY)
    server.RequestHandlerClass = KeySupplyingHandler
    return server
