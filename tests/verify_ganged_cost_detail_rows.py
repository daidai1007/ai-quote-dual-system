from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import scheme2_ui  # noqa: E402


def child_formula(material, auxiliary, labor, spray, management, total):
    return {
        "material_cost": material,
        "auxiliary_cost": auxiliary,
        "labor_cost": labor,
        "attachment_fee": 0,
        "spray_cost": spray,
        "management_fee": management,
        "total_cost": total,
    }


item = {
    "formula": {
        "material_cost": 250,
        "auxiliary_cost": 50,
        "labor_cost": 75,
        "attachment_fee": 12,
        "spray_cost": 100,
        "management_fee": 25,
        "total_cost": 512,
        "ganged_cabinet_costs": [
            {
                "cabinet_index": 1,
                "model_code": "1000*600*(2100+100)",
                "formula_cost": child_formula(100, 20, 30, 40, 10, 200),
            },
            {
                "cabinet_index": 2,
                "model_code": "1000*600*(2100+100)",
                "formula_cost": child_formula(150, 30, 45, 60, 15, 300),
            },
        ],
    }
}

rows = scheme2_ui._detail_rows(item)
assert any(row["type"].startswith("柜体1\n") for row in rows)
assert any(row["type"].startswith("柜体2\n") for row in rows)
assert all(row.get("_scheme2_version") == 3 for row in rows)
attachment_rows = [row for row in rows if row["category"] == "attachment_fee"]
assert len(attachment_rows) == 1
assert attachment_rows[0]["type"] == "并柜附件"
assert attachment_rows[0]["base_amount"] == 12
assert sum(float(row["base_amount"]) for row in rows) == 512

print("ganged cost detail rows passed")
