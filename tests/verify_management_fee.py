"""Six-component management pricing in shared rules and the recovered client."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtWidgets import QApplication
import quick_discount_rules as pricing
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
Window = ns["MainWindow"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None


def product(quantity=1):
    return dict(name="管理费验证柜", product_code="JP", material_code="SECC",
        specification="800*600*1800", quantity=quantity, freight_fee=50, labor_multiplier=1,
        quick_discount=.5, formula_discount=1,
        quick=dict(base_price=500, attachment_fee=80, total_cost=580),
        formula=dict(material_cost=100, auxiliary_cost=20, labor_cost=30, attachment_fee=40,
                     spray_cost=10, management_fee=3.9, total_cost=203.9),
        formula_base=dict(labor_cost=30),
        attachments=[dict(item_name="风机", quantity=1, status="FIXED", formula_amount=40,
                         formula_unit_cost=40, quick_amount=80, matched_price=80)])


class ManagementFee(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.addCleanup(self.window.close)

    def test_shared_money_fixtures_and_idempotence(self):
        samples = json.loads((ROOT / "tests/fixtures/management_fee.json").read_text(encoding="utf-8"))
        for sample in samples:
            with self.subTest(sample["name"]):
                before = copy.deepcopy(sample["quote"])
                result = pricing.apply_management_fee(sample["quote"], sample["freight"])
                self.assertEqual(result["management_fee_base"], sample["base"])
                self.assertEqual(result["management_fee"], sample["fee"])
                self.assertEqual(result["total_cost"], sample["total"])
                self.assertEqual(pricing.apply_management_fee(result, sample["freight"]), result)
                self.assertEqual(sample["quote"], before)

    def test_je_null_old_fee_and_total_work_in_live_controller_summary_and_export(self):
        item = product()
        item["freight_fee"] = 61.86
        item["formula"] = dict(material_cost=826.52, auxiliary_cost=49.60, labor_cost=332.54,
                               spray_cost=80.65, attachment_fee=None, management_fee=None, total_cost=None,
                               management_fee_rate=.13)
        item["formula_base"] = copy.deepcopy(item["formula"])
        item["attachments"][0]["formula_amount"] = 720.88
        self.window.current_result = dict(formula=copy.deepcopy(item["formula"]), quick=copy.deepcopy(item["quick"]))
        self.window._formula_base_result = copy.deepcopy(item["formula_base"])
        self.window.attachments = copy.deepcopy(item["attachments"])
        # This fixture injects a result directly. Complete the normal AUTO
        # initialization before simulating a subsequent manual freight edit.
        self.window.refresh_discounted_totals()
        self.assertEqual(self.window.freight_state.mode, "AUTO")
        self.assertEqual(self.window.current_result["formula"]["management_fee"], 120.61)
        self.window.freight_spin.setValue(61.86)
        self.window.refresh_discounted_totals()
        self.assertEqual(self.window.freight_spin.value(), 61.86)
        self.assertEqual(self.window.freight_state.mode, "MANUAL")
        self.assertEqual(self.window.current_result["formula"]["management_fee_base"], 2072.05)
        self.assertEqual(self.window.current_result["formula"]["management_fee"], 124.32)
        self.assertEqual(self.window.current_result["formula"]["total_cost"], 2134.51)
        self.window.draft_items = [item]
        self.window.refresh_summary()
        self.assertEqual(ui._row_values(item)[17], 2196.37)
        frozen = ui._quote_export_items_snapshot(self.window, items=[item])[0]
        self.assertEqual(frozen["formula"]["management_fee"], 124.32)
        self.assertEqual(frozen["formula"]["management_fee_rate"], .06)

    def test_manual_attachment_quantity_is_per_whole_set_in_python_too(self):
        row = dict(quantity=2, selection_source='manual', quick_amount=20, formula_amount=14)
        self.assertEqual(pricing.effective_attachment_quantity(row, 3, 4), 6)
        self.assertEqual(pricing.effective_attachment_line_amount(row, 3, 4), 60)
        self.assertEqual(pricing.effective_formula_attachment_line_amount(row, 3, 4), 42)
        children = [dict(row, ganged_cabinet_index=index) for index in range(4)]
        self.assertEqual(sum(pricing.effective_attachment_quantity(child, 3, 4) for child in children), 24)

    def test_missing_actual_cost_component_cannot_be_filled_from_old_total(self):
        item = product()
        del item["formula"]["auxiliary_cost"]
        with self.assertRaisesRegex(ValueError, "辅材成本"):
            ui._quote_export_items_snapshot(self.window, items=[item])

    def test_quantity_freight_popup_cost_and_export_stay_consistent(self):
        item = product(10)
        self.window.draft_items = [item]
        self.window.refresh_summary()
        table = self.window.summary_table
        self.assertEqual(table.item(0, ui.HEADERS.index("管理费用")).text(), "15.00")
        self.assertEqual(ui._row_values(item)[17:19], (265, 2650))
        quick_total = ui._row_values(item)[16]
        item["attachments"][0]["formula_amount"] = 60
        self.window.refresh_summary()
        self.assertEqual(item["formula"]["management_fee"], 16.2)
        self.assertEqual(ui._row_values(item)[17:19], (286.2, 2862))
        self.assertEqual(ui._row_values(item)[16], quick_total)
        table.item(0, ui.HEADERS.index("运费")).setText("100")
        self.assertEqual(item["formula"]["management_fee"], 19.2)
        self.assertEqual(ui._row_values(item)[17:19], (339.2, 3392))
        table.item(0, ui.HEADERS.index("数量")).setText("1")
        self.assertEqual(ui._row_values(item)[17:19], (339.2, 339.2))
        snapshot = ui._quote_export_items_snapshot(self.window)[0]
        self.assertEqual(snapshot["formula"]["management_fee"], 19.2)
        rows = ui._detail_rows(snapshot)
        fee = [row for row in rows if row["category"] == "management_fee"]
        self.assertEqual(len(fee), 1)
        self.assertEqual(fee[0]["base_amount"], 19.2)
        self.assertIn("运费", fee[0]["spec"])

    def test_ganged_management_is_one_whole_set_fee(self):
        item = product(3)
        item.update(ganged_cabinet_count=2, ganged_cabinets=[{}, {}])
        child = dict(material_cost=50, auxiliary_cost=10, labor_cost=15, spray_cost=5,
                     attachment_fee=0, management_fee=1.95, total_cost=81.95)
        item["formula"]["ganged_cabinet_costs"] = [dict(formula_cost=copy.deepcopy(child)) for _ in range(2)]
        self.window.draft_items = [item]
        self.window.refresh_summary()
        self.assertEqual(item["formula"]["management_fee"], 15)
        self.assertEqual(ui._row_values(item)[17:19], (265, 795))
        fees = [row for row in ui._detail_rows(item) if row["category"] == "management_fee"]
        self.assertEqual(len(fees), 1)
        self.assertEqual(fees[0]["base_amount"], 15)

    def test_labor_multiplier_changes_only_cabinet_labor_and_fee_base(self):
        item = product()
        self.window.draft_items = [item]
        self.window.refresh_summary()
        self.window.summary_table.selectRow(0)
        ui._apply_cost_control(self.window, "labor_discount", .5)
        self.assertEqual(item["formula"]["labor_cost"], 15)
        self.assertEqual(item["formula"]["attachment_fee"], 40)
        self.assertEqual(item["formula"]["management_fee"], 14.1)
        self.assertEqual(ui._row_values(item)[17], 249.1)


if __name__ == "__main__":
    unittest.main()
