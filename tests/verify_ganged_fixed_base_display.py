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
