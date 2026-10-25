"""Synthetic OAuth/JWKS fixtures; no account, token store, or network is accessed."""
from contextlib import contextmanager
import http.client
import io
import json
import secrets
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    jwt = None

from dashboard.recovery_auth import (APP_NAME, AUTHORIZE, DISCOVERY, FixedHTTPS, ISSUER,
                                     JWKS, MODELS, RESOURCE, RecoveryAuth, RecoveryAuthError,
                                     RESPONSES, SCOPES, TOKEN)


class Response(io.BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode())
        self.headers = {'Content-Type': 'application/json'}


class HTTP:
    def __init__(self):
        self.handler = None
        self.calls = []

    @contextmanager
    def open(self, method, url, *, headers=None, body=None, timeout=20):
        # Values are synthetic and remain in memory; assertion reports use URLs only.
        self.calls.append((method, url))
        value = self.handler(method, url, headers or {}, body)
        response = Response(value)
        try:
            yield response
        finally:
            response.close()


class Listener:
    def __init__(self, address, handler):
        self.server_address = ('127.0.0.1', 54321)
        self.handler = handler

    def serve_forever(self):
        pass

    def shutdown(self):
        pass

    def server_close(self):
        pass


@unittest.skipUnless(jwt is not None, 'Reviewed PyJWT[crypto] dependency is not installed')
class RecoveryAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid='synthetic-runtime-key', use='sig', alg='RS256')

    def setUp(self):
        self.patch = patch('dashboard.recovery_auth.ThreadingHTTPServer', Listener)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.http = HTTP()
        self.saved = []
        self.auth = RecoveryAuth(http=self.http, persist_metadata=self.saved.append)
        self.addCleanup(self.auth.close)
        self.subject = uuid.uuid4().hex
        self.client = 'oaiapp_' + uuid.uuid4().hex
        self.access = secrets.token_urlsafe(32)
        self.refresh = secrets.token_urlsafe(32)
        self.claim_overrides = {}
        self.token_overrides = {}
        self.exchange_hook = None
        self.http.handler = self.remote

    def remote(self, method, url, headers, body):
        if url == JWKS:
            return {'keys': [self.jwk]}
        if url == TOKEN:
            values = parse_qs(body.decode())
            self.assertEqual(values['resource'], [RESOURCE])
            self.assertNotIn('client_secret', values)
            if self.exchange_hook:
                self.exchange_hook(values)
            if values['grant_type'] == ['refresh_token']:
                return self.tokens(nonce=None)
            self.assertEqual(values['client_id'], [self.client])
            self.assertEqual(values['redirect_uri'], [self.pending['redirect']])
            self.assertEqual(values['code_verifier'], [self.pending['verifier']])
            return self.tokens(nonce=self.pending['nonce'])
        if url == DISCOVERY:
            return {'revocation_endpoint': ISSUER + '/api/accounts/oauth/revoke'}
        if url.endswith('/oauth/revoke'):
            return {}
        if url == MODELS:
            self.assertTrue(headers['Authorization'].startswith('Bearer '))
            return {'models': []}
        raise AssertionError('Unexpected synthetic request destination')

    def tokens(self, nonce):
        claims = {'iss': ISSUER, 'aud': self.client, 'sub': self.subject,
                  'iat': int(time.time()), 'exp': int(time.time()) + 600}
        if nonce is not None:
            claims['nonce'] = nonce
        claims.update(self.claim_overrides)
        value = {'refresh_token': self.refresh,
                 'id_token': jwt.encode(claims, self.key, algorithm='RS256',
                                        headers={'kid': self.jwk['kid']}),
                 'token_type': 'Bearer', 'expires_in': 3600, 'scope': SCOPES}
        value['access_token'] = self.access
        value.update(self.token_overrides)
        return value

    def begin(self):
        result = self.auth.start()
        self.pending = dict(self.auth._attempt)
        return result

    def complete(self, extra=None):
        values = {'state': self.pending['state'], 'code': secrets.token_urlsafe(24),
                  'client_id': self.client}
        if extra:
            values.update(extra)
        self.auth._callback('/auth/callback?' + urlencode(values), [self.pending['host']],
                            self.auth.status()['generation'])

    def login(self):
        self.begin()
        self.complete()

    def test_constructor_persists_only_nonsecret_host_without_network(self):
        self.assertEqual(self.http.calls, [])
        self.assertEqual(set(self.saved[0]), {'host_id'})
        self.assertEqual(uuid.UUID(self.saved[0]['host_id']).urn, self.saved[0]['host_id'])
        self.assertEqual(self.auth.status()['state'], 'signed_out')

    def test_initial_authorization_pkce_nonce_scope_exact_loopback(self):
        result = self.begin()
        parsed = urlsplit(result['authorization_url'])
        self.assertEqual(parsed.scheme + '://' + parsed.netloc + parsed.path, AUTHORIZE)
        query = parse_qs(parsed.query)
        self.assertEqual(query['client_id'], ['dynamic_agent_client'])
        self.assertEqual(query['agent_name_hint'], [APP_NAME])
        self.assertEqual(query['scope'], [SCOPES])
        self.assertEqual(query['resource'], [RESOURCE])
        self.assertEqual(query['redirect_uri'], ['http://127.0.0.1:54321/auth/callback'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotEqual(query['code_challenge'], [self.pending['verifier']])
        self.assertNotIn('id_token_hint', query)
        self.assertEqual(self.http.calls, [])

    def test_success_validates_signature_and_persists_only_fingerprint_client_host(self):
        self.login()
        status = self.auth.status()
        self.assertTrue(status['authenticated'])
        self.assertTrue(status['plan_enabled'])
        self.assertEqual(set(self.saved[-1]), {'host_id', 'client_id', 'identity_fingerprint'})
        serialized = json.dumps([self.saved, status])
        for forbidden in (self.subject, self.access, self.refresh, self.pending['verifier'], self.pending['nonce']):
            self.assertNotIn(forbidden, serialized)

    def test_callback_replay_cannot_exchange_code_twice(self):
        self.login()
        before = len(self.http.calls)
        with self.assertRaises(RecoveryAuthError):
            self.complete()
        self.assertEqual(len(self.http.calls), before)

    def test_wrong_host_rejected_before_network(self):
        self.begin()
        with self.assertRaises(RecoveryAuthError):
            self.auth._callback('/auth/callback?state=' + self.pending['state'], ['localhost:54321'],
                                self.auth.status()['generation'])
        self.assertEqual(self.http.calls, [])

    def test_duplicate_query_and_state_mismatch_and_path_are_rejected(self):
        for suffix in ('?state=x&state=y', '?state=wrong&code=x', '?code=x', '?state=x&unknown=y'):
            with self.subTest(case=suffix):
                self.begin()
                with self.assertRaises(RecoveryAuthError):
                    self.auth._callback('/auth/callback' + suffix, [self.pending['host']],
                                        self.auth.status()['generation'])
        self.assertEqual(self.http.calls, [])
        self.begin()
        with self.assertRaises(RecoveryAuthError):
            self.auth._callback('/callback?' + urlencode({'state': self.pending['state'], 'code': 'x'}),
                                [self.pending['host']], self.auth.status()['generation'])

    def test_callback_expiry_consumes_attempt_and_rejects(self):
        self.begin()
        self.auth._attempt['expires'] = time.monotonic() - 1
        with self.assertRaises(RecoveryAuthError):
            self.complete()
        self.assertIsNone(self.auth._attempt)
        self.assertEqual(self.http.calls, [])

    def test_oversized_callback_never_exchanges(self):
        self.begin()
        with self.assertRaises(RecoveryAuthError):
            self.auth._callback('/auth/callback?' + 'a' * 9000, [self.pending['host']],
                                self.auth.status()['generation'])
        self.assertEqual(self.http.calls, [])

    def test_denied_callback_state_checked_no_network_or_remote_error_echo(self):
        self.begin()
        with self.assertRaises(RecoveryAuthError) as caught:
            self.complete({'error': 'access_denied', 'error_description': self.access})
        self.assertEqual(caught.exception.code, 'sign_in_denied')
        self.assertNotIn(self.access, str(caught.exception))
        self.assertEqual(self.http.calls, [])

    def test_id_token_wrong_issuer_audience_nonce_expiry_subject_rejected(self):
        for overrides in ({'iss': 'https://invalid.example'}, {'aud': 'another_client'},
                          {'nonce': 'wrong'}, {'exp': int(time.time()) - 60}, {'sub': ''},
                          {'iat': int(time.time()) + 60}, {'exp': float('nan')}):
            with self.subTest(claim=next(iter(overrides))):
                self.claim_overrides = overrides
                self.begin()
                with self.assertRaises(RecoveryAuthError):
                    self.complete()
                self.assertFalse(self.auth.status()['authenticated'])

    def test_missing_issued_client_initial_registration_rejected(self):
        self.begin()
        with self.assertRaises(RecoveryAuthError):
            self.complete({'client_id': 'dynamic_agent_client'})
        self.assertEqual(self.http.calls, [])

    def test_unknown_jwks_key_or_ambiguous_key_rejected(self):
        original = self.remote
        for keys in ([], [self.jwk, self.jwk]):
            with self.subTest(count=len(keys)):
                self.http.handler = lambda method, url, headers, body: (
                    {'keys': keys} if url == JWKS else original(method, url, headers, body))
                self.begin()
                with self.assertRaises(RecoveryAuthError):
                    self.complete()
                self.assertFalse(self.auth.status()['authenticated'])

    def test_modified_token_signature_is_rejected(self):
        original = self.remote
        unrelated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        def modified(method, url, headers, body):
            value = original(method, url, headers, body)
            if url == TOKEN:
                claims = jwt.decode(value['id_token'], options={'verify_signature': False})
                value['id_token'] = jwt.encode(claims, unrelated, algorithm='RS256', headers={'kid': self.jwk['kid']})
            return value
        self.http.handler = modified
        self.begin()
        with self.assertRaises(RecoveryAuthError):
            self.complete()
        self.assertFalse(self.auth.status()['authenticated'])

    def test_returning_registration_reused_without_new_registration(self):
        self.login()
        result = self.begin()
        query = parse_qs(urlsplit(result['authorization_url']).query)
        self.assertEqual(query['client_id'], [self.client])
        self.assertNotIn('agent_name_hint', query)
        self.complete()
        self.assertTrue(self.auth.status()['authenticated'])

    def test_returning_client_switch_rejected_without_exchange(self):
        self.login()
        self.begin()
        before = len(self.http.calls)
        with self.assertRaises(RecoveryAuthError):
            self.complete({'client_id': 'oaiapp_other'})
        self.assertEqual(len(self.http.calls), before)

    def test_returning_verified_identity_switch_rejected(self):
        self.login()
        original = self.saved[-1].copy()
        self.begin()
        self.subject = uuid.uuid4().hex
        with self.assertRaises(RecoveryAuthError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'identity_mismatch')
        self.assertEqual(self.saved[-1], original)

    def test_missing_plan_scope_retains_identity_without_api_key_fallback(self):
        self.token_overrides['scope'] = 'openid profile email'
        self.login()
        self.assertEqual(self.auth.status()['state'], 'plan_unavailable')
        self.assertTrue(self.auth.status()['authenticated'])
        self.assertFalse(self.auth.status()['plan_enabled'])
        with self.assertRaises(RecoveryAuthError) as caught:
            with self.auth.authorized_open(MODELS):
                pass
        self.assertEqual(caught.exception.code, 'plan_unavailable')

    def test_cancel_and_late_token_response_cannot_install_credentials(self):
        self.begin()
        self.exchange_hook = lambda _values: self.auth.cancel()
        with self.assertRaises(RecoveryAuthError):
            self.complete()
        self.assertFalse(self.auth.status()['authenticated'])
        self.assertEqual(self.auth.status()['state'], 'signed_out')

    def test_signout_revokes_session_then_forgets_tokens_retains_registration(self):
        self.login()
        generation = self.auth.status()['generation']
        status = self.auth.sign_out()
        self.assertGreater(status['generation'], generation)
        self.assertFalse(status['authenticated'])
        self.assertTrue(status['remote_revocation_confirmed'])
        self.assertIn(('GET', DISCOVERY), self.http.calls)
        self.assertIn('client_id', self.saved[-1])
        self.assertIsNone(self.auth._tokens)

    def test_revocation_failure_exposes_only_confirmation_boolean(self):
        self.login()
        def failed(*_args):
            raise RuntimeError(self.access)
        self.http.handler = failed
        status = self.auth.sign_out()
        self.assertFalse(status['remote_revocation_confirmed'])
        self.assertNotIn(self.access, json.dumps(status))

    def test_untrusted_revocation_destination_never_receives_token(self):
        self.login()
        def redirect(method, url, headers, body):
            return {'revocation_endpoint': 'https://invalid.example/revoke'}
        self.http.handler = redirect
        status = self.auth.sign_out()
        self.assertFalse(status['remote_revocation_confirmed'])
        self.assertEqual(self.http.calls[-1], ('GET', DISCOVERY))

    def test_refresh_rotates_serially_and_retains_scope_when_omitted(self):
        self.login()
        self.auth._tokens['expires'] = time.monotonic()
        generation = self.auth.status()['generation']
        self.token_overrides['refresh_token'] = secrets.token_urlsafe(32)
        with self.auth.authorized_open(MODELS, generation=generation):
            pass
        self.assertEqual(self.auth._tokens['refresh'], self.token_overrides['refresh_token'])
        self.assertEqual(sum(url == TOKEN for _, url in self.http.calls), 2)
        with self.auth.authorized_open(MODELS, generation=generation):
            pass
        self.assertEqual(sum(url == TOKEN for _, url in self.http.calls), 2)

    def test_signout_during_refresh_discards_late_rotation(self):
        self.login()
        self.auth._tokens['expires'] = time.monotonic()
        generation = self.auth.status()['generation']
        self.exchange_hook = lambda _values: self.auth.close()
        with self.assertRaises(RecoveryAuthError):
            with self.auth.authorized_open(MODELS, generation=generation):
                pass
        self.assertIsNone(self.auth._tokens)

    def test_signout_during_rotation_does_not_claim_remote_revocation(self):
        self.login()
        self.auth._tokens['expires'] = time.monotonic()
        generation = self.auth.status()['generation']
        self.exchange_hook = lambda _values: self.auth.sign_out()
        with self.assertRaises(RecoveryAuthError):
            with self.auth.authorized_open(MODELS, generation=generation):
                pass
        self.assertFalse(self.auth.status()['remote_revocation_confirmed'])

    def test_concurrent_access_serializes_one_token_rotation(self):
        self.login()
        self.auth._tokens['expires'] = time.monotonic()
        generation = self.auth.status()['generation']
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def pause(_values):
            entered.set()
            if not release.wait(2):
                raise AssertionError('Synthetic refresh release timed out')
        self.exchange_hook = pause
        def access():
            try:
                with self.auth.authorized_open(MODELS, generation=generation):
                    pass
                outcomes.append(True)
            except Exception:
                outcomes.append(False)
        first, second = threading.Thread(target=access), threading.Thread(target=access)
        first.start()
        self.assertTrue(entered.wait(2))
        second.start()
        release.set()
        first.join(2)
        second.join(2)
        self.assertEqual(outcomes, [True, True])
        self.assertEqual(sum(url == TOKEN for _, url in self.http.calls), 2)

    def test_close_never_contacts_remote_endpoint(self):
        self.login()
        count = len(self.http.calls)
        self.auth.close()
        self.assertEqual(len(self.http.calls), count)
        self.assertFalse(self.auth.status()['authenticated'])

    def test_cancel_after_credential_acquisition_prevents_dispatch(self):
        self.login()
        before = len(self.http.calls)
        generation = self.auth.status()['generation']
        def cancelled(_generation, _cancel):
            self.auth.cancel()
            return self.access
        with patch.object(self.auth, '_access', cancelled):
            with self.assertRaises(RecoveryAuthError):
                with self.auth.authorized_open(MODELS, generation=generation):
                    pass
        self.assertEqual(len(self.http.calls), before)

    def test_signout_after_credential_acquisition_prevents_inference_dispatch(self):
        self.login()
        generation = self.auth.status()['generation']
        def signed_out(_generation, _cancel):
            self.auth.sign_out()
            return self.access
        with patch.object(self.auth, '_access', signed_out):
            with self.assertRaises(RecoveryAuthError):
                with self.auth.authorized_open(RESPONSES, body=b'{}', generation=generation):
                    pass
        self.assertNotIn(('POST', RESPONSES), self.http.calls)

    def test_cancel_event_after_credential_acquisition_prevents_dispatch(self):
        self.login()
        before = len(self.http.calls)
        generation = self.auth.status()['generation']
        cancel = threading.Event()
        def cancelled(_generation, _cancel):
            cancel.set()
            return self.access
        with patch.object(self.auth, '_access', cancelled):
            with self.assertRaises(RecoveryAuthError):
                with self.auth.authorized_open(MODELS, generation=generation, cancel=cancel):
                    pass
        self.assertEqual(len(self.http.calls), before)

    def test_signout_racing_dispatch_clears_tokens_and_discards_late_output(self):
        self.login()
        generation = self.auth.status()['generation']
        opening, release_open, finish_read, signed_out = (threading.Event() for _ in range(4))
        outcomes = []
        original = self.http.handler
        def opening_request(method, url, headers, body):
            if url == MODELS:
                opening.set()
                if not release_open.wait(2):
                    raise AssertionError('Synthetic HTTP open timed out')
            return original(method, url, headers, body)
        self.http.handler = opening_request
        def request():
            try:
                with self.auth.authorized_open(MODELS, generation=generation):
                    if not finish_read.wait(2):
                        raise AssertionError('Synthetic stream release timed out')
                outcomes.append('unexpected_success')
            except RecoveryAuthError as error:
                outcomes.append(error.code)
        def signout():
            self.auth.sign_out()
            signed_out.set()
        reader = threading.Thread(target=request)
        reader.start()
        self.assertTrue(opening.wait(2))
        # Open owns the lifecycle lock. Sign-out linearizes after that dispatch.
        self.assertFalse(self.auth._lock.acquire(blocking=False))
        signer = threading.Thread(target=signout)
        signer.start()
        release_open.set()
        self.assertTrue(signed_out.wait(2))
        finish_read.set()
        reader.join(2)
        signer.join(2)
        self.assertEqual(outcomes, ['request_cancelled'])
        self.assertFalse(self.auth.status()['authenticated'])
        self.assertIsNone(self.auth._tokens)

    def test_fixed_https_rejects_other_destinations_before_network(self):
        http = FixedHTTPS()
        for url in ('http://api.openai.com/v1/responses', 'https://invalid.example/',
                    RESPONSES + '?token=x', ISSUER + '@invalid.example/api/accounts/revoke'):
            with self.assertRaises(RecoveryAuthError):
                with http.open('GET', url):
                    pass

    def test_unknown_metadata_fields_and_incomplete_registration_rejected(self):
        for value in ({'access_token': '<REDACTED>'}, {'client_id': self.client}, {'host_id': 'bad'}):
            with self.assertRaises(ValueError):
                RecoveryAuth(value)

    def test_callback_http_logging_is_silent(self):
        self.begin()
        # BaseHTTPRequestHandler error paths also call this overridden hook.
        self.assertIsNone(self.auth._listener.handler.log_message(None, '%s', self.access))

    def test_failed_old_attempt_does_not_stop_replacement_listener(self):
        self.begin()
        old_generation = self.auth.status()['generation']
        self.begin()
        listener = self.auth._listener
        self.auth._failed_attempt(old_generation)
        self.assertIs(self.auth._listener, listener)

    def test_real_loopback_callback_exchanges_only_synthetic_code(self):
        self.patch.stop()
        self.begin()
        port = int(self.pending['host'].split(':')[1])
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        self.addCleanup(connection.close)
        query = urlencode({'state': self.pending['state'], 'code': secrets.token_urlsafe(24),
                           'client_id': self.client})
        connection.request('GET', '/auth/callback?' + query)
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        self.assertEqual(body, b'Sign-in complete. Return to the dashboard.')
        self.assertTrue(self.auth.status()['plan_enabled'])

    def test_real_loopback_wrong_host_returns_generic_error_without_exchange(self):
        self.patch.stop()
        self.begin()
        port = int(self.pending['host'].split(':')[1])
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        self.addCleanup(connection.close)
        connection.request('GET', '/auth/callback?' + urlencode({'state': self.pending['state'], 'code': 'synthetic'}),
                           headers={'Host': 'localhost:' + str(port)})
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.status, 400)
        self.assertNotIn(self.pending['state'].encode(), body)
        self.assertEqual(self.http.calls, [])


if __name__ == '__main__':
    unittest.main()
