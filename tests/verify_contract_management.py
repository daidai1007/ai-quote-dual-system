"""Real Qt + real HTTP API + disposable PostgreSQL + actual Office preview.
All fixtures are artificial; no service config, production data or client EXE.
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from unittest.mock import patch,Mock
import urllib.request
import urllib.error
from xml.etree import ElementTree as ET
from zipfile import ZipFile

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['PYTHONIOENCODING']='utf-8'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
TEMP=tempfile.TemporaryDirectory(prefix='contract-qt-')
os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=TEMP.name
os.environ['AI_QUOTE_UPDATE_CONFIG']=str(Path(TEMP.name)/'updates.json')
Path(os.environ['AI_QUOTE_UPDATE_CONFIG']).write_text('{}',encoding='utf-8')
from PySide6.QtCore import QSettings,Qt,QRect,QTimer
from PySide6.QtGui import QFontDatabase,QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog
import v3_launcher
import contract_management as ui
import quote_scheme_center as schemes
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,TEMP.name)
APP=QApplication.instance() or QApplication([])
NS=v3_launcher.load_v3_namespace();NS['install_application_font'](APP)
NS['MainWindow'].load_catalogs=lambda self:None
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')


def wait(predicate,timeout=90):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        APP.processEvents()
        if predicate():return
        QTest.qWait(20)
    raise AssertionError('Contract operation timed out')


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(TEMP.name);cls.state=cls.folder/'host.json'
        cls.host_log=open(cls.folder/'host.log','w',encoding='utf-8')
        cls.host=subprocess.Popen([shutil.which('node'),str(ROOT/'tests/helpers/contract_test_host.mjs'),str(cls.state),*getattr(cls,'host_arguments',[])],cwd=ROOT,
            stdin=subprocess.PIPE,stdout=cls.host_log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        until=time.monotonic()+100
        while time.monotonic()<until and not cls.state.is_file() and cls.host.poll() is None:time.sleep(.1)
        if not cls.state.is_file():raise AssertionError('Local contract API host failed: '+(cls.folder/'host.log').read_text(encoding='utf-8')[-1500:])
        cls.config=json.loads(cls.state.read_text(encoding='utf-8'))
        def login(name):
            request=urllib.request.Request(cls.config['base']+'/api/name-login',data=json.dumps({'name':name},ensure_ascii=False).encode('utf-8'),headers={'X-AI-Quote-Key':cls.config['key'],'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)
        cls.config['session']=login('本机人员甲');cls.config['other_session']=login('其他本机人员');cls.config['all_session']=login('姜艳娟')
        cls.real_urlopen=urllib.request.urlopen
        def local_only(request,*args,**kwargs):
            url=request.full_url if hasattr(request,'full_url') else str(request)
            if not url.startswith(cls.config['base']+'/'):raise AssertionError('Non-test network forbidden')
            return cls.real_urlopen(request,*args,**kwargs)
        cls.network=patch('urllib.request.urlopen',side_effect=local_only);cls.network.start()

    @classmethod
    def tearDownClass(cls):
        cls.network.stop()
        if cls.host.poll() is None:cls.host.communicate(b'done\n',timeout=40)
        cls.host_log.close();TEMP.cleanup()

    def api(self,path,payload=None,key=None):
        request=urllib.request.Request(self.config['base']+'/api/contracts'+path,
            data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8'),
            headers={'X-AI-Quote-Key':key or self.config['key'],'Content-Type':'application/json',**({'Authorization':'Bearer '+self.config['session']['token']} if key!='local-shared-test' else {})})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)

    def setUp(self):
        screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        self.screen=patch.object(NS['MainWindow'],'screen',return_value=screen);self.screen.start();self.addCleanup(self.screen.stop)
        import name_login;name_login.set_session(self.config['session'])
        self.window=NS['MainWindow']();self.w=self.window
        self.w.base_url=lambda:self.config['base'];self.w._quote_scheme_headers_factory=lambda:{'X-AI-Quote-Key':self.config['key'],'Authorization':'Bearer '+self.config['session']['token']}
        self.p=self.w.contract_management;self.w._quote_scheme_save_timer.stop();self.w._history_price_timer.stop()
        self.p.check_identity();self.w.resize(1560,960);self.w.show();self.w.show_section(self.w.contract_management_route);self.settled()
        self.p.customer.setCurrentIndex(self.p.customer.findData('LOCAL-A'))
        index=ui.index_of(self.p.source,(self.config['scheme_no'],1));self.assertGreater(index,0,(self.config['scheme_no'],[(self.p.source.itemText(i),repr(self.p.source.itemData(i))) for i in range(self.p.source.count())],self.p.data))
        self.p.source.setCurrentIndex(index)
        self.p.method.setCurrentIndex(self.p.method.findData('QUICK'));self.settled()
        self.addCleanup(self.close_window)

    def settled(self):
        wait(lambda:not self.p.busy and not self.p.queue and not self.p.workers)

    def close_window(self):
        self.settled();self.w._quote_scheme_save_timer.stop();self.w._quote_scheme_dirty_seq=self.w._quote_scheme_saved_seq
        self.p.shutdown();self.w.hide();self.w.deleteLater();APP.processEvents()

    def configure_template(self,format):
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=(str(self.folder/('local-template.'+format)),'')),patch.object(ui.QInputDialog,'getText',return_value=('本机界面合同'+format,True)):
            self.p.upload()
        self.settled();self.assertTrue(any(r['file_format']==format for r in self.p.data['templates']),(self.p.notice.text(),self.p.source.currentData(),self.p.customer.currentData()));row=next(i for i,r in enumerate(self.p.data['templates']) if r['file_format']==format)
        self.p.library.selectRow(row)
        original=ui.MappingDialog.exec
        def configure(dialog):
            if format=='xlsx':dialog.add_field(dict(source='total_amount',target='xl/worksheets/sheet1.xml#G10',find=''))
            dialog.accept();self.assertIsNotNone(dialog.mapping);return QDialog.DialogCode.Accepted
        with patch.object(ui.MappingDialog,'exec',configure):
            self.p.configure_library();self.settled()
        row=next(i for i,r in enumerate(self.p.data['templates']) if r['file_format']==format)
        self.p.library.selectRow(row);self.p.use_template();self.settled()
        self.assertIsNotNone(self.p.mapping,self.p.notice.text());self.assertEqual(self.p.current_quote['total'],650.3)

    def test_01_upload_generate_preview_export_reopen_and_identity(self):
        for format in ('docx','xlsx'):
            with self.subTest(format=format):
                self.configure_template(format)
                for key,value in dict(contract_no='LOCAL-UI-'+format,seller_name='本机测试供方',sign_date='2026-10-22').items():self.p.inputs[key].setText(value)
                self.p.save_draft();self.settled();draft=deepcopy(self.p.draft);self.assertTrue(draft['draft_id'])
                self.p.reload();self.settled();index=self.p.drafts.findData(draft['draft_id']);self.assertGreater(index,0)
                self.p.open_draft(index);self.settled();self.assertEqual(self.p.inputs['contract_no'].text(),'LOCAL-UI-'+format)
                self.assertTrue(self.p.generate_button.isEnabled(),self.p.notice.text())
                self.p.generate_button.click();self.settled()
                self.assertIsNotNone(self.p.output,self.p.notice.text());self.assertGreater(len(self.p.preview_pages),0,self.p.notice.text())
                pictures=[w for w in self.p.tray.findChildren(ui.QLabel) if hasattr(w,'source_pixmap')]
                self.assertTrue(pictures);self.assertGreater(pictures[0].width(),min(600,self.p.preview_scroll.viewport().width()*.8))
                self.assertEqual(self.p.preview_scroll.horizontalScrollBar().maximum(),0)
                original=self.p.output['bytes'];record=deepcopy(self.p.record)
                self.assertEqual(sha256(original).hexdigest(),record['file_sha256'])
                wrong=self.folder/('wrong-'+format+'.txt')
                with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(wrong),'')):self.p.export_file()
                self.assertFalse(wrong.exists())
                exported=self.folder/('output.'+format)
                with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(exported),'')):self.p.export_file()
                self.assertEqual(exported.read_bytes(),original)
                with ZipFile(exported) as package:
                    self.assertIsNone(package.testzip());text=package.read('word/document.xml' if format=='docx' else 'xl/worksheets/sheet1.xml').decode('utf-8')
                    self.assertIn('650.3',text);self.assertIn('本机测试客户 A',text);self.assertIn('500',text)
                artifacts=Path(os.environ.get('AI_QUOTE_CONTRACT_SCREENSHOT_DIR',str(ROOT/'test-output'/'contracts-qa')));artifacts.mkdir(parents=True,exist_ok=True)
                QTest.qWait(100);APP.processEvents();self.w.grab().save(str(artifacts/('实际程序_合同生成_'+format+'.png')))
                shutil.copy(self.p.preview_pages[0],artifacts/('实际文件预览_'+format+'.png'))
                self.p.reload();self.settled();index=next(i for i,r in enumerate(self.p.visible_records) if r['record_id']==record['record_id']);self.p.records.selectRow(index)
                self.p.open_record();self.settled();self.assertEqual(self.p.output['bytes'],original);self.assertTrue(self.p.historical);self.assertFalse(self.p.generate_button.isEnabled())
                self.assertTrue(self.p.inputs['contract_no'].isReadOnly());self.p.new_contract();self.settled()
        # A late response from an old identity cannot populate or expose output.
        import name_login;name_login.set_session(self.config['other_session'])
        self.w._quote_scheme_headers_factory=lambda:{'X-AI-Quote-Key':'local-contract-other','Authorization':'Bearer '+self.config['other_session']['token']};self.p.check_identity();self.assertIsNone(self.p.output);self.assertEqual(self.p.records.rowCount(),0)
        self.p.reload();self.settled();self.assertEqual(self.p.source.count(),1)

    def test_02_api_failure_permissions_and_recovery(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:self.api('/bootstrap',key='local-shared-test')
        self.assertEqual(caught.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.api('/templates',dict(scheme_no=self.config['scheme_no'],version_no=1,customer_code='LOCAL-A',template_name='bad',filename='bad.docx',format='docx',content='YmFk'))
        self.assertEqual(caught.exception.code,400)
        self.assertEqual([b.text() for b in self.w.nav_buttons],['选型配置','成本计算','报价单管理','合同管理','报价方案','报价分析'])
        nav_layout=self.w.scheme2_nav.layout()
        self.assertEqual(sorted(self.w.nav_buttons,key=nav_layout.indexOf),self.w.nav_buttons)
        self.p.tabs.setCurrentIndex(2);self.settled();self.assertEqual(self.p.record_total,2)
        self.p.record_search.setText('LOCAL-UI-docx');self.p.load_records(True);self.settled();self.assertEqual(self.p.records.rowCount(),1)
        self.p.record_search.clear();self.p.load_records(True);self.settled();self.p.tabs.setCurrentIndex(0)
        # Narrow desktop: action row stays within the actual viewport.
        for width,height in ((1560,960),(1366,900),(1092,720),(910,512)):
            self.w.setMinimumSize(0,0);self.w.resize(width,height);QTest.qWait(100);APP.processEvents()
            for control in (self.p.generate_button,self.p.export_button,self.p.save_button):
                self.assertTrue(self.p.rect().contains(control.mapTo(self.p,control.rect().bottomRight())),(width,control.text(),control.geometry(),self.p.size()))
        self.p.busy=True;event=QCloseEvent();self.w.closeEvent(event);self.assertFalse(event.isAccepted());self.p.busy=False

    def test_03_product_to_quote_export_to_contract_export(self):
        # Reuse the established real product-entry / cost / document / renderer
        # regression, retaining its frozen formal snapshot for the contract.
        import verify_quote_analysis_full_workflow as flow
        captured=[];original=flow.reg.ExportRegistration
        def harness():
            result=original();captured.append(result);return result
        case=flow.FullWorkflow('test_product_to_actual_xlsx_with_analysis_installed')
        try:
            with patch.object(flow.reg,'ExportRegistration',harness):case.test_product_to_actual_xlsx_with_analysis_installed()
            snapshot=deepcopy(captured[0].server['snapshot'])
            self.assertEqual(snapshot['contract_quote_snapshot']['items'][0]['quote_display']['unit_price'],175)
            self.assertEqual(snapshot['contract_quote_snapshot']['items'][0]['quote_display']['total'],350)
            with ZipFile(captured[0].path) as book:
                ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};workbook=ET.fromstring(book.read('xl/workbook.xml'));sheet=next(s for s in workbook.findall('s:sheets/s:sheet',ns) if '公式' in s.get('name','') and '报价' in s.get('name',''));rel=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id');rels=ET.fromstring(book.read('xl/_rels/workbook.xml.rels'));target=next(r.get('Target') for r in rels if r.get('Id')==rel);xml=ET.fromstring(book.read(target.lstrip('/') if target.startswith('/') else 'xl/'+target));cells={c.get('r'):c.findtext('s:v',namespaces=ns) for c in xml.findall('.//s:c',ns)};formula_total=float(cells['G11'])
        finally:case.doCleanups()
        def quote_api(path,payload):
            request=urllib.request.Request(self.config['base']+'/api/quote-schemes'+path,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'X-AI-Quote-Key':self.config['key'],'Content-Type':'application/json','Authorization':'Bearer '+self.config['session']['token']})
            with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
        # The calculator is synthetic in this UI regression. Register its
        # artificial references in this owned local cluster, as the real
        # calculator does atomically in production. Never bypass HTTP checks.
        refs=set()
        def collect(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('quote_line_id','quote_id') and item:refs.add(('QUOTE_LINE' if key=='quote_line_id' else 'QUOTE_ID',str(item)))
                    collect(item)
            elif isinstance(value,list):
                for item in value:collect(item)
        collect(snapshot);connection=self.config['connection'];literal=lambda value:"convert_from(decode('"+str(value).encode('utf-8').hex()+"','hex'),'UTF8')"
        sql=''.join(f"INSERT INTO calc.quote_name_owner(resource_kind,resource_key,owner_user_id,confirmed_by_name,mapping_source) VALUES({literal(kind)},{literal(key)},{literal(self.config['session']['person']['user_id'])},'LOCAL FIXTURE','SESSION_CREATED') ON CONFLICT DO NOTHING;" for kind,key in refs)
        if sql:
            done=subprocess.run([connection['psql'],'-X','-w','-h','127.0.0.1','-p',str(connection['port']),'-U',connection['user'],'-d','postgres','-v','ON_ERROR_STOP=1'],input=sql,capture_output=True,text=True,encoding='utf-8',timeout=20);self.assertEqual(done.returncode,0,done.stderr)
        created=quote_api('',dict(snapshot=snapshot,operator_name='本机人员甲'))
        quote_api('/'+created['scheme_no']+'/export-result',dict(snapshot=snapshot,operator_name='本机人员甲',kind='XLSX',succeeded=True,expected_version=1))
        uploaded=self.api('/templates',dict(scheme_no=created['scheme_no'],version_no=1,customer_code='LOCAL-CUSTOMER',template_name='填产品至合同全链路',filename='local.docx',format='docx',content=__import__('base64').b64encode((self.folder/'local-template.docx').read_bytes()).decode('ascii')))
        inspect=self.api('/templates/'+str(uploaded['template_version_id']))
        configured=self.api('/templates/'+str(uploaded['template_version_id'])+'/configure',dict(expected_version=1,mapping=inspect['inspection']['suggested']))
        self.p.reload();self.settled();self.p.customer.setCurrentIndex(self.p.customer.findData('LOCAL-CUSTOMER'))
        self.p.source.setCurrentIndex(ui.index_of(self.p.source,(created['scheme_no'],1)));self.p.method.setCurrentIndex(self.p.method.findData('QUICK'));self.settled()
        self.p.template.setCurrentIndex(self.p.template.findData(configured['template_version_id']));self.settled()
        for key,value in dict(contract_no='LOCAL-FULL-FLOW',seller_name='本机测试供方',sign_date='2026-10-22').items():self.p.inputs[key].setText(value)
        self.p.generate();self.settled();self.assertIsNotNone(self.p.output,self.p.notice.text())
        self.assertEqual(self.p.record['generation_snapshot']['quote']['total'],350)
        output=self.folder/'full-flow-contract.docx'
        with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(output),'')):self.p.export_file()
        with ZipFile(output) as package:
            text=package.read('word/document.xml').decode('utf-8');self.assertIn('175.00',text);self.assertIn('350.00',text);self.assertIn('叁佰伍拾元整',text)
        self.p.method.setCurrentIndex(self.p.method.findData('FORMULA'));self.settled();self.p.generate();self.settled();self.assertEqual(self.p.record['generation_snapshot']['quote']['total'],formula_total)

    def test_04_three_global_names_generate_foreign_quote_word_excel(self):
        import name_login
        for format in ('docx','xlsx'):
            if not any(r['file_format']==format and r['customer_code']=='LOCAL-A' and r['configured'] for r in self.p.data['templates']):self.configure_template(format)
        self.close_window()
        for name in ('戴晨丽','姜艳娟','翟晓峰'):
            request=urllib.request.Request(self.config['base']+'/api/name-login',data=json.dumps({'name':name},ensure_ascii=False).encode('utf-8'),headers={'X-AI-Quote-Key':self.config['key'],'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=20) as response:session=json.load(response)
            self.assertTrue(session['person']['can_manage_all_quotes']);name_login.set_session(session)
            self.w=NS['MainWindow']();self.w.base_url=lambda:self.config['base'];self.w._quote_scheme_headers_factory=lambda s=session:{'X-AI-Quote-Key':self.config['key'],'Authorization':'Bearer '+s['token']}
            self.p=self.w.contract_management;self.w._quote_scheme_save_timer.stop();self.w._history_price_timer.stop();self.w.resize(1560,960);self.w.show();self.w.show_section(self.w.contract_management_route);self.settled()
            self.p.customer.setCurrentIndex(self.p.customer.findData('LOCAL-A'));self.p.source.setCurrentIndex(ui.index_of(self.p.source,(self.config['scheme_no'],1)));self.settled()
            self.assertIn('全部报价 · 可操作',self.w.name_scope_label.text())
            for format in ('docx','xlsx'):
                with self.subTest(name=name,format=format):
                    row=next(i for i,r in enumerate(self.p.data['templates']) if r['file_format']==format and r['customer_code']=='LOCAL-A')
                    template=self.p.data['templates'][row];self.assertFalse(template['can_write']);self.assertTrue(template['can_use']);self.p.library.selectRow(row);self.p.use_template();self.settled()
                    self.p.method.setCurrentIndex(self.p.method.findData('QUICK'));self.settled()
                    for key,value in dict(contract_no='GLOBAL-'+name+'-'+format,seller_name='本机测试供方',sign_date='2026-10-23').items():self.p.inputs[key].setText(value)
                    self.p.save_draft();self.settled();self.p.generate();self.settled();self.assertIsNotNone(self.p.output,self.p.notice.text());self.assertTrue(self.p.preview_pages,self.p.notice.text())
                    self.assertEqual(self.p.record['generation_snapshot']['quote']['total'],650.3)
                    target=self.folder/('global-'+name+'.'+format)
                    with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(target),'')):self.p.export_file()
                    self.assertEqual(sha256(target.read_bytes()).hexdigest(),self.p.record['file_sha256'])
                    self.p.new_contract();self.settled()
            if name!='翟晓峰':self.close_window()

if __name__=='__main__':unittest.main(verbosity=2)
