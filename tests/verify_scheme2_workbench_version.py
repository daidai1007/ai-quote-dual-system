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

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

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
assert "V0交互工作台" in normalized
assert "V3交互工作台" not in normalized

window.close()
print("SCHEME2_WORKBENCH_VERSION=PASS")
