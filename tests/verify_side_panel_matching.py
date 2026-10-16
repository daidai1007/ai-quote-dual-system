"""Side-panel nearest-size and price ratios use cabinet H/D, never W."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import match_attachment_size  # noqa: E402
from attachment_v2_client import merge_cost  # noqa: E402
from scheme2_ui import AttachmentEditor  # noqa: E402


def side(identifier: int, width: int, height: int, depth: int, price: float) -> dict:
    return {
        "attachment_price_id": identifier,
        "category_level1": "侧板",
        "item_name": "JP控制柜侧板",
        "width_mm": width,
        "height_mm": height,
        "depth_mm": depth,
        "price": price,
    }


near = side(1, 9999, 1800, 400, 524.593927)
far = side(2, 700, 1600, 420, 500)
for width in (700, 1400):
    matched = match_attachment_size([near, far], far, (width, 1700, 420))
    assert matched is not None
    assert matched["attachment_price_id"] == 1
    assert matched["size_match_target_perimeter"] == 2120
    assert matched["size_match_perimeter"] == 2200
    assert matched["size_match_ratio"] == 2120 / 2200
    assert matched["unit_price_override"] == round(524.593927 * 2120 / 2200, 6)
    merged = merge_cost(
        {**matched, "quantity": 1},
        {"quantity": 1, "quick_amount": 524.59, "formula_amount": 137.16},
    )
    assert AttachmentEditor._display_amounts(merged) == (137.16, 505.52)

exact = side(3, 9999, 1700, 420, 530)
matched = match_attachment_size([near, exact], near, (700, 1700, 420))
assert matched is not None and matched["attachment_price_id"] == 3
assert matched["size_match_exact"] is True
assert "unit_price_override" not in matched

print("side panel height/depth matching passed")
