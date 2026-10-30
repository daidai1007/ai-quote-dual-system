"""Actual version table: all, selected pair, clear, history and output."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import verify_quote_export_customer as fixture
from verify_quote_document_progress import app,wait,ui,ns
from PySide6.QtCore import Qt,QRect
from PySide6.QtTest import QTest
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader
import quote_management_model as model
import quote_scheme_center as schemes

OUT=Path(os.environ.get('AI_QUOTE_COMPARISON_SCREENSHOT_DIR',fixture.ROOT/'test-output/version-comparison'))


class VersionComparisonUI(unittest.TestCase):
    clean_window=fixture.ExportCustomer.clean_window
    export=fixture.ExportCustomer.export
    posts=fixture.ExportCustomer.posts

    def setUp(self):
        screen=Mock(wraps=app.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        p=patch.object(ns['MainWindow'],'screen',return_value=screen);p.start();self.addCleanup(p.stop)
        fixture.ExportCustomer.setUp(self);self.w=self.window
        source=deepcopy(self.w.draft_items[0]);entries=[]
        for number,price in enumerate((100,90,95),1):
            row=deepcopy(source)
            row.update(name='合成版本柜',quantity=2,freight_fee=0,freight_mode='MANUAL',attachments=[],quick_discount=1)
            row['quick']=dict(base_price=price,attachment_fee=0,total_cost=price)
            row['formula']=dict(material_cost=40,auxiliary_cost=10,labor_cost=5,spray_cost=1.6,attachment_fee=0,management_fee=3.4,total_cost=60)
            row['quote_display']=dict(unit_price=price,total=price*2,quantity=2)
            row['quote_cost_display']=dict(schema=1,values={'成本总价':'120.00'})
            ui._quote_item_remark(row);ui._recalculate_item_management(row)
            version=model.make_version([row],self.w.scheme2_company.currentText(),number,'合成调价','合成人员','2026-10-26','EXTERNAL')
            version['confirmed']=True;entries.append(version)
        self.w._qm_state=dict(schema=1,versions=entries,current=3)
        self.w.draft_items=deepcopy(entries[-1]['items'])
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.m.show_detail();self.m.tabs.setCurrentIndex(3)
        self.w.resize(1519,987);self.w.show();app.processEvents()
        self.m.clear_comparison()

    def screenshot(self,name):
        OUT.mkdir(parents=True,exist_ok=True);app.processEvents()
        self.assertTrue(self.w.grab().save(str(OUT/name)))

    def test_default_all_previous_pairs_arbitrary_pair_and_clear_preserve_versions(self):
        before=deepcopy(self.m.state)
        self.assertIsNone(self.m.from_version.currentData());self.assertIsNone(self.m.to_version.currentData())
        grid=self.m.compare_table;self.assertEqual(grid.rowCount(),6)
        self.assertIn('首次报价',grid.item(0,0).text())
        self.assertEqual(grid.item(2,0).text(),'V1 → V2');self.assertEqual(grid.item(4,0).text(),'V2 → V3')
        self.assertIn('金额：-20.00',grid.item(2,5).text())
        # Current gross basis: production 56.60 plus manufacture 4% of
        # quote. V1/V2 margins are 39.40% and 33.111...%, freight is zero.
        self.assertIn('-6.29 个百分点',grid.item(2,5).text())
        self.screenshot('all-versions.png')
        self.m.from_version.setCurrentIndex(self.m.from_version.findData(1))
        self.m.to_version.setCurrentIndex(self.m.to_version.findData(3));app.processEvents()
        self.assertEqual(grid.rowCount(),2);self.assertEqual(grid.item(0,0).text(),'V1 → V3')
        self.assertIn('金额：-10.00',grid.item(0,5).text())
        self.assertIn('-2.98 个百分点',grid.item(0,5).text())  # V3=(95-56.6-3.8)/95.
        self.screenshot('selected-v1-v3.png')
        QTest.mouseClick(self.m.compare_clear,Qt.MouseButton.LeftButton);app.processEvents()
        self.assertEqual(grid.rowCount(),6)
        self.assertIsNone(self.m.from_version.currentData());self.assertIsNone(self.m.to_version.currentData())
        self.assertEqual(self.m.state,before)

    def test_narrow_comparison_and_readonly_versions_remain_visible(self):
        self.m.view_version(1);self.m.tabs.setCurrentIndex(3)
        self.assertEqual(self.m.compare_table.rowCount(),6)
        for width,height in ((1280,860),(1024,768)):
            self.w.resize(width,height);self.m.refresh();app.processEvents()
            self.assertEqual(self.m.compare_table.rowCount(),6)
            self.assertTrue(self.m.compare_clear.isVisible())
            self.screenshot(f'all-versions-{width}.png')

    def test_save_reopen_actual_pdf_excel_keep_current_and_historical_prices(self):
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(len(self.server['snapshot']['quote_management']['versions']),3)
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop();self.m.tabs.setCurrentIndex(3);self.m.clear_comparison()
        self.assertEqual(self.m.compare_table.rowCount(),6)
        self.assertTrue(model.same_document(dict(items=self.w.draft_items,company=self.w.scheme2_company.currentText(),order_nature='EXTERNAL'),self.m.state['versions'][-1]),
            {key:(self.w.draft_items[0].get(key),self.m.state['versions'][-1]['items'][0].get(key)) for key in
             set(self.w.draft_items[0])|set(self.m.state['versions'][-1]['items'][0]) if key not in ('quote_display','quote_cost_display','cost_detail_rows')
             and self.w.draft_items[0].get(key)!=self.m.state['versions'][-1]['items'][0].get(key)})
        self.export();self.assertTrue(self.path.exists(),self.messages)
        self.assertEqual(float(fixture.workbook_cell(self.path,'报价','F11')),95)
        self.assertEqual(float(fixture.workbook_cell(self.path,'报价','G11')),190)
        pdf=Path(self.folder.name)/'comparison-current.pdf'
        def choose(dialog):
            printer=dialog.printer();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            return QDialog.DialogCode.Accepted
        with patch.object(ui.QPrintDialog,'exec',choose):self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        self.assertIn('190.00',''.join(page.extract_text() for page in PdfReader(pdf).pages))
        self.m.tabs.setCurrentIndex(3);self.m.clear_comparison()
        self.assertEqual(self.m.compare_table.item(0,4).text(),'100.00')
        self.assertEqual(self.m.compare_table.item(4,4).text(),'95.00')


if __name__=='__main__':unittest.main(verbosity=2)
