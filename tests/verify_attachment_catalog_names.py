"""Real picker and authenticated GET on synthetic loopback HTTP; no production access."""
from pathlib import Path
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtCore import QRect, QSettings, QThread, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QWidget
from PySide6.QtTest import QTest
import name_login
import scheme2_ui as ui
import v3_launcher
from attachment_v2_client import match_catalog_attachment

PLASTIC=json.loads((ROOT/'tests/fixtures/plastic_nameplate.json').read_text(encoding='utf8'))
APP=QApplication.instance() or QApplication([])

def identity(name):
    return dict(token='T'*43,person=dict(user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),
        display_name=name,identity_mode='NAME_ONLY',scope='OWN'))

def wait(predicate):
    end=time.monotonic()+8
    while time.monotonic()<end:
        APP.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Picker request did not complete')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        self.server.calls.append((self.command,self.path,self.headers.get('Authorization')))
        self.server.started.set()
        self.server.release.wait(6)
        if self.path!='/api/attachments/catalog?v=2':
            status,body=404,dict(message='Unexpected synthetic endpoint')
        elif self.server.error:
            status,body=503,dict(message='Synthetic catalogue unavailable')
        else:
            status,body=200,deepcopy(self.server.body)
        data=json.dumps(body,ensure_ascii=False).encode('utf8')
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

class CatalogNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=ROOT/'.codex-tmp';folder.mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='catalog-names-',dir=folder)
        cls.env=patch.dict(os.environ,{'LOCALAPPDATA':cls.temp.name,'AI_QUOTE_ORDER_CACHE_ROOT':cls.temp.name,
            'AI_QUOTE_API_KEY':'synthetic-only','AI_QUOTE_V3_CORE_ROOT':str(ROOT/'desktop_client/v3_core')})
        cls.env.start()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,cls.temp.name)
        cls.ns=v3_launcher.load_v3_namespace()
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        cls.ns['install_application_font'](APP)
    @classmethod
    def tearDownClass(cls):
        cls.env.stop();cls.temp.cleanup()
    def setUp(self):
        name_login._required=False;name_login.set_session(identity('合成目录测试'))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.calls=[];self.server.body=dict(items=[deepcopy(PLASTIC)],data_version=PLASTIC['data_version'])
        self.server.error=False;self.server.started=threading.Event();self.server.release=threading.Event();self.server.release.set()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def local_only(request,*args,**kwargs):
            self.assertTrue(request.full_url.startswith(self.base+'/'),'External network forbidden')
            return opener.open(request,*args,**kwargs)
        self.network=patch('urllib.request.urlopen',side_effect=local_only);self.network.start()
        self.owner=QWidget();self.owner._name_user_id=name_login.user_id()
        self.owner._scheme2_api_worker_class=self.ns['ApiWorker']
        self.owner.base_url=lambda:self.base+'/api/quotes/calculate-dual'
        self.owner.selected_product_code=lambda:'JP_SINGLE'
        self.owner.material_combo=QComboBox(self.owner);self.owner.material_combo.addItem('碳钢','SECC')
        self.owner._attachment_catalog_cache=[]
        self.owner.attachments=[dict(item_name='旧附件',quantity=3,formula_amount=12,quick_amount=20)]
        self.before=deepcopy(self.owner.attachments);self.dialogs=[];self.windows=[]
    def tearDown(self):
        self.server.release.set()
        for worker in self.owner.findChildren(QThread):worker.wait(10000)
        APP.processEvents()
        for dialog in self.dialogs:
            if not dialog._catalog_closed:dialog.reject()
            dialog.deleteLater()
        for window in self.windows:
            for worker in window.findChildren(QThread):worker.wait(10000)
            APP.processEvents();window._scheme2_dirty=False;window.close();window.deleteLater()
        self.owner.deleteLater();APP.processEvents();self.network.stop()
        self.server.shutdown();self.server.server_close();self.thread.join(5)
    def dialog(self,selected=None):
        d=ui._SchemeAttachmentDialog(selected or [],'JP',self.owner)
        self.dialogs.append(d);d.resize(660,700);d.show();APP.processEvents()
        return d
    def reload(self,d):
        d.reload_catalog();wait(lambda:d._catalog_worker is None)
    def test_live_name_only_picker_matches_database_id_without_custom_price_or_quantity(self):
        d=self.dialog();self.assertEqual(d.category_combos['其他附件'].findText('塑料标牌'),-1)
        self.reload(d);combo=d.category_combos['其他附件'];index=combo.findText('塑料标牌')
        self.assertGreater(index,0);combo.toggle_row(index)
        selected=d.collect_attachments();self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['quantity'],1);self.assertNotIn('custom',selected[0]);self.assertNotIn('price',selected[0])
        matched=match_catalog_attachment(selected[0],self.owner._attachment_catalog_cache,product_code='JP_SINGLE')
        self.assertEqual(matched['attachment_price_id'],1238);self.assertEqual(matched['price'],2)
        self.assertEqual(matched['rules'][0]['fixed_cost'],1.6)
        self.assertEqual(self.server.calls,[('GET','/api/attachments/catalog?v=2','Bearer '+'T'*43)])
        self.assertEqual(self.owner.attachments,self.before)
        out=Path(os.environ.get('AI_QUOTE_CATALOG_NAMES_SCREENSHOT_DIR',ROOT/'outputs/catalog-names-screenshots'))
        out.mkdir(parents=True,exist_ok=True);d.search_edit.setText('塑料标牌');combo.showPopup();APP.processEvents()
        self.assertTrue(d.grab().save(str(out/'plastic-nameplate-picker.png')));combo.hidePopup()
    def test_cache_supplies_names_without_network_and_reopen_retains_the_selection(self):
        self.owner._attachment_catalog_cache=[deepcopy(PLASTIC)]
        d=self.dialog([dict(item_name='塑料标牌',category_level1='其他附件',quantity=8,formula_amount=12.8)])
        self.assertEqual(d.category_combos['其他附件'].selected_texts(),['塑料标牌'])
        self.assertEqual(self.server.calls,[]);self.assertEqual(self.owner.attachments,self.before)
    def test_actual_v3_open_reads_catalogue_automatically_and_cancel_leaves_order_unchanged(self):
        Window=self.ns['MainWindow']
        import client_update_ui
        screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        with patch.object(Window,'screen',return_value=screen),\
             patch.object(Window,'load_catalogs',lambda *_:None),patch.object(Window,'refresh_formula_inputs',lambda *_:None),\
             patch.object(client_update_ui,'UpdateController',lambda *_:None):
            window=Window();self.windows.append(window)
            window.base_url=self.owner.base_url;window.selected_product_code=lambda:'JP_SINGLE'
            window.product_combo.clear();window.product_combo.addItem('JP','JP_SINGLE')
            window.material_combo.clear();window.material_combo.addItem('碳钢','SECC')
            window.attachments=deepcopy(self.before);window._quote_scheme_save_timer.stop();window._history_price_timer.stop()
            window.resize(1366,768);window.show();APP.processEvents()
            anchor=window.findChild(QScrollArea,'scheme2OptionScroll');self.assertIsNotNone(anchor)
            ui._open_attachment_overlay(window,None,anchor)
            d=window._scheme2_attachment_overlay
            wait(lambda:d._catalog_worker is None)
            self.assertGreater(d.category_combos['其他附件'].findText('塑料标牌'),0)
            d.search_edit.setText('塑料标牌');APP.processEvents()
            combo=d.category_combos['其他附件'];combo.showPopup();APP.processEvents()
            index=combo.model().index(combo.findText('塑料标牌'),0)
            QTest.mouseClick(combo.view().viewport(),Qt.MouseButton.LeftButton,pos=combo.view().visualRect(index).center())
            self.assertEqual(combo.selected_texts(),['塑料标牌'])
            combo._keep_popup_open=False;combo.hidePopup();APP.processEvents()
            self.assertTrue(d.catalog_refresh_button.isVisible())
            self.assertGreaterEqual(d.catalog_refresh_button.width(),d.catalog_refresh_button.sizeHint().width())
            out=Path(os.environ.get('AI_QUOTE_CATALOG_NAMES_SCREENSHOT_DIR',ROOT/'outputs/catalog-names-screenshots'))
            out.mkdir(parents=True,exist_ok=True);self.assertTrue(d.grab().save(str(out/'actual-v3-picker.png')))
            d.reject();APP.processEvents();self.assertEqual(window.attachments,self.before)
    def test_refresh_preserves_uncommitted_other_and_specialist_and_custom_selections(self):
        d=self.dialog([dict(item_name='丝印',category_level1='配置变形'),dict(item_name='旧其他附件',category_level1='其他附件'),
                       dict(item_name='本次人工件',custom=True,quantity=4)])
        before=deepcopy(d.collect_attachments());self.reload(d)
        self.assertEqual(d.collect_attachments(),before);self.assertEqual(self.owner.attachments,self.before)
        self.assertGreater(d.category_combos['其他附件'].findText('塑料标牌'),0)
    def test_error_retry_and_invalid_response_preserve_selection_and_cache(self):
        self.owner._attachment_catalog_cache=[deepcopy(PLASTIC)];d=self.dialog([dict(item_name='塑料标牌',category_level1='其他附件')])
        before=deepcopy(d.collect_attachments());cache=deepcopy(self.owner._attachment_catalog_cache)
        self.server.error=True;self.reload(d)
        self.assertIn('读取失败',d.catalog_status.text());self.assertEqual(d.collect_attachments(),before)
        self.assertEqual(self.owner._attachment_catalog_cache,cache);self.assertTrue(d.catalog_refresh_button.isEnabled())
        self.server.error=False;self.server.body=dict(items='bad',data_version='bad');self.reload(d)
        self.assertIn('读取失败',d.catalog_status.text());self.assertEqual(self.owner._attachment_catalog_cache,cache)
        self.server.body=dict(items=[deepcopy(PLASTIC)],data_version=PLASTIC['data_version']);self.reload(d)
        self.assertIn('已刷新',d.catalog_status.text());self.assertEqual(d.collect_attachments(),before)
    def test_no_duplicate_request_and_closed_dialog_does_not_apply_response(self):
        self.server.release.clear();d=self.dialog();d.reload_catalog();d.reload_catalog()
        wait(self.server.started.is_set);self.assertFalse(d.catalog_refresh_button.isEnabled())
        d.reject();self.server.release.set();wait(lambda:d._catalog_worker is None)
        self.assertEqual(len(self.server.calls),1);self.assertEqual(self.owner._attachment_catalog_cache,[])
    def test_old_identity_response_does_not_enter_new_session_cache(self):
        self.server.release.clear();d=self.dialog();d.reload_catalog();wait(self.server.started.is_set)
        name_login.set_session(identity('另一个合成测试人员'));self.server.release.set();wait(lambda:d._catalog_worker is None)
        self.assertEqual(self.owner._attachment_catalog_cache,[])
        self.assertEqual(d.category_combos['其他附件'].findText('塑料标牌'),-1)
    def test_helper_filters_inactive_product_material_and_wide_without_changing_specialist_options(self):
        restricted=deepcopy(PLASTIC);restricted['item_name']='特定料质标牌'
        restricted['rules'][0].update(products=['JP_WIDE'],materials=['SUS304'])
        inactive=dict(PLASTIC,item_name='停用附件',is_active=False)
        other=dict(PLASTIC,item_name='不属于其他分类',category_level1='风机')
        rows=[deepcopy(PLASTIC),deepcopy(PLASTIC),restricted,inactive,other];before=deepcopy(rows)
        self.assertEqual(ui._catalog_other_attachment_names(rows,'JP_SINGLE','SECC'),['塑料标牌'])
        self.assertEqual(ui._catalog_other_attachment_names(rows,'JP_WIDE','SUS304'),['塑料标牌','特定料质标牌'])
        self.assertEqual(ui._catalog_other_attachment_names(rows,'JP_WIDE','SECC'),['塑料标牌'])
        self.assertEqual(rows,before)
        d=self.dialog();self.reload(d)
        self.assertEqual([d.category_combos['风机'].itemText(i) for i in range(1,d.category_combos['风机'].count())],list(ui.ATTACHMENT_OPTIONS['风机']))

if __name__=='__main__':unittest.main(verbosity=2)
