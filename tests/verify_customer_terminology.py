"""Offline customer terminology, recovered-core and legacy workspace contracts."""
from copy import deepcopy
import marshal
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel
import quote_scheme_center as centre
import scheme2_ui as ui
import v3_launcher


def strings(code):
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from strings(value)
        elif isinstance(value, (tuple, frozenset)):
            yield from (text for text in value if isinstance(text, str))
        elif isinstance(value, str):
            yield value


class CustomerTerminology(unittest.TestCase):
    def test_recovered_core_renames_labels_and_history_without_changing_keys(self):
        original = marshal.loads((v3_launcher._resource_root() / "main.raw").read_bytes())
        updated = v3_launcher._customer_ui_code(original)
        before, after = list(strings(original)), list(strings(updated))
        self.assertTrue(any("下单公司" in text for text in before))
        for old, new in v3_launcher._CUSTOMER_UI_REPLACEMENTS:
            self.assertFalse(any(old in text for text in after), old)
        expected = before[:]
        for old, new in v3_launcher._CUSTOMER_UI_REPLACEMENTS:
            expected = [text.replace(old, new) for text in expected]
        self.assertCountEqual(after, expected)
        self.assertEqual(original.co_code, updated.co_code)
        self.assertEqual(original.co_names, updated.co_names)
        for key in ("company_name", "company_code", "company_id"):
            self.assertEqual(before.count(key), after.count(key))
        code = compile("def value():\n return '下单公司', 'company_name'\n", "<test>", "exec")
        namespace = {}
        exec(v3_launcher._customer_ui_code(code), namespace)
        self.assertEqual(namespace["value"](), ("客户", "company_name"))
        self.assertCountEqual(list(strings(v3_launcher._customer_ui_code(updated))), after)

    def test_customer_input_old_saved_workspace_print_and_export(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            settings_file = str(Path(folder) / "settings.ini")
            settings = lambda: QSettings(settings_file, QSettings.Format.IniFormat)
            # Seed the previous client's key, including text that must remain user data.
            customer = "任务A测试客户（原下单公司名称）"
            settings().setValue(ui._CUSTOM_COMPANIES_KEY, [customer])
            with patch.object(ui, "_company_settings", settings), \
                    patch.dict(os.environ, {"AI_QUOTE_ORDER_CACHE_ROOT": folder}):
                namespace = v3_launcher.load_v3_namespace()
                namespace["MainWindow"].load_catalogs = lambda self: None
                if Path("C:/Windows/Fonts/msyh.ttc").is_file():
                    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
                namespace["install_application_font"](app)
                with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                    window = namespace["MainWindow"]()
                    try:
                        window.scheme2_company.setCurrentText(customer)
                        ui._sync_export_company(window)
                        self.assertEqual(window.company_combo.currentText(), customer)
                        label = window.scheme2_quote_company_field.findChild(QLabel, "scheme2FieldLabel")
                        self.assertEqual(label.text(), "客户")
                        self.assertEqual(window.quote_scheme_filters["company"].placeholderText(), "请输入客户")
                        self.assertEqual(window.quote_scheme_table.horizontalHeaderItem(1).text(), "客户")
                        window.draft_items = [dict(name="任务A测试柜", product_code="JP_SINGLE",
                            material_code="SECC", specification="800*600*1800", quantity=2,
                            quick_discount=0.8, freight_fee=10, attachments=[],
                            quick=dict(base_price=200, total_cost=200, attachment_fee=0),
                            formula=dict(material_cost=80, auxiliary_cost=5, labor_cost=10,
                                         spray_cost=5, attachment_fee=0, total_cost=100))]
                        window.refresh_summary()
                        expected = deepcopy(window.draft_items)
                        before = ui._row_values(window.draft_items[0])
                        saved = ui._order_workspace_payload(window)
                        self.assertEqual(saved["company"], customer)
                        self.assertEqual(centre._snapshot(window)["company"], customer)
                        destination = Path(folder) / "synthetic.aiquote"
                        ui._write_order_workspace_file("TASK-A-TEST", saved, destination)
                        order_number, loaded = ui._read_order_workspace_file(destination)
                        self.assertEqual(order_number, "TASK-A-TEST")
                        window.scheme2_company.setCurrentText("其他测试客户")
                        window.draft_items = []
                        ui._apply_order_workspace_payload(window, loaded, "任务A离线恢复")
                        self.assertEqual(window.scheme2_company.currentText(), customer)
                        expected[0]['quote_original_discount'] = 0.8
                        self.assertEqual(window.draft_items, expected)
                        self.assertEqual(ui._row_values(window.draft_items[0]), before)
                        rendered = ui._printable_quote_html(window)
                        self.assertIn(customer, rendered)
                        exported = ui._quote_export_items_snapshot(window)
                        self.assertEqual(exported[0]["quote_display"]["unit_price"], before[15])
                        self.assertEqual(exported[0]["quote_display"]["total"], before[16])
                        self.assertEqual(window.scheme2_quote_preview.item(3, 1).text(), customer)
                        self.assertEqual(window.draft_items, expected)
                        artifact_dir = os.environ.get("AI_QUOTE_UI_ARTIFACT_DIR")
                        if artifact_dir:
                            output = Path(artifact_dir)
                            output.mkdir(parents=True, exist_ok=True)
                            window.resize(1366, 820)
                            window.show()
                            window.show_section(ui.QUOTE_ROUTE)
                            app.processEvents()
                            self.assertTrue(window.scheme2_quote_company_field.grab().save(str(output / "customer-field.png")))
                    finally:
                        window._quote_scheme_save_timer.stop()
                        window._quote_scheme_id = ""
                        window._scheme2_dirty = False
                        window.close()
                        app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
