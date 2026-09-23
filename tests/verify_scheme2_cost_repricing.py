from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QTableWidget  # noqa: E402
import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
assert scheme2_ui.STAINLESS_DEFAULT_PRICES == {"SUS304": 16.0, "SUS316": 32.4}
assert scheme2_ui.SURFACE_DEFAULT_PRICES == {"橘纹": 26.0, "平光": 30.0, "无": 0.0}
assert [scheme2_ui._surface_default_price(value) for value in ("橘纹", "平光", "无")] == [26.0, 30.0, 0.0]
source = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
assert 'setPrefix(f"{coating} ")' not in source and 'setPrefix("橘纹 ")' not in source
table = QTableWidget(1, 1)
table.setCurrentCell(0, 0)
formula = {
    "material_cost": 197.75,
    "labor_cost": 80.0,
    "spray_cost": 40.0,
    "management_fee": 10.0,
    "management_fee_rate": 0.125,
    "total_cost": 327.75,
    "material_details": [
        {"material_code": "SUS304", "billable_weight_kg": 10.0, "material_unit_price": 17.5},
        {"material_code": "SECC", "billable_weight_kg": 5.0, "material_unit_price": 4.55},
    ],
}
item = {
    "material_code": "SUS304", "waste_factor": 1.2, "formula": formula,
    "formula_base": {"labor_cost": 80.0},
    "scheme2_cost_settings": {
        "galvanized_price": 4.55, "carbon_price": 4.2, "stainless_price": 17.5,
        "waste_factor": 1.2, "labor_discount": 1.0, "surface_price": 26.0,
    },
}
window = SimpleNamespace(
    summary_table=table, draft_items=[item], refresh_summary=lambda: None,
    scheme2_defaults=dict(item["scheme2_cost_settings"]),
)

scheme2_ui._apply_cost_control(window, "stainless_price", 20.0)
assert formula["material_cost"] == 222.75
scheme2_ui._apply_cost_control(window, "waste_factor", 1.5)
assert formula["material_cost"] == 278.44
scheme2_ui._apply_cost_control(window, "labor_discount", 0.8)
assert formula["labor_cost"] == 64.0 and formula["management_fee"] == 8.0
scheme2_ui._apply_cost_control(window, "surface_price", 30.0)
assert formula["spray_cost"] == 46.15
assert formula["total_cost"] == 396.59
scheme2_ui._apply_cost_control(window, "surface_price", 0.0)
assert formula["spray_cost"] == 0.0
assert formula["total_cost"] == 350.44
assert scheme2_ui._current_material_unit_price(item) == 20.0
print("scheme2 cost repricing contract passed")
