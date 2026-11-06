"""Opt-in signed bootstrap; automatic request, admin approval, per-install credential.

Only called by the background runtime controller. Existing configuration is never
replaced and a persistent stop preference always wins over a late approval.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import monitor_settings as settings

BOOTSTRAP_DOMAIN = b'AIQuote auto enrollment bootstrap v1\n'
REQUEST_DOMAIN = b'AIQuote auto enrollment request v1\n'
CLAIM_DOMAIN = b'AIQuote auto enrollment claim v1\n'
RESPONSE_DOMAIN = b'AIQuote auto enrollment response v1\n'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha(value): return hashlib.sha256(value).hexdigest()
def encode(value): return base64.b64encode(value).decode('ascii')
def decode(value): return base64.b64decode(value, validate=True)
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def instant(value):
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('Timezone required')
    return result


def load_bootstrap(path, version):
    path = Path(path)
    install = path.parent.parent if path.parent.name == '_internal' else path.parent
    for file in (path, install/'update_config.json'):
        for parent in (file,*file.parents):
            if parent.exists() and (parent.is_symlink() or getattr(parent.stat(),'st_file_attributes',0)&0x400):
                raise ValueError('Bootstrap links are refused')
    if path.stat().st_size > 65536: raise ValueError('Bootstrap too large')
    packet = read(path);payload = packet['payload']
    public = decode(read(install/'update_config.json')['public_key'])
    ed25519.Ed25519PublicKey.from_public_bytes(public).verify(decode(packet['signature']), BOOTSTRAP_DOMAIN+canonical(payload))
    if (payload.get('schema')!=1 or payload.get('purpose')!='quote-auto-enrollment-bootstrap' or
        payload.get('app_id')!='ai_quote' or payload.get('environment')!='production' or
        payload.get('enabled') is not True or not settings.https_url(payload.get('url','')) or
        not payload['url'].endswith('/api/v1/events') or
        not re.fullmatch(r'\d{1,4}(?:\.\d{1,4}){3}',version) or
        tuple(map(int,version.split('.')))<tuple(map(int,payload['minimum_version'].split('.')))):
        raise ValueError('Automatic enrollment bootstrap is invalid')
    certificate = decode(payload['ca_der'])
    if sha(certificate)!=payload['ca_sha256']: raise ValueError('Bootstrap CA mismatch')
    return payload,certificate,sha(canonical(packet))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise urllib.error.URLError('Enrollment redirects are refused')


def post(payload, certificate, route, body):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=context))
    origin=payload['url'][:-len('/api/v1/events')]
    request=urllib.request.Request(origin+route,data=canonical(body),headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=3) as response:
        data=response.read(65537)
    if len(data)>65536: raise ValueError('Enrollment reply too large')
    return json.loads(data)


def sign(private,body,domain):
    return dict(body,signature=encode(private.sign(domain+canonical(body),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.MAX_LENGTH),hashes.SHA256())))


class AutoEnrollment:
    def __init__(self,path,version,bootstrap):
        self.path,self.version,self.bootstrap=Path(path),version,Path(bootstrap)
        self.next_attempt=0
        self.state='awaiting_approval'

    def step(self,person):
        if self.path.exists(): return 'configured'
        if settings.collection_preference(self.path) is False: return 'disabled'
        if not self.bootstrap.exists(): return 'awaiting_configuration'
        if time.monotonic()<self.next_attempt: return self.state
        self.next_attempt=time.monotonic()+30
        try:
            payload,ca,bootstrap_hash=load_bootstrap(self.bootstrap,self.version)
            name=unicodedata.normalize('NFC',str(person.get('display_name','')).strip())
            user=person.get('user_id')
            if (not name or len(name)>80 or person.get('identity_mode')!='NAME_ONLY' or
                any(unicodedata.category(c) in ('Cc','Cf','Cs') for c in name) or user!='name-user:'+sha(name.encode())):
                return 'awaiting_identity'
            home=self.path.parent/'AutoEnrollment';home.mkdir(parents=True,exist_ok=True)
            pending=home/'request.dpapi'
            with settings.collection_lock(self.path):
                if self.path.exists(): return 'configured'
                if settings.collection_preference(self.path) is False:return 'disabled'
                if pending.exists():
                    saved=settings.load_secret(pending)
                    if (saved['request']['user_id']!=user or saved['request']['monitor_url']!=payload['url'] or
                        saved.get('ca_sha256')!=sha(ca)):
                        return 'enrollment_identity_mismatch'
                else:
                    private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
                    body=dict(schema=1,purpose='quote-auto-enrollment',app_id='ai_quote',environment='production',
                        request_id=uuid.uuid4().hex,device_id='QUOTE-AUTO-'+uuid.uuid4().hex,user_id=user,
                        display_name=name,app_version=self.version,created_at=datetime.now(timezone.utc).isoformat(),
                        public_key=encode(private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)),
                        bootstrap_sha256=bootstrap_hash,monitor_url=payload['url'])
                    saved=dict(request=sign(private,body,REQUEST_DOMAIN),bootstrap_sha256=bootstrap_hash,ca_sha256=sha(ca),
                        private_key=encode(private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())))
                    settings.save_secret(pending,saved)
            request=saved['request']
            private=serialization.load_der_private_key(decode(saved['private_key']),password=None)
            claim=sign(private,dict(request_id=request['request_id'],created_at=datetime.now(timezone.utc).isoformat(),nonce=uuid.uuid4().hex),CLAIM_DOMAIN)
            try: result=post(payload,ca,'/api/v1/enrollment/claim',claim)
            except urllib.error.HTTPError as error:
                if error.code!=404:raise
                post(payload,ca,'/api/v1/enrollment/requests',request)
                result={'status':'pending'}
            state=result.get('status')
            if state=='approved':
                self.import_grant(saved,private,result['response'],payload,ca)
                self.state='configured'
            else:
                self.state={'pending':'awaiting_approval','rejected':'enrollment_rejected',
                    'revoked':'enrollment_revoked','expired':'enrollment_expired'}.get(state,'enrollment_unavailable')
            return self.state
        except Exception:
            self.state='enrollment_unavailable'
            return self.state

    def import_grant(self,saved,private,packet,payload,ca):
        request=saved['request'];request_hash=sha(canonical(request))
        if packet.get('schema')!=1 or packet.get('purpose')!='quote-auto-enrollment-response' or packet.get('request_sha256')!=request_hash:
            raise ValueError('Response belongs to a different request')
        aes=private.decrypt(decode(packet['wrapped_key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=RESPONSE_DOMAIN))
        content=json.loads(AESGCM(aes).decrypt(decode(packet['nonce']),decode(packet['ciphertext']),RESPONSE_DOMAIN+request_hash.encode()))
        if (content['request_id']!=request['request_id'] or content['request_sha256']!=request_hash or
            instant(content['expires_at'])<=datetime.now(timezone.utc)):
            raise ValueError('Expired or mismatched reply')
        grant=content['grant']
        if (any(grant[field]!=request[field] for field in ('app_id','environment','device_id','user_id')) or
            not re.fullmatch(r'[A-Za-z0-9_-]{43}',grant['renewal_secret']) or
            instant(grant['expires_at'])<=datetime.now(timezone.utc)):
            raise ValueError('Credential scope mismatch')
        install=self.bootstrap.parent.parent if self.bootstrap.parent.name=='_internal' else self.bootstrap.parent
        business=read(install/'client_config.json')['api_url']
        if not settings.https_url(business):raise ValueError('Business HTTPS required')
        # One resumable staged transaction; publish config last, never overwrite another profile.
        with settings.collection_lock(self.path):
            if self.path.exists():return
            home=self.path.parent/'AutoEnrollment';stage=home/'staging';stage.mkdir(exist_ok=True)
            journal=home/'import.json';packet_hash=sha(canonical(packet))
            if journal.exists():
                record=read(journal)
                if record['request_sha256']!=request_hash or record['response_sha256']!=packet_hash:raise ValueError('Another import is pending')
            else:
                if any((self.path.parent/name).exists() for name in ('credential.dpapi','monitor-root.cer')):raise ValueError('Existing configuration protected')
                settings.save_secret(stage/'credential.dpapi',grant)
                (stage/'monitor-root.cer').write_bytes(ca)
                record=dict(request_sha256=request_hash,response_sha256=packet_hash,
                    files={n:sha((stage/n).read_bytes()) for n in ('credential.dpapi','monitor-root.cer')})
                settings.atomic_json(journal,record)
            for name,expected in record['files'].items():
                data=(stage/name).read_bytes();target=self.path.parent/name
                if sha(data)!=expected:raise ValueError('Staging changed')
                if target.exists():
                    if sha(target.read_bytes())!=expected:raise ValueError('Existing file protected')
                else:
                    temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                    try:
                        temporary.write_bytes(data)
                        os.rename(temporary,target)
                    finally:
                        if temporary.exists():temporary.unlink()
            config={field:request[field] for field in ('app_id','environment','device_id','user_id')}
            config.update(app_version=self.version,profile='production',enabled=settings.collection_preference(self.path) is not False,
                url=payload['url'],api_url=business,ca_file=str(self.path.parent/'monitor-root.cer'),ca_sha256=sha(ca))
            settings.atomic_json(self.path,config)
            settings.configuration(self.path)
            settings.atomic_json(home/'receipt.json',dict(request_id=request['request_id'],request_sha256=request_hash,device_id=request['device_id']))
