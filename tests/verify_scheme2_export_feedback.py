from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QWidget  # noqa: E402

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


class ExportWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.states = []
        self.continued = False

    def set_export_busy(self, busy, message=""):
        self.states.append((busy, message))

    def validate_export_environment(self):
        return None

    def confirmation_failed(self, message):
        raise AssertionError(message)

    def confirm_and_export(self):
        self.continued = True


export_window = ExportWindow()
scheme2_ui._start_export_validation(export_window)
assert export_window.states[0] == (True, "正在检查云端导出服务…")
for _ in range(100):
    app.processEvents()
    if export_window.continued:
        break
    QTest.qWait(5)
assert export_window.continued
assert export_window.states[-1] == (False, "")
for _ in range(20):
    app.processEvents()
    if export_window._scheme2_export_validation_worker is None:
        break
assert export_window._scheme2_export_validation_worker is None

visible = QComboBox()
visible.addItem("示例科技有限公司", "COMPANY-01")
legacy = QComboBox()
company_window = SimpleNamespace(scheme2_company=visible, company_combo=legacy)
scheme2_ui._sync_export_company(company_window)
assert legacy.currentText() == "示例科技有限公司"
assert legacy.currentData() == "COMPANY-01"
print("scheme2 export feedback contract passed")
