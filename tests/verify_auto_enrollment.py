"""SDK regression with synthetic identities, private test TLS and Windows DPAPI.

The simulated approval service exercises the client protocol. It does not test
the monitoring backend's database migrations or administrator permissions.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop_client'))
import auto_enrollment as auto
import monitor_settings as settings
import runtime_monitor

VERSION = '2026.11.06.9001'


def future():
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def wait(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError('Isolated SDK state did not settle')


class AutoEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='auto-enrollment-sdk-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.signer = ed25519.Ed25519PrivateKey.generate()
        self.entries, self.received, self.tokens = {}, [], {}
        self.lock = threading.Lock()
        self.redirect = False
        self.create_tls()
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    with case.lock:
                        status, value = case.respond(self.path, body, self.headers)
                    if status == 302:
                        self.send_response(302)
                        self.send_header('Location', case.origin + '/redirect-target')
                        self.end_headers()
                        return
                except Exception:
                    status, value = 400, {'error': 'invalid_synthetic_request'}
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.root / 'server.crt', self.root / 'server.key')
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.origin = f'https://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def create_tls(self):
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SDK isolated test CA')])
        now = datetime.now(timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
              .sign(ca_key, hashes.SHA256()))
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder().subject_name(x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')]))
                .issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
                .sign(ca_key, hashes.SHA256()))
        self.ca = ca.public_bytes(serialization.Encoding.DER)
        (self.root / 'server.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (self.root / 'server.key').write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    def prepare(self, name):
        install = self.root / name / 'client'
        internal = install / '_internal'
        internal.mkdir(parents=True)
        public = self.signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        settings.atomic_json(install / 'update_config.json', {'public_key': auto.encode(public)})
        settings.atomic_json(install / 'client_config.json', {
            'api_url': 'https://business.example.invalid/api/quotes/calculate-dual',
            'api_key': 'synthetic-business-config-must-be-preserved'})
        payload = dict(schema=1, purpose='quote-auto-enrollment-bootstrap', enabled=True,
                       app_id='ai_quote', environment='production', url=self.origin + '/api/v1/events',
                       ca_der=auto.encode(self.ca), ca_sha256=auto.sha(self.ca), minimum_version=VERSION,
                       collection_scope='runtime_heartbeat_only')
        bootstrap = internal / 'monitor-enrollment.json'
        self.sign_bootstrap(bootstrap, payload)
        person = dict(display_name='Synthetic-' + name, identity_mode='NAME_ONLY')
        person['user_id'] = 'name-user:' + auto.sha(person['display_name'].encode())
        profile = self.root / name / 'monitoring/config.json'
        return profile, bootstrap, person

    def sign_bootstrap(self, path, payload):
        settings.atomic_json(path, dict(payload=payload, signature=auto.encode(
            self.signer.sign(auto.BOOTSTRAP_DOMAIN + auto.canonical(payload)))))

    def verify_proof(self, body, public, domain):
        unsigned = {key: value for key, value in body.items() if key != 'signature'}
        public.verify(auto.decode(body['signature']), domain + auto.canonical(unsigned),
                      padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                      hashes.SHA256())
        age = abs((datetime.now(timezone.utc) - auto.instant(body['created_at'])).total_seconds())
        if age > 300:
            raise ValueError('Expired synthetic request')

    def respond(self, route, body, headers):
        if route.startswith('/api/v1/enrollment/') and self.redirect:
            return 302, {}
        if route == '/api/v1/enrollment/requests':
            public = serialization.load_der_public_key(auto.decode(body['public_key']))
            self.verify_proof(body, public, auto.REQUEST_DOMAIN)
            request_id = body['request_id']
            if request_id in self.entries:
                if auto.canonical(self.entries[request_id]['request']) != auto.canonical(body):
                    return 409, {}
            else:
                self.entries[request_id] = dict(request=body, public=public, status='pending')
            return 200, {'status': 'pending'}
        if route == '/api/v1/enrollment/claim':
            entry = self.entries.get(body['request_id'])
            if entry is None:
                return 404, {}
            self.verify_proof(body, entry['public'], auto.CLAIM_DOMAIN)
            value = {'status': entry['status']}
            if entry['status'] == 'approved':
                value['response'] = entry['packet']
            return 200, value
        if route == '/api/v1/credentials/renew':
            entry = next((value for value in self.entries.values()
                          if value.get('grant', {}).get('renewal_id') == body.get('renewal_id')), None)
            if entry is None or entry['status'] != 'approved':
                return 401, {}
            grant = entry['grant']
            if headers.get('Authorization') != 'Bearer ' + grant['renewal_secret']:
                return 401, {}
            if any(body[key] != grant[key] for key in ('app_id', 'environment', 'device_id', 'user_id')):
                return 400, {}
            token = secrets.token_urlsafe(32)
            self.tokens[token] = body['device_id']
            return 200, dict(body, token=token, expires_at=future())
        if route == '/api/v1/events':
            token = headers.get('Authorization', '').removeprefix('Bearer ')
            device = self.tokens.get(token)
            if device is None or any(event['device_id'] != device for event in body['events']):
                return 401, {}
            self.received.extend(body['events'])
            return 200, {'results': [dict(event_id=event['event_id'], status='accepted')
                                    for event in body['events']]}
        raise AssertionError('Unexpected isolated endpoint')

    def packet(self, entry, grant, expires=None):
        request = entry['request']
        request_hash = auto.sha(auto.canonical(request))
        content = dict(request_id=request['request_id'], request_sha256=request_hash,
                       expires_at=expires or future(), grant=grant)
        key, nonce = AESGCM.generate_key(bit_length=256), secrets.token_bytes(12)
        wrapped = entry['public'].encrypt(key, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=auto.RESPONSE_DOMAIN))
        encrypted = AESGCM(key).encrypt(nonce, auto.canonical(content), auto.RESPONSE_DOMAIN + request_hash.encode())
        return dict(schema=1, purpose='quote-auto-enrollment-response', request_sha256=request_hash,
                    wrapped_key=auto.encode(wrapped), nonce=auto.encode(nonce), ciphertext=auto.encode(encrypted))

    def approve(self, request_id):
        with self.lock:
            entry = self.entries[request_id]
            grant = {key: entry['request'][key] for key in ('app_id', 'environment', 'device_id', 'user_id')}
            grant.update(renewal_id=secrets.token_hex(16), renewal_secret=secrets.token_urlsafe(32), expires_at=future())
            entry.update(status='approved', grant=grant, packet=self.packet(entry, grant))
        return entry

    def begin(self, name):
        profile, bootstrap, person = self.prepare(name)
        enrollment = auto.AutoEnrollment(profile, VERSION, bootstrap)
        self.assertEqual(enrollment.step(person), 'awaiting_approval')
        saved = settings.load_secret(profile.parent / 'AutoEnrollment/request.dpapi')
        return profile, bootstrap, person, enrollment, saved

    def poll(self, enrollment, person):
        enrollment.next_attempt = 0
        return enrollment.step(person)

    def test_approval_installs_independent_credentials_and_native_heartbeats(self):
        installs = [self.prepare(name) for name in ('A', 'B')]
        controllers = []
        for profile, bootstrap, person in installs:
            controller = runtime_monitor.RuntimeController(profile, VERSION, lambda p=person: p, bootstrap)
            self.addCleanup(controller.close)
            controllers.append(controller)
        wait(lambda: len(self.entries) == 2 and all(c.state == 'awaiting_approval' for c in controllers))
        self.assertFalse(self.received)
        self.assertTrue(all(not profile.exists() for profile, _, _ in installs))
        for request_id in list(self.entries):
            self.approve(request_id)
        for controller in controllers:
            controller.enrollment.next_attempt = 0
        wait(lambda: all(c.state == 'active' and c.runtime is not None for c in controllers))
        grants = [settings.load_secret(profile.parent / 'credential.dpapi') for profile, _, _ in installs]
        self.assertNotEqual(grants[0]['device_id'], grants[1]['device_id'])
        self.assertNotEqual(grants[0]['renewal_secret'], grants[1]['renewal_secret'])
        for (profile, bootstrap, _), grant in zip(installs, grants):
            self.assertNotIn(grant['renewal_secret'], (profile.parent / 'credential.dpapi').read_text())
            self.assertNotIn('token', auto.read(profile))
            self.assertEqual(auto.read(bootstrap.parent.parent / 'client_config.json')['api_key'],
                             'synthetic-business-config-must-be-preserved')

        def heartbeats(device):
            with self.lock:
                return [event for event in self.received
                        if event['event_type'] == 'heartbeat' and event['device_id'] == device]

        # Approval polling is accelerated above. Native heartbeat timing is unmodified.
        wait(lambda: all(len(heartbeats(grant['device_id'])) >= 2 for grant in grants), seconds=78)
        for grant in grants:
            events = heartbeats(grant['device_id'])
            interval = (auto.instant(events[1]['occurred_at']) - auto.instant(events[0]['occurred_at'])).total_seconds()
            self.assertGreaterEqual(interval, 55)
            self.assertLess(interval, 75)
            self.assertTrue(all(event['user_id'] == grant['user_id'] for event in events))
        settings.set_collection_enabled(installs[0][0], False)
        wait(lambda: controllers[0].state == 'disabled' and controllers[0].runtime is None)
        self.assertEqual(controllers[1].state, 'active')

    def test_explicit_stop_survives_pending_approval_and_restart(self):
        profile, bootstrap, person = self.prepare('stopped')
        settings.set_collection_enabled(profile, False)
        enrollment = auto.AutoEnrollment(profile, VERSION, bootstrap)
        self.assertEqual(enrollment.step(person), 'disabled')
        self.assertFalse(self.entries)
        settings.set_collection_enabled(profile, True)
        self.assertEqual(self.poll(enrollment, person), 'awaiting_approval')
        saved = settings.load_secret(profile.parent / 'AutoEnrollment/request.dpapi')
        settings.set_collection_enabled(profile, False)
        self.approve(saved['request']['request_id'])
        restarted = auto.AutoEnrollment(profile, '2026.11.06.9002', bootstrap)
        self.assertEqual(restarted.step(person), 'disabled')
        self.assertFalse(profile.exists())
        self.assertFalse(self.received)
        settings.set_collection_enabled(profile, True)
        self.assertEqual(self.poll(restarted, person), 'configured')
        self.assertEqual(len(self.entries), 1)
        self.assertEqual(settings.configuration(profile)['device_id'], saved['request']['device_id'])

    def test_existing_disabled_profile_is_preserved_on_restart(self):
        profile, bootstrap, person, enrollment, saved = self.begin('legacy')
        self.approve(saved['request']['request_id'])
        self.assertEqual(self.poll(enrollment, person), 'configured')
        settings.set_collection_enabled(profile, False)
        before = profile.read_bytes()
        credentials = (profile.parent / 'credential.dpapi').read_bytes()
        controller = runtime_monitor.RuntimeController(profile, '2026.11.06.9002', lambda: person, bootstrap)
        self.addCleanup(controller.close)
        wait(lambda: controller.state == 'disabled')
        self.assertIsNone(controller.runtime)
        self.assertEqual(profile.read_bytes(), before)
        self.assertEqual((profile.parent / 'credential.dpapi').read_bytes(), credentials)
        self.assertEqual(len(self.entries), 1)

    def test_pending_upgrade_preserves_request_and_private_key(self):
        profile, bootstrap, person, _, saved = self.begin('pending')
        payload = auto.read(bootstrap)['payload']
        payload['minimum_version'] = '2026.11.06.9002'
        self.sign_bootstrap(bootstrap, payload)
        upgraded = auto.AutoEnrollment(profile, '2026.11.06.9002', bootstrap)
        self.assertEqual(upgraded.step(person), 'awaiting_approval')
        self.assertEqual(settings.load_secret(profile.parent / 'AutoEnrollment/request.dpapi'), saved)
        self.assertEqual(len(self.entries), 1)

    def test_stop_after_approval_response_wins_over_first_activation(self):
        profile, _, person, enrollment, saved = self.begin('late-stop')
        self.approve(saved['request']['request_id'])
        original = auto.post

        def response_then_stop(*args):
            result = original(*args)
            if result.get('status') == 'approved':
                settings.set_collection_enabled(profile, False)
            return result

        with patch.object(auto, 'post', response_then_stop):
            self.assertEqual(self.poll(enrollment, person), 'configured')
        self.assertFalse(settings.configuration(profile)['enabled'])
        self.assertFalse(settings.collection_preference(profile))
        self.assertFalse(self.received)

    def test_interrupted_import_resumes_without_reissuing_credentials(self):
        profile, _, person, enrollment, saved = self.begin('interrupted')
        entry = self.approve(saved['request']['request_id'])
        original = settings.atomic_json

        def fail_config_publication(path, value):
            if Path(path) == profile:
                raise OSError('Synthetic interruption before config publication')
            return original(path, value)

        with patch.object(settings, 'atomic_json', fail_config_publication):
            self.assertEqual(self.poll(enrollment, person), 'enrollment_unavailable')
        self.assertFalse(profile.exists())
        self.assertTrue((profile.parent / 'AutoEnrollment/import.json').exists())
        encrypted_before = (profile.parent / 'credential.dpapi').read_bytes()
        self.assertEqual(self.poll(enrollment, person), 'configured')
        self.assertEqual((profile.parent / 'credential.dpapi').read_bytes(), encrypted_before)
        self.assertEqual(settings.load_secret(profile.parent / 'credential.dpapi'), entry['grant'])
        self.assertEqual(len(self.entries), 1)

    def test_bootstrap_tamper_ca_and_minimum_version_fail_before_request(self):
        profile, bootstrap, person = self.prepare('invalid')
        original = auto.read(bootstrap)
        payloads = [dict(original['payload'], url=self.origin + '/different'),
                    dict(original['payload'], ca_sha256='0' * 64),
                    dict(original['payload'], minimum_version='2099.01.01.01')]
        for payload in payloads:
            self.sign_bootstrap(bootstrap, payload)
            with self.assertRaises(Exception):
                auto.load_bootstrap(bootstrap, VERSION)
        packet = dict(original)
        packet['payload'] = dict(original['payload'], url='https://other.invalid/api/v1/events')
        settings.atomic_json(bootstrap, packet)
        with patch.object(auto, 'post') as request:
            self.assertEqual(auto.AutoEnrollment(profile, VERSION, bootstrap).step(person), 'enrollment_unavailable')
            request.assert_not_called()
        self.assertFalse(self.entries)

    def test_encrypted_grant_is_bound_to_install_identity_and_expiry(self):
        profile, bootstrap, _, enrollment, saved = self.begin('owner')
        _, _, _, _, other = self.begin('other')
        owner_entry = self.approve(saved['request']['request_id'])
        other_entry = self.approve(other['request']['request_id'])
        key = serialization.load_der_private_key(auto.decode(saved['private_key']), password=None)
        payload = auto.read(bootstrap)['payload']
        packets = [other_entry['packet'],
                   self.packet(owner_entry, dict(owner_entry['grant'], user_id='different-user')),
                   self.packet(owner_entry, owner_entry['grant'], expires='2000-01-01T00:00:00+00:00')]
        for packet in packets:
            with self.assertRaises(ValueError):
                enrollment.import_grant(saved, key, packet, payload, self.ca)
            self.assertFalse(profile.exists())
            self.assertFalse((profile.parent / 'credential.dpapi').exists())

    def test_redirect_and_certificate_hostname_mismatch_are_refused(self):
        _, bootstrap, _ = self.prepare('transport')
        payload = auto.read(bootstrap)['payload']
        self.redirect = True
        with self.assertRaises(urllib.error.URLError):
            auto.post(payload, self.ca, '/api/v1/enrollment/claim', {})
        self.redirect = False
        wrong = dict(payload, url=payload['url'].replace('127.0.0.1', 'localhost'))
        with self.assertRaises(urllib.error.URLError):
            auto.post(wrong, self.ca, '/api/v1/enrollment/claim', {})
        self.assertFalse(self.entries)


if __name__ == '__main__':
    unittest.main(verbosity=2)
