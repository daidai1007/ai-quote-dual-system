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
from PySide6.QtTest import QTest  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
dialog = scheme2_ui._SchemeAttachmentDialog([], "JP")
check = dialog.category_checks["安装附件"]
combo = dialog.category_combos["安装附件"]
check.setChecked(True)

fixed = combo.findText("固定立柱")
section = combo.findText("分段板")
dialog.show()
combo.showPopup()
app.processEvents()
QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                 pos=combo.view().visualRect(combo.model().index(section, 0)).center())
app.processEvents()
assert combo.view().isVisible() and check.isChecked()
QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                 pos=combo.view().visualRect(combo.model().index(fixed, 0)).center())
app.processEvents()
assert combo.view().isVisible() and check.isChecked()
combo.hidePopup()
app.processEvents()
assert not combo.view().isVisible()
assert combo.selected_texts() == ["固定立柱", "分段板"]
assert combo.display_text() == "固定立柱\n分段板"
assert check.isChecked()

# Collapsed selections render as removable chips, wrap, and grow with available width.
combo.resize(125, combo.height())
combo.repaint()
app.processEvents()
placements, required_height = combo._chip_layout()
assert len(placements) == 2 and placements[0][1].y() < placements[1][1].y()
assert combo.minimumHeight() == required_height
first_chip = combo._chip_hit_rects[fixed]
QTest.mouseClick(combo, Qt.MouseButton.LeftButton, pos=first_chip.center())
app.processEvents()
assert combo.selected_texts() == ["分段板"] and not combo.view().isVisible()
combo.toggle_row(fixed)

rows = [
    row for row in dialog.collect_attachments()
    if row["category_level1"] == "安装附件"
]
assert [row["item_name"] for row in rows] == ["固定立柱", "分段板"]

delegate = combo.view().itemDelegate()
image = QImage(240, 40, QImage.Format.Format_ARGB32)
painter = QPainter(image)
option = QStyleOptionViewItem()
option.rect = image.rect()
delegate.paint(painter, option, combo.model().index(section, 0))
painter.end()
assert combo.is_row_selected(fixed) and combo.is_row_selected(section)

combo.toggle_row(fixed)
assert combo.selected_texts() == ["分段板"]
combo.toggle_row(section)
assert combo.selected_texts() == [] and not check.isChecked()

for category in ("资料盒", "配置变形"):
    category_check = dialog.category_checks[category]
    category_combo = dialog.category_combos[category]
    category_check.setChecked(True)
    first, second = 1, 2
    category_combo.showPopup()
    app.processEvents()
    for row in (first, second):
        QTest.mouseClick(
            category_combo.view().viewport(),
            Qt.MouseButton.LeftButton,
            pos=category_combo.view().visualRect(category_combo.model().index(row, 0)).center(),
        )
        app.processEvents()
    category_combo.hidePopup()
    app.processEvents()
    expected = [category_combo.itemText(first), category_combo.itemText(second)]
    assert category_combo.selected_texts() == expected
    assert category_combo.display_text() == "\n".join(expected)
    assert category_check.isChecked()
dialog.close()
print("scheme2 attachment multiselect contract passed")
