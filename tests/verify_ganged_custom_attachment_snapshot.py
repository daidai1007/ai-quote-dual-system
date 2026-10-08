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
