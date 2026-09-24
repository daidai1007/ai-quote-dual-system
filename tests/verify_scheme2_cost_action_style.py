"""Focused contract for the scheme-2 cost action buttons."""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QEnterEvent, QFocusEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import v3_launcher  # noqa: E402


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()

import_button = window._scheme2_import_button
cost_buttons = tuple(window.scheme2_cost_action_buttons[:5])
assert [button.text() for button in cost_buttons] == ["× 删除", "↑ 上移", "↓ 下移", "编辑", "返回"]
assert import_button.objectName() == "scheme2PrimaryGhost"
assert all(button.objectName() == import_button.objectName() for button in cost_buttons)
assert len({(button.width(), button.height()) for button in cost_buttons}) == 1

# Exercise all required visual states on the real widgets. Sharing the same
# object name is the QSS contract that makes these states identical to Import.
for button in (import_button, *cost_buttons):
    button.setEnabled(True)
    QApplication.sendEvent(button, QEnterEvent(QPoint(2, 2), QPoint(2, 2), QPoint(2, 2)))
    button.setDown(True)
    app.processEvents()
    button.setDown(False)
    QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusIn))
    QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusOut))
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    button.setEnabled(False)
    assert not button.isEnabled()
    button.setEnabled(True)

# Fixed geometry must still fit every label at common logical DPI scales.
for width, height in ((1024, 700), (1280, 720), (1536, 864)):
    window.resize(width, height)
    window.show_section(3)
    app.processEvents()
    for button in cost_buttons:
        text_rect = button.fontMetrics().boundingRect(button.text())
        assert text_rect.width() < button.width() and text_rect.height() < button.height(), (
            (width, height), button.text(), text_rect.size(), button.size()
        )

delete, up, down, edit, back = cost_buttons

# Preserve the original move rules, including no-op behavior at both edges.
window.refresh_summary = lambda: None
window.draft_items = ["A", "B", "C"]
window.summary_table.setRowCount(3)
window.summary_table.selectRow(1)
up.click()
assert window.draft_items == ["B", "A", "C"] and window.summary_table.currentRow() == 0
up.click()
assert window.draft_items == ["B", "A", "C"] and window.summary_table.currentRow() == 0
window.summary_table.selectRow(2)
down.click()
assert window.draft_items == ["B", "A", "C"] and window.summary_table.currentRow() == 2
window.summary_table.selectRow(0)
down.click()
assert window.draft_items == ["A", "B", "C"] and window.summary_table.currentRow() == 1

# Edit keeps the row in place, restores its snapshot and returns to options.
edited = {"name": "JP 测试", "scheme2_cost_settings": {}}
loaded = []
routes = []
real_show_section = window.show_section
window.draft_items = [edited]
window.summary_table.setRowCount(1)
window.summary_table.selectRow(0)
window.load_draft_item = loaded.append
window.show_section = routes.append
edit.click()
assert window._scheme2_edit_item is edited and loaded == [edited] and routes == [1]
window.show_section = real_show_section

# Deletion keeps the existing recoverable confirmation/undo flow.
window.draft_items = ["A", "B", "C"]
window.summary_table.setRowCount(3)
window.summary_table.selectRow(1)
delete.click()
assert window.draft_items == ["A", "C"]
assert window._scheme2_deleted == (1, "B") and window.scheme2_cost_undo.isVisible()
window.scheme2_cost_undo.findChild(QPushButton).click()
assert window.draft_items == ["A", "B", "C"] and window._scheme2_deleted is None

# Return keeps its original route and signal connection.
window.show_section(3)
back.click()
app.processEvents()
assert window.stack.currentIndex() == 1

print("scheme2 cost action style contract passed")
