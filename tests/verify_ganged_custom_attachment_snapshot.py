from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh  # noqa: E402


v2_attachment = {
    "attachment_price_id": 9001,
    "item_name": "固定底座",
    "category_level1": "底座",
    "catalog_version": "attachment-test-v2",
    "quantity": 1,
    "attachment_price_sign": 1,
    "manual_inputs": {},
}
custom_attachment = {
    "item_name": "底座加强筋",
    "category_level1": "其他附件",
    "quantity": 1,
    "custom": True,
    "formula_amount": 10,
    "quick_amount": 12,
    "manual_inputs": {"备注": "并柜新增附件"},
}

window = SimpleNamespace(
    attachments=[v2_attachment, custom_attachment],
    ganged_cabinets=[
        {"width_mm": 600, "height_mm": 1800, "depth_mm": 500},
        {"width_mm": 800, "height_mm": 1800, "depth_mm": 500},
    ],
    selected_product_code=lambda: "JP_SINGLE",
)
payload = layout_refresh._build_ganged_attachment_payload(
    window, [{"quote_id": "TMP-1"}]
)
assert payload is not None
assert window._v2_custom_attachments == [custom_attachment]
assert window._v2_custom_attachments[0] is not custom_attachment
assert window._v2_custom_attachments[0]["manual_inputs"] is not custom_attachment["manual_inputs"]
assert payload["attachments"] == [{
    "attachment_price_id": 9001,
    "quantity": 1,
    "attachment_price_sign": 1,
    "manual_inputs": {},
}]

window.attachments.append({"item_name": "旧目录附件", "quantity": 1})
try:
    layout_refresh._build_ganged_attachment_payload(window, [{"quote_id": "TMP-2"}])
except ValueError as error:
    assert "新旧目录数据" in str(error)
else:
    raise AssertionError("real legacy catalogue rows must still be rejected")

print("ganged custom attachment snapshot passed")

# The attachment snapshot is a distinct API request, so it must retain the
# same sidebar material prices used for both child-cabinet calculations.  The
# two automatic fixed bases must also keep their own child index and base
# height, while the custom row remains local-only.
first_base = {
    **v2_attachment,
    "attachment_price_id": 1043,
    "ganged_fixed_base_index": 0,
    "ganged_fixed_base_match": True,
    "required_parameters": [{"name": "底座高度", "source": "MANUAL"}],
}
second_base = {
    **v2_attachment,
    "attachment_price_id": 1042,
    "ganged_fixed_base_index": 1,
    "ganged_fixed_base_match": True,
    "required_parameters": [{"name": "底座高度", "source": "MANUAL"}],
}
window = SimpleNamespace(
    attachments=[first_base, second_base, custom_attachment],
    ganged_cabinets=[
        {"width_mm": 800, "height_mm": 1800, "depth_mm": 800, "base_height_mm": 100},
        {"width_mm": 600, "height_mm": 1800, "depth_mm": 800, "base_height_mm": 100},
    ],
    selected_product_code=lambda: "JP_SINGLE",
)
child_payloads = [
    {
        "quote_id": "TMP-BASE-1",
        "material_unit_price_override": 4.2,
        "galvanized_sheet_unit_price_override": 4.55,
        "carbon_steel_unit_price_override": 4.2,
        "surface_treatment_unit_price_override": 26.0,
    },
    {"quote_id": "TMP-BASE-2"},
]
payload = layout_refresh._build_ganged_attachment_payload(window, child_payloads)
assert payload["material_unit_price_override"] == 4.2
assert payload["galvanized_sheet_unit_price_override"] == 4.55
assert payload["carbon_steel_unit_price_override"] == 4.2
assert payload["surface_treatment_unit_price_override"] == 26.0
assert [row["ganged_cabinet_index"] for row in payload["attachments"]] == [0, 1]
assert [row["manual_inputs"]["底座高度"] for row in payload["attachments"]] == [100.0, 100.0]
assert len(payload["attachments"]) == 2
assert window._v2_custom_attachments == [custom_attachment]
assert layout_refresh._ganged_error_text(
    '{"error":"attachment_ganged_snapshot_failed","message":"当前材质价格必须由成本计算副导航栏提供有效正数"}'
) == "当前材质价格必须由成本计算副导航栏提供有效正数"

print("ganged fixed-base snapshot prices passed")
