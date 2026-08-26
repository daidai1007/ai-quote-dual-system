"""Offline regressions for attachment size matching and door-count defaults."""

from __future__ import annotations

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import (  # noqa: E402
    completed_size_dimensions,
    door_reinforcement_default_quantity,
    match_attachment_size,
    size_match_attachment_name,
)


def row(identifier, name, width, height, depth, price, model=""):
    return {
        "attachment_price_id": identifier,
        "category_level1": name,
        "item_name": name,
        "model_code": model,
        "width_mm": width,
        "height_mm": height,
        "depth_mm": depth,
        "price": price,
    }


exact = row(1, "固定底座", 1000, 100, 600, 200)
near = row(2, "固定底座", 900, 100, 600, 180)
matched = match_attachment_size([near, exact], near, (1000, 100, 600))
assert matched is not None
assert matched["attachment_price_id"] == 1
assert matched["size_match_exact"] is True
assert matched["matched_price"] == 200
assert "unit_price_override" not in matched

scaled = match_attachment_size([near], near, (1000, 100, 600))
assert scaled is not None
assert scaled["attachment_price_id"] == 2
assert scaled["size_match_exact"] is False
assert math.isclose(scaled["size_match_ratio"], 1700 / 1600)
assert math.isclose(scaled["unit_price_override"], 191.25)

# Same perimeter difference and squared distance: completed tuple/model/id
# provide a deterministic final choice independent of input order.
tie_a = row(10, "分段板", 900, 2000, 600, 100, "A10")
tie_b = row(11, "分段板", 1000, 1900, 600, 110, "A2")
first = match_attachment_size([tie_b, tie_a], tie_a, (950, 1950, 600))
second = match_attachment_size([tie_a, tie_b], tie_a, (950, 1950, 600))
assert first is not None and second is not None
assert first["attachment_price_id"] == second["attachment_price_id"] == 10

# Missing catalogue values are completed only for matching metadata. The raw
# database H/D fields remain missing on the selected record.
missing = row(20, "通风顶罩", 1000, None, None, 80)
completed = completed_size_dimensions(missing, (1000, 2000, 600))
assert completed == (1000.0, 2000.0, 600.0)
filled_match = match_attachment_size([missing], missing, (1000, 2000, 600))
assert filled_match is not None
assert filled_match["height_mm"] is None and filled_match["depth_mm"] is None
assert filled_match["size_match_height_mm"] == 2000
assert filled_match["size_match_depth_mm"] == 600

unsafe = row(21, "防雨顶", 1000, 2000, 600, "100-120")
unsafe_match = match_attachment_size([unsafe], unsafe, (1050, 2000, 600))
assert unsafe_match is not None
assert "unit_price_override" not in unsafe_match
assert "未执行比例折价" in unsafe_match["size_match_warning"]

for name in ("固定底座", "活动底座", "侧板", "安装板", "内门", "玻璃门", "通风顶罩", "防雨顶", "分段板", "JK安装板"):
    assert size_match_attachment_name({"item_name": name}) == name
assert size_match_attachment_name({"item_name": "门限位器"}) is None
assert size_match_attachment_name({"item_name": "安装板单发"}) is None

expected_quantities = {(1, 0): 1, (2, 0): 2, (0, 1): 2, (0, 2): 4, (1, 1): 3}
for counts, expected in expected_quantities.items():
    assert door_reinforcement_default_quantity(*counts) == expected

print("attachment size and reinforcement regressions passed")
