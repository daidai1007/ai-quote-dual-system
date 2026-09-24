"""Focused runtime contract for the user-visible workbench version label."""

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

from PySide6.QtWidgets import QApplication, QLabel, QToolButton  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402


namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window.show()
app.processEvents()

assert window.windowTitle() == scheme2_ui.WORKBENCH_WINDOW_TITLE
visible_text = [window.windowTitle()]
visible_text.extend(
    label.text()
    for label in window.findChildren(QLabel)
    if label.isVisibleTo(window) and label.text().strip()
)
normalized = "\n".join(visible_text).replace(" ", "")
assert "AI智能报价" not in normalized
assert "V0交互工作台" not in normalized
assert "V3交互工作台" not in normalized
save_button = window.findChild(QToolButton, "scheme2SaveButton")
assert save_button is window.scheme2_save_button
assert save_button.accessibleName() == "保存当前订单进度"

window.close()
print("SCHEME2_WORKBENCH_VERSION=PASS")
