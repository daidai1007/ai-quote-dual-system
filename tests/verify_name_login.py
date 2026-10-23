"""Actual recovered startup/UI with synthetic sessions and offline workers."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
TEMP=tempfile.TemporaryDirectory(prefix='name-login-ui-')
os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=TEMP.name
os.environ['AI_QUOTE_UPDATE_CONFIG']=str(Path(TEMP.name)/'updates.json')
Path(os.environ['AI_QUOTE_UPDATE_CONFIG']).write_text('{}',encoding='utf-8')
from PySide6.QtCore import QSettings,QTimer,Qt,QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QTableWidgetItem
import v3_launcher
import name_login as login
import quote_scheme_center as centre
import scheme2_ui as ui

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,TEMP.name)
APP=QApplication.instance() or QApplication([])
NS=v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');NS['install_application_font'](APP)
NS['MainWindow'].load_catalogs=lambda self:None
OUT=Path(os.environ.get('AI_QUOTE_NAME_LOGIN_QA_OUTPUT') or ROOT/'.codex-tmp'/'name-login-qa');OUT.mkdir(parents=True,exist_ok=True)

def person(name,all=False,manage=False):
 return dict(token=hashlib.sha256(('token:'+name).encode()).hexdigest()[:43],expires_at='2030-01-01T00:00:00+00:00',
  person=dict(user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),display_name=name,scope='ALL' if all else 'OWN',can_view_all_quotes=all,can_manage_all_quotes=manage,identity_mode='NAME_ONLY'))
def wait(predicate):
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  APP.processEvents()
  if predicate():return
  QTest.qWait(10)
 raise AssertionError('Offline login UI timed out')

class LoginTests(unittest.TestCase):
 def setUp(self):
  login._state=None;login._required=False;login._epoch=0;self.windows=[]
  self.network=patch('urllib.request.urlopen',side_effect=AssertionError('External network forbidden'));self.network.start()
  self.transport=patch.object(centre.QuoteSchemeWorker,'run',lambda worker:worker.succeeded.emit(dict(items=[],total=0)));self.transport.start()
  screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
  self.screen=patch.object(NS['MainWindow'],'screen',return_value=screen);self.screen.start()
 def tearDown(self):
  for w in self.windows:
   try:
    w._quote_scheme_id='';w._scheme2_dirty=False;w._quote_scheme_save_timer.stop();w._quote_scheme_workers.clear();w.close();w.deleteLater()
   except RuntimeError:pass
  APP.processEvents();login._state=None;login._required=False;self.transport.stop();self.network.stop();self.screen.stop()
 def window(self):
  w=NS['MainWindow']();w.resize(1280,860);w.show();APP.processEvents();self.windows.append(w);return w
 def test_startup_cancellation_never_initializes_private_workbench(self):
  previous=NS['_name_login_core_main'];NS['_name_login_core_main']=lambda:self.window()
  try:
   with patch.object(login.NameLoginDialog,'exec',return_value=QDialog.DialogCode.Rejected):
    self.assertIsNone(NS['main']());self.assertEqual(self.windows,[])
   def accepted(dialog):dialog.value=person('普通测试人员');return QDialog.DialogCode.Accepted
   with patch.object(login.NameLoginDialog,'exec',accepted):w=NS['main']()
   self.assertEqual(w._name_user_id,person('普通测试人员')['person']['user_id'])
   self.assertIn('仅本人报价',w.name_scope_label.text());self.assertTrue(w.quote_scheme_operator_name.isReadOnly())
   self.assertEqual(centre._operator_name(w),'普通测试人员')
  finally:NS['_name_login_core_main']=previous
 def test_real_name_dialog_and_own_all_scope_screens(self):
  def run(worker):worker.succeeded.emit(person('普通测试人员'))
  with patch.object(login.SessionWorker,'run',run):
   d=login.NameLoginDialog('https://offline.invalid',{});d.show();APP.processEvents()
   d.login();self.assertIn('请输入姓名',d.error.text());d.name.setText('普通测试人员')
   d.error.clear();d.grab().save(str(OUT/'name-login.png'));d.enter.click();wait(lambda:d.result()==QDialog.DialogCode.Accepted)
   login.set_session(d.value)
  w=self.window();w.show_section(centre.SCHEME_ROUTE);wait(lambda:not w._quote_scheme_workers);w.grab().save(str(OUT/'scope-own.png'))
  # A distinct new window must start with empty work data for the next person.
  login.set_session(person('姜艳娟',True));admin=self.window();admin.show_section(centre.SCHEME_ROUTE);wait(lambda:not admin._quote_scheme_workers);admin.grab().save(str(OUT/'scope-all.png'))
  self.assertIn('全部报价',admin.name_scope_label.text())
 def test_old_callbacks_and_request_headers_are_frozen(self):
  login.set_session(person('张三'));w=self.window();received=[];held=[]
  with patch.object(centre.QuoteSchemeWorker,'start',lambda worker:held.append(worker)):
   worker=centre._run(w,'GET','/api/quote-schemes',None,received.append)
  before=dict(worker.headers);login.set_session(person('李四'))
  worker.succeeded.emit(dict(items=['old-private-value']));worker.finished.emit();APP.processEvents()
  self.assertEqual(received,[]);self.assertEqual(worker.headers,before)
  self.assertNotEqual(ui._order_workspace_cache_dir('same'),Path(TEMP.name)/'order-workspaces'/'same')
  self.assertFalse(login.window_is_current(w))
  w.quote_analysis_page.loaded(dict(summary={'quoted':999},product_filter_mode='family-v1'))
  self.assertIsNone(w.quote_analysis_page.data)
 def test_switch_clears_old_data_and_does_not_adopt_pending_exports(self):
  a,b=person('张三'),person('李四');login.set_session(a);w=self.window()
  first_cache=ui._order_workspace_cache_dir('same')
  w._quote_scheme_pending_export={'frozen':'synthetic'}
  def blocked(dialog):
   self.assertEqual(dialog.expected_user,a['person']['user_id']);return QDialog.DialogCode.Rejected
  with patch.object(login.NameLoginDialog,'exec',blocked),patch.object(QMessageBox,'information'):
   login.switch_or_renew(w,NS)
  self.assertEqual(login.user_id(),a['person']['user_id']);w._quote_scheme_pending_export=None
  w._scheme2_dirty=False;w._quote_scheme_dirty_seq=w._quote_scheme_saved_seq=0
  w.draft_items=[{'name':'原人员私有测试数据'}]
  def accepted(dialog):dialog.value=b;return QDialog.DialogCode.Accepted
  def logout(worker):
   self.assertEqual(worker.headers['Authorization'],'Bearer '+a['token']);worker.succeeded.emit({'logged_out':True})
  with patch.object(login.NameLoginDialog,'exec',accepted),patch.object(login.SessionWorker,'run',logout):
   login.switch_or_renew(w,NS);wait(lambda:login.user_id()==b['person']['user_id'])
   wait(lambda:hasattr(APP,'_name_main_window'))
  replacement=APP._name_main_window;self.windows.append(replacement)
  self.assertEqual(replacement.draft_items,[]);self.assertEqual(replacement.quote_management.state['versions'],[])
  self.assertNotEqual(first_cache,ui._order_workspace_cache_dir('same'))
 def test_same_identity_renewal_preserves_frozen_export_and_epoch(self):
  a=person('张三');login.set_session(a);w=self.window();epoch=login.identity_epoch()
  receipt={'person':w._name_user_id,'path':'synthetic-local.xlsx'};w._quote_scheme_pending_export=deepcopy(receipt)
  renewed=deepcopy(a);renewed['token']='R'*43
  def accept(dialog):
   self.assertEqual(dialog.expected_user,a['person']['user_id']);dialog.value=renewed;return QDialog.DialogCode.Accepted
  with patch.object(login.NameLoginDialog,'exec',accept),patch.object(QMessageBox,'information'):
   login.switch_or_renew(w,NS)
  self.assertEqual(login.identity_epoch(),epoch);self.assertEqual(w._quote_scheme_pending_export,receipt)
  w._quote_scheme_pending_export=None
 def test_foreign_quote_stays_readonly_after_cancelled_new_scheme(self):
  login.set_session(person('姜艳娟',True));w=self.window()
  centre._apply_opened_scheme(w,dict(scheme_no='BJ-20261022-000001',status='DRAFT',lock_version=1,
   can_write=False,snapshot=dict(company='他人测试客户',draft_items=[],quote_management={})),2)
  self.assertTrue(w._quote_scheme_read_only);self.assertTrue(w._name_scope_foreign)
  with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):centre._new_scheme(w)
  self.assertTrue(w._name_scope_foreign)
  centre._apply_read_only(w,False);self.assertTrue(w._quote_scheme_read_only)
  with patch.object(QMessageBox,'information'):
   self.assertFalse(centre._prepare_export(w))
  w.quote_management.status_changed();self.assertFalse(w.scheme2_quote_export.isEnabled())
  centre._list_loaded(w,dict(items=[dict(scheme_no='BJ-20261022-000001',company_name='他人测试客户',status='DRAFT',quoted_amount=100,
   creator_name='李四',last_editor_name='姜艳娟',can_write=False)],total=1,page=1,page_size=10))
  self.assertEqual(w.quote_scheme_table.item(0,6).text(),'—')
  w._name_scope_foreign=False;centre._apply_read_only(w,False)
  ui._apply_order_workspace_payload(w,dict(company='只读测试缓存',draft_items=[],_name_workspace_scope=dict(owner_user_id=person('李四')['person']['user_id'],read_only=True)),'本机合成测试')
  self.assertTrue(w._name_scope_foreign);self.assertTrue(w._quote_scheme_read_only)
 def test_runtime_api_worker_keeps_original_token(self):
  a=person('张三');login.set_session(a);w=self.window()
  worker=NS['ApiWorker']('https://offline.invalid/api/orders/workspace/load',{'order_number':'synthetic'},w)
  login.set_session(person('李四'))
  response=Mock();response.__enter__=lambda _:response;response.__exit__=lambda *args:None
  response.read.return_value=b'{"found":false}'
  with patch('urllib.request.urlopen',return_value=response) as transport:worker.run()
  self.assertEqual(transport.call_args.args[0].get_header('Authorization'),'Bearer '+a['token'])
 def test_explicit_logout_waits_for_acknowledgement_then_returns_to_empty_login(self):
  a=person('张三');login.set_session(a);w=self.window();w._scheme2_dirty=False
  w._quote_scheme_dirty_seq=w._quote_scheme_saved_seq=0
  def revoked(worker):
   self.assertEqual(worker.headers['Authorization'],'Bearer '+a['token']);worker.succeeded.emit({'logged_out':True})
  with patch.object(login.SessionWorker,'run',revoked),patch.object(login.NameLoginDialog,'exec',return_value=QDialog.DialogCode.Rejected):
   login.logout(w,NS);self.assertFalse(w.isEnabled());wait(lambda:login.session() is None)
  self.assertTrue(w._name_session_closed)

 def test_canonical_owner_revision_ignores_stale_local_readonly_scope(self):
  login.set_session(person('戴晨丽',True));w=self.window()
  snapshot=dict(company='本机合成客户',draft_items=[],quote_management={},
   _name_workspace_scope=dict(owner_user_id=person('旧本机身份')['person']['user_id'],read_only=True))
  centre._apply_opened_scheme(w,dict(scheme_no='BJ-20261023-999999',status='REVISING',lock_version=1,can_write=True,snapshot=snapshot),3)
  self.assertFalse(w._name_scope_foreign);self.assertFalse(w._quote_scheme_read_only)
  # Directly restoring the same untrusted local workspace stays read-only.
  ui._apply_order_workspace_payload(w,snapshot,'本机合成缓存')
  self.assertTrue(w._name_scope_foreign);self.assertTrue(w._quote_scheme_read_only)

 def test_null_legacy_permission_is_readonly_for_a_logged_in_name(self):
  login.set_session(person('戴晨丽',True));w=self.window()
  centre._apply_opened_scheme(w,dict(scheme_no='BJ-20261023-999998',status='REVISING',lock_version=1,can_write=None,
   snapshot=dict(company='本机合成客户',draft_items=[],quote_management={})),3)
  self.assertTrue(w._name_scope_foreign);self.assertTrue(w._quote_scheme_read_only)

 def test_three_managers_open_foreign_revision_using_server_write_permission(self):
  for name in ['戴晨丽','姜艳娟','翟晓峰']:
   with self.subTest(name=name):
    login.set_session(person(name,True,True));w=self.window()
    self.assertIn('全部报价 · 可操作',w.name_scope_label.text())
    centre._apply_opened_scheme(w,dict(scheme_no='BJ-20261023-999997',status='REVISING',lock_version=1,can_write=True,
     creator_user_id=person('原始本机创建人')['person']['user_id'],snapshot=dict(company='本机合成客户',draft_items=[],quote_management={})),3)
    self.assertFalse(w._name_scope_foreign);self.assertFalse(w._quote_scheme_read_only)

if __name__=='__main__':unittest.main(verbosity=2)
