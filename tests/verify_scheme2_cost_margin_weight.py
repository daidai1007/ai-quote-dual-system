from types import SimpleNamespace
from pathlib import Path
import sys
import unittest

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop_client'))
import scheme2_ui


app = QApplication.instance() or QApplication([])


def sample_item():
    return {
        "quantity": 2,
        "quick_discount": 0.8,
        "freight_mode": "MANUAL", "freight_fee": 0,
        "quick": {"total_cost": 1000},
        "formula": {"material_cost":400,"auxiliary_cost":50,"labor_cost":50,
                    "attachment_fee":0,"spray_cost":50,"management_fee":33,
                    "total_cost":583,"corrected_material_weight_kg":42.5},
    }


def test_margin_and_billable_weight_columns():
    values = scheme2_ui._row_values(sample_item())
    assert scheme2_ui.HEADERS[21:24] == ("毛利率", "自制件重量", "成本明细")
    # 550 base cost + 6% management = 583 per cabinet; quantity is two.
    assert values[16] == 1600 and values[18] == 1166
    assert values[19] == "27.12%" and values[20] == "42.50" and values[21] == "明细 ›"


def test_discount_coefficient_is_directly_editable_like_freight():
    item = sample_item()
    table = QTableWidget(1, len(scheme2_ui.HEADERS))
    table.setItem(0, 9, QTableWidgetItem("0.75"))
    window = SimpleNamespace(_scheme2_refreshing=False, draft_items=[item], summary_table=table)
    window.refresh_summary = lambda: None
    scheme2_ui._cost_cell_changed(window, 0, 9)
    assert item["quick_discount"] == 0.75


def test_navigation_uses_its_own_quieter_type_token():
    style = scheme2_ui._typography_style_sheet()
    rule = style[style.index("QFrame#navPanel QPushButton {"):]
    assert f"font-size:{scheme2_ui.NAVIGATION_PX}px" in rule.split("}", 1)[0]
    assert scheme2_ui.NAVIGATION_PX < scheme2_ui.PAGE_TITLE_PX


if __name__=='__main__':
    suite=unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_margin_and_billable_weight_columns,
        test_discount_coefficient_is_directly_editable_like_freight,
        test_navigation_uses_its_own_quieter_type_token))
    result=unittest.TextTestRunner().run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
