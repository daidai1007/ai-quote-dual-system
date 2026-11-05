"""Per-Windows-user monitor settings. No business configuration is ever written."""
import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import time
import urllib.parse


def default_path():
    return Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local/share'))/'AIQuoteDualSystem/Monitoring/config.json'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+os.urandom(6).hex()+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19: raise
                time.sleep(.025)
    finally:
        if temporary.exists(): temporary.unlink()


def _dpapi(value, protect):
    if os.name != 'nt': raise RuntimeError('Production credential storage requires Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, target = Blob(len(value), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Cannot access this Windows user\'s monitor credential')
    try: return ctypes.string_at(target.data, target.size)
    finally: kernel.LocalFree(target.data)


def save_secret(path, value):
    atomic_json(path, {'dpapi_user': base64.b64encode(_dpapi(json.dumps(value).encode(), True)).decode()})


def load_secret(path):
    wrapped = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return json.loads(_dpapi(base64.b64decode(wrapped['dpapi_user']), False))


def https_url(value):
    parsed = urllib.parse.urlsplit(value)
    return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not parsed.fragment and not parsed.query)


def configuration(path):
    path = Path(path)
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if type(value.get('enabled')) is not bool: raise ValueError('Explicit enabled boolean required')
    profile = value.get('profile', 'local-test')
    if profile in ('production', 'https-test'):
        business = urllib.parse.urlsplit(value.get('api_url', ''))
        isolated_business = (business.scheme == 'http' and business.hostname == '127.0.0.1'
                             and not business.username and not business.password)
        if (not https_url(value.get('url', '')) or
            (profile == 'production' and (value.get('environment') != 'production' or not https_url(value.get('api_url', '')))) or
            (profile == 'https-test' and (value.get('environment') != 'test' or not isolated_business))):
            raise ValueError('Production monitor and business URLs must use HTTPS')
        parsed = urllib.parse.urlsplit(value['url'])
        if parsed.path != '/api/v1/events': raise ValueError('Invalid ingest endpoint')
        if value.get('token') or value.get('renewal_secret'):
            raise ValueError('Plaintext production credentials are not permitted in configuration')
        # Fixed name outside the program directory; no arbitrary path from downloaded settings.
        secret = load_secret(path.parent/'credential.dpapi')
        for key in ('app_id','environment','device_id','user_id'):
            if secret.get(key) != value.get(key): raise ValueError('Credential mapping mismatch')
        value.update({key: secret[key] for key in ('token','expires_at','renewal_id','renewal_secret') if key in secret})
        value['renew_url'] = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '/api/v1/credentials/renew', '', ''))
    elif value.get('profile', 'local-test') == 'local-test':
        if value.get('environment') != 'test': raise ValueError('Local profile requires test environment')
        for key in ('url','api_url'):
            p = urllib.parse.urlsplit(value[key])
            if p.scheme != 'http' or p.hostname != '127.0.0.1' or p.username or p.password:
                raise ValueError('Test profile requires loopback endpoints')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', value.get('token', '')):
            raise ValueError('Invalid test token')
    else: raise ValueError('Unknown monitoring profile')
    if 'ca_file' in value or 'ca_sha256' in value:
        if not isinstance(value.get('ca_file'), str) or not Path(value['ca_file']).is_absolute():
            raise ValueError('An absolute monitor-only CA path is required')
        if not re.fullmatch(r'[a-f0-9]{64}', value.get('ca_sha256', '')):
            raise ValueError('The monitor CA fingerprint is required')
    for key in ('device_id','user_id','app_version','app_id'):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value.get(key, '')):
            raise ValueError('Invalid monitoring identifier')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='独立监控配置；不改报价配置或更新源')
    parser.add_argument('action', choices=['init','stop','resume','status'])
    parser.add_argument('--config', type=Path, default=default_path())
    parser.add_argument('--url')
    parser.add_argument('--client-config', type=Path)
    parser.add_argument('--enrollment', type=Path)
    parser.add_argument('--version', default='configured')
    parser.add_argument('--ca-file', type=Path)
    parser.add_argument('--isolated-test', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'init':
        if args.config.exists(): raise ValueError('Existing mapping is preserved; revoke and archive it before enrolling another identity')
        if not args.enrollment or not args.client_config or not args.url: raise ValueError('URL, existing client config and private enrollment response required')
        grant = json.loads(args.enrollment.read_text(encoding='utf-8-sig'))
        business = json.loads(args.client_config.read_text(encoding='utf-8-sig'))
        value = {key: grant[key] for key in ('app_id','environment','device_id','user_id')}
        value.update(profile='https-test' if args.isolated_test else 'production', enabled=False, app_version=args.version,
                     url=args.url, api_url=business['api_url'])
        if grant['environment'] != ('test' if args.isolated_test else 'production') or not https_url(args.url) or (not args.isolated_test and not https_url(business['api_url'])):
            raise ValueError('Formal enrollment requires production mapping and HTTPS endpoints')
        if args.ca_file:
            import hashlib
            value.update(ca_file=str(args.ca_file.resolve()), ca_sha256=hashlib.sha256(args.ca_file.read_bytes()).hexdigest())
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', grant.get('renewal_secret','')):
            raise ValueError('Invalid renewal credential')
        save_secret(args.config.parent/'credential.dpapi', grant)
        atomic_json(args.config, value)
        configuration(args.config)
    else:
        if not args.config.exists():
            if args.action == 'status': print(json.dumps({'state':'not_configured','enabled':False})); return
            raise ValueError('Monitoring is not configured')
        value = json.loads(args.config.read_text(encoding='utf-8-sig'))
        if args.action in ('stop','resume'):
            if args.action == 'resume': configuration(args.config)
            value['enabled'] = args.action == 'resume'
            atomic_json(args.config, value)
    status_path = args.config.parent/'status.json'
    status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    print(json.dumps({'configured':True,'enabled':value['enabled'], 'runtime':status}, ensure_ascii=False))


if __name__ == '__main__': main()
