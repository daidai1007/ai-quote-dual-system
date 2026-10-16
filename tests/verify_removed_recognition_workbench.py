"""The retired recognition workbench must never be reachable or visible."""

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

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import v3_launcher  # noqa: E402


workflow_source = (ROOT / "desktop_client" / "drawing_workflow.py").read_text(
    encoding="utf-8"
)
for removed_symbol in (
    "class CabinetSummaryTable",
    "def build_summary",
    "def open_cabinet",
    "def reorder_cabinets",
):
    assert removed_symbol not in workflow_source

namespace = v3_launcher.load_v3_namespace()
app = QApplication.instance() or QApplication([])
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()

for retired_route in (0, 4):
    assert window.stack.widget(retired_route).objectName() == "retiredWorkbenchRoute"
    window.show_section(retired_route)
    app.processEvents()
    assert window.stack.currentIndex() == 1
    assert window.stack.currentWidget().objectName() == "scheme2OptionPage"

forbidden_labels = {"图纸识别", "柜体汇总", "图纸识别工作台"}
visible_text = {
    widget.text().replace("&", "").strip()
    for widget_type in (QPushButton, QLabel)
    for widget in window.findChildren(widget_type)
    if widget.isVisibleTo(window)
}
assert forbidden_labels.isdisjoint(visible_text), visible_text & forbidden_labels
assert forbidden_labels.isdisjoint(
    {button.text().replace("&", "").strip() for button in window.nav_buttons}
)

assert len(window._scheme2_retired_pages) >= 3
assert all(page.isHidden() and page.maximumWidth() == 0 and page.maximumHeight() == 0
           for page in window._scheme2_retired_pages[-2:])

window.deleteLater()
app.processEvents()
print("PASS: retired recognition workbench is removed from navigation and routing")
