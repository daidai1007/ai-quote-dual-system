"""Focused contract for the cost-page company field layout."""

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

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel  # noqa: E402

import v3_launcher  # noqa: E402


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.resize(1366, 820)
window.show()
window.show_section(2)
app.processEvents()

field = window.scheme2_quote_company_field
label = field.findChild(QLabel, "scheme2FieldLabel")
combo = window.scheme2_company
assert isinstance(field.layout(), QHBoxLayout)
assert label.text() == "下单公司" and label.buddy() is combo
assert label.geometry().right() < combo.geometry().left(), (label.geometry(), combo.geometry())
assert label.geometry().top() < combo.geometry().bottom()
assert combo.geometry().top() < label.geometry().bottom()
combo.setEditText("杭州拓强机械股份有限公司")
label.setFocus()
app.processEvents()
assert combo.lineEdit().text() == "杭州拓强机械股份有限公司"
assert "color:transparent" not in combo.lineEdit().styleSheet().replace(" ", "")
assert not combo._scheme2_multiline_filter.eventFilter(combo, QEvent(QEvent.Type.Paint))
assert all(label.text() != "下单公司" for label in window.scheme2_cost_page.findChildren(QLabel))
print("scheme2 quote company inline layout contract passed")
