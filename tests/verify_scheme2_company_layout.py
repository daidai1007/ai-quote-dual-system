"""Focused contract for the quote-page company field layout."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

from PySide6.QtCore import QEvent, QRect  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel  # noqa: E402

import v3_launcher  # noqa: E402
import scheme2_ui  # noqa: E402
import quote_scheme_center
from PySide6.QtTest import QTest
quote_scheme_center.QuoteSchemeWorker.run=lambda worker:worker.succeeded.emit({'items':[],'total':0})


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
work_area = Mock(wraps=app.primaryScreen())
work_area.availableGeometry.return_value = QRect(0, 0, 4096, 2160)
screen_override = patch.object(namespace["MainWindow"], "screen", return_value=work_area)
screen_override.start()
window = namespace["MainWindow"]()
window.resize(1366, 820)
window.show()
assert window.width() == 1366
window._qm_entry_pending = True
window.show_section(2)
app.processEvents()

field = window.scheme2_quote_company_field
label = field.findChild(QLabel, "scheme2FieldLabel")
combo = window.scheme2_company
assert 0 < field.width() <= round(scheme2_ui.QUOTE_COMPANY_FIELD_WIDTH * window._scheme2_scale)
assert combo.width() > combo.fontMetrics().horizontalAdvance('客户名称至少可输入')
assert isinstance(field.layout(), QHBoxLayout)
assert label.text() == "客户" and label.buddy() is combo
assert label.geometry().right() < combo.geometry().left(), (label.geometry(), combo.geometry())
assert label.geometry().top() < combo.geometry().bottom()
assert combo.geometry().top() < label.geometry().bottom()
combo.setEditText("杭州拓强机械股份有限公司")
label.setFocus()
app.processEvents()
assert combo.lineEdit().text() == "杭州拓强机械股份有限公司"
assert "color:transparent" not in combo.lineEdit().styleSheet().replace(" ", "")
assert not combo._scheme2_multiline_filter.eventFilter(combo, QEvent(QEvent.Type.Paint))
assert all(label.text() != "客户" for label in window.scheme2_cost_page.findChildren(QLabel))
for worker in list(window._quote_scheme_workers):worker.wait(1000)
app.processEvents()
window.close()
screen_override.stop()
app.processEvents()
print("scheme2 quote company inline layout contract passed")
