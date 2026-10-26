"""Focused Qt checks for the approved full-width cost page and coefficient dialog."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import layout_refresh
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
ns = v3_launcher.load_v3_namespace()
ns["install_application_font"](app)
Window = ns["MainWindow"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
ns["ApiWorker"].run = lambda self: self.failed.emit("offline cost layout test")


def sample(name, quantity):
    return {
        "name": name, "product_code": "JS", "material_code": "SECC",
        "specification": "1300*600*1800", "quantity": quantity,
        "quick_discount": 0.8, "attachments": [],
        "quick": {"total_cost": 1000},
        "formula": {"material_cost": 200, "auxiliary_cost": 50, "labor_cost": 100,
                    "spray_cost": 50, "management_fee": 30, "total_cost": 500},
    }


class CostCombinedLayout(unittest.TestCase):
    def setUp(self):
        for module in (layout_refresh, ui):
            patcher = patch.object(module, "_fit_window_minimum_to_screen", lambda window: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.window.setMinimumSize(1, 1)
        self.addCleanup(self.window.close)
        self.window.show()
        self.window.show_section(ui.COST_ROUTE)
        self.window.refresh_summary = lambda: ui._refresh_cost_table(self.window)
        self.window.draft_items = [sample("一号柜", 1), sample("二号柜", 2)]
        ui._refresh_cost_table(self.window)
        self.window.resize(1280, 720)
        QTest.qWait(50)
        ui._apply_responsive(self.window)

    def test_full_width_table_and_selected_row_detail_keep_all_fields(self):
        table = self.window.summary_table
        self.assertTrue(self.window.scheme2_cost_sidebar.isHidden())
        self.assertTrue(self.window.scheme2_cost_edit_coefficients.isVisible())
        self.assertEqual(table.columnCount(), len(ui.HEADERS))
        self.assertEqual(set(self.window.scheme2_cost_selection_values), set(ui.COST_SELECTION_DETAIL_COLUMNS))
        self.assertGreater(table.viewport().width(), 600)
        table.selectRow(1)
        ui._sync_cost_selection_detail(self.window)
        self.assertEqual(self.window.scheme2_cost_selection_context.text(), "二号柜 · 1300*600*1800")
        for column, label in self.window.scheme2_cost_selection_values.items():
            text = table.item(1, column).text()
            if column == 22: text += ' kg'
            if column == 5: text = text.removesuffix(' ›')
            self.assertEqual(label.text(), text, ui.HEADERS[column])

    def test_coefficient_dialog_cancel_does_not_modify_pricing(self):
        self.window.summary_table.selectRow(0)
        source = self.window.scheme2_cost_controls["carbon_price"]
        before = source.value()
        def cancel():
            dialog = self.window.findChild(ui._CostCoefficientDialog)
            self.assertIsNotNone(dialog)
            dialog.controls["carbon_price"].setValue(before + 1)
            dialog.reject()
        QTimer.singleShot(0, cancel)
        ui._show_cost_coefficients(self.window)
        self.assertEqual(source.value(), before)
        self.assertEqual(
            self.window.draft_items[0].get("scheme2_cost_settings", {}).get("carbon_price", before),
            before,
        )

    def test_coefficient_dialog_confirm_updates_only_selected_item(self):
        table = self.window.summary_table
        table.selectRow(1)
        source = self.window.scheme2_cost_controls["carbon_price"]
        before = source.value()
        def confirm():
            dialog = self.window.findChild(ui._CostCoefficientDialog)
            self.assertIsNotNone(dialog)
            dialog.controls["carbon_price"].setValue(before + 1)
            dialog.accept()
        QTimer.singleShot(0, confirm)
        ui._show_cost_coefficients(self.window)
        self.assertEqual(source.value(), before + 1)
        self.assertEqual(self.window.draft_items[1]["scheme2_cost_settings"]["carbon_price"], before + 1)
        self.assertEqual(
            self.window.draft_items[0].get("scheme2_cost_settings", {}).get("carbon_price", before),
            before,
        )

    def test_read_only_disables_coefficient_editor(self):
        self.window._quote_scheme_read_only = True
        ui._sync_sidebar(self.window)
        self.assertFalse(self.window.scheme2_cost_edit_coefficients.isEnabled())

    def test_detail_and_actions_fit_resized_windows(self):
        for width, height in ((1536, 960), (1024, 620), (840, 600)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                QTest.qWait(30)
                ui._apply_responsive(self.window)
                self.assertTrue(self.window.scheme2_cost_selection_detail.isVisible())
                self.assertGreater(self.window.summary_table.viewport().height(), 30)
                self.assertTrue(self.window.scheme2_cost_edit_coefficients.isVisible())


if __name__ == "__main__":
    unittest.main()
