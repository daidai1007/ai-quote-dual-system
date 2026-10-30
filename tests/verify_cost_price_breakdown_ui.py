"""Real Qt columns/dialogs, formal snapshots, PDF and production XLSX renderer."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import verify_quote_export_customer as fixture
from verify_quote_document_progress import app, wait, ui
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader
import quote_scheme_center as schemes

OUT=Path(os.environ.get('AI_QUOTE_PRICE_BREAKDOWN_SCREENSHOT_DIR',fixture.ROOT/'test-output/price-breakdown'))


class PriceBreakdownUI(unittest.TestCase):
    clean_window=fixture.ExportCustomer.clean_window
    export=fixture.ExportCustomer.export
    posts=fixture.ExportCustomer.posts
    # Run only this feature's tests, using the existing real exporter fixture.
    def setUp(self):
        fixture.ExportCustomer.setUp(self)
        self.w=self.window
        item=self.w.draft_items[0]
        item.update(material_code='SECC',quantity=2,quick_discount=.8,freight_fee=9,freight_mode='MANUAL')
        item['attachments']=[
            dict(item_name='内门',category_level1='内门',quantity=1,quick_amount=100,formula_amount=40),
            dict(item_name='风机',category_level1='风机',quantity=1,quick_amount=30,formula_amount=10),
            dict(item_name='安装板',category_level1='其他附件',quantity=1,quick_amount=20,formula_amount=5),
            dict(item_name='填充安装板',quantity=1,quick_amount=15,formula_amount=5),
            dict(item_name='安装板',quantity=1,attachment_price_sign=-1,quick_amount=-5,formula_amount=-2),
        ]
        item['quick']=dict(base_price=1000,attachment_fee=160,total_cost=1160)
        for index,attachment in enumerate(item['attachments'],9):
            attachment.update(attachment_price_id=index,status='FIXED')
        item['attachment_snapshot_dirty']=False
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.w.show_section(ui.COST_ROUTE);self.w.resize(1560,960);app.processEvents()
        self.w.summary_table.selectRow(0);app.processEvents()

    def screenshot(self,widget,name):
        OUT.mkdir(parents=True,exist_ok=True);app.processEvents()
        self.assertTrue(widget.grab().save(str(OUT/name)))

    def test_columns_adjacency_and_real_click_and_keyboard_dialogs(self):
        grid=self.w.summary_table;header=grid.horizontalHeader()
        self.assertNotIn('面价',ui.HEADERS)
        self.assertEqual([ui.HEADERS[header.logicalIndex(i)] for i in range(header.visualIndex(7),header.visualIndex(9)+1)],
                         ['固定报价','折扣面价','折扣系数'])
        self.assertEqual(grid.item(0,7).text(),'74.00');self.assertEqual(grid.item(0,24).text(),'876.00')
        self.assertEqual(grid.item(0,10).text(),'950.00')
        before=deepcopy(self.w.draft_items)
        opened=[]
        def inspect(dialog):
            data=[[dialog.table.item(row,col).text() for col in range(4)] for row in range(dialog.table.rowCount())]
            opened.append(data)
            dialog.show();app.processEvents();self.screenshot(dialog,f'popup-{len(opened)}.png');dialog.hide()
            return QDialog.DialogCode.Accepted
        with patch.object(ui.QuickPriceBreakdownDialog,'exec',inspect):
            grid.scrollToItem(grid.item(0,7));app.processEvents()
            QTest.mouseClick(grid.viewport(),Qt.MouseButton.LeftButton,pos=grid.visualItemRect(grid.item(0,7)).center())
            grid.setCurrentCell(0,24);grid.setFocus();QTest.keyClick(grid,Qt.Key.Key_Return);app.processEvents()
        self.assertEqual(opened[0][-1],['汇总','','','74.00'])
        self.assertEqual(opened[1][0],['柜体','1,000.00','0.8','800.00'])
        self.assertEqual(opened[1][-1],['汇总','','','876.00'])
        self.assertEqual(self.w.draft_items,before)
        self.screenshot(self.w,'cost-table.png')

    def test_formal_save_reopen_actual_pdf_excel_and_frozen_components(self):
        self.m.show_detail();self.export()
        self.assertTrue(self.path.exists(),dict(messages=self.messages,reason=self.controller.reason,state=self.controller.state,information=self.information))
        for sheet in ('快速报价单','公式法报价单'):
            self.assertIsNotNone(fixture.workbook_cell(self.path,sheet,'F11'))
        self.assertEqual(float(fixture.workbook_cell(self.path,'快速报价单','F11')),950)
        self.assertEqual(float(fixture.workbook_cell(self.path,'快速报价单','G11')),1900)
        saved=deepcopy(self.server['snapshot'])
        component=saved['contract_quote_snapshot']['items'][0]['quote_cost_display']
        self.assertEqual(component['values']['固定报价'],'74.00')
        self.assertEqual(component['values']['折扣面价'],'876.00')
        self.assertEqual(component['price_breakdown']['total'],950)
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop()
        self.assertIn('950.00',ui._printable_quote_html(self.w))
        self.w.show_section(ui.COST_ROUTE)
        self.assertEqual(self.w.summary_table.item(0,7).text(),'74.00')
        self.assertEqual(self.w.summary_table.item(0,24).text(),'876.00')
        pdf=Path(self.folder.name)/'price-components.pdf'
        def choose(dialog):
            printer=dialog.printer();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            return QDialog.DialogCode.Accepted
        self.m.show_detail()
        with patch.object(ui.QPrintDialog,'exec',choose):self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        self.assertIn('950.00',''.join(page.extract_text() for page in PdfReader(pdf).pages))

    def test_discount_edit_updates_only_discountable_bucket(self):
        grid=self.w.summary_table;attachments=deepcopy(self.w.draft_items[0]['attachments'])
        grid.item(0,9).setText('0.5');app.processEvents()
        self.assertEqual(grid.item(0,7).text(),'74.00')
        self.assertEqual(grid.item(0,24).text(),'547.50')
        self.assertEqual(grid.item(0,10).text(),'621.50')
        self.assertEqual(self.w.draft_items[0]['attachments'],attachments)

    def test_narrow_layout_and_empty_fixed_bucket_remain_readonly(self):
        components=ui._cost_price_components(self.w.draft_items[0])
        for width,height in ((1280,860),(1024,768)):
            self.w.resize(width,height);app.processEvents()
            self.w.summary_table.scrollToItem(self.w.summary_table.item(0,24));app.processEvents()
            self.screenshot(self.w,f'cost-table-{width}.png')
            dialog=ui.QuickPriceBreakdownDialog(self.w,'折扣面价',components,'discounted')
            dialog.show();app.processEvents()
            self.assertFalse(dialog.table.editTriggers())
            self.assertLessEqual(dialog.width(),width)
            self.screenshot(dialog,f'popup-{width}.png');dialog.close()
        from cost_price_breakdown import quick_price_components
        empty=quick_price_components(dict(base_price=100,total_cost=100),[],1)
        dialog=ui.QuickPriceBreakdownDialog(self.w,'固定报价',empty,'fixed')
        self.assertEqual(dialog.table.rowCount(),1)
        self.assertEqual(dialog.table.item(0,3).text(),'0.00');dialog.close()


if __name__=='__main__':unittest.main(verbosity=2)
