"""Existing quote editor, frozen versions and Office outputs retain their boundaries."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
import verify_quote_remark_format_runtime as fixture
from verify_quote_document_progress import ui, wait
from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader

class ConfirmedRemarkUI(unittest.TestCase):
    # Reuse the actual save/reopen/PDF/XLSX fixtures, not a synthetic editor.
    setUp=fixture.RemarkFormatRuntime.setUp
    clean_window=fixture.RemarkFormatRuntime.clean_window
    export=fixture.RemarkFormatRuntime.export
    posts=fixture.RemarkFormatRuntime.posts
    assert_outputs=fixture.RemarkFormatRuntime.assert_outputs
    screenshot=fixture.RemarkFormatRuntime.screenshot
    edit=fixture.RemarkFormatRuntime.edit
    configured_item=fixture.RemarkFormatRuntime.configured_item
    def test_confirmed_structure_and_dash_in_saved_and_exported_quote(self):
        item=self.configured_item()
        item['quote_configuration'].update(installation_plate_quantity='—',excluded_items=['安装板','空调'])
        before_prices=ui._row_values(item)[15:17]
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        text=self.w.scheme2_quote_preview.item(10,7).text()
        self.assertIn('仿威图JP柜，侧板、后背板可拆，不含安装板。',text)
        self.assertNotIn('配2.5mm镀锌安装板',text)
        self.assertEqual(text.count('不含安装板'),1)
        cell=self.w.scheme2_quote_preview.item(10,7)
        self.assertFalse(cell.icon().isNull());self.assertIn('需复核',cell.toolTip())
        self.assertIn('需复核',cell.data(Qt.ItemDataRole.AccessibleDescriptionRole))
        self.assertNotIn('需复核',text)
        self.screenshot('06-confirmed-template-and-review.png')
        self.assert_outputs(text)
        self.assertEqual(ui._row_values(item)[15:17],before_prices)

    def test_manual_override_and_frozen_history_are_not_rewritten(self):
        item=self.configured_item();manual='人工确认：按旧订单原文供货。'
        item['quote_remark_manual']=True;ui._synchronize_export_remark(item,manual)
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),manual)
        self.assertTrue(self.w.scheme2_quote_preview.item(10,7).icon().isNull())
        item['quote_remark_manual']=False
        self.w._quote_scheme_read_only=True
        before=deepcopy(item);self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),manual)
        self.assertEqual(item,before)

    def test_removing_board_clears_automatic_remark_and_export(self):
        item=self.configured_item()
        self.assertIn('配2.5mm镀锌安装板1块',self.w.scheme2_quote_preview.item(10,7).text())
        item['attachments']=[row for row in item['attachments'] if row['item_name']!='安装板']
        item['quote_configuration'].update(installation_plate_quantity=1,excluded_items=['安装板','空调'])
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        text=self.w.scheme2_quote_preview.item(10,7).text()
        self.assertNotIn('安装板',text)
        self.assertIn('不含空调',text)
        self.assertIn('配门锁2把',text)
        self.screenshot('07-removed-installation-board.png')

        pdf=Path(self.folder.name)/'removed-installation-board.pdf'
        def choose_pdf(dialog):
            printer=dialog.printer()
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(pdf))
            return QDialog.DialogCode.Accepted

        with patch.object(ui.QPrintDialog,'exec',choose_pdf):
            self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        printed=''.join(''.join(page.extract_text() for page in PdfReader(pdf).pages).split())
        self.assertIn('配门锁2把',printed)
        self.assertIn('不含空调',printed)
        self.assertNotIn('安装板',printed)
        self.assert_outputs(text)

if __name__=='__main__':unittest.main(verbosity=2)
