from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import scheme2_ui  # noqa: E402


app = QApplication.instance() or QApplication([])
cases = (
    ("JS", (0, 1), ("JS、JP单开门改为双开门",)),
    ("JP", (2, 0), ("JS、JP后背板改为单开门",)),
    ("JS", (1, 1), ("JS、JP后背板改为双开门",)),
    ("JP", (0, 2), ("JS、JP单开门改为双开门", "JS、JP后背板改为双开门")),
    ("JA", (0, 1), ("JA、JE单开门改为双开门",)),
    ("JE", (0, 1), ("JA、JE单开门改为双开门",)),
)

for product, door_counts, expected in cases:
    dialog = scheme2_ui._SchemeAttachmentDialog(
        [], product, door_counts=door_counts
    )
    combo = dialog.category_combos["门变形"]
    assert tuple(combo.selected_texts()) == expected, (
        product, door_counts, combo.selected_texts()
    )
    rows = [
        row["item_name"]
        for row in dialog.collect_attachments()
        if row["category_level1"] == "门变形"
    ]
    assert tuple(rows) == expected, (product, door_counts, rows)
    dialog.close()

plain = scheme2_ui._SchemeAttachmentDialog([], "JA", door_counts=(1, 0))
assert plain.category_combos["门变形"].selected_texts() == []
plain.close()

print("scheme2 door transformation defaults passed")
