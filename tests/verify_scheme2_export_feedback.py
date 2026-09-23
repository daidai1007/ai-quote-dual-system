from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
calls = []
window = SimpleNamespace(
    draft_items=[{"name": "测试柜"}],
    set_export_busy=lambda busy, message="": calls.append((busy, message)),
)
button = QPushButton("导出报价单")
scheme2_ui._install_export_busy_feedback(window, button)

window.set_export_busy(True, "正在检查并生成旧版模板报价单")
assert calls[-1] == (True, "正在检查并生成旧版模板报价单")
assert not button.isEnabled() and button.text() == "正在导出…"
assert button.toolTip() == "正在检查并生成旧版模板报价单"

window.set_export_busy(False, "导出完成")
assert button.isEnabled() and button.text() == "导出报价单"
assert button.toolTip() == "导出完成"
print("scheme2 export feedback contract passed")
