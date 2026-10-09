"""Focused regression for per-child fixed bases in ganged mode."""

from __future__ import annotations

import os
from pathlib import Path
import sys


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
manual_bases, retained = layout_refresh._partition_ganged_fixed_base_selections(
    [recognized, manual, old_child, other]
)
assert manual_bases == [manual]
assert retained == [manual, other]

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
