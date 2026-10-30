"""Deterministic expiry/restart recovery, concurrent requests and identity races."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop_client'))
from name_session_recovery import NameSessionRecovery


def person(name='测试甲', token='A'):
    return {'token': token * 43, 'expires_at': '2030-01-01T00:00:00Z', 'person': {
        'user_id': 'name-user:' + hashlib.sha256(name.encode()).hexdigest(),
        'display_name': name, 'identity_mode': 'NAME_ONLY', 'scope': 'OWN'}}


def response(value):
    return io.BytesIO(json.dumps(value, ensure_ascii=False).encode())


def rejected(request, code=401, kind='name_session_required'):
    return urllib.error.HTTPError(request.full_url, code, 'synthetic rejection', {}, response({'error': kind}))


class Fixture:
    def __init__(self):
        self.value = person()
        self.epoch = 1
        self.requests = []
        self.accepted = []
        self.valid = 'R' * 43
        self.login_value = person(token='R')
        self.time = 0
        self.transport = NameSessionRecovery(self.open, lambda: deepcopy(self.value), self.adopt, clock=lambda: self.time)
        self.transport.register('http://127.0.0.1:12345/service/api/quotes/calculate-dual')
        self.transport.remember(self.value, self.epoch)

    def adopt(self, value):
        if self.value is None or self.value['person']['user_id'] != value['person']['user_id']:
            self.epoch += 1
        self.value = deepcopy(value)
        self.transport.remember(value, self.epoch)

    def clear(self):
        self.value = None
        self.epoch += 1
        self.transport.remember(None, self.epoch)

    def request(self, path='quotes/calculate-dual', method='POST', data=b'{"unchanged":true}', token=None):
        return urllib.request.Request('http://127.0.0.1:12345/service/api/' + path,
            data=data, method=method, headers={'Authorization': 'Bearer ' + (token or 'A' * 43),
                'X-AI-Quote-Key': 'local-synthetic-only', 'X-Quote-Request-Id': 'keep-request-id'})

    def open(self, request, *args, **kwargs):
        self.requests.append(request)
        if request.full_url.endswith('/api/name-login'):
            return response(self.login_value)
        if self.transport.token(request) != self.valid:
            raise rejected(request)
        self.accepted.append(request)
        return response({'ok': True})

    def execute(self, request=None):
        with self.transport(request or self.request(), timeout=60) as result:
            return json.loads(result.read())

    def logins(self):
        return [request for request in self.requests if request.full_url.endswith('/api/name-login')]


class SessionRecovery(unittest.TestCase):
    def test_expired_session_recovers_same_person_and_replays_only_rejected_request(self):
        f = Fixture()
        original = f.request()
        original_headers = dict(original.header_items())
        self.assertEqual(f.execute(original), {'ok': True})
        self.assertEqual(len(f.logins()), 1)
        self.assertEqual(json.loads(f.logins()[0].data), {'name': '测试甲'})
        self.assertIsNone(f.logins()[0].get_header('Authorization'))
        self.assertEqual(f.logins()[0].get_header('X-ai-quote-key'), 'local-synthetic-only')
        self.assertEqual(f.value['person']['user_id'], person()['person']['user_id'])
        self.assertEqual(f.epoch, 1)
        replay = f.accepted[0]
        self.assertEqual(replay.data, original.data)
        self.assertEqual(replay.get_method(), 'POST')
        self.assertEqual(replay.get_header('X-quote-request-id'), 'keep-request-id')
        self.assertEqual(dict(original.header_items()), original_headers)

    def test_parallel_requests_and_old_captured_headers_share_one_recovery(self):
        f = Fixture()
        count = 8
        waiting = threading.Barrier(count)
        original = f.open
        def open_request(request, *args, **kwargs):
            if f.transport.token(request) == 'A' * 43:
                waiting.wait(timeout=5)
            return original(request, *args, **kwargs)
        f.transport.open_request = open_request
        with ThreadPoolExecutor(max_workers=count) as pool:
            self.assertEqual(list(pool.map(lambda _: f.execute(), range(count))), [{'ok': True}] * count)
        self.assertEqual(len(f.logins()), 1)
        self.assertEqual(len(f.accepted), count)
        f.transport.open_request = original
        f.execute(f.request(token='A' * 43))
        self.assertEqual(len(f.logins()), 1)

    def test_403_and_wrong_api_key_401_preserve_errors_without_relogin(self):
        for code, kind in [(403, 'forbidden'), (401, 'unauthorized'), (500, 'database_error')]:
            with self.subTest(code=code):
                f = Fixture()
                def fail(request, *args, **kwargs):
                    f.requests.append(request)
                    raise rejected(request, code, kind)
                f.transport.open_request = fail
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    f.execute()
                self.assertEqual(json.loads(caught.exception.read()), {'error': kind})
                self.assertEqual(len(f.requests), 1)

    def test_timeout_and_successful_requests_never_replay_business_operations(self):
        f = Fixture()
        f.valid = 'A' * 43
        f.execute()
        self.assertEqual(len(f.accepted), 1)
        self.assertEqual(f.logins(), [])
        calls = []
        def timed_out(request, *args, **kwargs):
            calls.append(request)
            raise TimeoutError('synthetic timeout after an unknown write outcome')
        f.transport.open_request = timed_out
        with self.assertRaises(TimeoutError):
            f.execute()
        self.assertEqual(len(calls), 1)

    def test_second_session_rejection_is_not_a_retry_loop(self):
        f = Fixture()
        f.valid = 'Z' * 43
        with self.assertRaises(urllib.error.HTTPError):
            f.execute()
        self.assertEqual(len(f.requests), 3)
        self.assertEqual(len(f.logins()), 1)

    def test_unknown_origin_tokens_login_and_logout_are_not_recovered(self):
        for kind in ['origin', 'token', 'login', 'logout', 'string_url']:
            with self.subTest(kind=kind):
                f = Fixture()
                request = f.request()
                if kind == 'origin':
                    request = urllib.request.Request('http://127.0.0.1:54321/service/api/private', headers=dict(request.header_items()))
                elif kind == 'token': request = f.request(token='Z' * 43)
                elif kind in ('login', 'logout'): request = f.request('name-' + kind)
                else:
                    self.assertIsNone(f.transport.binding(request.full_url))
                    continue
                self.assertIsNone(f.transport.binding(request))

    def test_failed_recovery_preserves_identity_and_throttles_parallel_failures(self):
        f = Fixture()
        original = f.open
        def offline(request, *args, **kwargs):
            if request.full_url.endswith('/api/name-login'):
                f.requests.append(request)
                raise urllib.error.URLError('synthetic offline')
            return original(request, *args, **kwargs)
        f.transport.open_request = offline
        for _ in range(4):
            with self.assertRaises(urllib.error.URLError): f.execute()
        self.assertEqual(len(f.logins()), 1)
        self.assertEqual(f.value, person())
        f.time = 6
        f.transport.open_request = original
        f.execute()
        self.assertEqual(len(f.logins()), 2)

    def test_recovery_cannot_adopt_a_different_identity(self):
        f = Fixture()
        f.login_value = person('另一位人员', 'R')
        with self.assertRaisesRegex(ValueError, '不同人员'):
            f.execute()
        self.assertEqual(f.value, person())
        self.assertEqual(f.accepted, [])

    def test_logout_or_switch_during_recovery_does_not_restore_old_identity(self):
        for action in ['logout', 'switch', 'logout_and_same_name_login', 'logout_pending']:
            with self.subTest(action=action):
                f = Fixture()
                entered, release = threading.Event(), threading.Event()
                original = f.open
                def blocked(request, *args, **kwargs):
                    if request.full_url.endswith('/api/name-login'):
                        entered.set()
                        if not release.wait(5): raise TimeoutError('test recovery release missing')
                    return original(request, *args, **kwargs)
                f.transport.open_request = blocked
                with ThreadPoolExecutor(max_workers=1) as pool:
                    work = pool.submit(f.execute)
                    self.assertTrue(entered.wait(5))
                    if action == 'logout_pending': f.transport.suspend()
                    elif action == 'switch': f.adopt(person('另一位人员', 'B'))
                    else:
                        f.clear()
                        if action == 'logout_and_same_name_login': f.adopt(person(token='C'))
                    expected = deepcopy(f.value)
                    release.set()
                    with self.assertRaises(urllib.error.HTTPError): work.result(timeout=5)
                self.assertEqual(f.value, expected)
                self.assertEqual(f.accepted, [])

    def test_manual_same_name_login_wins_over_pending_recovery(self):
        f = Fixture()
        original = f.open
        def manual_login(request, *args, **kwargs):
            if request.full_url.endswith('/api/name-login'):
                f.adopt(person(token='M'))
                f.valid = 'M' * 43
            return original(request, *args, **kwargs)
        f.transport.open_request = manual_login
        f.execute()
        self.assertEqual(f.value['token'], 'M' * 43)


if __name__ == '__main__':
    unittest.main(verbosity=2)
