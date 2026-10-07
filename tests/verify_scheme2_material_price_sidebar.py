from pathlib import Path
from types import SimpleNamespace
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QFrame, QLabel, QTableWidget
import scheme2_ui

app = QApplication.instance() or QApplication([])
controls = {key: QDoubleSpinBox() for key in (
    "galvanized_price", "carbon_price", "stainless_price",
    "material_difference", "waste_factor", "labor_discount", "surface_price",
)}
defaults = {
    "galvanized_price": 4.55, "carbon_price": 4.2, "stainless_price": 16.0,
    "material_difference": 25.0,
    "waste_factor": 1.2, "labor_discount": 1.0, "surface_price": 26.0,
}
table = QTableWidget(0, len(scheme2_ui.HEADERS))
compact_key = QComboBox()
for key in controls:
    compact_key.addItem(key, key)
compact_key.setCurrentIndex(compact_key.findData("material_difference"))
item = {
    "material_code": "SUS304",
    "scheme2_cost_settings": {**defaults, "stainless_price": 16.0},
    "formula": {}, "quick": {}, "quantity": 1,
}
window = SimpleNamespace(
    summary_table=table, draft_items=[item], scheme2_defaults=defaults,
    scheme2_cost_controls=controls, scheme2_material_price_label=QLabel(),
    scheme2_stainless_price_field=QFrame(), scheme2_stainless_price_label=QLabel(),
    scheme2_material_difference_field=QFrame(),
    scheme2_compact_key=compact_key, scheme2_compact_value=QDoubleSpinBox(),
    refresh_summary=lambda: None,
)

scheme2_ui._refresh_cost_table(window)
table.selectRow(0)
scheme2_ui._refresh_cost_table(window)
assert window.scheme2_stainless_price_label.text() == "SUS304价格"
assert not window.scheme2_stainless_price_field.isHidden()
assert controls["stainless_price"].value() == 16.0
assert window.scheme2_material_difference_field.isHidden()
assert compact_key.currentData() != "material_difference"

item["material_code"] = "SUS316"
item["scheme2_cost_settings"]["stainless_price"] = 32.4
scheme2_ui._refresh_cost_table(window)
assert window.scheme2_stainless_price_label.text() == "SUS316价格"
assert controls["stainless_price"].value() == 32.4
assert not window.scheme2_material_difference_field.isHidden()
assert controls["material_difference"].value() == 25.0
assert not compact_key.view().isRowHidden(compact_key.findData("material_difference"))
scheme2_ui._apply_cost_control(window, "material_difference", 30.0)
assert item["scheme2_cost_settings"]["material_difference"] == 30.0

sus304_item = {
    "material_code": "SUS304", "scheme2_cost_settings": {**defaults, "stainless_price": 16.0},
    "formula": {}, "quick": {}, "quantity": 1,
}
window.draft_items = [item, sus304_item]
window.material_combo = QComboBox()
window.material_combo.addItem("不锈钢 SUS316", "SUS316")
window.material_combo.addItem("不锈钢 SUS304", "SUS304")
window.material_combo.setCurrentIndex(1)
scheme2_ui._refresh_cost_table(window)
table.selectRow(0)
scheme2_ui._select_cost_item_for_current_material(window)
assert table.currentRow() == 1
assert window.scheme2_stainless_price_label.text() == "SUS304价格"
assert controls["stainless_price"].value() == 16.0
assert window.scheme2_material_difference_field.isHidden()
print("scheme2 material price sidebar contract passed")
