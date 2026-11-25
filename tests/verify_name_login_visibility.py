"""Real Qt name-login contrast, busy feedback, failures and retry; no network."""
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel
import name_login as login
from dialog_style import DIALOG_COLORS

app = QApplication.instance() or QApplication([])
app.setStyle('Fusion')
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei', 10))
OUT = Path(os.environ.get('AI_QUOTE_NAME_VISIBILITY_OUTPUT', ROOT.parent / '测试报告_姓名登录可见性_20261125'))


def wait(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), 'login state did not settle'


def luminance(color):
    c = QColor(color)
    def channel(value):
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    return sum(channel(value) * weight for value, weight in
               zip((c.redF(), c.greenF(), c.blueF()), (.2126, .7152, .0722)))


def contrast(color):
    a, b = sorted((luminance(color), luminance(DIALOG_COLORS['background'])))
    return (b + .05) / (a + .05)


def response():
    value = dict(token='T' * 43, person=dict(display_name='合成测试人员', scope='OWN',
        identity_mode='NAME_ONLY', user_id='name-user:' + hashlib.sha256(b'offline').hexdigest()))
    return io.BytesIO(json.dumps(value, ensure_ascii=False).encode('utf-8'))


class NameLoginVisibility(unittest.TestCase):
    def setUp(self):
        self.palette = app.palette()
        self.styles = app.styleSheet()
        palette = QPalette(self.palette)
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(role, QColor('#ffffff'))
        for role in (QPalette.Window, QPalette.Base, QPalette.Button):
            palette.setColor(role, QColor('#202020'))
        palette.setColor(QPalette.PlaceholderText, QColor('#eeeeee'))
        app.setPalette(palette)
        # Match a startup form whose background was styled independently of
        # the operating-system text palette.
        app.setStyleSheet('QLineEdit {background:#ffffff;}')
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            if dialog.worker is not None:
                dialog.worker.wait(5000)
                app.processEvents()
            dialog.close()
        app.setStyleSheet(self.styles)
        app.setPalette(self.palette)
        app.processEvents()

    def dialog(self, **kwargs):
        dialog = login.NameLoginDialog('https://offline.invalid/api/quotes/calculate-dual', {}, **kwargs)
        self.dialogs.append(dialog)
        dialog.resize(520, 300)
        dialog.show()
        app.processEvents()
        return dialog

    def assert_readable(self, dialog):
        for label in dialog.findChildren(QLabel):
            if label.text():
                self.assertGreaterEqual(contrast(label.palette().color(QPalette.WindowText)), 4.5, label.text())
        self.assertGreaterEqual(contrast(dialog.name.palette().color(QPalette.Text)), 4.5)
        self.assertGreaterEqual(contrast(dialog.name.palette().color(QPalette.PlaceholderText)), 3)

    def test_light_and_dark_palettes_keep_all_text_readable(self):
        OUT.mkdir(parents=True, exist_ok=True)
        for theme in ('dark', 'light'):
            with self.subTest(theme=theme):
                if theme == 'light':
                    app.setPalette(app.style().standardPalette())
                dialog = self.dialog()
                self.assert_readable(dialog)
                self.assertTrue(dialog.grab().save(str(OUT / (theme + '-login.png'))))
                dialog.close()

    def test_blank_name_shows_readable_validation_without_a_request(self):
        dialog = self.dialog()
        with patch('urllib.request.urlopen', side_effect=AssertionError('empty name made a request')):
            QTest.mouseClick(dialog.enter, Qt.MouseButton.LeftButton)
        self.assertIn('请输入姓名', dialog.error.text())
        self.assert_readable(dialog)
        self.assertTrue(dialog.enter.isEnabled())

    def test_slow_request_has_busy_feedback_and_cannot_be_submitted_twice(self):
        dialog = self.dialog()
        dialog.name.setText('合成测试人员')
        entered, gate = threading.Event(), threading.Event()
        calls = []
        def open_request(request, **kwargs):
            calls.append((request.full_url, json.loads(request.data), kwargs['timeout']))
            entered.set()
            gate.wait(4)
            return response()
        with patch('urllib.request.urlopen', side_effect=open_request):
            try:
                QTest.mouseClick(dialog.enter, Qt.MouseButton.LeftButton)
                wait(entered.is_set)
                self.assertFalse(dialog.enter.isEnabled())
                self.assertIn('正在登录', dialog.enter.text())
                self.assertIn('正在登录', dialog.error.text())
                self.assert_readable(dialog)
                dialog.login()
                self.assertEqual(len(calls), 1)
            finally:
                gate.set()
                wait(lambda: dialog.worker is None)
        self.assertEqual(calls, [('https://offline.invalid/api/name-login', {'name': '合成测试人员'}, 30)])
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_network_failures_keep_name_show_error_and_restore_retry(self):
        for error in (urllib.error.URLError('offline'), TimeoutError('timeout'), OSError('unreachable')):
            with self.subTest(error=type(error).__name__):
                dialog = self.dialog()
                dialog.name.setText('合成测试人员')
                with patch('urllib.request.urlopen', side_effect=error):
                    dialog.enter.click()
                    wait(lambda: dialog.worker is None)
                self.assertIn('连接失败', dialog.error.text())
                self.assertEqual(dialog.name.text(), '合成测试人员')
                self.assertEqual(dialog.enter.text(), '进入')
                self.assertTrue(dialog.name.isEnabled() and dialog.enter.isEnabled())
                self.assert_readable(dialog)
                dialog.close()

    def test_http_failure_is_visible_and_retry_can_log_in(self):
        dialog = self.dialog()
        dialog.name.setText('合成测试人员')
        error = urllib.error.HTTPError('https://offline.invalid/api/name-login', 503, 'Unavailable', {},
            io.BytesIO(json.dumps({'message': '姓名登录服务暂不可用，请稍后重试。'}, ensure_ascii=False).encode('utf-8')))
        with patch('urllib.request.urlopen', side_effect=error):
            dialog.enter.click()
            wait(lambda: dialog.worker is None)
        self.assertIn('服务暂不可用', dialog.error.text())
        self.assert_readable(dialog)
        OUT.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dialog.grab().save(str(OUT / 'dark-login-failure.png')))
        with patch('urllib.request.urlopen', return_value=response()):
            dialog.enter.click()
            wait(lambda: dialog.worker is None)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_wrong_identity_during_renewal_keeps_readable_error(self):
        dialog = self.dialog(expected_user='name-user:' + '0' * 64)
        dialog.name.setText('合成测试人员')
        with patch('urllib.request.urlopen', return_value=response()):
            dialog.enter.click()
            wait(lambda: dialog.worker is None)
        self.assertIsNone(dialog.value)
        self.assertIn('原姓名', dialog.error.text())
        self.assertTrue(dialog.enter.isEnabled())
        self.assert_readable(dialog)

    def test_missing_and_invalid_business_credentials_have_distinct_feedback(self):
        for headers,expected in (({},'未读取到'),({'X-AI-Quote-Key':'   '},'未读取到'),
                                 ({'x-ai-quote-key':'synthetic-private-key'},'校验失败')):
            with self.subTest(configured=bool(headers)):
                dialog=self.dialog()
                dialog.headers=headers
                dialog.name.setText('合成测试人员')
                error=urllib.error.HTTPError('https://offline.invalid/api/name-login',401,'Unauthorized',{},
                    io.BytesIO(b'{"error":"unauthorized","message":"invalid client access key"}'))
                with patch('urllib.request.urlopen',side_effect=error):
                    QTest.mouseClick(dialog.enter,Qt.MouseButton.LeftButton)
                    wait(lambda:dialog.worker is None)
                self.assertIn(expected,dialog.error.text())
                self.assertIn('HTTP 401',dialog.error.text())
                self.assertNotIn('synthetic-private-key',dialog.error.text())
                self.assertTrue(dialog.name.isEnabled() and dialog.enter.isEnabled())
                self.assert_readable(dialog)
                dialog.close()

    def test_name_session_and_other_http_errors_are_not_reported_as_bad_api_keys(self):
        for status,payload in ((401,{'error':'name_session_required','message':'姓名会话已失效'}),
                               (400,{'error':'name_login_failed','message':'请输入有效姓名'}),
                               (403,{'error':'forbidden','message':'无权操作'}),
                               (429,{'error':'name_login_failed','message':'登录过于频繁'}),
                               (503,{'message':'服务暂不可用'})):
            with self.subTest(status=status):
                self.assertEqual(login.session_http_error_message(status,payload,{}),payload['message'])
        for payload in (None,[], 'not-json-object'):
            self.assertIn('暂不可用',login.session_http_error_message(500,payload,{}))

    def test_first_login_retry_reloads_the_administrator_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'client_config.json'
            path.write_text(json.dumps({'api_url':'https://offline.invalid/api/quotes/calculate-dual',
                                        'api_key':''}),encoding='utf-8')
            namespace={'API_URL':'https://offline.invalid/api/quotes/calculate-dual','API_KEY':'',
                       'load_client_config':lambda:json.loads(path.read_text(encoding='utf-8'))}
            namespace['_name_connection_headers']=lambda:{'X-AI-Quote-Key':namespace['API_KEY']} if namespace['API_KEY'] else {}
            options={'startup':True}
            if 'connection_settings' in inspect.signature(login.NameLoginDialog).parameters:
                options['connection_settings']=lambda:login.reload_startup_connection(namespace)
            dialog=login.NameLoginDialog(namespace['API_URL'],{},**options)
            self.dialogs.append(dialog)
            dialog.show();app.processEvents();dialog.name.setText('合成测试人员')
            sent=[]
            def gateway(request,**kwargs):
                key=request.get_header('X-ai-quote-key')
                sent.append(key)
                if key!='synthetic-approved':
                    raise urllib.error.HTTPError(request.full_url,401,'Unauthorized',{},
                        io.BytesIO(b'{"error":"unauthorized","message":"invalid client access key"}'))
                return response()
            with patch.dict(os.environ,{'AI_QUOTE_API_KEY':'','AI_QUOTE_API_URL':''}),\
                 patch('urllib.request.urlopen',side_effect=gateway):
                dialog.enter.click();wait(lambda:dialog.worker is None)
                self.assertIn('未读取到',dialog.error.text())
                path.write_text(json.dumps({'api_url':namespace['API_URL'],'api_key':'synthetic-approved'}),encoding='utf-8')
                dialog.enter.click();wait(lambda:dialog.worker is None)
            self.assertEqual(sent,[None,'synthetic-approved'])
            self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)

    def test_reload_keeps_existing_environment_override_policy(self):
        namespace={'API_URL':'https://offline.invalid/api/quotes/calculate-dual','API_KEY':'old',
                   'load_client_config':lambda:{'api_url':'https://configured.invalid/api/quotes/calculate-dual','api_key':'file-key'}}
        namespace['_name_connection_headers']=lambda:{'X-AI-Quote-Key':namespace['API_KEY']}
        with patch.dict(os.environ,{'AI_QUOTE_API_KEY':'environment-key','AI_QUOTE_API_URL':'https://environment.invalid/api/quotes/calculate-dual'}):
            url,headers=login.reload_startup_connection(namespace)
        self.assertEqual(url,'https://environment.invalid/api/quotes/calculate-dual')
        self.assertEqual(headers,{'X-AI-Quote-Key':'environment-key'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
