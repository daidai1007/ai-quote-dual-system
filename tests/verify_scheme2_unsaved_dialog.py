from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
dialog = scheme2_ui._SchemeConfirmDialog(
    None,
    "有未保存变更",
    "当前配置尚未加入报价清单，关闭后将丢失本次填写的内容。",
    "放弃更改并关闭",
)

assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
assert dialog.shell.width() == 386
assert dialog.findChild(QLabel, "scheme2ConfirmWarningIcon").text() == "⚠"
assert dialog.reject_button.text() == "继续编辑"
assert dialog.accept_button.text() == "放弃更改并关闭"
assert not dialog.reject_button.autoDefault() and not dialog.accept_button.autoDefault()

dialog.reject_button.click()
assert dialog.result() == dialog.DialogCode.Rejected
print("scheme2 unsaved dialog contract passed")
