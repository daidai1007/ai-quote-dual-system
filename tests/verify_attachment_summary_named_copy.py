"""Named attachment columns and copied cost rows in the live offline UI."""
import copy
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
ns["install_application_font"](app)
ns["MainWindow"].load_catalogs = lambda self: None
ns["MainWindow"].refresh_formula_inputs = lambda self, *args: None
ns["ApiWorker"].run = lambda self: self.failed.emit("offline named/copy summary test")


def product():
    rows = [dict(item_name="固定底座", attachment_price_id=101, width_mm=800,
                 height_mm=100, depth_mm=600, quantity=1, formula_amount=25,
                 quick_amount=50, ganged_fixed_base_match=True, ganged_cabinet_index=0),
            dict(item_name="固定底座", attachment_price_id=102, width_mm=600,
                 height_mm=100, depth_mm=600, quantity=1, formula_amount=20,
                 quick_amount=40, ganged_fixed_base_match=True, ganged_cabinet_index=1),
            dict(item_name="安装板", attachment_price_id=103, width_mm=600,
                 height_mm=1800, quantity=1, formula_amount=30, quick_amount=60),
            dict(item_name="风机KA1238HA2/B(国产)", attachment_price_id=104,
                 quantity=2, formula_amount=8, quick_amount=20)]
    return dict(name="并柜", product_code="JP", material_code="SECC", quantity=2,
                specification="(800+600)*600*(1800+100)", ganged_cabinet_count=2,
                quote_line_id="same-snapshot-on-copy", attachments=rows,
                quick_discount=.5, freight_fee=10,
                quick={"attachment_fee": 170, "total_cost": 370},
                formula={"attachment_fee": 83, "total_cost": 250})


class NamedCopySummary(unittest.TestCase):
    def setUp(self):
        self.window = ns["MainWindow"]()
        self.addCleanup(self.window.close)
        self.window.draft_items = [product()]
        self.window.refresh_summary()

    def dialog(self):
        dialog = ui.AttachmentSummaryDialog(self.window)
        self.addCleanup(dialog.reject)
        return dialog

    def test_columns_list_actual_names_and_price_changes_reconcile(self):
        dialog = self.dialog()
        table = dialog.product_table
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertNotIn("其他附件/差额", headers)
        self.assertIn("安装板", headers)
        self.assertIn("风机KA1238HA2/B(国产)", headers)
        self.assertEqual(table.item(0, headers.index("安装板")).text(), "30.00")
        self.assertEqual(table.item(0, headers.index("风机KA1238HA2/B(国产)")).text(), "10.00")
        self.assertAlmostEqual(sum(float(table.item(0, c).text().replace(",", ""))
                                   for c in range(9, table.columnCount() - 1)), 190)
        detail = next(r for r in range(dialog.table.rowCount())
                      if dialog.table.item(r, 0).text() == "安装板")
        dialog.table.cellWidget(detail, 5).setValue(80)
        self.assertEqual(table.item(0, headers.index("安装板")).text(), "40.00")
        self.assertEqual(table.item(0, 5).text(), "200.00")

    def test_copies_count_every_occurrence_and_accumulate_detail_money(self):
        copy_button = self.window.scheme2_cost_action_buttons[3]
        for _ in range(3):
            self.window.summary_table.selectRow(0)
            copy_button.click()
        items = self.window.draft_items
        self.assertEqual(len(items), 4)
        self.assertEqual(self.window.summary_table.item(4, 5).text(), "16 项 ›")
        dialog = self.dialog()
        table = dialog.table
        self.assertEqual(table.rowCount(), 4, "detail groups identical specs but not their counts")
        for row, expected in enumerate(((8, 200, 400), (8, 160, 320), (8, 240, 480), (16, 64, 160))):
            actual = tuple(float(table.item(row, c).text().replace(",", "")) for c in (2, 3, 4))
            self.assertEqual(actual, expected)
        self.assertEqual(dialog.product_table.rowCount(), 5)
        self.assertEqual(dialog.product_table.item(4, 3).text(), "8")
        self.assertEqual(dialog.product_table.item(4, 6).text(), "1,520.00")
        table.cellWidget(2, 5).setValue(80)
        self.assertTrue(all(row["quick"]["total_cost"] == 390 for row in items))
        self.assertEqual(table.item(2, 4).text(), "640.00")
        self.assertEqual(dialog.product_table.item(4, 6).text(), "1,600.00")
        dialog.resize(1560, 720)
        dialog.show()
        app.processEvents()
        path = ROOT / "outputs" / "attachment-summary-named-copy.png"
        path.parent.mkdir(exist_ok=True)
        self.assertTrue(dialog.grab().save(str(path)))

    def test_named_custom_material_surcharge_and_quote_fee_difference(self):
        item = self.window.draft_items[0]
        item.update(material_code="SUS316", scheme2_cost_settings={"material_difference": 2.5})
        item["formula"]["corrected_material_weight_kg"] = 10
        item["attachments"].append(dict(custom=True, item_name="木托123", quantity=1,
                                          formula_amount=5, quick_amount=6))
        # Historical totals can have a fee not present in the attachment detail;
        # retain it explicitly, never silently drop it or label it another part.
        item["quick"].update(attachment_fee=180, total_cost=380)
        self.window.refresh_summary()
        dialog = self.dialog()
        table = dialog.product_table
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertIn("木托123", headers)
        self.assertIn("材料差价", headers)
        self.assertIn("附件差额", headers)
        self.assertNotIn("其他附件/差额", headers)
        self.assertEqual(table.item(0, headers.index("材料差价")).text(), "25.00")
        self.assertEqual(table.item(0, headers.index("附件差额")).text(), "2.00")
        self.assertAlmostEqual(sum(float(table.item(0, c).text().replace(",", ""))
                                   for c in range(9, table.columnCount() - 1)),
                               float(table.item(0, 5).text()))

    def test_screenshot_counts_26_times_6_plus_1_times_4_plus_6_times_4(self):
        items = []
        for indexes, copies in ((range(26), 6), (range(1), 4), (range(24, 30), 4)):
            rows = [dict(item_name=f"附件{index}", attachment_price_id=300 + index,
                         quantity=1, formula_amount=2, quick_amount=3) for index in indexes]
            item = dict(name="副本", quantity=1, attachments=rows, quote_line_id="shared-snapshot",
                        quick={"attachment_fee": len(rows) * 3, "total_cost": 100 + len(rows) * 3},
                        formula={"total_cost": 80})
            items.extend(copy.deepcopy(item) for _ in range(copies))
        self.window.draft_items = items
        self.window.refresh_summary()
        self.assertEqual(self.window.summary_table.item(14, 5).text(), "184 项 ›")
        grouped = ui._all_attachment_rows(items)
        self.assertEqual(len(grouped), 30)
        self.assertEqual(sum(row["quantity"] for row in grouped), 184)
        self.assertEqual(sum(row["cost"] for row in grouped), 368)
        self.assertEqual(sum(row["amount"] for row in grouped), 552)


if __name__ == "__main__":
    unittest.main()
