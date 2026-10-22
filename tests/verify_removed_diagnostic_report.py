"""Offline recovered-workbench checks after removing report submission."""
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
namespace["install_application_font"](app)
Window = namespace["MainWindow"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None


class RemovedDiagnosticReport(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.addCleanup(self.window.close)

    def assert_no_report_state(self):
        for name in ("scheme2_diagnostic_button", "_scheme2_diagnostic_api_url",
                     "_scheme2_diagnostic_headers_factory", "_scheme2_diagnostic_worker", "_diagnostic_events"):
            self.assertFalse(hasattr(self.window, name), name)

    def test_sidebar_has_quote_navigation_without_report_button(self):
        labels = {button.text() for button in self.window.scheme2_nav.findChildren(QPushButton)}
        self.assertTrue({"选型配置", "成本计算", "报价单管理"}.issubset(labels), labels)
        self.assertFalse(any("诊断报告" in label for label in labels))
        self.assert_no_report_state()
        for name in ("_DiagnosticSubmissionWorker", "_diagnostic_client_version", "_submit_diagnostic_report"):
            self.assertFalse(hasattr(ui, name), name)

    def test_selection_and_navigation_do_not_collect_operation_history(self):
        self.window.quantity_spin.setValue(2)
        self.window.quantity_spin.editingFinished.emit()
        for route in (ui.COST_ROUTE, ui.QUOTE_ROUTE, ui.OPTION_ROUTE):
            self.window.show_section(route)
            self.assertEqual(self.window.stack.currentIndex(), route)
        self.assert_no_report_state()

    def test_quote_editing_snapshot_and_management_remain_usable(self):
        item = dict(name="移除报告验证柜", product_code="JP", material_code="SECC",
            specification="800*600*1800", quantity=1, quick_discount=.5, freight_fee=50,
            attachments=[], quick=dict(base_price=500, total_cost=500, attachment_fee=0),
            formula=dict(material_cost=100, auxiliary_cost=20, labor_cost=30,
                         attachment_fee=0, spray_cost=10, management_fee=0, total_cost=160))
        self.window.draft_items = [item]
        self.window.refresh_summary()
        self.window.summary_table.item(0, ui.HEADERS.index("数量")).setText("2")
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["formula"]["management_fee"], 12.6)
        frozen = self.window.quote_export_items_snapshot()
        self.assertEqual(frozen[0]["quote_display"]["total"], 600)
        self.assert_no_report_state()

    def test_sidebar_and_scheme_status_still_render(self):
        self.window.resize(1440, 900)
        self.window.show()
        self.window.show_section(ui.OPTION_ROUTE)
        QTest.qWait(50)
        ui._set_nav_collapsed(self.window, False, manual=True)
        app.processEvents()
        self.assertTrue(self.window.scheme2_nav.isVisible())
        self.assert_no_report_state()
        screenshot = os.getenv("AI_QUOTE_REMOVAL_SCREENSHOT")
        if screenshot:
            self.assertTrue(self.window.grab().save(screenshot))
        self.window._scheme2_dirty = False


if __name__ == "__main__":
    unittest.main()
