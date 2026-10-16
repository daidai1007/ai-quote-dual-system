"""Fixed-column catalogue matching and pricing depend on height only."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import match_attachment_size  # noqa: E402
from attachment_v2_client import merge_cost  # noqa: E402
from scheme2_ui import AttachmentEditor  # noqa: E402


def column(identifier: int, width: int, height: int, depth: int) -> dict:
    return {
        "attachment_price_id": identifier,
        "category_level1": "安装附件",
        "category_level2": "固定立柱",
        "item_name": "固定立柱",
        "width_mm": width,
        "height_mm": height,
        "depth_mm": depth,
        "price": 100,
    }


height_exact = column(1, 9999, 1800, 9999)
width_depth_exact = column(2, 700, 1600, 420)
for width, depth in ((700, 420), (1400, 800)):
    target = (width, 1800, depth)
    matched = match_attachment_size([height_exact, width_depth_exact], width_depth_exact, target)
    assert matched is not None and matched["attachment_price_id"] == 1
    assert matched["size_match_exact"] is True
    assert matched["size_match_target_perimeter"] == 1800
    assert matched["size_match_perimeter"] == 1800

    scaled = match_attachment_size([width_depth_exact], width_depth_exact, target)
    assert scaled is not None
    assert scaled["size_match_ratio"] == 1800 / 1600
    assert scaled["unit_price_override"] == 112.5
    merged = merge_cost(
        {**scaled, "quantity": 2},
        {"quantity": 2, "quick_amount": 200, "formula_amount": 40},
    )
    assert AttachmentEditor._display_amounts(merged) == (40, 225)

print("fixed column height-only matching passed")
