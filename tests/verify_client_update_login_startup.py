"""Real subprocess startup deadlines and offline Qt login phase transitions."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop_client'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import client_update_runner as runner
from client_update_core import read_json

CHILD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
from client_update_runner import report_startup_phase, acknowledge_startup
version='2026.10.23.01'
mode=sys.argv[2]
def waiting(seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        report_startup_phase(version,'waiting_for_name');time.sleep(.04)
if mode=='success':
    waiting(1.2);report_startup_phase(version,'starting_main_window');time.sleep(.15);acknowledge_startup(version)
elif mode=='main_timeout':
    waiting(1.2);report_startup_phase(version,'starting_main_window')
elif mode=='repeat_start':
    for _ in range(100):report_startup_phase(version,'starting_main_window');time.sleep(.04)
elif mode=='retry':
    waiting(.7);report_startup_phase(version,'starting_main_window');time.sleep(.15)
    waiting(.7);report_startup_phase(version,'starting_main_window');time.sleep(.15);acknowledge_startup(version)
elif mode=='hung_login':report_startup_phase(version,'waiting_for_name')
elif mode=='cancel':waiting(.7);sys.exit(0)
elif mode=='wrong_identity':
    os.environ['AI_QUOTE_UPDATE_HEALTH_TOKEN']='wrong';waiting(2)
elif mode=='legacy':acknowledge_startup(version)
time.sleep(10)
'''


class StartupDeadlineTests(unittest.TestCase):
    def run_client(self, mode):
        with tempfile.TemporaryDirectory(prefix='login-startup-') as temp:
            path=Path(temp)/'health.json'
            job=dict(health_file=str(path),token='synthetic-token',
                     envelope=dict(release=dict(version='2026.10.23.01')))
            children=[]
            def launch(_job,health=False):
                self.assertTrue(health)
                env=dict(os.environ,AI_QUOTE_UPDATE_HEALTH_FILE=str(path),
                    AI_QUOTE_UPDATE_HEALTH_TOKEN=job['token'],AI_QUOTE_UPDATE_HEALTH_VERSION='2026.10.23.01',
                    AI_QUOTE_UPDATE_HEALTH_PROTOCOL=runner.STARTUP_PROTOCOL)
                process=subprocess.Popen([sys.executable,'-c',CHILD,str(ROOT/'desktop_client'),mode],
                    env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                children.append(process);return process
            began=time.monotonic();messages=[]
            try:
                with patch.object(runner,'launch_client',side_effect=launch):
                    result=runner.check_new_client(job,timeout=.6,progress=messages.append)
                return result,time.monotonic()-began,messages
            finally:
                for process in children:
                    if process.poll() is None:process.terminate()
                    stdout,stderr=process.communicate(timeout=10)
                    if process.returncode not in (0,1) or stderr:
                        self.assertFalse(stderr,stderr.decode('utf-8',errors='replace'))

    def test_waiting_longer_than_deadline_then_main_window_succeeds(self):
        ok,elapsed,messages=self.run_client('success')
        self.assertTrue(ok);self.assertGreater(elapsed,1.2)
        self.assertEqual(len(messages),2)
    def test_submit_starts_a_fresh_deadline_and_missing_main_fails(self):
        ok,elapsed,_=self.run_client('main_timeout')
        self.assertFalse(ok);self.assertGreater(elapsed,1.7);self.assertLess(elapsed,3.5)
    def test_repeated_start_phase_cannot_keep_extending_deadline(self):
        ok,elapsed,_=self.run_client('repeat_start')
        self.assertFalse(ok);self.assertLess(elapsed,2)
    def test_failed_login_can_wait_for_retry_then_start_main(self):
        ok,elapsed,_=self.run_client('retry')
        self.assertTrue(ok);self.assertGreater(elapsed,1.6)
    def test_unresponsive_login_does_not_wait_forever(self):
        ok,elapsed,_=self.run_client('hung_login')
        self.assertFalse(ok);self.assertLess(elapsed,2)
    def test_closed_login_is_not_success(self):
        ok,_,_=self.run_client('cancel');self.assertFalse(ok)
    def test_wrong_token_cannot_pause_startup_deadline(self):
        ok,elapsed,_=self.run_client('wrong_identity')
        self.assertFalse(ok);self.assertLess(elapsed,2)
    def test_existing_final_receipt_remains_supported(self):
        ok,_,_=self.run_client('legacy');self.assertTrue(ok)
    def test_windows_sharing_conflict_is_retried_without_claiming_early_success(self):
        with patch.object(runner,'atomic_json',side_effect=[PermissionError('sharing'),None]) as write:
            runner._write_startup_receipt('synthetic.json',{'phase':'waiting_for_name'})
            self.assertEqual(write.call_count,2)
        with patch.object(runner,'atomic_json',side_effect=PermissionError('denied')) as write:
            with self.assertRaises(PermissionError):
                runner._write_startup_receipt('synthetic.json',{'phase':'waiting_for_name'})
            self.assertEqual(write.call_count,20)
    def test_phases_are_not_written_for_legacy_updater_or_normal_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'health.json'
            with patch.dict(os.environ,AI_QUOTE_UPDATE_HEALTH_FILE=str(path),
                AI_QUOTE_UPDATE_HEALTH_TOKEN='test',AI_QUOTE_UPDATE_HEALTH_VERSION='2026.10.23.01',
                AI_QUOTE_UPDATE_HEALTH_PROTOCOL=''):
                runner.report_startup_phase('2026.10.23.01','waiting_for_name')
                self.assertFalse(path.exists())


class LoginDialogPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def test_visible_wait_empty_name_and_failed_request_retry(self):
        import name_login as login
        from PySide6.QtTest import QTest
        with patch.object(runner,'report_startup_phase') as report:
            dialog=login.NameLoginDialog('http://127.0.0.1:9',{},startup=True)
            dialog.show();self.app.processEvents()
            self.assertEqual(report.call_args.args[1],'waiting_for_name')
            dialog.login();self.assertEqual(report.call_args.args[1],'waiting_for_name')
            dialog.name.setText('离线合成测试人员')
            def failed(worker):worker.failed.emit('离线失败，无业务请求')
            with patch.object(login.SessionWorker,'run',failed):
                dialog.login()
                self.assertEqual(report.call_args.args[1],'starting_main_window')
                deadline=time.monotonic()+3
                while dialog.worker is not None and time.monotonic()<deadline:
                    self.app.processEvents();QTest.qWait(10)
            self.assertIsNone(dialog.worker)
            self.assertEqual(report.call_args.args[1],'waiting_for_name')
            self.assertTrue(dialog._startup_timer.isActive())
            dialog.reject();self.app.processEvents()
            self.assertFalse(dialog._startup_timer.isActive())
    def test_normal_switch_dialog_does_not_change_startup_receipt(self):
        import name_login as login
        with patch.object(runner,'report_startup_phase') as report:
            dialog=login.NameLoginDialog('http://127.0.0.1:9',{})
            dialog.show();self.app.processEvents();dialog.reject()
            self.assertFalse(dialog._startup_timer.isActive());report.assert_not_called()
    def test_successful_name_submission_requires_actual_main_window_acknowledgement(self):
        import hashlib
        import name_login as login
        import quote_scheme_center as centre
        import v3_launcher
        from verify_name_login_endpoint import LoginServer
        from PySide6.QtCore import QTimer,QSettings
        from PySide6.QtTest import QTest
        with tempfile.TemporaryDirectory(prefix='login-main-health-') as temp:
            root=Path(temp);health=root/'health.json';updates=root/'updates.json'
            updates.write_text('{}',encoding='utf-8')
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,temp)
            env=dict(LOCALAPPDATA=temp,AI_QUOTE_ORDER_CACHE_ROOT=temp,AI_QUOTE_UPDATE_CONFIG=str(updates),
                AI_QUOTE_UPDATE_HEALTH_FILE=str(health),AI_QUOTE_UPDATE_HEALTH_TOKEN='synthetic-main',
                AI_QUOTE_UPDATE_HEALTH_VERSION=centre.CLIENT_VERSION,
                AI_QUOTE_UPDATE_HEALTH_PROTOCOL=runner.STARTUP_PROTOCOL)
            session=dict(token='T'*43,person=dict(user_id='name-user:'+hashlib.sha256(b'offline').hexdigest(),
                display_name='离线合成测试人员',identity_mode='NAME_ONLY',scope='OWN'))
            namespace=v3_launcher.load_v3_namespace()
            namespace['MainWindow'].load_catalogs=lambda self:None
            namespace['_name_login_core_main']=lambda:namespace['MainWindow']()
            server=LoginServer();server.__enter__()
            namespace['API_URL']=server.base+'/api/quotes/calculate-dual'
            namespace['API_KEY']='synthetic-only'
            namespace['_name_connection_headers']=lambda:{'X-AI-Quote-Key':'synthetic-only'}
            original_exec=login.NameLoginDialog.exec
            def submit(dialog):
                self.assertEqual(read_json(health)['phase'],'waiting_for_name')
                dialog.name.setText(session['person']['display_name']);dialog.enter.click()
            def enter(dialog):
                QTimer.singleShot(0,lambda:submit(dialog));return original_exec(dialog)
            window=None
            try:
                login._state=None;login._required=False
                with patch.dict(os.environ,env),patch.object(login.NameLoginDialog,'exec',enter),\
                    patch.object(centre.QuoteSchemeWorker,'run',lambda worker:worker.succeeded.emit(dict(items=[],total=0))),\
                    patch('urllib.request.urlopen',side_effect=server.open_local):
                    window=namespace['main']();window.show()
                    self.assertEqual(server.requests,[dict(path='/api/name-login',
                        body={'name':session['person']['display_name']},key='synthetic-only')])
                    self.assertEqual(read_json(health)['phase'],'starting_main_window')
                    self.assertIn('仅本人报价',window.name_scope_label.text())
                    deadline=time.monotonic()+6
                    expected={'token':'synthetic-main','version':centre.CLIENT_VERSION}
                    while read_json(health)!=expected and time.monotonic()<deadline:
                        self.app.processEvents();QTest.qWait(10)
                    self.assertEqual(read_json(health),expected)
            finally:
                if window is not None:
                    window._quote_scheme_id='';window._scheme2_dirty=False
                    window._quote_scheme_save_timer.stop();window.close();window.deleteLater()
                    self.app.processEvents()
                login._state=None;login._required=False
                server.__exit__(None,None,None)


if __name__=='__main__':unittest.main(verbosity=2)
