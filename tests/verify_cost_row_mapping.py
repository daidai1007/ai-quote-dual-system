import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QTableWidget
import scheme2_ui

app = QApplication.instance() or QApplication([])
item = {
    "name": "测试柜", "product_code": "JP", "specification": "800*800*1800", "quantity": 2,
    "material_code": "SECC",
    "quick_discount": 0.9, "quick": {"total_cost": 500},
    "formula": {"total_cost": 300, "material_cost": 100, "auxiliary_cost": 20,
                "labor_cost": 30, "attachment_fee": 40, "spray_cost": 50,
                "management_fee": 60, "corrected_material_weight_kg": 12.345,
                "material_details": [
                    {"material_code": "SUS316", "billable_weight_kg": 10.0},
                    {"material_code": "SGCC", "billable_weight_kg": 2.345},
                ]},
    "freight_fee": 10, "attachments": [{"item_name": "附件", "quantity": 1, "quick_amount": 0, "formula_amount": 40}],
}
table = QTableWidget(0, len(scheme2_ui.HEADERS))
window = SimpleNamespace(summary_table=table, draft_items=[item], _scheme2_refreshing=False)
scheme2_ui._refresh_cost_table(window)
actual = [table.item(0, column).text() for column in range(table.columnCount())]
# Current baseline: fixed bucket excludes discountable cabinet face price;
# manufacturing is 460*4%=18.4, management is 460*5%=23.
assert actual[4:13] == ["2", "1 项 ›", "0.00", "10.00", "—", "0.9", "460.00", "920.00", "327.40"], actual
assert actual[13:21] == ["100.00", "20.00", "30.00", "40.00", "50.00", "23.00", "10.00", "654.80"]
assert actual[21:] == ["41.65%", "12.35", "明细 ›", "450.00", "28.83%", "18.40", "10.00", "36.00"]
assert table.isColumnHidden(scheme2_ui.MATERIAL_DIFFERENCE_COLUMN)
assert [table.item(0, column).background().color().name().upper() for column in (0, 5, 7, 12, 21, 22, 23)] == [
    "#FFFFFF", "#F5F6F8", "#FFF7E6", "#F0F6FD", "#F5F0FA", "#ECF4F1", "#F5F6F8",
]
assert table.item(0, 21).foreground().color().name().upper() == "#D97706"

item["material_code"] = "SUS316"
item["scheme2_cost_settings"] = {"material_difference": 25.0}
scheme2_ui._refresh_cost_table(window)
assert not table.isColumnHidden(scheme2_ui.MATERIAL_DIFFERENCE_COLUMN)
assert table.item(0, 8).text() == "250.00"
assert table.item(0, 7).text() == "260.00"
assert table.item(0, 10).text() == "710.00"
assert table.item(0, 11).text() == "1,420.00"
table.close()
print("PASS: cost row values align with all 29 conditional headers")
