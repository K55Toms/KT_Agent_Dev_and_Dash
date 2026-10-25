"""Separate, memory-only public-client ChatGPT plan sign-in for recovery.

This does not inspect, import, or change native Codex authentication. Only host and
validated registration identifiers cross the metadata persistence callback. See
https://developers.openai.com/siwc/token-sharing-open-source/sign-in .
"""
import base64
from contextlib import ExitStack, contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

try:
    import jwt
except ImportError:
    jwt = None

ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
JWKS = ISSUER + '/.well-known/jwks.json'
DISCOVERY = ISSUER + '/.well-known/openid-configuration'
RESOURCE = 'https://api.openai.com/v1'
MODELS = RESOURCE + '/models'
RESPONSES = RESOURCE + '/responses'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
APP_NAME = 'AI-native engineering dashboard'
CLIENT = re.compile(r'[A-Za-z0-9_-]{1,200}\Z')
FINGERPRINT = re.compile(r'[a-f0-9]{64}\Z')


class RecoveryAuthError(ValueError):
    """Errors contain a fixed code, never a remote body or credential."""
    def __init__(self, code='authentication_failed'):
        allowed = {
            'authentication_failed', 'sign_in_required', 'sign_in_expired',
            'sign_in_cancelled', 'sign_in_denied', 'invalid_callback',
            'identity_mismatch', 'plan_unavailable', 'request_cancelled',
            'connection_failed', 'remote_rejected', 'rate_limited',
            'response_invalid', 'response_too_large', 'dependency_unavailable',
            'registration_store_unavailable', 'listener_unavailable',
        }
        self.code = code if code in allowed else 'authentication_failed'
        super().__init__(self.code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FixedHTTPS:
    """No proxy/environment discovery, redirect, retry, cookie jar, or raw logging."""
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    @contextmanager
    def open(self, method, url, *, headers=None, body=None, timeout=20):
        parts = urlsplit(url)
        allowed = url in {TOKEN, JWKS, DISCOVERY, MODELS, RESPONSES}
        # Revocation is discovered, but must stay on the fixed OpenAI auth host.
        allowed = allowed or (parts.scheme == 'https' and parts.netloc == 'auth.openai.com'
                              and parts.path.startswith('/api/accounts/')
                              and not parts.query and not parts.fragment)
        if not allowed or method not in {'GET', 'POST'}:
            raise RecoveryAuthError('remote_rejected')
        response = None
        try:
            request = Request(url, data=body, headers=headers or {}, method=method)
            response = self.opener.open(request, timeout=timeout)
            if response.status != 200 or response.geturl() != url:
                raise RecoveryAuthError('remote_rejected')
            yield response
        except HTTPError as error:
            code = ('sign_in_required' if error.code == 401 else 'plan_unavailable'
                    if error.code == 403 else 'rate_limited' if error.code == 429
                    else 'remote_rejected')
            error.close()
            raise RecoveryAuthError(code) from None
        except (URLError, OSError, TimeoutError):
            raise RecoveryAuthError('connection_failed') from None
        finally:
            if response is not None:
                response.close()


def _json(response, limit=262144):
    try:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise RecoveryAuthError('response_too_large')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise RecoveryAuthError('response_invalid') from None


def _credential(value):
    # Opaque token contents are never interpreted, displayed or persisted.
    if (not isinstance(value, str) or not 1 <= len(value) <= 32768
            or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise RecoveryAuthError('response_invalid')
    return value


class RecoveryAuth:
    def __init__(self, metadata=None, persist_metadata=None, http=None):
        metadata = metadata or {}
        if not isinstance(metadata, dict) or set(metadata) - {'host_id', 'client_id', 'identity_fingerprint'}:
            raise ValueError('Invalid recovery registration metadata')
        host = metadata.get('host_id', uuid.uuid4().urn)
        try:
            if uuid.UUID(host).urn != host:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid recovery host identifier') from None
        client, fingerprint = metadata.get('client_id'), metadata.get('identity_fingerprint')
        if (('client_id' in metadata or 'identity_fingerprint' in metadata) and (not client or not fingerprint)
                or bool(client) != bool(fingerprint) or (client and (
                not isinstance(client, str) or not CLIENT.fullmatch(client)
                or client == 'dynamic_agent_client' or not isinstance(fingerprint, str)
                or not FINGERPRINT.fullmatch(fingerprint)))):
            raise ValueError('Invalid recovery registration metadata')
        self._metadata = {'host_id': host}
        if client:
            self._metadata.update(client_id=client, identity_fingerprint=fingerprint)
        self._persist = persist_metadata or (lambda _value: None)
        self._http = http or FixedHTTPS()
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._refreshing = False
        self._tokens = None
        self._attempt = None
        self._listener = None
        self._timer = None
        self._generation = 0
        self._state = 'signed_out' if jwt is not None else 'dependency_unavailable'
        self._error = None if jwt is not None else 'dependency_unavailable'
        self._revoked = None
        self._streams = set()
        self._save_metadata()

    def _save_metadata(self):
        try:
            self._persist(dict(self._metadata))
        except Exception:
            raise RecoveryAuthError('registration_store_unavailable') from None

    def status(self):
        with self._lock:
            ready = self._state != 'signing_in'
            return {'state': self._state, 'authenticated': ready and self._tokens is not None,
                    'plan_enabled': bool(ready and self._tokens and self._tokens['plan_enabled']),
                    'generation': self._generation, 'error_code': self._error,
                    'registration': ({k: self._metadata[k] for k in ('client_id', 'identity_fingerprint')}
                                     if 'client_id' in self._metadata else None),
                    'remote_revocation_confirmed': self._revoked}

    def _stop_listener(self, generation=None):
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            listener, self._listener = self._listener, None
            timer, self._timer = self._timer, None
        if timer:
            timer.cancel()
        if listener:
            # Also safe when invoked inside the listener's request handler.
            def stop():
                listener.shutdown()
                listener.server_close()
            threading.Thread(target=stop, daemon=True).start()

    def _invalidate(self):
        self._generation += 1
        self._attempt = None
        for stream in tuple(self._streams):
            try:
                stream.close()
            except Exception:
                pass
        self._streams.clear()

    def start(self):
        if jwt is None:
            raise RecoveryAuthError('dependency_unavailable')
        with self._lock:
            self._stop_listener()
            self._invalidate()
            generation = self._generation
            owner = self

            class Callback(BaseHTTPRequestHandler):
                def setup(self):
                    super().setup()
                    self.connection.settimeout(5)

                def log_message(self, *_args):
                    pass

                def send_error(self, code, message=None, explain=None):
                    # Base-class parser errors may contain the raw request line.
                    # Never reflect it, even on unsupported methods or syntax.
                    body = b'Recovery sign-in callback request was not accepted.'
                    self.send_response(code)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.end_headers()
                    if getattr(self, 'command', None) != 'HEAD':
                        self.wfile.write(body)

                def do_GET(self):
                    # Neither raw callback URI nor request headers are logged/reflected.
                    ok = False
                    try:
                        owner._callback(self.path, self.headers.get_all('Host', []), generation)
                        ok = True
                    except Exception:
                        owner._failed_attempt(generation)
                    body = (b'Sign-in complete. Return to the dashboard.' if ok else
                            b'Sign-in could not be completed. Return to the dashboard and try again.')
                    self.send_response(200 if ok else 400)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
                    self.end_headers()
                    self.wfile.write(body)

            try:
                listener = ThreadingHTTPServer(('127.0.0.1', 0), Callback)
            except OSError:
                self._state, self._error = 'error', 'listener_unavailable'
                raise RecoveryAuthError('listener_unavailable') from None
            listener.daemon_threads = True
            # Socket resets/parser failures must not print raw request tracebacks.
            listener.handle_error = lambda *_args: None
            self._listener = listener
            port = listener.server_address[1]
            redirect = f'http://127.0.0.1:{port}/auth/callback'
            verifier, state, nonce = secrets.token_urlsafe(64), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            client = self._metadata.get('client_id', 'dynamic_agent_client')
            self._attempt = {'verifier': verifier, 'state': state, 'nonce': nonce,
                             'redirect': redirect, 'host': f'127.0.0.1:{port}',
                             'client': client, 'expires': time.monotonic() + 600,
                             'fingerprint': self._metadata.get('identity_fingerprint')}
            self._state, self._error = 'signing_in', None
            query = {'client_id': client, 'ext_agent_host_id': self._metadata['host_id'],
                     'response_type': 'code', 'redirect_uri': redirect, 'scope': SCOPES,
                     'resource': RESOURCE, 'state': state, 'nonce': nonce,
                     'code_challenge_method': 'S256',
                     'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
            if client == 'dynamic_agent_client':
                query['agent_name_hint'] = APP_NAME
            # Deliberately omit optional id_token_hint: no credential enters a URL.
            self._timer = threading.Timer(600, lambda: self._failed_attempt(generation, 'sign_in_expired'))
            self._timer.daemon = True
            self._timer.start()
            threading.Thread(target=listener.serve_forever, daemon=True).start()
            return {'authorization_url': AUTHORIZE + '?' + urlencode(query), 'expires_in': 600}

    def _failed_attempt(self, generation, code='authentication_failed'):
        with self._lock:
            if generation != self._generation or self._state != 'signing_in':
                return
            self._invalidate()
            generation = self._generation
            self._state = ('authenticated' if self._tokens and self._tokens['plan_enabled'] else
                           'plan_unavailable' if self._tokens else 'error')
            self._error = code
        self._stop_listener(generation)

    def _callback(self, target, hosts, generation):
        with self._lock:
            attempt = self._attempt
            if generation != self._generation or not attempt:
                raise RecoveryAuthError('invalid_callback')
            # Consume on every callback, including malformed or denied results.
            self._attempt = None
        try:
            if (not isinstance(target, str) or len(target) > 8192 or hosts != [attempt['host']]
                    or time.monotonic() >= attempt['expires']):
                raise RecoveryAuthError('invalid_callback')
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != '/auth/callback':
                raise RecoveryAuthError('invalid_callback')
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
            query = dict(pairs)
            if len(query) != len(pairs) or set(query) - {'code', 'state', 'client_id', 'scope', 'error', 'error_description', 'error_uri'}:
                raise RecoveryAuthError('invalid_callback')
            if not secrets.compare_digest(query.get('state', ''), attempt['state']):
                raise RecoveryAuthError('invalid_callback')
            if 'error' in query:
                raise RecoveryAuthError('sign_in_denied')
            code = _credential(query.get('code'))
            client = query.get('client_id', attempt['client'])
            if (not CLIENT.fullmatch(client) or client == 'dynamic_agent_client'
                    or attempt['client'] != 'dynamic_agent_client' and client != attempt['client']):
                raise RecoveryAuthError('invalid_callback')
            tokens = self._form(TOKEN, {'grant_type': 'authorization_code', 'client_id': client,
                                       'code': code, 'code_verifier': attempt['verifier'],
                                       'redirect_uri': attempt['redirect'], 'resource': RESOURCE})
            claims = self._validate_id(tokens.get('id_token'), client, attempt['nonce'])
            fingerprint = self._identity(claims['sub'], client)
            if attempt['fingerprint'] and not secrets.compare_digest(fingerprint, attempt['fingerprint']):
                raise RecoveryAuthError('identity_mismatch')
            prepared = self._prepare_tokens(tokens, client, fingerprint)
            with self._lock:
                self.guard(generation)
                old_metadata = dict(self._metadata)
                self._metadata.update(client_id=client, identity_fingerprint=fingerprint)
                try:
                    self._save_metadata()
                except RecoveryAuthError:
                    self._metadata = old_metadata
                    raise
                self._tokens = prepared
                self._state = 'authenticated' if prepared['plan_enabled'] else 'plan_unavailable'
                self._error = None if prepared['plan_enabled'] else 'plan_unavailable'
                self._revoked = None
        except RecoveryAuthError as error:
            self._failed_attempt(generation, error.code)
            raise
        except Exception:
            self._failed_attempt(generation)
            raise RecoveryAuthError('authentication_failed') from None
        finally:
            self._stop_listener(generation)

    @staticmethod
    def _identity(subject, client):
        return hashlib.sha256(json.dumps([ISSUER, client, subject], separators=(',', ':')).encode()).hexdigest()

    def _validate_id(self, token, client, nonce=None):
        if jwt is None:
            raise RecoveryAuthError('dependency_unavailable')
        try:
            token = _credential(token)
            header = jwt.get_unverified_header(token)
            algorithm, kid = header.get('alg'), header.get('kid')
            if (algorithm not in {'RS256', 'ES256'} or not isinstance(kid, str) or not 1 <= len(kid) <= 200
                    or set(header) - {'alg', 'kid', 'typ'} or header.get('typ', 'JWT') != 'JWT'):
                raise ValueError()
            # Fetch only the fixed issuer JWKS. Never follow token-supplied key URLs.
            with self._http.open('GET', JWKS, headers={'Accept': 'application/json'}) as response:
                keys = _json(response).get('keys')
            if not isinstance(keys, list) or len(keys) > 100:
                raise ValueError()
            candidates = [key for key in keys if isinstance(key, dict) and key.get('kid') == kid
                          and key.get('use', 'sig') == 'sig' and key.get('alg', algorithm) == algorithm]
            if len(candidates) != 1:
                raise ValueError()
            key = jwt.PyJWK.from_dict(candidates[0], algorithm=algorithm).key
            claims = jwt.decode(token, key, algorithms=[algorithm], issuer=ISSUER,
                                audience=client, leeway=5,
                                options={'require': ['iss', 'aud', 'exp', 'iat', 'sub'], 'strict_aud': True})
            if (not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 1024
                    or type(claims['exp']) not in {int, float} or type(claims['iat']) not in {int, float}
                    or not math.isfinite(claims['exp']) or not math.isfinite(claims['iat'])
                    or claims['exp'] <= claims['iat']):
                raise ValueError()
            if nonce is not None and (not isinstance(claims.get('nonce'), str)
                                      or not secrets.compare_digest(claims['nonce'], nonce)):
                raise ValueError()
            return claims
        except RecoveryAuthError:
            raise
        except Exception:
            raise RecoveryAuthError('authentication_failed') from None

    def _form(self, url, values, empty=False):
        with self._http.open('POST', url, headers={'Accept': 'application/json',
                            'Content-Type': 'application/x-www-form-urlencoded'},
                            body=urlencode(values).encode()) as response:
            return None if empty else _json(response)

    def _prepare_tokens(self, values, client, fingerprint, previous=None):
        lifetime = values.get('expires_in')
        scopes = values.get('scope', previous.get('scope') if previous else None)
        if (not isinstance(scopes, str) or len(scopes) > 2048
                or not set(scopes.split()) <= set(SCOPES.split()) or 'openid' not in scopes.split()):
            raise RecoveryAuthError('response_invalid')
        plan = {'resource.invoke', 'chatgpt.tokens.use.direct'} <= set(scopes.split())
        if plan and (not isinstance(values.get('token_type'), str)
                     or values['token_type'].lower() != 'bearer' or type(lifetime) is not int
                     or not 1 <= lifetime <= 86400):
            raise RecoveryAuthError('response_invalid')
        return {'access': _credential(values.get('access_token')) if plan or 'access_token' in values else None,
                'refresh': _credential(values.get('refresh_token')) if plan or 'refresh_token' in values else None,
                'expires': time.monotonic() + lifetime if type(lifetime) is int else 0, 'scope': scopes,
                'plan_enabled': plan,
                'client': client, 'fingerprint': fingerprint}

    def guard(self, generation, cancel=None):
        with self._lock:
            if generation != self._generation or cancel is not None and cancel.is_set():
                raise RecoveryAuthError('request_cancelled')

    def _access(self, generation, cancel):
        self.guard(generation, cancel)
        with self._refresh_lock:
            with self._lock:
                self.guard(generation, cancel)
                tokens = self._tokens
                if not tokens or self._state == 'signing_in':
                    raise RecoveryAuthError('sign_in_required')
                if not tokens['plan_enabled']:
                    raise RecoveryAuthError('plan_unavailable')
                if tokens['expires'] > time.monotonic() + 30:
                    return tokens['access']
                self._refreshing = True
            try:
                values = self._form(TOKEN, {'grant_type': 'refresh_token', 'client_id': tokens['client'],
                                           'refresh_token': tokens['refresh'], 'resource': RESOURCE})
                if 'id_token' in values:
                    claims = self._validate_id(values['id_token'], tokens['client'])
                    if self._identity(claims['sub'], tokens['client']) != tokens['fingerprint']:
                        raise RecoveryAuthError('identity_mismatch')
                replacement = self._prepare_tokens(values, tokens['client'], tokens['fingerprint'], tokens)
                with self._lock:
                    self.guard(generation, cancel)
                    self._tokens = replacement
                    if not replacement['plan_enabled']:
                        self._state, self._error = 'plan_unavailable', 'plan_unavailable'
                        raise RecoveryAuthError('plan_unavailable')
                    return replacement['access']
            except RecoveryAuthError:
                with self._lock:
                    if generation == self._generation:
                        self._tokens = None
                        self._state, self._error = 'error', 'sign_in_required'
                raise
            finally:
                with self._lock:
                    self._refreshing = False

    @contextmanager
    def authorized_open(self, url, *, body=None, cancel=None, generation=None):
        if url not in {MODELS, RESPONSES}:
            raise RecoveryAuthError('remote_rejected')
        generation = self.status()['generation'] if generation is None else generation
        access = self._access(generation, cancel)
        headers = {'Authorization': 'Bearer ' + access, 'Accept': 'text/event-stream' if body is not None else 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        try:
            with ExitStack() as opened:
                # Credential acquisition may have refreshed or yielded to logout.
                # Dispatch is one lifecycle transition with cancellation/sign-out:
                # hold only through bounded HTTP open, never through SSE reading.
                with self._lock:
                    self.guard(generation, cancel)
                    response = opened.enter_context(self._http.open(
                        'POST' if body is not None else 'GET', url, headers=headers,
                        body=body, timeout=20))
                    self.guard(generation, cancel)
                    self._streams.add(response)
                try:
                    yield response
                    self.guard(generation, cancel)
                finally:
                    with self._lock:
                        self._streams.discard(response)
        except RecoveryAuthError as error:
            if error.code in {'sign_in_required', 'plan_unavailable'}:
                with self._lock:
                    if generation == self._generation:
                        self._invalidate()
                        self._tokens = None
                        self._state, self._error = 'error', error.code
            raise

    def cancel(self):
        with self._lock:
            self._invalidate()
            self._state = ('authenticated' if self._tokens and self._tokens['plan_enabled'] else
                           'plan_unavailable' if self._tokens else 'signed_out')
            self._error = None
            generation = self._generation
        self._stop_listener(generation)
        return self.status()

    def sign_out(self):
        with self._lock:
            self._invalidate()
            tokens, self._tokens = self._tokens, None
            generation = self._generation
            self._state, self._error = 'signed_out', None
            self._revoked = None
            refresh_in_flight = self._refreshing
        self._stop_listener(generation)
        revoked = False
        if tokens and tokens['refresh']:
            try:
                with self._http.open('GET', DISCOVERY, headers={'Accept': 'application/json'}) as response:
                    endpoint = _json(response).get('revocation_endpoint')
                parts = urlsplit(endpoint) if isinstance(endpoint, str) else None
                if (not parts or parts.scheme != 'https' or parts.netloc != 'auth.openai.com'
                        or not parts.path.startswith('/api/accounts/') or parts.query or parts.fragment):
                    raise RecoveryAuthError('remote_rejected')
                self._form(endpoint, {'token': tokens['refresh'], 'token_type_hint': 'refresh_token',
                                      'client_id': tokens['client']}, empty=True)
                # A refresh already in flight could have rotated the revoked value.
                # Never claim remote-session clearance on that uncertain path.
                revoked = not refresh_in_flight
            except Exception:
                pass
        with self._lock:
            if self._generation == generation:
                self._revoked = revoked if tokens else None
        return self.status()

    def close(self):
        # Shutdown has no new outbound network work; credentials simply die in memory.
        with self._lock:
            self._invalidate()
            self._tokens = None
            self._state, self._error = 'signed_out', None
            generation = self._generation
        self._stop_listener(generation)
