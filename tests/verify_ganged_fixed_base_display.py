"""Focused regression for per-child fixed bases in ganged mode."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import layout_refresh  # noqa: E402
import scheme2_ui  # noqa: E402
import attachment_v2_client  # noqa: E402


recognized = {
    "item_name": "固定底座", "category_level1": "底座",
    "category_level2": "固定底座", "recognized": True,
}
manual = {
    "item_name": "固定底座", "category_level1": "底座",
    "category_level2": "固定底座", "selection_source": "manual",
}
old_child = {
    "item_name": "固定底座", "category_level1": "底座",
    "category_level2": "固定底座", "ganged_fixed_base_match": True,
    "ganged_fixed_base_index": 0,
}
other = {"item_name": "风机", "category_level1": "风机"}
candidates = [
    {
        "item_name": "固定底座", "category_level1": "底座",
        "category_level2": "固定底座", "attachment_price_id": 1000,
        "ganged_fixed_base_match": True, "ganged_fixed_base_index": 0,
        "size_match_target_width_mm": 1000,
        "size_match_target_height_mm": 100,
        "size_match_target_depth_mm": 600,
    },
    {
        "item_name": "固定底座", "category_level1": "底座",
        "category_level2": "固定底座", "attachment_price_id": 800,
        "ganged_fixed_base_match": True, "ganged_fixed_base_index": 1,
        "size_match_target_width_mm": 800,
        "size_match_target_height_mm": 100,
        "size_match_target_depth_mm": 600,
    },
]
replaced, added = layout_refresh._replace_ganged_fixed_base_selections(
    [recognized, manual, old_child, other], candidates, True
)
base_rows = [row for row in replaced if row.get("ganged_fixed_base_match")]
assert added == 2
assert replaced[0] == other
assert len(base_rows) == 2
assert [row["attachment_price_id"] for row in base_rows] == [1000, 800]
assert [row["ganged_fixed_base_index"] for row in base_rows] == [0, 1]

parent_window = SimpleNamespace(ganged_cabinets=[
    {"width_mm": 1000, "depth_mm": 600, "height_mm": 2100, "base_height_mm": 100},
    {"width_mm": 800, "depth_mm": 600, "height_mm": 2100, "base_height_mm": 100},
])
dialog = SimpleNamespace(
    parentWidget=lambda: parent_window,
    default_ganged_fixed_base_matches=tuple(candidates),
    default_selection_opt_outs={layout_refresh.DEFAULT_FIXED_BASE},
)
expanded = layout_refresh._expand_collected_ganged_fixed_bases(
    dialog, [manual, other]
)
expanded_bases = [row for row in expanded if row.get("ganged_fixed_base_match")]
assert len(expanded_bases) == 2
assert [row["attachment_price_id"] for row in expanded_bases] == [1000, 800]
assert layout_refresh.DEFAULT_FIXED_BASE not in dialog.default_selection_opt_outs

# The V2 catalogue is loaded asynchronously. Even if the initialization cache
# contains only the first child, confirmation must rematch every child from the
# current catalogue instead of persisting that stale partial cache.
stale_dialog = SimpleNamespace(
    parentWidget=lambda: parent_window,
    catalog=(
        {**candidates[0], "width_mm": 1000, "height_mm": 100, "depth_mm": 600},
        {**candidates[1], "width_mm": 800, "height_mm": 100, "depth_mm": 600},
    ),
    default_ganged_fixed_base_matches=(candidates[0],),
    default_selection_opt_outs={layout_refresh.DEFAULT_FIXED_BASE},
)
rematched = layout_refresh._expand_collected_ganged_fixed_bases(
    stale_dialog, [manual, other]
)
rematched_bases = [row for row in rematched if row.get("ganged_fixed_base_match")]
assert [row["attachment_price_id"] for row in rematched_bases] == [1000, 800]
assert [row["ganged_fixed_base_index"] for row in rematched_bases] == [0, 1]

# Even if a legacy/async dialog path persisted just the first base, the final
# ganged calculation boundary must repair the main-window attachment list.
calculation_window = SimpleNamespace(
    ganged_cabinets=parent_window.ganged_cabinets,
    attachments=[manual, {"item_name": "木托", "custom": True}],
    _attachment_catalog_cache=list(stale_dialog.catalog),
)
assert layout_refresh._ensure_window_ganged_fixed_bases(calculation_window)
calculation_bases = [
    row for row in calculation_window.attachments
    if row.get("ganged_fixed_base_match")
]
assert [row["attachment_price_id"] for row in calculation_bases] == [1000, 800]
assert calculation_window.attachments[0]["item_name"] == "木托"

# The live scheme2 picker stores one logical fixed-base row.  Quote resolution
# must expand that row again even when it already carries the first child's ID.
scheme2_window = SimpleNamespace(
    ganged_cabinets=parent_window.ganged_cabinets,
    selected_product_code=lambda: "JP",
)
scheme2_rows, scheme2_missing = attachment_v2_client.expand_ganged_fixed_bases_for_quote(
    scheme2_window,
    [{**manual, "attachment_price_id": 1000}, {"item_name": "木托", "custom": True}],
    list(stale_dialog.catalog),
    "test-catalog",
)
assert scheme2_missing == []
scheme2_bases = [row for row in scheme2_rows if row.get("ganged_fixed_base_match")]
assert [row["attachment_price_id"] for row in scheme2_bases] == [1000, 800]
assert [row["ganged_fixed_base_index"] for row in scheme2_bases] == [0, 1]
assert scheme2_rows[-1]["item_name"] == "木托"

rows = [
    {
        "item_name": "固定底座", "category_level1": "底座",
        "category_level2": "固定底座", "quantity": 1,
        "width_mm": 600, "depth_mm": 500, "height_mm": 100,
        "ganged_fixed_base_match": True, "ganged_fixed_base_index": 0,
    },
    {
        "item_name": "固定底座", "category_level1": "底座",
        "category_level2": "固定底座", "quantity": 1,
        "width_mm": 900, "depth_mm": 500, "height_mm": 100,
        "ganged_cabinet_index": 1,
    },
]
app = QApplication.instance() or QApplication([])
parent = QWidget()
parent.refresh_summary = lambda: None
item = {"attachments": rows, "formula": {}, "quick": {}}
editor = scheme2_ui.AttachmentEditor(parent, item)
assert editor.table.rowCount() == 2
assert editor.table.item(0, 0).text() == "柜体1｜固定底座"
assert editor.table.item(1, 0).text() == "柜体2｜固定底座"
assert editor.table.item(0, 1).text() == "600×500×100 mm"
assert editor.table.item(1, 1).text() == "900×500×100 mm"
assert scheme2_ui._attachment_chip_text(rows[0]).startswith("柜体1：")
assert scheme2_ui._attachment_chip_text(rows[1]).startswith("柜体2：")
editor.close()

print("ganged fixed base display passed")
