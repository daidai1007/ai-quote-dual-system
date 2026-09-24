"""Focused contract for the selected-attachment specification column."""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QFrame, QWidget  # noqa: E402

import scheme2_ui  # noqa: E402


app = QApplication.instance() or QApplication([])
parent = QWidget()
parent.refresh_summary = lambda: None
rows = [
    {
        "item_name": "固定底座", "model_code": "BASE-800", "specification": "快速匹配",
        "size_match_width_mm": 800, "size_match_depth_mm": 600, "size_match_height_mm": 100,
        "custom": True,
    },
    {
        "item_name": "侧板", "model_code": "JP682060",
        "height_mm": 2000, "depth_mm": 600,
    },
    {
        "item_name": "滤网", "model_code": "FU-9803A", "specification": "普通规格",
    },
    {
        "item_name": "安装板", "model_code": "BOARD-A", "specification": "760×500×100 mm",
    },
    {"item_name": "无规格附件", "specification": "普通附件"},
]
item = {"attachments": rows, "formula": {}, "quick": {}}
editor = scheme2_ui.AttachmentEditor(parent, item)
editor.show()
app.processEvents()

assert editor.table.columnCount() == 5
assert [editor.table.horizontalHeaderItem(column).text() for column in range(5)] == [
    "名称", "尺寸 / 规格", "数量", "成本", "金额",
]
assert editor.table.item(0, 1).text() == "BASE-800"
assert editor.table.item(1, 1).text() == "深 600 × 高 2000 mm"
assert editor.table.item(2, 1).text() == "FU-9803A"
assert editor.table.item(3, 1).text() == "BOARD-A"
assert editor.table.item(4, 1).text() == ""
cost_editor = editor.table.cellWidget(0, 3)
amount_editor = editor.table.cellWidget(0, 4)
assert isinstance(cost_editor, QDoubleSpinBox)
assert type(amount_editor) is QDoubleSpinBox
assert amount_editor.lineEdit().textMargins().right() == 0
assert editor.size().width() == 650 and editor.size().height() == 315
original_size = editor.size()
parent.resize(1800, 1000)
app.processEvents()
assert editor.size() == original_size
for row in range(editor.table.rowCount()):
    for column in range(editor.table.columnCount()):
        widget = editor.table.cellWidget(row, column)
        if widget is not None:
            assert widget.height() <= editor.table.rowHeight(row)

header = editor.findChild(QFrame, "scheme2AttachmentEditorHeader")
assert isinstance(header, scheme2_ui._SchemeAttachmentHeader)
assert header.cursor().shape() == Qt.CursorShape.SizeAllCursor


class DragEvent:
    def __init__(self, position, buttons=Qt.MouseButton.LeftButton):
        self.position = QPointF(position)
        self._buttons = buttons

    def button(self):
        return Qt.MouseButton.LeftButton

    def buttons(self):
        return self._buttons

    def globalPosition(self):
        return self.position

    def accept(self):
        pass


editor.move(100, 100)
header.mousePressEvent(DragEvent(QPoint(120, 110)))
header.mouseMoveEvent(DragEvent(QPoint(220, 160)))
assert editor.pos() == QPoint(200, 150)
header._drag_offset = None
editor.accept()
assert item["attachments"][4]["specification"] == "普通附件"
print("scheme2 attachment specification contract passed")
