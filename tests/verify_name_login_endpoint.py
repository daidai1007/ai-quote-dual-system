"""Real Qt POSTs from deployed-style API URLs to an isolated loopback server."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hashlib,json,os
from pathlib import Path
import sys,threading,time,unittest
from unittest.mock import patch
import urllib.request
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtTest import QTest
import name_login


class LoginServer:
    def __init__(self,prefix=''):
        self.prefix=prefix;self.requests=[]
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append(dict(path=self.path,body=body,
                    key=self.headers.get('X-AI-Quote-Key')))
                if self.path!=prefix+'/api/name-login':
                    value={'error':'name_session_required','message':'请先输入姓名登录；会话可能已失效，旧客户端需升级后使用。'}
                    status=401
                else:
                    name=body['name']
                    value=dict(token='T'*43,person=dict(user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),
                        display_name=name,scope='OWN',identity_mode='NAME_ONLY',can_view_all_quotes=False))
                    status=200
                content=json.dumps(value,ensure_ascii=False).encode('utf-8')
                self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.base='http://127.0.0.1:'+str(self.server.server_port)+prefix
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
    def open_local(self,request,*args,**kwargs):
        url=urlsplit(request.full_url)
        if url.scheme!='http' or url.hostname!='127.0.0.1' or url.port!=self.server.server_port:
            raise AssertionError('Only the synthetic loopback login server is allowed')
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,*args,**kwargs)


class LoginEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def check_url(self,suffix='',prefix=''):
        with LoginServer(prefix) as server,patch('urllib.request.urlopen',side_effect=server.open_local):
            dialog=name_login.NameLoginDialog(server.base+suffix,{'X-AI-Quote-Key':'synthetic-only'})
            try:
                dialog.show();self.app.processEvents()
                dialog.name.setText(' 离线登录测试人员 ');dialog.enter.click()
                deadline=time.monotonic()+5
                while dialog.worker is not None and time.monotonic()<deadline:
                    self.app.processEvents();QTest.qWait(10)
                self.assertIsNone(dialog.worker)
                self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted,dialog.error.text())
                self.assertEqual(dialog.value['person']['display_name'],'离线登录测试人员')
                self.assertEqual(server.requests,[dict(path=prefix+'/api/name-login',
                    body={'name':'离线登录测试人员'},key='synthetic-only')])
            finally:
                if dialog.worker is not None:dialog.worker.wait(5000);self.app.processEvents()
                dialog.reject();dialog.deleteLater();self.app.processEvents()
    def test_full_calculate_dual_url_used_in_real_client_config(self):
        self.check_url('/api/quotes/calculate-dual')
    def test_service_root_used_when_switching_or_renewing_name(self):self.check_url()
    def test_full_endpoint_with_trailing_slash(self):self.check_url('/api/quotes/calculate-dual/')
    def test_service_root_with_trailing_slash(self):self.check_url('/')
    def test_full_endpoint_preserves_service_path_prefix(self):self.check_url('/api/quotes/calculate-dual','/quote-service')


if __name__=='__main__':unittest.main(verbosity=2)
