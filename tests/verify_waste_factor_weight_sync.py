from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop_client.cost_adjustments import rescale_material_weight


formula = {
    "corrected_material_weight_kg": 18.0,
    "material_details": [
        {"material_code": "SECC", "billable_weight_kg": 12.0},
        {"material_code": "SGCC", "billable_weight_kg": 6.0},
    ],
    "cabinet_material_part_details": [
        {"part_name": "柜体", "billable_weight_kg": 12.0, "waste_factor": 1.2},
        {"part_name": "安装板", "billable_weight_kg": 6.0, "waste_factor": 1.2},
    ],
}

ratio = rescale_material_weight(formula, 1.0, 1.2)
assert ratio == 1.0 / 1.2
assert formula["corrected_material_weight_kg"] == 15.0
assert [row["billable_weight_kg"] for row in formula["material_details"]] == [10.0, 5.0]
assert [row["billable_weight_kg"] for row in formula["cabinet_material_part_details"]] == [10.0, 5.0]
assert all(row["waste_factor"] == 1.0 for row in formula["cabinet_material_part_details"])

# Repeated edits must always use the original snapshot, not compound rounding.
rescale_material_weight(formula, 1.5, 1.2)
assert formula["corrected_material_weight_kg"] == 22.5
assert [row["billable_weight_kg"] for row in formula["material_details"]] == [15.0, 7.5]

source = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
assert 'item.pop("cost_detail_rows", None)' in source
assert "rescale_material_weight(formula, value, original)" in source
print("waste factor weight/detail synchronization passed")
