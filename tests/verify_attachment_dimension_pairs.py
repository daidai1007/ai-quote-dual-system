"""Pairwise nearest-size matching for doors, segment panels and rain covers."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import (  # noqa: E402
    match_attachment_size, size_match_display_text, size_match_target_dimensions,
)


def row(name: str, identifier: int, width: int, height, depth, category="控制柜附件") -> dict:
    return {
        "attachment_price_id": identifier,
        "category_level1": category,
        "category_level2": name,
        "item_name": name,
        "width_mm": width,
        "height_mm": height,
        "depth_mm": depth,
        "price": 100,
    }


for name, category in (("内门", "控制柜附件"), ("玻璃门", "控制箱附件"), ("分段板", "安装附件")):
    face_match = row(name, 1, 700, 1700, 9999, category)
    depth_match = row(name, 2, 600, 1600, 420, category)
    matched = match_attachment_size([depth_match, face_match], depth_match, (700, 1700, 420))
    assert matched is not None and matched["attachment_price_id"] == 1
    assert matched["size_match_exact"] is True
    scaled = match_attachment_size([depth_match], depth_match, (700, 1700, 420))
    assert scaled is not None
    assert scaled["size_match_ratio"] == 2400 / 2200
    assert scaled["unit_price_override"] == round(100 * 2400 / 2200, 6)
    assert match_attachment_size([depth_match], depth_match, (700, 1700, 800))["unit_price_override"] == scaled["unit_price_override"]
    assert size_match_display_text(face_match) == "宽 700 × 高 1700 mm"

for category, stored in (("控制箱附件", (None, 400)), ("控制柜附件", (400, None))):
    close = row("防雨顶", 1, 700, stored[0], stored[1], category)
    farther = row("防雨顶", 2, 600, stored[0], stored[1], category)
    matched = match_attachment_size([farther, close], farther, (700, 1700, 420))
    assert matched is not None and matched["attachment_price_id"] == 1
    assert matched["size_match_target_perimeter"] == 1120
    assert matched["size_match_perimeter"] == 1100
    assert matched["size_match_depth_mm"] == 400
    assert matched["unit_price_override"] == round(100 * 1120 / 1100, 6)
    assert match_attachment_size([close], close, (700, 2200, 420))["unit_price_override"] == matched["unit_price_override"]
    assert size_match_display_text(close) == "宽 700 × 深 400 mm"

glass = row("玻璃门", 11, 400, 500, 9999)
glass["manual_inputs"] = {"玻璃门宽度": 400, "玻璃门高度": 500}
assert size_match_target_dimensions(glass, (800, 1800, 600)) == (400, 500, 600)
assert match_attachment_size([glass], glass, (800, 1800, 600))["size_match_exact"] is True
segment = row("分段板", 12, 800, 150, None, "安装附件")
segment["manual_inputs"] = {"分段板高度": 150}
assert size_match_target_dimensions(segment, (800, 1800, 600)) == (800, 150, 600)
assert match_attachment_size([segment], segment, (800, 1800, 600))["size_match_exact"] is True

print("attachment W/H and W/D matching passed")
