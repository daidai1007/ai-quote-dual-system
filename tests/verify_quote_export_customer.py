"""Actual V3 export controller: visible buyer, file name, XLSX and frozen receipt.

Only synthetic customers and loopback-free API fixtures; Node renders real XLSX.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import verify_quote_scheme_export_registration as registration
from verify_quote_document_progress import app, wait, ui, QTimer, QFileDialog, ExportWorker
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QComboBox
import quote_scheme_center as schemes
import quote_management_model as model

ROOT=Path(__file__).resolve().parents[1]
OLD='双子测试旧客户'
NEW='本机新输入测试客户'
EXISTING='本机已有测试客户'


def workbook_cell(path,sheet_name,address):
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as book:
        shared=[]
        if 'xl/sharedStrings.xml' in book.namelist():
            shared=[''.join(node.itertext()) for node in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('s:si',ns)]
        sheets=ET.fromstring(book.read('xl/workbook.xml'))
        sheet=next(node for node in sheets.findall('s:sheets/s:sheet',ns) if node.get('name')==sheet_name)
        rel=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        target=next(node.get('Target') for node in ET.fromstring(book.read('xl/_rels/workbook.xml.rels')) if node.get('Id')==rel)
        xml=ET.fromstring(book.read(target.lstrip('/') if target.startswith('/') else 'xl/'+target))
        cell=xml.find(f'.//s:c[@r="{address}"]',ns)
        value=cell.findtext('s:v',default='',namespaces=ns)
        if cell.get('t')=='s':return shared[int(value)]
        if cell.get('t')=='inlineStr':return ''.join(cell.find('s:is',ns).itertext())
        return value


class ExportCustomer(unittest.TestCase):
    clean_window=registration.ExportRegistration.clean_window
    export=registration.ExportRegistration.export
    posts=registration.ExportRegistration.posts

    def setUp(self):
        registration.ExportRegistration.setUp(self)
        self.m=self.window.quote_management
        self.workbooks=[];self.default_names=[]
        for combo in (self.window.company_combo,self.window.scheme2_company):
            with QSignalBlocker(combo):
                combo.clear();combo.addItem(OLD,'OLD-CODE');combo.addItem(EXISTING,'SECOND-CODE');combo.setCurrentIndex(0)
        self.window.company_catalog=[dict(company_name=OLD,company_code='OLD-CODE'),dict(company_name=EXISTING,company_code='SECOND-CODE')]
        self.m.sync();self.window._quote_scheme_save_timer.stop()

        def choose(_parent,_title,default,*_args):
            self.default_names.append(Path(default).name)
            self.path=Path(self.folder.name)/Path(default).name
            return str(self.path),''

        def render(worker):
            worker.test_running=True
            self.workbooks.append(deepcopy(worker.payload))
            source=Path(self.folder.name)/f'payload-{len(self.workbooks)}.json'
            source.write_text(json.dumps(worker.payload,ensure_ascii=False),encoding='utf-8')
            result=subprocess.run(['node',str(ROOT/'export_dual_quote_workbook.mjs'),str(source),str(worker.output_path)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40)
            def ready():
                worker.test_running=False
                if result.returncode:worker.failed.emit(result.stderr)
                else:worker.succeeded.emit(str(worker.output_path))
                worker.finished.emit()
            QTimer.singleShot(1,ready)

        original=schemes.QuoteSchemeWorker.start
        def server(worker):
            if worker.method!='PUT':return original(worker)
            worker.test_running=True
            self.scheme_requests.append((worker.method,worker.url,deepcopy(worker.payload)))
            self.server.update(snapshot=deepcopy(worker.payload['snapshot']),lock_version=self.server['lock_version']+1)
            def saved():
                worker.test_running=False;worker.succeeded.emit(dict(saved=True,lock_version=self.server['lock_version']));worker.finished.emit()
            QTimer.singleShot(1,saved)
        for p in (patch.object(QFileDialog,'getSaveFileName',choose),patch.object(ExportWorker,'start',render),
                  patch.object(schemes.QuoteSchemeWorker,'start',server)):
            p.start();self.addCleanup(p.stop)

    def type_customer(self,name):
        self.window.scheme2_company.setEditText(name)
        self.window._quote_scheme_save_timer.stop()

    def assert_export_customer(self,name,code):
        self.assertEqual(self.window.scheme2_company.currentText(),name)
        self.assertEqual(self.window.scheme2_quote_preview.item(3,1).text(),name)
        amounts=ui._row_values(self.window.draft_items[0])
        self.export()
        self.assertTrue(self.path.exists(),self.messages)
        self.assertIn(name,self.default_names[-1])
        for url,payload in self.requests:
            if url.endswith(('/confirm-check','/confirm')):
                self.assertEqual(payload['company_name'],name)
                self.assertEqual(payload['company_code'],code)
        self.assertEqual(self.workbooks[-1]['company_name'],name)
        for sheet,cell in [('成本','B4'),('报价','B4'),('成本明细','H2')]:
            self.assertEqual(workbook_cell(self.path,sheet,cell),name,sheet)
        self.assertEqual(float(workbook_cell(self.path,'报价','F11')),float(amounts[15]))
        self.assertEqual(float(workbook_cell(self.path,'报价','G11')),float(amounts[16]))
        self.assertEqual(self.posts()[-1]['snapshot']['company'],name)
        self.assertEqual(self.posts()[-1]['snapshot']['analysis_customer']['customer_name'],name)
        self.assertIn(name,ui._printable_quote_html(self.window))

    def test_typed_customer_replaces_stale_catalogue_identity_in_real_export(self):
        self.type_customer(NEW)
        self.assertEqual(self.window.scheme2_company.currentData(),'OLD-CODE','Reproduce editable-combo stale data')
        self.assert_export_customer(NEW,NEW)
        self.assertNotIn(OLD,self.default_names[-1])
        self.assertNotIn(OLD,ui._printable_quote_html(self.window))

    def test_typing_another_existing_name_resolves_its_own_code(self):
        self.type_customer(EXISTING)
        self.assertEqual(self.window.scheme2_company.currentData(),'OLD-CODE')
        self.assert_export_customer(EXISTING,'SECOND-CODE')

    def test_saved_and_reopened_typed_customer_drives_export_and_print(self):
        self.type_customer(NEW)
        self.m.save();wait(lambda:self.window._quote_scheme_save_worker is None)
        saved=deepcopy(self.server['snapshot'])
        self.assertEqual(saved['company'],NEW)
        self.assertEqual(saved['quote_management']['versions'][-1]['company'],NEW)
        with QSignalBlocker(self.window.scheme2_company):self.window.scheme2_company.setCurrentIndex(0)
        schemes._apply_opened_scheme(self.window,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.window._quote_scheme_save_timer.stop()
        self.assertEqual(self.window.scheme2_company.currentText(),NEW)
        self.assert_export_customer(NEW,NEW)
        self.assertEqual(self.posts()[-1]['snapshot']['quote_management']['versions'][-1]['company'],NEW)

    def test_registration_retry_preserves_exported_customer_and_file(self):
        self.type_customer(NEW);self.registration_error='offline registration failure'
        self.assert_export_customer(NEW,NEW)
        before=self.path.read_bytes();receipt=deepcopy(self.posts()[-1]);requests=deepcopy(self.requests)
        self.type_customer(EXISTING)  # A late programmatic update must not rewrite the frozen receipt.
        self.registration_error=None
        self.controller.feedback['export']['retry'].click()
        wait(lambda:not self.controller.busy and not self.window._quote_scheme_workers)
        self.assertEqual(self.posts()[-1],receipt)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.requests,requests)
        self.assertEqual(len(self.workbooks),1)

    def test_historical_version_exports_its_customer_then_restores_latest(self):
        w=self.window;items=deepcopy(w.draft_items)
        versions=[model.make_version(items,name,i+1,'合成历史版本','测试人员','2026-10-22','EXTERNAL')
                  for i,name in enumerate((OLD,NEW))]
        for version in versions:version['sealed']=True
        w._qm_state=dict(schema=1,current=2,versions=versions)
        w._quote_scheme_status='QUOTED';w._quote_scheme_read_only=True
        w._qm_historical_export_supported=True;self.server['status']='QUOTED'
        self.type_customer(NEW);self.m.view_version(1)
        self.assertEqual(w.scheme2_company.currentText(),OLD)
        self.assert_export_customer(OLD,'OLD-CODE')
        self.assertEqual(self.posts()[-1]['historical_quote_version'],1)
        self.m.restore_latest()
        self.assertEqual(w.scheme2_company.currentText(),NEW)
        ui._sync_export_company(w)
        self.assertEqual(w.company_combo.currentText(),NEW)
        self.assertNotEqual(w.company_combo.currentData(),'OLD-CODE')

    def test_selected_catalogue_blank_and_noneditable_export_selector(self):
        visible,legacy=self.window.scheme2_company,self.window.company_combo
        visible.setCurrentIndex(1);ui._sync_export_company(self.window)
        self.assertEqual((legacy.currentText(),legacy.currentData()),(EXISTING,'SECOND-CODE'))
        self.type_customer('');ui._sync_export_company(self.window)
        self.assertEqual(legacy.currentText(),'');self.assertIsNone(legacy.currentData())
        legacy.setEditable(False);self.type_customer(NEW);ui._sync_export_company(self.window)
        self.assertEqual(legacy.currentText(),NEW)
        self.assertNotEqual(legacy.currentData(),'OLD-CODE')


if __name__=='__main__':unittest.main()
