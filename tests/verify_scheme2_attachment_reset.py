from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout  # noqa: E402
import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
summary = QFrame()
summary.setLayout(QVBoxLayout())
page = {"state": {"attachments": [{"item_name": "风机"}], "attachments_manual": True}}
refresh_calls = []
window = SimpleNamespace(
    attachments=[{"item_name": "风机"}], _scheme2_attachments_manual=True,
    scheme2_attachment_summary=summary, _scheme2_drawing_pages=[page],
    _scheme2_drawing_page_index=0, update_attachment_view=lambda: refresh_calls.append(True),
)
scheme2_ui._clear_scheme2_attachments(window)
assert window.attachments == [] and window._scheme2_attachments_manual is False
assert page["state"]["attachments"] == [] and page["state"]["attachments_manual"] is False
assert refresh_calls and summary.layout().itemAt(0).widget().text() == "未选择附件"
print("scheme2 attachment reset contract passed")
