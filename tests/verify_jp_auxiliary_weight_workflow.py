"""Real API weight builder → real Qt save/reopen/PDF/Excel; synthetic data only."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import verify_weight_freight as baseline
from verify_weight_freight import ui,wait,fixture,schemes
from verify_quote_document_progress import app
from freight_state import self_made_weight,JP_AUXILIARY_WEIGHT_BASIS
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]


class JPWeightWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise the production API helper rather than a Python copy of its formulas.
        code="import {jpAuxiliaryWeight} from './api/jp_auxiliary_weight.mjs';console.log(JSON.stringify(jpAuxiliaryWeight({product_code:'JP',width_mm:800,depth_mm:600,height_mm:1800})));"
        cls.weight=json.loads(subprocess.check_output(['node','--input-type=module','-e',code],cwd=ROOT,text=True,encoding='utf-8'))

    def setUp(self):
        self.h=baseline.WeightFreight();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.w=self.h.w;self.item=self.h.item;self.m=self.h.m
        self.item['formula'].update(cabinet_auxiliary_self_made_weight_kg=self.weight['weight_kg'],
            cabinet_auxiliary_weight_basis=self.weight['basis'],cabinet_auxiliary_weight_lines=deepcopy(self.weight['lines']))
        self.w._quote_order_nature='EXTERNAL';self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()

    def test_save_reopen_print_and_actual_excel_use_added_weight_and_freight(self):
        self.assertEqual(self.weight['weight_kg'],32.63283936)
        self.assertEqual(self_made_weight(self.item),Decimal('80.13283936'))
        self.assertEqual(self.item['freight_fee'],80.13)
        grid=self.w.summary_table
        self.assertEqual(grid.item(0,ui.HEADERS.index('自制件重量')).text(),'80.13')
        self.assertEqual(grid.item(0,ui.HEADERS.index('运费')).text(),'80.13')
        self.item['quantity']=3;self.w.refresh_summary()
        self.assertEqual(self.item['freight_fee'],80.13)
        saved=self.h.reopen();self.assertEqual(saved['draft_items'][0]['formula']['cabinet_auxiliary_self_made_weight_kg'],32.63283936)
        current=self.w.draft_items[0]
        self.assertEqual(current['freight_fee'],80.13)
        self.assertEqual(current['formula']['cabinet_auxiliary_weight_basis'],JP_AUXILIARY_WEIGHT_BASIS)
        prices=ui._row_values(current)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'jp-weight.pdf';printer=QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(target))
            doc=QTextDocument();doc.setHtml(ui._printable_quote_html(self.w));doc.print_(printer)
            text=''.join(p.extract_text() for p in PdfReader(str(target)).pages)
            self.assertIn(f'{prices[15]:,.2f}',text);self.assertIn(f'{prices[16]:,.2f}',text)
        self.h.export();self.assertTrue(self.h.path.exists(),self.h.messages)
        receipt=self.h.posts()[-1]['snapshot'];self.assertEqual(receipt['draft_items'][0]['freight_fee'],80.13)
        self.assertEqual(receipt['draft_items'][0]['formula']['cabinet_auxiliary_self_made_weight_kg'],32.63283936)
        self.assertEqual(receipt['quote_management']['versions'][-1]['items'][0]['formula']['cabinet_auxiliary_self_made_weight_kg'],32.63283936)
        self.assertEqual(receipt['contract_quote_snapshot']['items'][0]['freight_fee'],80.13)
        for sheet,unit,total in [('快速报价单',prices[15],prices[16]),('公式法报价单',prices[17],prices[18])]:
            self.assertEqual(float(fixture.workbook_cell(self.h.path,sheet,'F11')),unit)
            self.assertEqual(float(fixture.workbook_cell(self.h.path,sheet,'G11')),total)
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with baseline.ZipFile(self.h.path) as book:
            shared=[''.join(node.itertext()) for node in baseline.ET.fromstring(book.read('xl/sharedStrings.xml'))]
            for name in ('xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'):
                cells=baseline.ET.fromstring(book.read(name)).findall('.//m:c',ns)
                header=next(c for c in cells if c.get('t')=='s' and shared[int(c.find('m:v',ns).text)]=='运费')
                column=baseline.re.match('[A-Z]+',header.get('r'))[0]
                value=next(c for c in cells if c.get('r')==column+'11').findtext('m:v',namespaces=ns)
                self.assertEqual(float(value),80.13)

    def test_live_calculation_and_ganged_children_keep_accepted_weights(self):
        self.w.current_result={'formula':deepcopy(self.item['formula']),'quick':deepcopy(self.item['quick'])}
        self.w.attachments=deepcopy(self.item['attachments']);self.w.freight_state.reset();self.w.refresh_discounted_totals()
        self.assertEqual(self.w.freight_spin.value(),80.13)
        self.item['formula']={'corrected_material_weight_kg':100,'ganged_cabinet_costs':[
            {'formula_cost':{'cabinet_auxiliary_self_made_weight_kg':32.63283936,'cabinet_auxiliary_weight_basis':JP_AUXILIARY_WEIGHT_BASIS}},
            {'formula_cost':{'cabinet_auxiliary_self_made_weight_kg':32.63283936,'cabinet_auxiliary_weight_basis':JP_AUXILIARY_WEIGHT_BASIS}}]}
        self.item['attachments']=[]
        self.assertEqual(self_made_weight(self.item),Decimal('165.26567872'))

    def test_actual_show_result_keeps_new_api_metadata_and_automatic_freight(self):
        from quote_request_context import bind_quote_request,stamp_quote_response
        payload={'quote_id':'LOCAL-JP-API-001','product_code':'JP','risk_flags':[],
                 'formula_cost':deepcopy(self.item['formula']),'quick_quote':deepcopy(self.item['quick'])}
        self.w.attachments=deepcopy(self.item['attachments']);self.w.freight_state.reset()
        worker=SimpleNamespace();bind_quote_request(self.w,worker,payload['quote_id'],False)
        self.w.show_result(stamp_quote_response(worker,payload))
        self.assertEqual(self.w.current_result['formula']['cabinet_auxiliary_self_made_weight_kg'],32.63283936)
        self.assertEqual(self.w.freight_spin.value(),80.13)

    def test_manual_freight_and_frozen_history_are_not_repriced(self):
        self.item.update(freight_mode='MANUAL',freight_fee=0);self.w.refresh_summary();self.assertEqual(self.item['freight_fee'],0)
        self.item.update(freight_mode='AUTO',freight_fee=70);self.w._quote_scheme_read_only=True
        self.w.refresh_summary();self.assertEqual(self.item['freight_fee'],70)
        frozen=ui._quote_export_items_snapshot(self.w);self.assertEqual(frozen[0]['freight_fee'],70)


if __name__=='__main__':unittest.main(verbosity=2)
