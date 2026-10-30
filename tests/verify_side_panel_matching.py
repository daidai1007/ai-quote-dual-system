"""Side panels match depth before H+D; price ratios still use H/D, never W."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import match_attachment_size  # noqa: E402
from attachment_v2_client import merge_cost, match_catalog_attachment  # noqa: E402
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
    assert matched["attachment_price_id"] == 2
    assert matched["size_match_target_perimeter"] == 2120
    assert matched["size_match_perimeter"] == 2020
    assert matched["size_match_ratio"] == 2120 / 2020
    assert matched["unit_price_override"] == round(500 * 2120 / 2020, 6)
    merged = merge_cost(
        {**matched, "quantity": 1},
        {"quantity": 1, "quick_amount": 500, "formula_amount": 137.16},
    )
    assert AttachmentEditor._display_amounts(merged) == (137.16, 524.75)

exact = side(3, 9999, 1700, 420, 530)
matched = match_attachment_size([near, exact], near, (700, 1700, 420))
assert matched is not None and matched["attachment_price_id"] == 3
assert matched["size_match_exact"] is True
assert "unit_price_override" not in matched

# Matching perimeter alone must not outrank the correct depth.
wrong_depth = side(4, 700, 1600, 520, 400)  # H+D=2120 exactly.
assert match_attachment_size([wrong_depth, far],far,(700,1700,420))['attachment_price_id']==2
# Without an exact depth, compare depth distance before perimeter distance.
closest_depth = side(5, 1, 2200, 430, 700)
assert match_attachment_size([wrong_depth,closest_depth],wrong_depth,(700,1700,420))['attachment_price_id']==5
# Equal depth (including equal nonzero depth distance): perimeter decides.
same_depth_nearer = side(6, 3, 1800, 420, 550)
assert match_attachment_size([far,same_depth_nearer],far,(700,1750,420))['attachment_price_id']==6
equal_distance = side(7, 1, 1700, 410, 450)
assert match_attachment_size([closest_depth,equal_distance],closest_depth,(700,1700,420))['attachment_price_id']==7
# Deterministic ties and manually selected source price schemes stay intact.
duplicate = side(8, 9999, 1800, 420, 800)
for candidates in ([same_depth_nearer,duplicate],[duplicate,same_depth_nearer]):
    assert match_attachment_size(candidates,far,(700,1750,420))['attachment_price_id']==6
scheme = {**wrong_depth,'attachment_price_id':9,'variant':'指定方案'}
assert match_attachment_size([far,scheme],scheme,(700,1700,420))['attachment_price_id']==9
# Unknown depth is a fallback, not an invented exact-depth catalogue record.
unknown = side(10,700,1700,None,100)
assert match_attachment_size([unknown,closest_depth],unknown,(700,1700,420))['attachment_price_id']==5
assert match_attachment_size([unknown],unknown,(700,1700,420))['attachment_price_id']==10
# A historical automatic model must not bypass the new priority on recalculation.
old = {**wrong_depth,'model_code':'OLD'}
catalog = [old,{**far,'model_code':'NEW'}]
selection={**old,'size_match_target_width_mm':700,'size_match_target_height_mm':1700,'size_match_target_depth_mm':420}
assert match_catalog_attachment(selection,catalog,(700,1700,420),'JP_SINGLE')['attachment_price_id']==2
assert match_catalog_attachment(selection,catalog,(700,1700,520),'JP_SINGLE')['attachment_price_id']==4
print("PASS: side-panel depth then perimeter, scaling, fallback, cached-model recalculation and deterministic ties")
