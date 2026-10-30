"""Real V3 cost classification, snapshots, PDF and both production XLSX sheets."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
import verify_quote_export_customer as fixture
from verify_quote_document_progress import app,wait,ui,ns
from PySide6.QtCore import QRect
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import quote_scheme_center as schemes
import quote_management_model as versions
from quick_discount_rules import money_sum

DATA=json.loads((fixture.ROOT/'tests/fixtures/formula_attachment_allocation.json').read_text(encoding='utf-8'))
OUT=Path(os.environ.get('AI_QUOTE_ALLOCATION_SCREENSHOT_DIR',fixture.ROOT/'test-output/formula-allocation'))


def workbook_rows(path,sheet_name):
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as book:
        strings=[''.join(n.itertext()) for n in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('s:si',ns)] if 'xl/sharedStrings.xml' in book.namelist() else []
        wb=ET.fromstring(book.read('xl/workbook.xml'))
        rel=next(s for s in wb.findall('s:sheets/s:sheet',ns) if s.get('name')==sheet_name).get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        target=next(r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels')) if r.get('Id')==rel)
        sheet=ET.fromstring(book.read(target.lstrip('/') if target.startswith('/') else 'xl/'+target))
        return [{c.get('r').rstrip('0123456789'):(strings[int(c.findtext('s:v',namespaces=ns))] if c.get('t')=='s' else
            ''.join(c.find('s:is',ns).itertext()) if c.get('t')=='inlineStr' else c.findtext('s:v',default='',namespaces=ns))
            for c in row.findall('s:c',ns)} for row in sheet.findall('s:sheetData/s:row',ns)]


class AllocationUI(unittest.TestCase):
    clean_window=fixture.ExportCustomer.clean_window
    export=fixture.ExportCustomer.export
    posts=fixture.ExportCustomer.posts

    def setUp(self):
        screen=Mock(wraps=app.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        p=patch.object(ns['MainWindow'],'screen',return_value=screen);p.start();self.addCleanup(p.stop)
        fixture.ExportCustomer.setUp(self);self.w=self.window
        row=self.w.draft_items[0]
        row.update(quantity=3,freight_fee=8,freight_mode='MANUAL',quick_discount=1,formula_discount=.8,
            formula=deepcopy(DATA['formula']),attachments=deepcopy(DATA['attachments']),attachment_snapshot_dirty=False)
        for a in row['attachments']:a['catalog_version']='synthetic-allocation-v1'
        row['attachments'][0]['category_level1']='其他附件';row['attachments'][1]['category_level1']='其他附件'
        row['quick']=dict(base_price=500,attachment_fee=113,total_cost=613)
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop();self.m.show_detail()
        self.w.resize(1560,960);self.w.show();app.processEvents()

    def screenshot(self,name):
        OUT.mkdir(parents=True,exist_ok=True);app.processEvents();self.assertTrue(self.w.grab().save(str(OUT/name)))

    def assert_costs(self):
        grid=self.w.summary_table
        for col,value in ((13,135),(14,23),(15,37),(16,12),(17,15),(18,31.05),(19,8),(12,350.09),(20,1050.27),(ui.TAX_COST_COLUMN,64.2),(ui.MANUFACTURING_COLUMN,24.84)):
            self.assertEqual(float(grid.item(0,col).text().replace(',','')),value,(col,grid.item(0,col).text()))
        self.assertEqual(self.w.draft_items[0]['formula']['attachment_fee'],62,'Original pricing ledger remains unchanged')
        self.assertEqual(float(grid.item(0,10).text().replace(',','')),621)
        self.assertEqual(grid.item(0,21).text(),'58.96%')
        self.assertEqual(grid.item(0,ui.NET_MARGIN_COLUMN).text(),'43.62%')

    def test_repeated_refresh_detail_close_and_order_quantity_do_not_double_charge(self):
        for _ in range(4):self.w.refresh_summary();self.assert_costs()
        item=self.w.draft_items[0];original=deepcopy(item['formula'])
        ui._show_detail(self.w,item)
        rows=item['cost_detail_rows'];allocated=[r for r in rows if r.get('attachment_cost_source')]
        self.assertEqual(len(allocated),9)
        self.assertEqual(money_sum(r['base_amount'] for r in allocated),62)
        for i,row in enumerate(rows):
            if row.get('attachment_cost_source'):self.assertIsNone(self.w.scheme2_detail_table.cellWidget(i,8))
        self.assertEqual(money_sum(r['base_amount'] for r in rows),342.09)
        self.screenshot('cost-detail.png');self.w.scheme2_close_detail();self.assert_costs()
        self.assertEqual(item['formula'],original)
        self.w.summary_table.item(0,4).setText('2');app.processEvents()
        self.assertEqual(float(self.w.summary_table.item(0,20).text().replace(',','')),700.18)
        self.assertEqual(float(self.w.summary_table.item(0,16).text()),12)
        self.w.summary_table.selectRow(0);self.w.summary_table.scrollToItem(self.w.summary_table.item(0,16))
        self.screenshot('cost-table.png')

    def test_save_reopen_real_pdf_and_workbook_keep_allocation_margin_and_prices(self):
        self.assert_costs();self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(self.server['snapshot']['draft_items'][0]['formula']['cost_allocation']['totals'],dict(DATA['expected'],manufacturing_cost=24.84,management_fee=31.05,tax_cost=64.2))
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop();self.assert_costs()
        self.export();self.assertTrue(self.path.exists(),self.messages)
        self.assertEqual(float(fixture.workbook_cell(self.path,'快速报价单','F11')),621)
        self.assertEqual(float(fixture.workbook_cell(self.path,'快速报价单','G11')),1863)
        self.assertEqual(float(fixture.workbook_cell(self.path,'公式法报价单','F11')),296.07)
        rows=workbook_rows(self.path,'成本明细')
        split=[r for r in rows if '合成公式附件－' in r.get('E','')]
        self.assertEqual(len(split),4)
        self.assertEqual(money_sum(float(r['M']) for r in split),180)
        self.assertFalse(any(r.get('D')=='附件成本' and r.get('E')=='合成公式附件' for r in rows))
        frozen=self.posts()[-1]['snapshot']['contract_quote_snapshot']['items'][0]
        self.assertEqual(frozen['quote_cost_display']['values']['附件成本'],'12.00')
        self.assertEqual(frozen['quote_cost_display']['values']['毛利率'],'58.96%')
        self.assertEqual(frozen['quote_cost_display']['values']['净利率'],'43.62%')
        pdf=Path(self.folder.name)/'allocation.pdf'
        def choose(dialog):
            p=dialog.printer();p.setOutputFormat(QPrinter.OutputFormat.PdfFormat);p.setOutputFileName(str(pdf));return QDialog.DialogCode.Accepted
        with patch.object(ui.QPrintDialog,'exec',choose):self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        self.assertIn('1,863.00',''.join(page.extract_text() for page in PdfReader(pdf).pages))

    def test_missing_formula_components_are_visible_and_cannot_be_exported(self):
        item=self.w.draft_items[0];item['attachments'][0].pop('material_cost')
        self.w.refresh_summary();self.assertEqual(self.w.summary_table.item(0,13).text(),'待重算')
        with self.assertRaisesRegex(ValueError,'重新计算'):ui._quote_export_items_snapshot(self.w)

    def test_ganged_set_allocation_occurs_once(self):
        item=self.w.draft_items[0]
        a=dict(DATA['formula'],material_cost=50,auxiliary_cost=10,labor_cost=15,spray_cost=5,attachment_fee=0)
        item['formula']['ganged_cabinet_costs']=[dict(cabinet_index=i,formula_cost=deepcopy(a)) for i in (1,2)]
        item['ganged_cabinet_count']=2;self.w.refresh_summary();self.assert_costs()
        rows=ui._detail_rows(item)
        self.assertEqual(len([r for r in rows if r.get('attachment_cost_source')]),9)
        self.assertEqual(money_sum(r['base_amount'] for r in rows),342.09)

    def test_derived_allocation_does_not_invent_an_unconfirmed_business_change(self):
        item=self.w.draft_items[0]
        prior=versions.make_version([item],self.w.scheme2_company.currentText(),1,'已确认','合成人员','2026-10-26','EXTERNAL')
        prior['confirmed']=True;prior['items'][0]['formula'].pop('cost_allocation')
        metadata={key:prior[key] for key in ('updated_at','operator','reason','amount')}
        self.w._qm_state=dict(schema=1,current=1,versions=[prior]);self.m.refresh()
        self.assertEqual(len(self.m.state['versions']),1)
        self.assertEqual({key:prior[key] for key in metadata},metadata)
        self.assertTrue(prior['items'][0]['formula']['cost_allocation']['complete'])
        self.export();self.assertTrue(self.path.exists(),self.messages)

    def test_old_formal_snapshot_keeps_legacy_cost_categories_and_output(self):
        item=self.w.draft_items[0];item['formula'].pop('cost_allocation')
        # This fixture represents a formal version saved before the tax field.
        item.pop('tax_cost_basis',None)
        for key in tuple(item['formula']):
            if key.startswith('tax_'):item['formula'].pop(key)
        item['formula']=ui.apply_management_fee(item['formula'],item['freight_fee'])
        for row in item['attachments']:row.pop('cost_method',None)
        prior=versions.make_version([item],self.w.scheme2_company.currentText(),1,'旧正式版本','合成人员','2026-10-26','EXTERNAL')
        prior.update(sealed=True,confirmed=True)
        self.w._qm_state=dict(schema=1,current=1,versions=[prior])
        self.w._quote_scheme_read_only=True;self.w._quote_scheme_status='QUOTED';self.server['status']='QUOTED'
        before=deepcopy(prior);self.w.refresh_summary();self.m.refresh()
        self.assertEqual(self.w.summary_table.item(0,16).text(),'62.00')
        self.assertEqual(self.m.state['versions'][0],before)
        original_cost=deepcopy(item['formula'])
        ui._show_detail(self.w,item);self.w.scheme2_close_detail()
        self.assertEqual(item['formula'],original_cost,'Viewing and closing old formal details cannot rewrite costs')
        self.export();self.assertTrue(self.path.exists(),self.messages)
        rows=workbook_rows(self.path,'成本明细')
        self.assertTrue(any(r.get('D')=='附件成本' and r.get('E')=='合成公式附件' for r in rows))
        self.assertFalse(any('合成公式附件－' in r.get('E','') for r in rows))
        self.assertEqual(float(fixture.workbook_cell(self.path,'快速报价单','F11')),621)


if __name__=='__main__':unittest.main(verbosity=2)
