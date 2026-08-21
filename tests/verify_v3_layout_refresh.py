"""Runtime contract check for the source-controlled V3 layout overlay.

The verified client core remains an external build artifact.  Point
``AI_QUOTE_V3_CORE_ROOT`` at its ``_internal/v3_core`` directory and run this
script with the Python 3.12/PySide6 environment used to build the client.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "desktop_client"
sys.path.insert(0, str(CLIENT_ROOT))

core_root = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core_root.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core directory")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QAbstractButton,
    QFrame,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
)

import layout_refresh  # noqa: E402
import v3_launcher  # noqa: E402


def buttons_with_text(root, captions: set[str]):
    return [
        button
        for button in root.findChildren(QAbstractButton)
        if button.text().replace("&", "").strip() in captions
    ]


namespace = v3_launcher.load_v3_namespace()

# The layout contract is offline.  Product/company loading is separately
# covered by API tests and must not contact Render or Neon from this check.
namespace["MainWindow"].load_catalogs = lambda self: None

app = QApplication.instance() or QApplication(sys.argv[:1])
namespace["install_application_font"](app)
window = namespace["MainWindow"]()
window.resize(1519, 987)
window.show()
app.processEvents()

assert window.stack.count() == 4
nav = window.findChild(QFrame, "navPanel")
assert nav is not None and nav.width() == 168

style = window.styleSheet()
for token in (
    layout_refresh.STEEL_CANVAS,
    layout_refresh.GRAPHITE,
    layout_refresh.BLUEPRINT,
    layout_refresh.INSPECTION_GREEN,
    layout_refresh.WARNING_AMBER,
):
    assert token in style, token

window.stack.setCurrentIndex(0)
app.processEvents()
recognition_page = window.stack.widget(0)
workbench = recognition_page.findChild(QSplitter, "workbenchSplitter")
assert workbench is not None and workbench.count() == 3
left, center, right = workbench.sizes()
assert 228 <= left <= 264, workbench.sizes()
assert center >= 520, workbench.sizes()
assert 348 <= right <= 420, workbench.sizes()

candidate_table = recognition_page.findChild(QTableWidget, "candidateTable")
assert candidate_table is not None
candidate_actions = buttons_with_text(
    recognition_page,
    {"复核类型", "新增拆分项", "合并", "排除"},
)
assert len(candidate_actions) == 4
assert all(not action.isEnabled() for action in candidate_actions)
candidate_table.setRowCount(1)
candidate_table.setItem(0, 0, QTableWidgetItem("候选 1"))
candidate_table.selectRow(0)
app.processEvents()
assert all(action.isEnabled() for action in candidate_actions)

window.stack.setCurrentIndex(1)
app.processEvents()
quote_page = window.stack.widget(1)
quote_workspace = quote_page.findChild(QSplitter, "quoteWorkspace")
assert quote_workspace is not None and quote_workspace.count() == 2
quote_left, quote_right = quote_workspace.sizes()
assert quote_left >= 570, quote_workspace.sizes()
assert 520 <= quote_right <= 680, quote_workspace.sizes()
assert window.findChild(QAbstractButton, "primaryQuoteAction").accessibleName() == "计算双报价"
assert window.width_spin.specialValueText() == ""
assert window.depth_spin.specialValueText() == ""
assert window.height_spin.specialValueText() == ""
assert window.door_counts() == (1, 0)
assert "宽×深×高" in window.quote_spec_edit.toolTip()

window.stack.setCurrentIndex(3)
app.processEvents()
summary_page = window.stack.widget(3)
empty_action = summary_page.findChild(QPushButton, "emptyStateAction")
assert empty_action is not None and empty_action.isVisible()
list_actions = buttons_with_text(summary_page, {"编辑", "删除", "上移", "下移"})
assert len(list_actions) == 4
assert all(not action.isEnabled() for action in list_actions)

summary_table = window.summary_table
summary_table.setRowCount(1)
summary_table.setItem(0, 0, QTableWidgetItem("1"))
summary_table.selectRow(0)
layout_refresh._sync_summary_action_state(window)
app.processEvents()
assert all(action.isEnabled() for action in list_actions)
assert not empty_action.isVisible()

artifact_dir_text = os.environ.get("AI_QUOTE_UI_ARTIFACT_DIR", "").strip()
if artifact_dir_text:
    artifact_dir = Path(artifact_dir_text)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    candidate_table.setRowCount(0)
    layout_refresh._sync_recognition_action_state(window)
    summary_table.setRowCount(0)
    layout_refresh._sync_summary_action_state(window)
    for index, name in ((0, "recognition"), (1, "quote"), (3, "summary")):
        window.show_section(index)
        app.processEvents()
        assert window.grab().save(str(artifact_dir / f"v3_{name}_refresh.png"))

window.close()
app.processEvents()

print("V3_LAYOUT_REFRESH=PASS")
print(f"WORKBENCH_SIZES={workbench.sizes()}")
print(f"QUOTE_SIZES={quote_workspace.sizes()}")
