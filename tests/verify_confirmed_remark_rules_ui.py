"""Existing quote editor, frozen versions and Office outputs retain their boundaries."""
from copy import deepcopy
import unittest
import verify_quote_remark_format_runtime as fixture
from verify_quote_document_progress import app,ui
from PySide6.QtCore import Qt

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

if __name__=='__main__':unittest.main(verbosity=2)
