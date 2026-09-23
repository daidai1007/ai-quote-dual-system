from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
dialog = scheme2_ui._SchemeAttachmentDialog([], "JP")
check = dialog.category_checks["安装附件"]
combo = dialog.category_combos["安装附件"]
assert not check.isChecked() and combo.isEnabled()

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
placements, required_height = combo._chip_layout(90)
assert len(placements) == 2 and placements[0][1].y() < placements[1][1].y()
assert required_height > 36
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
image.fill(QColor("#FFFFFF"))
painter = QPainter(image)
option = QStyleOptionViewItem()
option.rect = image.rect()
delegate.paint(painter, option, combo.model().index(section, 0))
painter.end()
assert combo.is_row_selected(fixed) and combo.is_row_selected(section)
checkbox = delegate.checkbox_rect(option.rect)
selected_fill = image.pixelColor(checkbox.left() + 3, checkbox.top() + 3)
assert selected_fill.blue() > selected_fill.red() + 40

unchecked_image = QImage(240, 40, QImage.Format.Format_ARGB32)
unchecked_image.fill(QColor("#FFFFFF"))
unchecked_painter = QPainter(unchecked_image)
delegate.paint(unchecked_painter, option, combo.model().index(combo.findText("绑线条"), 0))
unchecked_painter.end()
unchecked_border = unchecked_image.pixelColor(checkbox.left(), checkbox.center().y())
assert unchecked_border != QColor("#FFFFFF")

combo.toggle_row(fixed)
assert combo.selected_texts() == ["分段板"]
combo.toggle_row(section)
assert combo.selected_texts() == [] and not check.isChecked()

for category in ("资料盒", "风机", "滤网", "门变形", "控制柜附件", "配置变形", "其他附件"):
    category_check = dialog.category_checks[category]
    category_combo = dialog.category_combos[category]
    category_check.setChecked(False)
    assert category_combo.isEnabled()
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
        assert category_combo.view().isVisible(), f"{category} popup closed after selecting row {row}"
        assert category_check.isChecked(), f"{category} was not checked after selecting row {row}"
    category_combo.hidePopup()
    app.processEvents()
    expected = [category_combo.itemText(first), category_combo.itemText(second)]
    assert category_combo.selected_texts() == expected
    assert category_combo.display_text() == "\n".join(expected)
    assert category_check.isChecked()

# A category can be selected directly from its dropdown; the category check
# follows the selection. Only an explicit arrow click collapses the popup.
direct_combo = dialog.category_combos["其他附件"]
direct_check = dialog.category_checks["其他附件"]
direct_check.setChecked(False)
assert direct_combo.isEnabled()
direct_combo.showPopup()
app.processEvents()
QTest.mouseClick(
    direct_combo.view().viewport(), Qt.MouseButton.LeftButton,
    pos=direct_combo.view().visualRect(direct_combo.model().index(1, 0)).center(),
)
app.processEvents()
assert direct_check.isChecked() and direct_combo.view().isVisible()
option = scheme2_ui.QStyleOptionComboBox()
direct_combo.initStyleOption(option)
arrow = direct_combo.style().subControlRect(
    scheme2_ui.QStyle.ComplexControl.CC_ComboBox,
    option,
    scheme2_ui.QStyle.SubControl.SC_ComboBoxArrow,
    direct_combo,
)
QTest.mouseClick(direct_combo, Qt.MouseButton.LeftButton, pos=arrow.center())
app.processEvents()
assert not direct_combo.view().isVisible()

control_dialog = scheme2_ui._SchemeAttachmentDialog([], "JK")
control_combo = control_dialog.category_combos["控制箱附件"]
control_check = control_dialog.category_checks["控制箱附件"]
assert not control_check.isChecked() and control_combo.isEnabled()
control_dialog.show()
control_combo.showPopup()
app.processEvents()
for row in (1, 2):
    QTest.mouseClick(
        control_combo.view().viewport(), Qt.MouseButton.LeftButton,
        pos=control_combo.view().visualRect(control_combo.model().index(row, 0)).center(),
    )
    app.processEvents()
    assert control_combo.view().isVisible()
    assert control_check.isChecked()
assert len(control_combo.selected_texts()) == 2
control_dialog.close()
dialog.close()
print("scheme2 attachment multiselect contract passed")
