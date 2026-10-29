"""Actual Qt save/reopen/PDF/XLSX with a real loopback API calculation fixture."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import verify_quote_export_customer as fixture
from verify_quote_document_progress import app, wait, ui
from verify_formula_attachment_allocation_ui import workbook_rows
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader
import quote_scheme_center as schemes
import layout_refresh as client
from attachment_category_browser import parse_base_specification

OUT=Path(os.environ.get('AI_QUOTE_WIDE_SCREENSHOT_DIR',fixture.ROOT/'test-output/wide-labor'))


class WideLaborWorkflow(unittest.TestCase):
    clean_window=fixture.ExportCustomer.clean_window
    export=fixture.ExportCustomer.export
    posts=fixture.ExportCustomer.posts

    @classmethod
    def setUpClass(cls):
        configured=os.environ.get('AI_QUOTE_WIDE_CALCULATION_FIXTURE')
        if configured:
            path=Path(configured)
        else:
            cls.temporary=tempfile.TemporaryDirectory(prefix='wide-labor-calculation-')
            cls.addClassCleanup(cls.temporary.cleanup)
            path=Path(cls.temporary.name)/'calculation.json'
            result=subprocess.run(['node','--test','tests/wide_labor_http.test.mjs'],cwd=fixture.ROOT,
                env={**os.environ,'AI_QUOTE_WIDE_CALCULATION_FIXTURE':str(path)},capture_output=True,text=True,
                encoding='utf-8',timeout=150)
            if result.returncode:raise AssertionError(result.stdout[-3000:]+result.stderr[-1000:])
        cls.calculation=json.loads(path.read_text(encoding='utf-8'))
        assert cls.calculation['result']['formula_cost']['labor_cost']==316.22
        assert cls.calculation['height1800']['result']['formula_cost']['labor_cost']==374.19

    def setUp(self):
        fixture.ExportCustomer.setUp(self);self.w=self.window
        self.load_calculation(self.calculation)

    def load_calculation(self,calculation):
        data=deepcopy(calculation);source,result=data['input'],data['result']
        row=self.w.draft_items[0]
        row.update(source)
        row.update(name='本机合成JS超宽柜',specification=f"1350*400*({source['height_mm']}+200)",quantity=2,
            formula=deepcopy(result['formula_cost']),formula_base=deepcopy(result['formula_cost']),
            quick=deepcopy(result['quick_quote']),attachments=deepcopy(result['attachments']),
            quote_line_id=result['quote_line_id'],attachment_contract=2,attachment_snapshot_dirty=False,
            freight_fee=0,freight_mode='MANUAL',quick_discount=1,formula_discount=1)
        self.w.refresh_summary();self.m.show_detail();self.w._quote_scheme_save_timer.stop()
        self.w.resize(1519,987);self.w.show();app.processEvents()

    def test_screenshot_dimensions_save_reopen_print_export_and_margin_keep_the_same_labor(self):
        self.check_workflow(1250,316.22)

    def test_screenshot_1800_body_and_200_base_keeps_same_amount_through_workflow(self):
        self.load_calculation(self.calculation['height1800'])
        self.check_workflow(1800,374.19)

    def check_workflow(self,height,labor_cost):
        specification=f'1350*400*({height}+200)'
        self.assertEqual(parse_base_specification(specification),(1350,height,400,200))
        self.assertEqual(client._parse_specification_dimensions(specification),(1350,height,400))
        self.w.show_section(ui.COST_ROUTE);self.w.summary_table.selectRow(0);app.processEvents()
        self.assertEqual(self.w.summary_table.item(0,15).text(),f'{labor_cost:.2f}')
        before=ui._row_values(self.w.draft_items[0]);before_margin=self.w.summary_table.item(0,21).text()
        self.controller.generate();wait(lambda:not self.controller.busy)
        self.assertFalse(self.messages,self.messages)
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        saved=self.server['snapshot']['draft_items'][0]
        self.assertEqual(saved['formula']['labor_cost'],labor_cost)
        self.assertEqual(saved['formula']['labor_reference_model_code'],'JS131860')
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(ui._row_values(self.w.draft_items[0]),before)
        self.assertEqual(self.w.summary_table.item(0,21).text(),before_margin)
        self.export();self.assertTrue(self.path.exists(),self.messages)
        rows=workbook_rows(self.path,'成本明细')
        labor=[row for row in rows if any('柜体人工成本' in str(v) for v in row.values())]
        self.assertTrue(labor)
        self.assertTrue(any(abs(float(v)-labor_cost)<.001 for row in labor for v in row.values()
                            if str(v).replace('.','',1).replace('-','',1).isdigit()),labor)
        pdf=Path(self.folder.name)/'wide-labor.pdf'
        def choose(dialog):
            p=dialog.printer();p.setOutputFormat(QPrinter.OutputFormat.PdfFormat);p.setOutputFileName(str(pdf))
            return QDialog.DialogCode.Accepted
        self.m.show_detail()
        with patch.object(ui.QPrintDialog,'exec',choose):self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        text=''.join(page.extract_text() for page in PdfReader(pdf).pages)
        self.assertIn('1350',text);self.assertIn(f'{before[16]:,.2f}',text)
        self.w.show_section(ui.COST_ROUTE);self.w.summary_table.selectRow(0)
        self.w.summary_table.scrollToItem(self.w.summary_table.item(0,15));app.processEvents()
        OUT.mkdir(parents=True,exist_ok=True)
        self.assertTrue(self.w.grab().save(str(OUT/f'wide-labor-cost-page-h{height}.png')))
        self.assertEqual(self.w.draft_items[0]['formula']['labor_cost'],labor_cost)

    def test_conflict_message_identifies_rules_while_transport_errors_keep_network_guidance(self):
        text=client._quote_calculation_failure_text(json.dumps({'message':'JS_WIDE_EXP 非标尺寸人工规则存在同级冲突'}))
        self.assertIn('成本规则匹配冲突',text);self.assertNotIn('检查网络',text)
        network=client._quote_calculation_failure_text('The read operation timed out')
        self.assertIn('检查网络',network)


if __name__=='__main__':unittest.main(verbosity=2)
