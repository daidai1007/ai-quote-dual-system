"""Real API restarts, no database process or business connection is used."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from name_session_recovery import NameSessionRecovery


class RestartRecoveryHTTP(unittest.TestCase):
    def test_real_api_restart_preserves_name_and_recovers_concurrent_requests_without_database(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        environment = dict(os.environ)
        for key in list(environment):
            if key.startswith('PG') or key.startswith('AI_QUOTE_DB_') or key in (
                    'DATABASE_URL', 'RENDER', 'AI_QUOTE_PRINCIPALS_JSON'):
                del environment[key]
        environment.update(PORT=str(port), AI_QUOTE_API_HOST='127.0.0.1',
            AI_QUOTE_API_KEY='owned-local-session-test', AI_QUOTE_DB_HOST='127.0.0.1',
            AI_QUOTE_DB_PORT='9', AI_QUOTE_DB_NAME='NO_DATABASE_USED',
            AI_QUOTE_DB_USER='NO_DATABASE_USED', PSQL_PATH='NO_DATABASE_USED')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        calls = []
        def open_local(request, *args, **kwargs):
            url = urlsplit(request.full_url)
            self.assertEqual((url.scheme, url.hostname, url.port), ('http', '127.0.0.1', port))
            calls.append(url.path)
            return opener.open(request, *args, **kwargs)
        child = None
        with tempfile.TemporaryDirectory(prefix='name-recovery-api-') as folder:
            with open(Path(folder) / 'api.log', 'w+', encoding='utf-8') as log:
                def start():
                    nonlocal child
                    child = subprocess.Popen([shutil.which('node'), 'api/server.mjs'], cwd=ROOT,
                        env=environment, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        try:
                            with open_local(urllib.request.Request(base + '/health'), timeout=1) as result:
                                if result.status == 200: return
                        except (OSError, urllib.error.URLError): pass
                        if child.poll() is not None:
                            raise AssertionError('Owned API startup failed; no business database was configured')
                        time.sleep(.05)
                    raise AssertionError('Owned loopback API startup timed out')
                def stop():
                    if child is not None and child.poll() is None:
                        child.terminate()
                        child.wait(timeout=10)
                try:
                    start()
                    request = urllib.request.Request(base + '/api/name-login', method='POST',
                        data=json.dumps({'name': '长时间停留回归人员'}).encode(),
                        headers={'X-AI-Quote-Key': 'owned-local-session-test', 'Content-Type': 'application/json'})
                    with open_local(request, timeout=5) as result: state = json.loads(result.read())
                    original = deepcopy(state)
                    transport = None
                    def adopt(value):
                        nonlocal state
                        self.assertEqual(value['person']['user_id'], original['person']['user_id'])
                        state = deepcopy(value)
                        transport.remember(value, 1)
                    transport = NameSessionRecovery(open_local, lambda: deepcopy(state), adopt)
                    transport.register(base)
                    transport.remember(state, 1)
                    def current_request(path='name-session', data=None):
                        return urllib.request.Request(base + '/api/' + path, data=data,
                            headers={'Authorization': 'Bearer ' + original['token'],
                                     'X-AI-Quote-Key': 'owned-local-session-test', 'Content-Type': 'application/json'})
                    def describe(_=None):
                        with transport(current_request(), timeout=5) as result: return json.loads(result.read())
                    self.assertEqual(describe()['person'], original['person'])
                    stop();start()
                    with self.assertRaises(urllib.error.HTTPError) as expired:
                        open_local(current_request(), timeout=5)
                    self.assertEqual(expired.exception.code, 401)
                    login_count = calls.count('/api/name-login')
                    with ThreadPoolExecutor(max_workers=6) as pool:
                        results = list(pool.map(describe, range(6)))
                    self.assertTrue(all(value['person'] == original['person'] for value in results))
                    self.assertEqual(state['person']['scope'], 'OWN')
                    self.assertNotEqual(state['token'], original['token'])
                    self.assertEqual(calls.count('/api/name-login'), login_count + 1)
                    # The next stale captured header is replaced by the recovered token.
                    describe()
                    self.assertEqual(calls.count('/api/name-login'), login_count + 1)
                    stop();start()
                    # The 401 guard runs before business validation. The replay
                    # reaches normal 400 validation, without attempting SQL.
                    with self.assertRaises(urllib.error.HTTPError) as business_error:
                        transport(current_request('quotes/calculate-dual', b'{}'), timeout=5)
                    self.assertEqual(business_error.exception.code, 400)
                    self.assertIn('quote_id', json.loads(business_error.exception.read())['message'])
                    self.assertEqual(calls.count('/api/name-login'), login_count + 2)
                finally:
                    stop()


if __name__ == '__main__':
    unittest.main(verbosity=2)
