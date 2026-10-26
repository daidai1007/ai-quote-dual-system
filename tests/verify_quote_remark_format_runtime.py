"""Actual Qt configuration remarks through save/reopen, PDF and Excel."""
from copy import deepcopy
import html
from pathlib import Path
import unittest
from unittest.mock import patch

import verify_quote_remarks as fixture
from verify_quote_remark_format import product
from verify_quote_document_progress import app,wait,ui
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QAbstractItemView
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from pypdf import PdfReader
import quote_scheme_center as schemes
import quote_management_model as model


class RemarkFormatRuntime(unittest.TestCase):
    clean_window=fixture.QuoteRemarks.clean_window
    export=fixture.QuoteRemarks.export
    posts=fixture.QuoteRemarks.posts
    setUp=fixture.QuoteRemarks.setUp
    assert_outputs=fixture.QuoteRemarks.assert_outputs
    screenshot=fixture.QuoteRemarks.screenshot
    edit=fixture.QuoteRemarks.edit

    def configured_item(self):
        item=self.w.draft_items[0]
        item.update(product())
        for index,row in enumerate(item['attachments']):
            row.update(attachment_price_id=500+index,status='FIXED',formula_amount=1,quick_amount=2,
                       matched_price=2/row['quantity'])
            if row.get('custom'):row.update(custom_cost=1,unit_price_override=2)
        item.pop('final_remark',None);item.pop('quote_remark_manual',None)
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        return item

    def test_full_format_real_ui_save_reopen_pdf_and_xlsx(self):
        item=self.configured_item()
        expected=self.w.scheme2_quote_preview.item(10,7).text()
        self.assertIn('D-001/M-01',expected)
        self.assertIn('配国产220VSG220风机2只',expected)
        self.assertTrue(expected.endswith('IP54；木箱包装；安装板先发。'))
        self.w.summary_table.item(0,4).setText('12');app.processEvents()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),expected)
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(self.server['snapshot']['draft_items'][0]['quote_configuration'],item['quote_configuration'])
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),expected)
        pdf=Path(self.folder.name)/'configuration-template.pdf'
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
        document=QTextDocument();document.setHtml(ui._printable_quote_html(self.w));document.print_(printer)
        printed=''.join(''.join(page.extract_text() for page in PdfReader(pdf).pages).split())
        for phrase in ('D-001/M-01','门板2mm','配MS821门锁2把','配接地线3根','不含空调','安装板先发'):
            self.assertIn(phrase,printed)
        self.assert_outputs(expected)
        for width,height in ((1560,960),(1024,768)):
            self.w.resize(width,height);app.processEvents()
            QTest.qWait(80)
            table=self.w.scheme2_quote_preview
            table.scrollToItem(table.item(10,7),QAbstractItemView.ScrollHint.PositionAtCenter)
            app.processEvents()
            self.assertTrue(table.viewport().rect().intersects(table.visualItemRect(table.item(10,7))))
            self.assertGreaterEqual(table.rowHeight(10),table.sizeHintForRow(10))
            self.screenshot(f'05-new-format-{width}.png')
            editor=self.edit(expected,commit=False)
            self.assertTrue(table.viewport().rect().contains(editor.geometry()))
            self.assertEqual(editor.toPlainText(),expected)
            QTest.keyClick(editor,Qt.Key.Key_Escape);app.processEvents()

    def test_old_automatic_remark_migrates_but_sealed_history_is_preserved(self):
        item=self.w.draft_items[0]
        old=ui._previous_scheme2_quote_remark(item)
        item.pop('quote_remark_manual',None);ui._synchronize_export_remark(item,old)
        self.w._quote_scheme_read_only=True;self.w.refresh_summary()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),old)
        self.assertNotIn('quote_remark_manual',item)
        self.w._quote_scheme_read_only=False;self.w.refresh_summary()
        self.assertFalse(item['quote_remark_manual'])
        self.assertIn('风机3只',self.w.scheme2_quote_preview.item(10,7).text())
        self.assertNotIn('风机×6',self.w.scheme2_quote_preview.item(10,7).text())

    def test_latest_confirmed_old_format_is_not_rewritten_by_refresh_or_export(self):
        item=self.w.draft_items[0]
        old=ui._previous_scheme2_quote_remark(item)
        item.pop('quote_remark_manual',None);ui._synchronize_export_remark(item,old)
        entry=model.make_version([item],'合成测试客户',1)
        entry['confirmed']=True
        self.m.state.update(versions=[entry],current=1)
        before=deepcopy(entry)
        self.w.refresh_summary()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),old)
        self.assertEqual(ui._quote_export_items_snapshot(self.w)[0]['quote_display']['remark'],old)
        self.assertEqual(entry,before)
        self.assertNotIn('quote_remark_manual',item)
        self.m.state['versions'][-1]['pending_confirmation']=True
        self.w.refresh_summary()
        self.assertIn('风机3只',self.w.scheme2_quote_preview.item(10,7).text())


if __name__=='__main__':unittest.main(verbosity=2)
