"""Fill product -> real Qt add -> cost -> document -> actual Node XLSX.

Calculation and confirmation/registration transports return synthetic local
responses. The UI, frozen export payload and production Excel renderer run.
No online API or installed user files are accessed.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import verify_quote_scheme_export_registration as reg
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from quote_request_context import stamp_quote_response
import scheme2_ui as ui

ROOT=Path(__file__).resolve().parents[1]

def wait(predicate):
    until=time.monotonic()+20
    while time.monotonic()<until:
        reg.app.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Full quotation workflow did not finish')

class FullWorkflow(unittest.TestCase):
    def test_product_to_actual_xlsx_with_analysis_installed(self):
        harness=reg.ExportRegistration()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        w=harness.window
        w._quote_scheme_loading=True
        w.request_history_match=lambda *_:None
        w.draft_items=[]
        w.current_result=None
        w.product_catalog={'JQ':{'method':'experience','codes':{'SINGLE':'JQ_EXP'}}}
        w.product_combo.blockSignals(True)
        w.product_combo.clear();w.product_combo.addItem('请选择产品',None);w.product_combo.addItem('JQ','JQ')
        w.product_combo.setCurrentIndex(1);w.product_combo.blockSignals(False)
        w.material_combo.blockSignals(True)
        w.material_combo.clear();w.material_combo.addItem('镀锌板','SECC');w.material_combo.blockSignals(False)
        w.width_spin.setValue(800);w.depth_spin.setValue(600);w.height_spin.setValue(1800)
        w.quote_spec_edit.setText('800*600*1800')
        w.quantity_spin.setValue(2)
        w.scheme2_name_edit.setText('本机分析回归柜')
        w.scheme2_company.setEditText('本机回归客户')
        w.company_catalog=[{'company_name':'本机回归客户','company_code':'LOCAL-CUSTOMER'}]
        w.attachments=[]
        w._history_price_timer.stop()
        w._quote_scheme_save_timer.stop()
        requests=[]
        old_start=reg.base.Worker.start
        def calculate(worker):
            if worker.test_url.endswith('/calculate-dual'):
                p=deepcopy(worker.test_payload);requests.append(p)
                worker.test_running=True
                value=dict(quote_id=p['quote_id'],formula_cost=dict(material_cost=80,auxiliary_cost=10,labor_cost=20,
                    attachment_fee=0,spray_cost=10,management_fee=7.2,total_cost=127.2,product_area_m2=4,
                    corrected_material_weight_kg=20),quick_quote=dict(base_price=200,attachment_fee=0,total_cost=200),
                    attachments=[],attachment_contract=2,quote_line_id='11111111-1111-4111-8111-111111111111',risk_flags=[])
                def respond():
                    worker.test_running=False
                    worker.succeeded.emit(stamp_quote_response(worker,value));worker.finished.emit()
                QTimer.singleShot(10,respond)
            elif worker.test_url.endswith('/match'):
                QTimer.singleShot(0,lambda:(worker.succeeded.emit({'found':False}),worker.finished.emit()))
            else:old_start(worker)
        with patch.object(reg.base.Worker,'start',calculate):
            w.show_section(ui.OPTION_ROUTE)
            w.scheme2_add_button.click()
            wait(lambda:bool(w.draft_items) or w.scheme2_add_button.text()=='重试')
        self.assertEqual(len(w.draft_items),1,(harness.messages,w.risk_label.text()))
        self.assertEqual(requests[0]['width_mm'],800)
        self.assertEqual(requests[0]['depth_mm'],600)
        self.assertEqual(requests[0]['height_mm'],1800)
        self.assertEqual(requests[0]['material_code'],'SECC')
        self.assertEqual(w.draft_items[0]['quantity'],2)
        # Explicit synthetic sales inputs: 200 * .85 + 5 freight = 175 per
        # unit; quantity 2 gives 350. The new analysis must not alter this.
        w.draft_items[0]['quick_discount']=.85
        w.draft_items[0]['freight_fee']=5
        w.refresh_summary()
        w._quote_scheme_loading=False
        w._quote_scheme_save_timer.stop()
        w.show_section(ui.COST_ROUTE)
        w.scheme2_cost_generate.click()
        wait(lambda:not harness.controller.busy)
        self.assertEqual(w.stack.currentIndex(),ui.QUOTE_ROUTE)
        visible_unit=w.scheme2_quote_preview.item(10,5).text().replace(',','')
        visible_total=w.scheme2_quote_preview.item(10,6).text().replace(',','')
        self.assertEqual(float(visible_unit),175)
        self.assertEqual(float(visible_total),350)
        frozen=ui._quote_export_items_snapshot(w)
        self.assertEqual(frozen[0]['quote_display']['total'],350)
        self.assertIn('350.00',ui._printable_quote_html(w))
        exported=[]
        def render(output_path,payload):
            exported.append(deepcopy(payload))
            source=Path(harness.folder.name)/'synthetic-quote-input.json'
            source.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            completed=subprocess.run([shutil.which('node'),str(ROOT/'export_dual_quote_workbook.mjs'),str(source),str(output_path)],
                                     cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            if completed.returncode:raise RuntimeError(completed.stderr)
        def real_start(worker):
            worker.test_running=True
            worker.finished.connect(lambda:setattr(worker,'test_running',False))
            QThread.start(worker)
        with patch.object(w,'export_workbook',render),patch.object(reg.base.ExportWorker,'start',real_start):
            harness.controller.export()
            wait(lambda:not harness.controller.busy and not w._quote_scheme_workers)
        self.assertTrue(harness.path.is_file(),harness.messages)
        self.assertEqual(w._quote_scheme_status,'QUOTED')
        self.assertTrue(w._quote_scheme_read_only)
        self.assertEqual(exported[0]['items'][0]['quote_display']['total'],350)
        saved=harness.server['snapshot']
        self.assertEqual(saved['scheme_summary']['quoted_amount'],350)
        self.assertEqual(saved['analysis_customer']['customer_code'],'LOCAL-CUSTOMER')
        with ZipFile(harness.path) as package:
            self.assertIsNone(package.testzip())
            self.assertIn('[Content_Types].xml',package.namelist())
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            book=ET.fromstring(package.read('xl/workbook.xml'))
            quick=next(s for s in book.findall('s:sheets/s:sheet',ns) if s.get('name')=='快速报价单')
            rel=quick.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            relations=ET.fromstring(package.read('xl/_rels/workbook.xml.rels'))
            target=next(r.get('Target') for r in relations if r.get('Id')==rel)
            sheet=ET.fromstring(package.read(target.lstrip('/') if target.startswith('/') else 'xl/'+target))
            values={cell.get('r'):cell.findtext('s:v',namespaces=ns) for cell in sheet.findall('.//s:c',ns)}
            # The production renderer freezes the same face price and total;
            # these are actual XLSX cells, not a placeholder ZIP file.
            self.assertEqual(float(values['F11']),175)
            self.assertEqual(float(values['G11']),350)
        before=deepcopy(w.draft_items)
        from quote_analysis import AnalysisWorker
        def analysis_start(worker):
            QTimer.singleShot(0,lambda:(worker.failed.emit('离线回归：分析服务尚未部署'),worker.finished.emit()))
        with patch.object(AnalysisWorker,'start',analysis_start):
            w.show_section(w.quote_analysis_route);wait(lambda:w.quote_analysis_page.worker is None)
        self.assertEqual(w.draft_items,before)
        self.assertIn('350.00',ui._printable_quote_html(w))
        # Reopen the registered, frozen formal quote through the existing
        # restore path and compare the visible, print and next-export values.
        import quote_scheme_center as schemes
        schemes._apply_opened_scheme(w,dict(harness.server,snapshot=deepcopy(saved),version_no=1),route=ui.QUOTE_ROUTE)
        self.assertEqual(float(w.scheme2_quote_preview.item(10,5).text().replace(',','')),175)
        self.assertEqual(float(w.scheme2_quote_preview.item(10,6).text().replace(',','')),350)
        self.assertEqual(ui._quote_export_items_snapshot(w)[0]['quote_display']['total'],350)
        self.assertIn('350.00',ui._printable_quote_html(w))
        w.company_catalog=[]
        self.assertEqual(schemes._snapshot(w)['analysis_customer']['customer_code'],'LOCAL-CUSTOMER')

if __name__=='__main__':unittest.main(verbosity=2)
