"""Native Qt UI + real loopback HTTP transport, only synthetic catalog rows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=str(ROOT/'test-output/attachment-maintenance/private-cache')
sys.path.insert(0,str(ROOT/'desktop_client'))
import hashlib, json, threading, unittest, urllib.request
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog, QDialog, QLabel
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QFontDatabase
import name_login
import attachment_maintenance as maintenance
import v3_launcher

APP=QApplication.instance() or QApplication([])
NS=v3_launcher.load_v3_namespace();Window=NS['MainWindow']
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');NS['install_application_font'](APP)
OUT=ROOT/'test-output/attachment-maintenance';OUT.mkdir(parents=True,exist_ok=True)
def session(name):
    return dict(token='T'*43,expires_at='2030-01-01T00:00:00+00:00',person=dict(display_name=name,
        user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),identity_mode='NAME_ONLY',
        scope='ALL' if name in ('戴晨丽','姜艳娟','翟晓峰') else 'OWN'))
def wait(predicate):
    for _ in range(500):
        APP.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Qt request did not finish')

ROW=dict(attachment_price_id=100,item_name='本地照明灯',model_code='24V-0.6m',unit='件',category_level1='电气附件',category_level2=None,category_level3=None,
 quick_face_price='85.123456',is_active=True,editable=True,rules=[dict(rule_id=20,method='FIXED',fixed_cost='48.125',products=[],materials=[],issues=[])],notes='本地测试',revision_no=1)
FORMULA=dict(attachment_price_id=101,item_name='本地公式附件',model_code='随柜',unit='件',category_level1='钣金附件',quick_face_price='240',is_active=True,editable=False,
 rules=[dict(rule_id=21,method='CALCULATED',fixed_cost=None,products=['JP_SINGLE'],materials=['SECC'],issues=[],formulas={'weight_kg':'宽度*高度*0.000001','material_cost':'材料重量*材质单价','spray_cost':'喷塑面积*喷塑单价','labor_cost':'5'})])

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path.endswith('/history'):body={'items':self.server.logs}
        else:body=dict(items=self.server.rows,products=['JS_SINGLE','JP_SINGLE'],can_maintain=True)
        self.reply(body)
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.server.posts.append(data)
        if self.server.error:self.reply({'message':self.server.error},409);return
        if data['action']=='CREATE':
            row=dict(data['item'],attachment_price_id=200+len(self.server.posts),editable=True,is_active=True,
                rules=[dict(rule_id=200,method='FIXED',fixed_cost=data['cost_rules'][0]['fixed_cost'],products=data['products'],materials=[],issues=[])])
            self.server.rows.append(row)
        else:
            row=next(x for x in self.server.rows if x['attachment_price_id']==data['attachment_price_id'])
            old=deepcopy(row)
            if data['action']=='EDIT':
                row.update(data['item'])
                for saved,changed in zip(row['rules'],data['cost_rules']):saved['fixed_cost']=changed['fixed_cost']
            else:row['is_active']=data['action']=='ENABLE'
            self.server.logs.insert(0,dict(created_at='2026-11-03 10:00',actor_name='戴晨丽',action=data['action'],reason=data['reason'],before_state={'item':old,'rules':old['rules']},after_state={'item':row,'rules':row['rules']}))
        self.reply(dict(saved=True,attachment_price_id=row['attachment_price_id']))
    def reply(self,body,status=200):
        raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class AttachmentMaintenanceUI(unittest.TestCase):
    def setUp(self):
        name_login.set_session(session('戴晨丽'))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.rows=deepcopy([ROW,FORMULA]);self.server.posts=[];self.server.logs=[];self.server.error=None
        threading.Thread(target=self.server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{self.server.server_port}'
        original=urllib.request.urlopen
        def local_only(request,*a,**kw):
            url=request.full_url if hasattr(request,'full_url') else str(request)
            if not url.startswith(base+'/'):raise AssertionError('Non-test network blocked')
            return original(request,*a,**kw)
        self.network=patch('urllib.request.urlopen',local_only);self.network.start()
        import client_update_ui
        screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        self.patches=[patch.object(Window,'screen',return_value=screen),patch.object(Window,'load_catalogs',lambda *_:None),patch.object(Window,'refresh_formula_inputs',lambda *_:None),patch.object(NS['ApiWorker'],'start',lambda *_:None),patch.object(client_update_ui,'UpdateController',lambda *_:None)]
        for p in self.patches:p.start()
        self.w=Window();self.w.base_url=lambda:base;self.w._quote_scheme_headers_factory=lambda:{'Authorization':'Bearer '+'T'*43}
        self.w._quote_scheme_save_timer.stop();self.w._history_price_timer.stop();self.page=self.w.attachment_maintenance
        self.w.resize(1440,940);self.w.show();self.w.show_section(self.w.attachment_maintenance_route);wait(lambda:self.page.worker is None)
        self.assertTrue(self.page.ready,self.page.notice.text())
        self.addCleanup(self.clean)
    def clean(self):
        wait(lambda:self.page.worker is None);self.page.unsaved=False;self.w.draft_items=[]
        self.network.stop();self.w.hide();self.w.deleteLater();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.server.shutdown();self.server.server_close()
    def image(self,name):
        APP.processEvents();self.assertTrue(self.w.grab().save(str(OUT/name)))
    def test_native_list_new_edit_confirmation_reopen_and_history(self):
        self.assertEqual(self.page.table.rowCount(),2);self.image('list.png')
        self.page.edit(self.page.rows[0]);self.page.price.setText('90.123456');self.page.cost_fields[0].setText('52.5');self.page.reason.setText('本机测试调价')
        self.image('edit.png');self.page.prepare_save();self.assertEqual(self.page.pages.currentIndex(),2)
        self.image('confirm.png');QTest.mouseClick(self.page.save_button,Qt.MouseButton.LeftButton);wait(lambda:self.page.worker is None and not self.page.pending_reload)
        self.assertEqual(self.server.posts[-1]['cost_rules'][0]['fixed_cost'],'52.5');self.assertEqual(self.page.rows[0]['quick_face_price'],'90.123456')
        self.page.edit(self.page.rows[0]);self.assertEqual(self.page.cost_fields[0].text(),'52.5');self.page.cancel_edit()
        self.page.set_tab(True);wait(lambda:self.page.worker is None);self.assertEqual(self.page.history_table.rowCount(),1);self.image('history.png')
        self.page.set_tab(False);QTest.mouseClick(self.page.add_button,Qt.MouseButton.LeftButton)
        self.page.fields['item_name'].setText('本地新增风机');self.page.fields['model_code'].setText('LOCAL-FAN');self.page.price.setText('120');self.page.cost_fields[0].setText('60');self.page.reason.setText('本地新增测试')
        self.page.product.setCurrentIndex(2);self.page.prepare_save();self.page.save();wait(lambda:self.page.worker is None and not self.page.pending_reload)
        self.assertEqual(self.server.posts[-1]['products'],['JP_SINGLE']);self.assertEqual(self.page.table.rowCount(),3)
    def test_formula_readonly_filter_state_and_unsaved_guard(self):
        self.page.search.setText('不存在');self.assertEqual(self.page.table.rowCount(),0);self.page.search.clear()
        self.page.inspect(self.page.rows[1]);self.assertEqual(self.page.pages.currentIndex(),3);self.image('formula-readonly.png');self.page.pages.setCurrentIndex(0)
        self.page.edit(self.page.rows[0]);self.page.unsaved=True;self.w.show_section(1)
        self.assertEqual(self.w.stack.currentIndex(),self.w.attachment_maintenance_route)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Discard):self.page.cancel_edit()
        with patch.object(QInputDialog,'getText',return_value=('本地停用测试',True)):self.page.toggle(self.page.rows[0])
        wait(lambda:self.page.worker is None and not self.page.pending_reload);self.assertFalse(self.page.rows[0]['is_active'])
        self.page.status.setCurrentIndex(2);self.assertEqual(self.page.table.rowCount(),1)
    def test_conflict_preserves_form_and_request_id_for_retry(self):
        self.page.edit(self.page.rows[0]);self.page.price.setText('123.45');self.page.reason.setText('测试冲突');self.page.prepare_save();request=self.page.pending['request_id']
        self.server.error='附件已被他人修改，请刷新后重试';self.page.save();wait(lambda:self.page.worker is None)
        self.assertTrue(self.page.unsaved);self.assertEqual(self.page.pending['request_id'],request);self.assertEqual(self.page.price.text(),'123.45');self.assertIn('他人修改',self.page.notice.text())
        self.page.save();wait(lambda:self.page.worker is None);self.assertEqual(self.server.posts[-1]['request_id'],request)
    def test_four_names_and_ordinary_scope(self):
        for name in maintenance.MAINTAINERS:
            name_login.set_session(session(name));self.assertTrue(maintenance.authorized())
        name_login.set_session(session('普通同事'));self.assertFalse(maintenance.authorized());self.page.reload();self.assertFalse(self.page.ready);self.assertEqual(self.page.rows,[])
        name_login.set_session(session('戴晨丽'))
    def test_multiple_fixed_rules_and_zero_cost_are_preserved(self):
        row=deepcopy(ROW);row['rules'][0]['materials']=['SECC'];row['rules'].append(dict(rule_id=25,fixed_cost='80',method='FIXED',products=['JP_SINGLE'],materials=['SUS304']))
        self.page.edit(row);self.page.cost_fields[0].setText('0');self.page.reason.setText('零成本核定');self.page.prepare_save()
        self.assertEqual(self.page.pending['cost_rules'],[{'rule_id':20,'fixed_cost':'0'},{'rule_id':25,'fixed_cost':'80'}]);self.assertNotIn('products',self.page.pending)
    def test_invalid_amounts_and_blank_cost_do_not_submit(self):
        self.page.edit(None);self.page.fields['item_name'].setText('本地附件');self.page.price.setText('50');self.page.reason.setText('测试')
        for value in ('','-1','NaN'):
            self.page.cost_fields[0].setText(value);self.page.prepare_save();self.assertEqual(self.page.pages.currentIndex(),1)
        self.assertEqual(self.server.posts,[])
    def test_picker_add_preserves_uncommitted_selection_and_returns_to_picker(self):
        import layout_refresh
        owner=QDialog(self.w);owner.resize(1024,760);owner.catalog_hint=QLabel(owner);owner.reload_catalog=Mock()
        owner.selected_fixture=[{'attachment_price_id':100,'quantity':3}];original=deepcopy(owner.selected_fixture);owner.show();failures=[]
        def edit():
            try:
                editor=owner._attachment_maintenance_dialog;page=editor.page
                wait(lambda:page.worker is None and page.pages.currentIndex()==1)
                page.fields['item_name'].setText('本地弹窗新增');page.price.setText('10');page.cost_fields[0].setText('5');page.reason.setText('弹窗新增测试');page.prepare_save();page.save()
                wait(lambda:page.worker is None and not page.pending_reload);self.assertFalse(page.unsaved);editor.reject()
            except BaseException as error:
                failures.append(error);owner._attachment_maintenance_dialog.done(0)
        QTimer.singleShot(50,edit);layout_refresh._show_add_attachment_dialog(owner,NS)
        if failures:raise failures[0]
        self.assertTrue(owner.isVisible());self.assertEqual(owner.selected_fixture,original);owner.reload_catalog.assert_not_called();self.assertIn('未改动',owner.catalog_hint.text());owner.hide()
    def test_laptop_layout_keeps_editor_actions_and_list_operations_visible(self):
        self.w.resize(1366,768);APP.processEvents();self.image('laptop-list.png')
        scroll=self.w.findChild(maintenance.QScrollArea,'mainScroll');self.assertEqual(scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(self.page.add_button.isVisible());self.page.edit(self.page.rows[0]);APP.processEvents();self.image('laptop-editor.png')
        self.assertFalse(self.page.advanced.isVisible());self.assertEqual(self.page.pages.currentIndex(),1)

if __name__=='__main__':unittest.main()
