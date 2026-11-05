"""Opt-in quotation monitoring. Never retries business actions.

Events are bounded, contain identifiers only, and are persisted by a background
sender. Changing the name session suspends collection until its mapping agrees.
No quote payload, file name, price, login token or exception text is collected.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import random
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from monitor_settings import configuration, default_path, atomic_json, load_secret, save_secret

_runtime = None
_thread = threading.local()
_installed = False
_CAPACITY = 1000


class _NoMonitorRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise urllib.error.URLError('Monitoring endpoint redirects are refused')


def _monitor_open(request):
    # Credentials never follow a redirect or an ambient system proxy.
    handlers = [urllib.request.ProxyHandler({}), _NoMonitorRedirect()]
    ca_file = getattr(request, '_monitor_ca_file', None)
    if ca_file:
        certificate = Path(ca_file).read_bytes()
        if hashlib.sha256(certificate).hexdigest() != request._monitor_ca_sha256:
            raise ValueError('Monitor CA fingerprint mismatch')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=(certificate.decode('ascii') if certificate.startswith(b'-----BEGIN CERTIFICATE-----')
                                             else ssl.DER_cert_to_PEM_cert(certificate)))
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers).open(request, timeout=2)


def _monitor_request(configuration, url, payload, credential):
    target, expected = urllib.parse.urlsplit(url), urllib.parse.urlsplit(configuration['url'])
    if (target.scheme, target.netloc) != (expected.scheme, expected.netloc):
        raise ValueError('Monitoring credentials cannot leave their configured origin')
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer '+credential, 'Content-Type': 'application/json'})
    if configuration.get('ca_file'):
        request._monitor_ca_file = configuration['ca_file']
        request._monitor_ca_sha256 = configuration['ca_sha256']
    return request


def enforce_local_test(namespace=None):
    """Explicit test launcher guard; has no effect on ordinary client startup."""
    if os.getenv('AI_QUOTE_MONITOR_LOCAL_ONLY') != '1': return
    configuration = _config(os.environ['AI_QUOTE_MONITOR_CONFIG'])
    if namespace is not None:
        namespace['API_URL'] = configuration['api_url']
        namespace['API_KEY'] = ''
    if getattr(urllib.request.urlopen, '_monitor_loopback_only', False): return
    original = urllib.request.urlopen
    allowed = {urllib.parse.urlsplit(configuration[key]).netloc for key in ('url','api_url')}
    def local_only(request, *args, **kwargs):
        url = request if isinstance(request, str) else request.full_url
        if not _loopback(url) or urllib.parse.urlsplit(url).netloc not in allowed:
            raise urllib.error.URLError('本地监控接入测试禁止访问非测试地址')
        return original(request, *args, **kwargs)
    local_only._monitor_loopback_only = True
    urllib.request.urlopen = local_only


def _loopback(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and not parsed.username and not parsed.password


def _config(path):
    return configuration(path)


def current_user():
    try:
        from name_login import user_id
        return user_id()
    except Exception:
        return None


class LocalMonitor:
    def __init__(self, config_path, identity=current_user, app_version=None):
        self.path = Path(config_path).resolve()
        self.config = _config(self.path)
        self.identity = identity
        self.base = {key: self.config[key] for key in
                     ('app_id', 'environment', 'device_id', 'user_id', 'app_version')}
        self.base.update(schema_version=1, source='client')
        if app_version and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', app_version):
            self.base['app_version'] = app_version
        self.events = queue.Queue(maxsize=_CAPACITY)
        self.stop = threading.Event()
        self.dropped = 0
        self.pending = 1
        self.intents = {}
        self.records = {}
        self.active = self.config['enabled']
        self.epoch = 0
        self.state = 'starting' if self.active else 'disabled'
        self.lock = threading.RLock()
        self.scope = ':'.join(str(self.config[k]) for k in ('app_id','environment','device_id','user_id'))
        if self.config.get('profile') in ('production', 'https-test'):
            self.scope += ':'+self.config['url']+':'+self.config['api_url']
        self.spool = self.path.parent/'monitor-spool.sqlite'
        # Read-only startup recovery; all subsequent writes/network work use the sender.
        if self.spool.exists():
            with contextlib.closing(sqlite3.connect(self.spool, timeout=.1)) as previous:
                tables = {r[0] for r in previous.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'scope' in tables and previous.execute('SELECT value FROM scope').fetchone()[0] != self.scope:
                    raise ValueError('Archive the old monitoring state before changing its mapping')
                if 'intents' in tables:
                    for key, payload in previous.execute('SELECT key,payload FROM intents'):
                        span = json.loads(payload)
                        span['started'] = time.monotonic()-span.pop('_elapsed_ms',0)/1000
                        span['_epoch'] = self.epoch
                        self.intents[tuple(json.loads(key))] = span
        self.worker = threading.Thread(target=self._send, daemon=True, name='quote-monitor')
        self.worker.start()
        threading.Thread(target=self._heartbeat, daemon=True, name='quote-monitor-heartbeat').start()

    def emit(self, kind, _intent_state=None, **fields):
        if not self.active: return
        try:
            event = dict(self.base, event_id=uuid.uuid4().hex, event_type=kind,
                         occurred_at=datetime.now(timezone.utc).isoformat(), **fields)
            self.events.put_nowait((event, _intent_state))
        except Exception:
            self.dropped += 1

    def begin(self, operation, operation_id=None):
        if not self.active or self.identity() != self.base['user_id']:
            return None
        span = dict(operation=operation, operation_id=operation_id or uuid.uuid4().hex,
                    started=time.monotonic(), ended=False, category='program', _epoch=self.epoch)
        self.emit('operation_started', **self.fields(span))
        return span

    def begin_intent(self, operation, request_id):
        if not request_id: return self.begin(operation)
        key = (self.base['user_id'], operation, str(request_id))
        if not self.active or self.identity() != self.base['user_id']: return None
        if key in self.intents:
            self.intents[key]['_epoch'] = self.epoch
            return self.intents[key]
        if len(self.intents) >= _CAPACITY:
            completed = next((k for k, v in self.intents.items() if v['ended']), None)
            if completed is None: return None
            self.intents.pop(completed)
        scope = ':'.join(str(self.base[k]) for k in ('app_id','environment','device_id','user_id'))
        operation_id = uuid.uuid5(uuid.NAMESPACE_URL, scope+':'+operation+':'+str(request_id)).hex
        span = self.begin(operation, operation_id)
        if span:
            span['intent'] = True
            span['_intent_key'] = key
            self.intents[key] = span
            try: self.events.put_nowait((None, self._intent_state(span)))
            except queue.Full: self.dropped += 1
        return span

    def _intent_state(self, span):
        if '_intent_key' not in span: return None
        value = dict(span)
        value['_elapsed_ms'] = min(86400000, max(0,round((time.monotonic()-span['started'])*1000)))
        value.pop('started', None)
        return (json.dumps(span['_intent_key']), json.dumps(value))

    @staticmethod
    def fields(span):
        return {key: span[key] for key in ('operation', 'operation_id')}

    def finish(self, span, outcome='success', category=None):
        if not span or span['ended'] or not self.active or span.get('_epoch') != self.epoch:
            return
        if outcome == 'failed' and span.get('request_outcome') in ('denied', 'validation'):
            outcome = span['request_outcome']
        span['ended'] = True
        fields = dict(self.fields(span), outcome=outcome,
                      elapsed_ms=min(86400000, round((time.monotonic()-span['started'])*1000)))
        if outcome == 'failed':
            fields['error_category'] = category or span['category']
            self.emit('error', **fields, error_code='QUOTE_OPERATION_FAILED',
                      summary='程序处理失败，请按请求编号排查')
        self.emit('operation_finished', _intent_state=self._intent_state(span), **fields)

    def _heartbeat(self):
        last = 0
        while not self.stop.is_set():
            if self.identity() == self.base['user_id'] and time.monotonic()-last >= 60:
                self.emit('heartbeat')
                last = time.monotonic()
            elif self.identity() != self.base['user_id']:
                last = 0
            self.stop.wait(1)

    def _send(self):
        # Disk and HTTP are confined to this thread, including token refresh.
        db = None
        try:
            db = sqlite3.connect(self.spool, timeout=1)
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS scope(value TEXT NOT NULL)')
            if not db.execute('SELECT value FROM scope').fetchone(): db.execute('INSERT INTO scope VALUES(?)',(self.scope,))
            db.execute('CREATE TABLE IF NOT EXISTS intents(key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            next_poll, next_renew, next_status = 0, 0, 0
            retry_at, retry_delay = 0, 1
            self.last_delivered_at = None
            while True:
                if time.monotonic() >= next_poll:
                    next_poll = time.monotonic()+.2
                    try:
                        fresh = _config(self.path)
                        if any(fresh[k] != self.config[k] for k in ('app_id','environment','device_id','user_id','url','api_url')):
                            raise ValueError('Mapping changed')
                        enabled = fresh['enabled']
                        if not enabled: self.state = 'disabled'
                        elif self.state not in ('delivery_unavailable','credential_unavailable','credential_rejected'):
                            self.state = 'active'
                        if enabled and fresh.get('profile') in ('production', 'https-test') and time.monotonic() >= next_renew:
                            next_renew = time.monotonic()+30
                            expires = datetime.fromisoformat(fresh.get('expires_at','2000-01-01T00:00:00+00:00').replace('Z','+00:00'))
                            if not fresh.get('token') or expires.timestamp()-time.time() < 600:
                                try:
                                    self._renew(fresh)
                                    fresh = _config(self.path)
                                except Exception:
                                    self.state = 'credential_unavailable'
                        if self.active != enabled:
                            self.active = enabled
                            self.epoch += 1
                        self.config = fresh
                    except Exception:
                        if self.active: self.epoch += 1
                        self.active = False
                        self.state = 'configuration_unavailable'
                drained = 0
                for _ in range(_CAPACITY):
                    try:
                        event, intent_state = self.events.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        if intent_state:
                            db.execute('INSERT OR REPLACE INTO intents VALUES(?,?)',intent_state)
                            excess = db.execute('SELECT max(count(*)-?,0) FROM intents',(_CAPACITY,)).fetchone()[0]
                            if excess:
                                db.execute("DELETE FROM intents WHERE key IN (SELECT key FROM intents WHERE json_extract(payload,'$.ended')=1 ORDER BY rowid LIMIT ?)",(excess,))
                        count = db.execute('SELECT count(*) FROM pending').fetchone()[0]
                        if event and count < _CAPACITY:
                            db.execute('INSERT OR IGNORE INTO pending VALUES(?,?)',
                                       (event['event_id'], json.dumps(event, separators=(',', ':'))))
                        elif event:
                            self.dropped += 1
                    finally:
                        drained += 1
                db.commit()
                self.pending = db.execute('SELECT count(*) FROM pending').fetchone()[0]
                for _ in range(drained): self.events.task_done()
                if self.stop.is_set():
                    break
                if time.monotonic() >= next_status:
                    next_status = time.monotonic()+.3
                    try:
                        atomic_json(self.path.parent/'status.json',dict(state=self.state, enabled=self.active,
                            pending=self.pending, dropped=self.dropped, app_version=self.base['app_version'],
                            updated_at=datetime.now(timezone.utc).isoformat(), last_delivered_at=self.last_delivered_at))
                    except OSError: pass
                if not self.active:
                    self.stop.wait(.1)
                    continue
                batch = db.execute('SELECT id,payload FROM pending ORDER BY rowid LIMIT 30').fetchall()
                if not batch:
                    self.stop.wait(.1)
                    continue
                if time.monotonic() < retry_at:
                    self.stop.wait(.1)
                    continue
                try:
                    fresh = _config(self.path)
                    if not fresh['enabled']: continue
                    if any(fresh[k] != self.config[k] for k in
                           ('app_id', 'environment', 'device_id', 'user_id', 'url', 'api_url')):
                        raise ValueError('Mapping changed; pending events require the original mapping')
                    request = _monitor_request(fresh, fresh['url'],
                        {'events': [json.loads(row[1]) for row in batch]}, fresh['token'])
                    with _monitor_open(request) as response:
                        results = json.load(response)['results']
                    by_id = {item['event_id']: item['status'] for item in results}
                    for event_id, _ in batch:
                        status = by_id.get(event_id)
                        if status in ('accepted', 'duplicate', 'rejected'):
                            db.execute('DELETE FROM pending WHERE id=?', (event_id,))
                            if status == 'rejected': self.dropped += 1
                    db.commit()
                    self.pending = db.execute('SELECT count(*) FROM pending').fetchone()[0]
                    self.state = 'active'
                    self.last_delivered_at = datetime.now(timezone.utc).isoformat()
                    retry_at, retry_delay = 0, 1
                except Exception as failure:
                    # Includes expired credentials: preserve events; a replacement
                    # token for this same mapping is read on the next attempt.
                    self.state = 'credential_rejected' if isinstance(failure,urllib.error.HTTPError) and failure.code in (401,403) else 'delivery_unavailable'
                    retry_at = time.monotonic()+retry_delay*random.uniform(.8, 1.2)
                    retry_delay = min(60, retry_delay*2)
        except Exception:
            self.dropped += 1
            self.active = False
            self.state = 'storage_unavailable'
        finally:
            if db is not None: db.close()

    def _renew(self, fresh):
        payload = {key:fresh[key] for key in ('app_id','environment','device_id','user_id','renewal_id')}
        request = _monitor_request(fresh, fresh['renew_url'], payload, fresh['renewal_secret'])
        with _monitor_open(request) as response: value=json.load(response)
        if any(value.get(k) != fresh[k] for k in ('app_id','environment','device_id','user_id')):
            raise ValueError('Renewal mapping mismatch')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',value.get('token','')): raise ValueError('Invalid renewed token')
        secret = load_secret(self.path.parent/'credential.dpapi')
        secret.update(token=value['token'],expires_at=value['expires_at'])
        save_secret(self.path.parent/'credential.dpapi',secret)

    def flush(self, timeout=8):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if not self.events.unfinished_tasks and not self.pending:
                return True
            time.sleep(.05)
        return False

    def close(self):
        self.stop.set()
        self.worker.join(3)


def begin(operation):
    try:
        return _runtime.begin(operation) if _runtime else None
    except Exception:
        return None


def finish(span, outcome='success', category=None):
    try:
        if _runtime: _runtime.finish(span, outcome, category)
    except Exception:
        pass


def finish_attempt(span, outcome='success'):
    """An uncertain idempotent write stays pending until its retry is resolved."""
    if not span: return
    if span.get('intent') and outcome == 'failed' and not span['ended']:
        try:
            _runtime.emit('error', **_runtime.fields(span), outcome='failed',
                          error_category=span['category'],error_code='WRITE_RESULT_UNCONFIRMED',
                          summary='操作未完成，请按请求编号排查')
        except Exception: pass
        return
    finish(span,outcome)


def bind_calculation(window, worker, context):
    # Superseded calculations finish cancelled, never successful or failed.
    old = getattr(window, '_monitor_calculation', None)
    finish(old, 'cancelled')
    span = begin('calculate')
    worker._monitor_span = window._monitor_calculation = span


def settle_calculation(window, state):
    finish(getattr(window, '_monitor_calculation', None),
           {'accepted': 'success', 'failed': 'failed', 'rejected': 'validation',
            'cancelled': 'cancelled'}.get(state, 'cancelled'))


@contextlib.contextmanager
def monitored_urlopen(request, *args, **kwargs):
    span = getattr(_thread, 'span', None)
    observed = bool(_runtime and _runtime.active and span and span.get('_epoch') == _runtime.epoch and
                    urllib.parse.urlsplit(request.full_url).netloc ==
                    urllib.parse.urlsplit(_runtime.config['api_url']).netloc)
    started = time.monotonic()
    result, category = 'success', None
    request_id = None
    if observed:
        groups=getattr(_thread,'request_groups',None)
        if groups is None:
            groups={}
            _thread.request_groups=groups
        route=(request.get_method(),urllib.parse.urlsplit(request.full_url).path)
        request_id = uuid.uuid5(uuid.NAMESPACE_URL,span['operation_id']+':'+':'.join(route)).hex if span.get('intent') else request.get_header('X-quote-request-id') or groups.setdefault(route,uuid.uuid4().hex)
        for key, value in {'X-Quote-Request-Id': request_id,
                           'X-Monitor-Operation-Id': span['operation_id'],
                           'X-Monitor-Operation': span['operation'],
                           'X-Monitor-App-Version': _runtime.base['app_version'],
                           'X-Monitor-User-Id': _runtime.base['user_id'],
                           'X-Monitor-Device-Id': _runtime.base['device_id']}.items():
            request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, *args, **kwargs) as response:
            yield response
    except Exception as error:
        result = 'failed'
        if isinstance(error, urllib.error.HTTPError):
            if error.code in (401,403): result, category = 'denied', 'permission'
            elif error.code in (400,409,422): result, category = 'validation', 'validation'
            else: category = 'program'
        elif isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError)):
            category = 'network'
        else: category = 'program'
        if observed:
            span['category'] = category
            span['request_outcome'] = result
        raise
    finally:
        if observed:
            try:
                span['request_outcome'] = result
                if category: span['category'] = category
                _runtime.emit('request_finished', **_runtime.fields(span), request_id=request_id,
                              outcome=result, elapsed_ms=min(86400000, round((time.monotonic()-started)*1000)),
                              **({'error_category': category} if category else {}))
            except Exception: pass


def _worker_context(cls, operation_for=None, has_result=False):
    if getattr(cls, '_monitor_wrapped', False): return
    prior = cls.run
    def run(worker):
        span = getattr(worker, '_monitor_span', None)
        own = not span and operation_for
        if own:
            operation = operation_for(worker)
            try:
                key = (getattr(worker, 'payload', None) or {}).get('request_id')
                if operation and _runtime:
                    span = _runtime.begin_intent(operation,key)
                else:
                    match=re.fullmatch(r'/api/contracts/records/([^/]+)/file',urllib.parse.urlsplit(worker.url).path)
                    span=_runtime.records.get(match[1]) if match and _runtime and _runtime.identity()==_runtime.base['user_id'] else None
                    own=False
            except Exception: span = None
        previous = getattr(_thread, 'span', None)
        previous_groups=getattr(_thread,'request_groups',None)
        _thread.span = span
        _thread.request_groups={}
        try:
            value = prior(worker)
            if own and span:
                if worker.isInterruptionRequested(): finish(span, 'cancelled')
                elif has_result:
                    if not worker.error and isinstance(worker.result,dict) and worker.result.get('record_id'):
                        if len(_runtime.records)>=_CAPACITY:_runtime.records.pop(next(iter(_runtime.records)))
                        _runtime.records[str(worker.result['record_id'])]=span
                    finish_attempt(span, span.get('request_outcome', 'failed') if worker.error else 'success')
            elif span and has_result and worker.error:
                _runtime.emit('error',**_runtime.fields(span),outcome='failed',error_category=span['category'],
                              error_code='CONTRACT_DOWNLOAD_FAILED',summary='操作未完成，请按请求编号排查')
            return value
        except BaseException:
            finish(span, 'failed')
            raise
        finally:
            _thread.span = previous
            _thread.request_groups=previous_groups
    cls.run = run
    cls._monitor_wrapped = True


def _scheme_operation(method, path):
    route = urllib.parse.urlsplit(path).path
    if route == '/api/quote-schemes' and method == 'POST': return 'save'
    if re.fullmatch(r'/api/quote-schemes/[^/]+', route):
        return {'GET': 'open', 'PUT': 'save'}.get(method)
    if route == '/api/quote-deliveries' and method == 'POST': return 'send'
    return None


def install_quote_monitoring(namespace):
    global _installed, _runtime
    if _installed: return
    _installed = True
    path = os.getenv('AI_QUOTE_MONITOR_CONFIG') or str(default_path())
    if not Path(path).is_file(): return
    try:
        from quote_scheme_center import CLIENT_VERSION
        _runtime = LocalMonitor(path, app_version=CLIENT_VERSION)
    except Exception:
        # An unavailable monitor must not break quotation startup.
        return
    import layout_refresh
    import quote_scheme_center as schemes
    import contract_management
    _worker_context(namespace['ApiWorker'])
    _worker_context(layout_refresh._GangedQuoteWorker)
    _worker_context(schemes.QuoteSchemeWorker)
    _worker_context(contract_management.ContractWorker,
                    lambda w: 'contract' if urllib.parse.urlsplit(w.url).path == '/api/contracts/generate' else None,
                    has_result=True)
    api_init = namespace['ApiWorker'].__init__
    def api_worker_init(worker,*args,**kwargs):
        api_init(worker,*args,**kwargs)
        route=urllib.parse.urlsplit(str(getattr(worker,'url',''))).path
        if route in ('/api/quotes/preview-check','/api/quotes/confirm-check','/api/quotes/confirm'):
            owner=worker.parent()
            worker._monitor_span=getattr(owner,'_monitor_export',None)
    namespace['ApiWorker'].__init__=api_worker_init
    prior = schemes._run
    # Bind before QThread.start, while preserving the existing identity freeze.
    original_init = schemes.QuoteSchemeWorker.__init__
    def init_worker(worker, method, url, headers, payload=None, parent=None):
        original_init(worker, method, url, headers, payload, parent)
        worker._monitor_span = getattr(_thread, 'scheme_span', None)
    schemes.QuoteSchemeWorker.__init__ = init_worker
    def safe_run(window, method, path, payload, success, failure=None):
        # Capture one operation around the existing success/failure callbacks.
        operation = _scheme_operation(method, path)
        receipt=getattr(window,'_quote_scheme_pending_export',None)
        registration=bool(isinstance(receipt,dict) and receipt.get('scheme_no') and path.split('?')[0] in (
            '/api/quote-schemes/'+receipt['scheme_no'],
            '/api/quote-schemes/'+receipt['scheme_no']+'/export-result'))
        if registration: operation=None
        if operation=='send' and _runtime:
            try: span=_runtime.begin_intent(operation,(payload or {}).get('request_id'))
            except Exception: span=None
        else: span = begin(operation) if operation else getattr(window,'_monitor_export',None) if registration else None
        old = getattr(_thread, 'scheme_span', None)
        _thread.scheme_span = span
        try: return run_bound(span, bool(operation), window,method,path,payload,success,failure)
        finally: _thread.scheme_span = old
    def run_bound(span, owns_terminal, window, method, path, payload, success, failure=None):
        def ok(value):
            try: result = success(value)
            except BaseException:
                if owns_terminal: finish_attempt(span, 'failed')
                raise
            if owns_terminal:
                confirmed = not span or span['operation']!='send' or (isinstance(value,dict) and value.get('sent') is True)
                finish_attempt(span,'success' if confirmed else 'failed')
            return result
        def error(message):
            if owns_terminal: finish_attempt(span, span.get('request_outcome', 'failed') if span else 'failed')
            elif span and _runtime:
                _runtime.emit('error',**_runtime.fields(span),outcome='failed',error_category=span['category'],
                              error_code='EXPORT_REGISTRATION_UNCONFIRMED',summary='操作未完成，请按请求编号排查')
            if failure: return failure(message)
            return schemes._set_state(window, '保存失败：'+message, 'error')
        return prior(window, method, path, payload, ok, error)
    schemes._run = safe_run
    prepare, exported, release = schemes._prepare_export, schemes._file_exported, schemes._release_export
    def prepare_export(window, *args, **kwargs):
        result = prepare(window, *args, **kwargs)
        if result: window._monitor_export = begin('export')
        return result
    def file_exported(window, *args, **kwargs):
        finish(getattr(window, '_monitor_export', None))
        return exported(window, *args, **kwargs)
    def release_export(window, *args, **kwargs):
        finish(getattr(window, '_monitor_export', None), 'cancelled')
        return release(window, *args, **kwargs)
    schemes._prepare_export, schemes._file_exported, schemes._release_export = prepare_export, file_exported, release_export
    prior_init = namespace['MainWindow'].__init__
    def window_init(window, *args, **kwargs):
        prior_init(window, *args, **kwargs)
        if os.getenv('AI_QUOTE_MONITOR_LOCAL_ONLY') == '1':
            window.setWindowTitle(window.windowTitle()+' · 监控接入本地测试（合成数据）')
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and not getattr(app, '_quote_monitor_shutdown', False):
            app.aboutToQuit.connect(_runtime.close)
            app._quote_monitor_shutdown = True
        controller=getattr(window,'_scheme2_document_controller',None)
        if controller:
            original_fail=controller.fail
            def document_failed(value):
                finish(getattr(window,'_monitor_export',None),'validation' if isinstance(value,ValueError) else 'failed')
                return original_fail(value)
            controller.fail=document_failed
        for name in ('confirmation_failed', 'export_failed', 'persistence_failed', 'finalization_failed'):
            callback = getattr(window, name, None)
            if callable(callback):
                def failed(*a, _callback=callback, **kw):
                    finish(getattr(window, '_monitor_export', None), 'failed')
                    return _callback(*a, **kw)
                setattr(window, name, failed)
    namespace['MainWindow'].__init__ = window_init
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app: app.aboutToQuit.connect(_runtime.close)
