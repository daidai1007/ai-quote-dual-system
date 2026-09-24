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
    "quick_discount": 0.9, "quick": {"total_cost": 500},
    "formula": {"total_cost": 300, "material_cost": 100, "auxiliary_cost": 20,
                "labor_cost": 30, "attachment_fee": 40, "spray_cost": 50,
                "management_fee": 60, "corrected_material_weight_kg": 12.345},
    "freight_fee": 10, "attachments": [{"item_name": "附件"}],
}
table = QTableWidget(0, len(scheme2_ui.HEADERS))
window = SimpleNamespace(summary_table=table, draft_items=[item], _scheme2_refreshing=False)
scheme2_ui._refresh_cost_table(window)
actual = [table.item(0, column).text() for column in range(table.columnCount())]
assert actual[4:11] == ["2", "1 项 ›", "510.00", "0.9", "459.00", "918.00", "310.00"]
assert actual[11:19] == ["100.00", "20.00", "30.00", "40.00", "50.00", "60.00", "10.00", "620.00"]
assert actual[19:] == ["32.46%", "12.35", "明细 ›"]
assert [table.item(0, column).background().color().name().upper() for column in (0, 5, 6, 10, 19, 20, 21)] == [
    "#FFFFFF", "#F5F6F8", "#FFF7E6", "#F0F6FD", "#F5F0FA", "#ECF4F1", "#F5F6F8",
]
assert table.item(0, 19).foreground().color().name().upper() == "#D97706"
table.close()
print("PASS: cost row values align with all 22 visible headers")
