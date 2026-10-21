"""Extract and check the actual first installer without touching HKCU/shortcuts."""
from __future__ import annotations
import argparse
import base64
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
import threading
import uuid
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop_client'), str(ROOT / 'packaging'), str(ROOT / 'tests')]
from build_first_install import audit_no_secrets, public_update_config, secret_patterns
from client_update_core import (ENTRY, check_release, digest, load_config, open_url, read_json, verify_manifest, atomic_json)
from verify_client_update_bundle import owned_children, stop_owned
from verify_review_package import verify


def verify_candidate_feed(manifest, updater, version):
    """Exercise the unpublished signed release over local HTTP, never publish it.

    The production URL/pin/signature are unchanged. Only the TCP connection is
    redirected to a disposable loopback server inside this test process.
    """
    manifest = Path(manifest).resolve()
    envelope = read_json(manifest)
    release = verify_manifest(envelope, updater)
    assert release['version'] == version
    package = manifest.parent / unquote(Path(urlsplit(release['url']).path).name)
    assert package.stat().st_size == release['size'] and digest(package) == release['sha256']
    content = json.dumps(envelope, ensure_ascii=False).encode('utf-8')
    expected = urlsplit(updater['manifest_url'])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != expected.path:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def connect_local(connection):
        assert (connection.host, connection.port) == (expected.hostname, expected.port or 80)
        connection.sock = socket.create_connection(('127.0.0.1', server.server_port), connection.timeout)

    try:
        with patch.object(http.client.HTTPConnection, 'connect', connect_local):
            assert check_release(updater, version) is None, 'Candidate must not offer itself'
            offered = check_release(updater, '0.0.0.0')
            assert offered is not None and verify_manifest(offered, updater) == release
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return {'candidate_manifest_checked': True, 'candidate_feed_local_simulation': True,
            'candidate_version': version, 'candidate_package_sha256': release['sha256']}


def startup(bundle, output, version):
    profile = output / 'clean-user-profile'
    receipt = output / 'clean-startup-health.json'
    token = uuid.uuid4().hex
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', LOCALAPPDATA=str(profile),
               AI_QUOTE_UPDATE_HEALTH_FILE=str(receipt), AI_QUOTE_UPDATE_HEALTH_TOKEN=token,
               AI_QUOTE_UPDATE_HEALTH_VERSION=version)
    # Neither inherited API secrets nor test overrides may mask missing package configuration.
    for name in ('AI_QUOTE_API_KEY', 'AI_QUOTE_API_URL', 'AI_QUOTE_UPDATE_CONFIG', 'AI_QUOTE_V3_CORE_ROOT'):
        env.pop(name, None)
    process = subprocess.Popen([str(bundle / ENTRY)], cwd=bundle, env=env,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    children = set()
    try:
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            children.update(owned_children(process.pid))
            if process.poll() is not None:
                raise RuntimeError('Clean first client exited before real startup acknowledgement')
            if receipt.is_file() and read_json(receipt) == {'token': token, 'version': version}:
                time.sleep(1)
                assert process.poll() is None
                return {'main_window_started': True, 'version': version,
                        'clean_profile': True, 'business_api_key_in_environment': False}
            time.sleep(.1)
        raise TimeoutError('Clean first client startup timed out; inspect retained clean profile logs')
    finally:
        children.update(owned_children(process.pid))
        for child in children:
            stop_owned(child)
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)


def main(args):
    installer = Path(args.installer).resolve()
    stage = Path(args.stage).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError('Use a fresh verification output directory')
    output.mkdir(parents=True)
    extracted = output / 'extracted'
    with (output / 'extract.log').open('w', encoding='utf-8') as stream:
        subprocess.run([str(Path(args.seven_zip).resolve()), 'x', str(installer), '-y', '-bb0', '-o' + str(extracted)],
                       check=True, stdout=stream, stderr=subprocess.STDOUT,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    entries = list(extracted.rglob(ENTRY))
    assert len(entries) == 1, 'Installer must contain exactly the updatable entry EXE'
    bundle = entries[0].parent
    count = 0
    for source in stage.rglob('*'):
        if source.is_file() and source.name not in {'installer_sidebar.bmp', 'installer_header.bmp'}:
            target = bundle / source.relative_to(stage)
            assert target.is_file() and digest(source) == digest(target), str(source.relative_to(stage))
            count += 1
    assert not list((bundle / 'output').glob('*')) if (bundle / 'output').exists() else True
    business = read_json(args.business_config)
    assert read_json(bundle / 'client_config.json') == {'api_url': business['api_url'], 'api_key': ''}
    expected_updater = public_update_config(read_json(args.update_config))
    assert read_json(bundle / 'update_config.json') == expected_updater, 'Packaged update configuration differs from trusted release input'
    updater = load_config(bundle)
    assert updater == expected_updater, 'An environment override must not mask the packaged configuration'
    assert updater['manifest_url'] == updater['lan_http_origin'] + '/stable/manifest.json'
    version = read_json(bundle / 'release-manifest.json')['version']
    audit = audit_no_secrets(bundle, secret_patterns(business, args.private_key))
    code = verify(bundle, public_config=True)
    config_hashes = {name: digest(bundle / name) for name in ('client_config.json', 'update_config.json')}
    smoke = startup(bundle, output, version)
    for name, expected in config_hashes.items():
        assert digest(bundle / name) == expected, 'Startup changed initial configuration: ' + name
    with open_url(updater['manifest_url'], updater) as response:
        live_raw = response.read(65537)
    assert len(live_raw) <= 65536
    live_release = verify_manifest(json.loads(live_raw.decode('utf-8')), updater)
    assert check_release(updater, version) is None, 'Published feed must not offer a downgrade'
    candidate = {}
    if args.candidate_manifest:
        candidate = verify_candidate_feed(args.candidate_manifest, updater, version)
    else:
        offered = check_release(updater, '0.0.0.0')
        assert offered is not None and verify_manifest(offered, updater)['version'] == version
    # Exact installed-payload hashes plus current-source verification establish bundle identity.
    report = {'installer_sha256': digest(installer), 'installer_extraction_matches_stage': True,
              'installer_payload_files_verified': count, 'developer_secret_audit': audit,
              'business_api_key_empty': True, 'online_update_configured': True,
              'update_origin': updater['lan_http_origin'], 'manifest_url': updater['manifest_url'],
              'live_lan_signed_manifest_check': True, 'same_version_not_offered': True,
              'live_lan_release_version': live_release['version'],
              'live_lan_manifest_sha256': hashlib.sha256(live_raw).hexdigest(),
              **candidate,
              'previous_version_recognizes_release': True, 'startup': smoke,
              'packaged_source': code, 'extracted_bundle': str(bundle),
              'registry_or_shortcuts_modified_by_test': False}
    atomic_json(output / 'verification-result.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', required=True)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--seven-zip', required=True)
    parser.add_argument('--business-config', required=True)
    parser.add_argument('--update-config', required=True, help='Trusted expected public update configuration')
    parser.add_argument('--candidate-manifest', help='Validate an unpublished signed candidate using loopback transport')
    parser.add_argument('--private-key', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
