from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from desktop_client import scheme2_ui


app = QApplication.instance() or QApplication([])


def sample_item():
    return {
        "quantity": 2,
        "quick_discount": 0.8,
        "quick": {"total_cost": 1000},
        "formula": {"total_cost": 600, "corrected_material_weight_kg": 42.5},
    }


def test_margin_and_billable_weight_columns():
    values = scheme2_ui._row_values(sample_item())
    assert scheme2_ui.HEADERS[19:22] == ("毛利率", "自制件重量", "成本明细")
    assert values[16] == 1600 and values[18] == 1200
    assert values[19] == "25.00%" and values[20] == "42.50" and values[21] == "明细 ›"


def test_discount_coefficient_is_directly_editable_like_freight():
    item = sample_item()
    table = QTableWidget(1, len(scheme2_ui.HEADERS))
    table.setItem(0, 14, QTableWidgetItem("0.75"))
    window = SimpleNamespace(_scheme2_refreshing=False, draft_items=[item], summary_table=table)
    window.refresh_summary = lambda: None
    scheme2_ui._cost_cell_changed(window, 0, 14)
    assert item["quick_discount"] == 0.75


def test_navigation_font_is_two_pixels_larger():
    source = open(scheme2_ui.__file__, encoding="utf-8").read()
    rule = source[source.index("QFrame#navPanel QPushButton {"):]
    assert "font-size:15px" in rule.split("}", 1)[0]
