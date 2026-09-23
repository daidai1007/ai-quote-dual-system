from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
dialog = scheme2_ui._SchemeAttachmentDialog([], "JP")
check = dialog.category_checks["安装附件"]
combo = dialog.category_combos["安装附件"]
check.setChecked(True)

fixed = combo.findText("固定立柱")
beam = combo.findText("三排安装梁")
combo.toggle_row(beam)
combo.toggle_row(fixed)
assert combo.selected_texts() == ["固定立柱", "三排安装梁"]
assert check.isChecked()

rows = [
    row for row in dialog.collect_attachments()
    if row["category_level1"] == "安装附件"
]
assert [row["item_name"] for row in rows] == ["固定立柱", "三排安装梁"]

delegate = combo.view().itemDelegate()
image = QImage(240, 40, QImage.Format.Format_ARGB32)
painter = QPainter(image)
option = QStyleOptionViewItem()
option.rect = image.rect()
delegate.paint(painter, option, combo.model().index(beam, 0))
painter.end()
assert combo.is_row_selected(fixed) and combo.is_row_selected(beam)

combo.toggle_row(fixed)
assert combo.selected_texts() == ["三排安装梁"]
combo.toggle_row(beam)
assert combo.selected_texts() == [] and not check.isChecked()
dialog.close()
print("scheme2 attachment multiselect contract passed")
