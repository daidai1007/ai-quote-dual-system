"""Focused recovered-client checks for cabinet + current-popup weight statistics."""
import copy
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
Window = ns["MainWindow"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None


def product(quantity=1):
    return dict(name="重量验证柜", product_code="JP", material_code="SECC",
        specification="800*600*1800", quantity=quantity, freight_fee=70,
        quick_discount=0.75, quick=dict(base_price=500, attachment_fee=20, total_cost=520),
        formula=dict(total_cost=320, attachment_fee=20, corrected_material_weight_kg=42.5),
        attachments=[dict(item_name="侧板", quantity=2, weight_kg=2.5,
            formula_amount=20, quick_amount=20, formula_unit_cost=10)])


class SelfMadeWeight(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.addCleanup(self.window.close)

    def show(self, items):
        self.window.draft_items = items
        self.window.refresh_summary()
        return self.window.summary_table

    def test_ordinary_row_is_per_cabinet_and_footer_scales_by_order_quantity(self):
        item = product(10)
        table = self.show([item])
        column = ui.HEADERS.index("自制件重量")
        self.assertEqual(table.item(0, column).text(), "47.50")
        self.assertEqual(table.item(1, column).text(), "475.00")
        table.item(0, ui.HEADERS.index("数量")).setText("2")
        self.assertEqual(table.item(0, column).text(), "47.50")
        self.assertEqual(table.item(1, column).text(), "95.00")
        self.assertIn("无有效重量数据", table.item(0, column).toolTip())

    def test_ganged_children_and_selected_attachments_are_not_counted_twice(self):
        item = product(3)
        item.update(ganged_cabinet_count=2, ganged_cabinets=[{}, {}])
        item["formula"].update(corrected_material_weight_kg=100,
            ganged_cabinet_costs=[{"formula_cost": {"corrected_material_weight_kg": 40}},
                                  {"formula_cost": {"corrected_material_weight_kg": 60}}])
        item["attachments"] = [dict(item_name="固定底座", weight_kg=3, quantity=1, ganged_cabinet_index=0),
            dict(item_name="固定底座", weight_kg=4, quantity=2, ganged_cabinet_index=1)]
        table = self.show([item])
        column = ui.HEADERS.index("自制件重量")
        self.assertEqual(table.item(0, column).text(), "111.00")
        self.assertEqual(table.item(1, column).text(), "333.00")

    def test_popup_quantity_edit_immediately_updates_weight(self):
        item = product()
        self.show([item])
        editor = ui.AttachmentEditor(self.window, item)
        self.addCleanup(editor.close)
        editor.table.cellWidget(0, editor.COL_QUANTITY).setValue(3)
        editor.accept()
        self.assertEqual(item["attachments"][0]["weight_kg"], 2.5)
        self.assertEqual(item["attachments"][0]["quantity"], 3)
        self.assertEqual(self.window.summary_table.item(0, ui.HEADERS.index("自制件重量")).text(), "50.00")

    def test_installation_board_deduction_reduces_weight(self):
        item = product()
        item["attachments"] = [dict(item_name="安装板", weight_kg=2, quantity=2, attachment_price_sign=-1)]
        self.assertEqual(ui._self_made_weight(item), 38.5)
        item["attachments"][0].update(quantity=-2, attachment_price_sign=1)
        self.assertEqual(ui._self_made_weight(item), 38.5)

    def test_missing_or_unfinished_attachment_weight_is_not_estimated_from_prices(self):
        item = product()
        item["attachments"] = [dict(item_name="风机", quantity=4, quick_amount=480),
            dict(item_name="玻璃门", quantity=2, weight_kg=None),
            dict(weight_kg=float("nan"), quantity=1), dict(weight_kg=float("inf"), quantity=1),
            dict(weight_kg=9, quantity=1, status="PENDING_MANUAL"),
            dict(weight_kg=9, quantity=1, status="ERROR"),
            dict(weight_kg=9, quantity=1, pending_manual_dimensions=["高度"])]
        self.assertEqual(ui._self_made_weight(item), 42.5)

    def test_cabinet_waste_and_attachment_unit_weight_are_applied_once(self):
        item = product()
        item["formula"].update(net_material_weight_kg=100, corrected_material_weight_kg=120, waste_factor=1.2)
        item["attachments"] = [dict(weight_kg=2, quantity=2)]
        self.assertEqual(ui._self_made_weight(item), 124)

    def test_weight_only_changes_do_not_change_material_cost_freight_or_quote(self):
        item = product()
        before = copy.deepcopy(item)
        values = ui._row_values(item)
        item["attachments"][0]["weight_kg"] = 8
        updated = ui._row_values(item)
        self.assertEqual(updated[:20], values[:20])
        self.assertNotEqual(updated[20], values[20])
        self.assertEqual(item["formula"], before["formula"])
        self.assertEqual(item["freight_fee"], before["freight_fee"])

    def test_footer_uses_full_weight_precision_before_display_rounding(self):
        item = product(100)
        item["formula"]["corrected_material_weight_kg"] = 0
        item["attachments"] = [dict(weight_kg=0.004, quantity=1)]
        table = self.show([item])
        column = ui.HEADERS.index("自制件重量")
        self.assertEqual(table.item(0, column).text(), "0.00")
        self.assertEqual(table.item(1, column).text(), "0.40")


if __name__ == "__main__":
    unittest.main()
