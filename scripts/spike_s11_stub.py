#!/usr/bin/env python3
"""Spike S11 throwaway stub listener (stdlib only, loopback 127.0.0.1 only, runs outside the dashboard).

Never decides anything itself: every mode is a candidate "no decision" reply to a Claude Code http hook.
  empty_object  HTTP 200, body {}
  status_204    HTTP 204, no body
  close         drop the connection without a reply
  hold          keep the connection open until the client gives up
--script allow|deny --after SECONDS answers a PermissionRequest with that decision after the delay instead
(to cover late allow/deny and simultaneous-answer cases). The log holds time, event name and field NAMES only.
"""
import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ('empty_object', 'status_204', 'close', 'hold')
MAX_BODY = 1 << 20
HOLD_CAP = 600.0


def _safe(text):
    return re.sub(r'[^A-Za-z0-9_]', '?', str(text))[:48]


def make_server(mode, port, log_path, script=None, after=0.0):
    if mode not in MODES:
        raise ValueError('unknown mode')
    lock = threading.Lock()

    def log(line):
        with lock, open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(time.strftime('%H:%M:%S', time.gmtime()) + ' ' + line + '\n')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _reply(self, status, body=b''):
            self.send_response(status)
            if status != 204:
                self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _hold(self, seconds):
            self.connection.settimeout(0.2)
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try:
                    if self.connection.recv(1) == b'':
                        return False
                except TimeoutError:
                    continue
                except OSError:
                    return False
            return True

        def do_POST(self):
            try:
                length = min(int(self.headers.get('Content-Length') or 0), MAX_BODY)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length else b''
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
            if isinstance(data, dict):
                event = _safe(data.get('hook_event_name', 'unknown'))
                fields = ','.join(sorted(_safe(k) for k in data))
            else:
                event, fields = 'unparsed', ''
            log('event=%s mode=%s fields=[%s]' % (event, mode, fields))
            if script and event == 'PermissionRequest':
                if after > 0 and not self._hold(after):
                    log('event=%s client_gone_before_script' % event)
                    self.close_connection = True
                    return
                decision = {'hookSpecificOutput': {'hookEventName': 'PermissionRequest',
                                                   'decision': {'behavior': script}}}
                self._reply(200, json.dumps(decision).encode())
                log('event=%s answered=%s' % (event, script))
                return
            if mode == 'empty_object':
                self._reply(200, b'{}')
            elif mode == 'status_204':
                self._reply(204)
            elif mode == 'close':
                self.close_connection = True
                self.connection.close()
            else:
                self._hold(HOLD_CAP)
                log('event=%s hold_ended' % event)
                self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--mode', choices=MODES, default='empty_object')
    parser.add_argument('--port', type=int, default=53411)
    parser.add_argument('--log', required=True)
    parser.add_argument('--script', choices=('allow', 'deny'))
    parser.add_argument('--after', type=float, default=0.0)
    args = parser.parse_args()
    server = make_server(args.mode, args.port, args.log, args.script, args.after)
    print('S11 stub on 127.0.0.1:%d mode=%s script=%s after=%s' % (server.server_address[1], args.mode,
                                                                    args.script, args.after))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
