from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
allowed = {"JA", "JE", "JK", "JM"}
for product in ("JA", "JE", "JK", "JM", "JS", "JP"):
    selected = [{"category_level1": "控制箱附件", "item_name": "内门"}]
    dialog = scheme2_ui._SchemeAttachmentDialog(selected, product)
    visible = "控制箱附件" in dialog.category_names
    assert visible == (product in allowed), (product, dialog.category_names)
    if visible:
        assert dialog.category_combos["控制箱附件"].currentText() == "内门"
    else:
        assert "控制箱附件" not in dialog.category_checks
        assert "控制箱附件" not in dialog.category_combos
        assert not any(row["category_level1"] == "控制箱附件" for row in dialog.collect_attachments())
    dialog.close()

product_combo = QComboBox()
product_combo.addItem("JM", "JM")
holder = type("Holder", (), {"product_combo": product_combo})()
assert scheme2_ui._current_product_code(holder) == "JM"
print("attachment category visibility contract passed")
