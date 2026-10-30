"""Recover only rejected name sessions, without replaying accepted operations.

All client workers use urllib. Scope this shared transport to configured API
roots and tokens already issued to the current identity. Never recover logout,
permission failures, timeouts, or a response whose business handler has run.
"""
from collections import OrderedDict
import io
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class NameSessionRecovery:
    def __init__(self, open_request, current_session, adopt_session, *, clock=time.monotonic):
        self.open_request = open_request
        self.current_session = current_session
        self.adopt_session = adopt_session
        self.clock = clock
        self.condition = threading.Condition(threading.RLock())
        self.epoch = None
        self.tokens = OrderedDict()
        self.roots = set()
        self.inflight = set()
        self.retry_after = {}
        self.suspended = False

    def remember(self, value, epoch):
        with self.condition:
            if self.epoch != epoch:
                self.tokens.clear()
                self.retry_after.clear()
            self.epoch = epoch
            self.suspended = False
            if value:
                self.tokens[value['token']] = value['person']['user_id']
                while len(self.tokens) > 64:
                    self.tokens.popitem(last=False)
            self.condition.notify_all()

    def suspend(self, value=True):
        with self.condition:
            self.suspended = value
            self.condition.notify_all()

    def register(self, url):
        root = str(url).strip().split('/api/', 1)[0].rstrip('/')
        parsed = urllib.parse.urlsplit(root)
        if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password:
            with self.condition:
                self.roots.add(root)

    @staticmethod
    def token(request):
        value = dict((key.lower(), value) for key, value in request.header_items()).get('authorization', '')
        return value[7:] if value.startswith('Bearer ') else None

    @staticmethod
    def with_token(request, token):
        headers = {key: value for key, value in request.header_items() if key.lower() != 'authorization'}
        headers['Authorization'] = 'Bearer ' + token
        return urllib.request.Request(request.full_url, data=request.data, headers=headers,
            method=request.get_method(), origin_req_host=request.origin_req_host, unverifiable=request.unverifiable)

    def binding(self, request):
        if not isinstance(request, urllib.request.Request) or request.data is not None and not isinstance(request.data, bytes):
            return None
        path = urllib.parse.urlsplit(request.full_url).path.rstrip('/')
        if path.endswith(('/api/name-login', '/api/name-logout')):
            return None
        with self.condition:
            current = self.current_session()
            token = self.token(request)
            person = (current or {}).get('person', {}).get('user_id')
            root = next((root for root in self.roots if request.full_url.startswith(root + '/api/')), None)
            if self.suspended or not root or not person or self.tokens.get(token) != person:
                return None
            return self.epoch, person, root, current['token']

    @staticmethod
    def session_rejected(error):
        if error.code != 401:
            return False
        body = error.fp.read()
        error.fp.close()
        error.fp = error.file = io.BytesIO(body)
        error.read = error.fp.read  # HTTPError may cache a reader for its original stream.
        try:
            return json.loads(body).get('error') == 'name_session_required'
        except (ValueError, AttributeError):
            return False

    def _current(self, binding, rejected):
        current = self.current_session()
        if self.suspended or self.epoch != binding[0] or (current or {}).get('person', {}).get('user_id') != binding[1]:
            raise rejected
        return current

    def recover(self, request, binding, rejected):
        sent_token = self.token(request)
        key = binding[0], sent_token
        with self.condition:
            while True:
                current = self._current(binding, rejected)
                if current['token'] != sent_token:
                    return current['token']
                if key in self.inflight:
                    self.condition.wait()
                    continue
                if self.retry_after.get(key, 0) > self.clock():
                    raise urllib.error.URLError('姓名会话暂未恢复，当前填写内容已保留，请稍后重试。')
                self.inflight.add(key)
                name = current['person']['display_name']
                break
        # Never hold the identity lock during network I/O: switching or logging
        # out must be able to invalidate this in-flight recovery immediately.
        try:
            headers = {key: value for key, value in request.header_items() if key.lower() == 'x-ai-quote-key'}
            headers['Content-Type'] = 'application/json; charset=utf-8'
            login = urllib.request.Request(binding[2] + '/api/name-login',
                data=json.dumps({'name': name}, ensure_ascii=False).encode('utf-8'), headers=headers, method='POST')
            with self.open_request(login, timeout=30) as response:
                renewed = json.loads(response.read().decode('utf-8'))
            with self.condition:
                current = self._current(binding, rejected)
                if current['token'] != sent_token:
                    return current['token']
                if renewed.get('person', {}).get('user_id') != binding[1]:
                    raise ValueError('姓名会话恢复返回了不同人员，当前工作区已保留。')
                self.adopt_session(renewed)
                return renewed['token']
        except Exception:
            with self.condition:
                if self.epoch == binding[0]:
                    self.retry_after[key] = self.clock() + 5
            raise
        finally:
            with self.condition:
                self.inflight.discard(key)
                self.condition.notify_all()

    def __call__(self, request, *args, **kwargs):
        binding = self.binding(request)
        prepared = self.with_token(request, binding[3]) if binding else request
        try:
            return self.open_request(prepared, *args, **kwargs)
        except urllib.error.HTTPError as error:
            if not binding or not self.session_rejected(error):
                raise
            token = self.recover(prepared, binding, error)
            # The API rejects name sessions before entering any business handler.
            # Retry exactly once; accepted requests and partial streams never replay.
            return self.open_request(self.with_token(request, token), *args, **kwargs)
