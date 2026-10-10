"""Offline selected-attachment dialog resize contract; no build or API."""
import copy
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QSizeGrip, QWidget
from scheme2_ui import AttachmentEditor

app = QApplication.instance() or QApplication([])
parent = QWidget()
parent.refresh_summary = lambda: None
row = dict(custom=True, item_name='木托', quantity=1, unit_price_override=10,
           quick_amount=10, formula_amount=5)
item = dict(attachments=[copy.deepcopy(row) for _ in range(12)],
            formula={'attachment_fee': 60, 'total_cost': 160},
            quick={'attachment_fee': 120, 'total_cost': 220})
original = copy.deepcopy(item)
editor = AttachmentEditor(parent, item)
editor.show()
app.processEvents()
assert editor.size() == QSize(650, 315)
assert editor.isSizeGripEnabled(), 'The frameless dialog needs a manual resize handle'
grip = editor.findChild(QSizeGrip)
assert grip is not None and grip.isVisible()
assert editor.minimumWidth() < editor.width() < editor.maximumWidth()
assert editor.minimumHeight() < editor.height() < editor.maximumHeight()
initial_table_height = editor.table.height()
initial_name_width = editor.table.columnWidth(editor.COL_NAME)
editor.resize(900, 500)
app.processEvents()
assert editor.size() == QSize(900, 500)
assert editor.table.height() > initial_table_height
assert editor.table.columnWidth(editor.COL_NAME) > initial_name_width
editor.resize(540, 270)
app.processEvents()
assert editor.size() == QSize(540, 270)

# Drag the actual Qt resize grip, rather than testing only programmatic resize.
editor.resize(650, 315)
editor.move(20, 20)
app.processEvents()
start_size = editor.size()
start_pos = editor.pos()
local = QPointF(2, 2)
global_start = QPointF(grip.mapToGlobal(QPoint(2, 2)))
delta = QPointF(70, 50)
for event_type, position, global_pos, button, buttons in (
    (QEvent.Type.MouseButtonPress, local, global_start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
    (QEvent.Type.MouseMove, local + delta, global_start + delta, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
    (QEvent.Type.MouseButtonRelease, local + delta, global_start + delta, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
):
    QApplication.sendEvent(grip, QMouseEvent(event_type, position, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier))
    app.processEvents()
assert editor.width() > start_size.width() and editor.height() > start_size.height()
assert editor.pos() == start_pos
assert editor.table.rowCount() == 12 and item == original
assert editor.table.verticalScrollBar().maximum() > 0
editor.reject()
assert item == original
parent.close()
print('PASS: manual resize grip, enlarge/shrink, adaptive table and unchanged attachment data')
