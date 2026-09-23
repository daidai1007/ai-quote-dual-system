"""Focused contract for leaving the formula-template waiting state."""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
window = QWidget()
window._scheme2_add_after_calculate = True
window._pending_formula_calculation = False
window.quote_calculation_in_progress = False
window.template_worker = None
window.worker = None
window.current_result = None
window.risk_label = QLabel("公式模板读取失败：测试错误", window)
errors = []
window.show_error = errors.append

scheme2_ui._monitor_formula_calculation(window)
QTest.qWait(250)
app.processEvents()
assert errors == ["公式模板读取失败：测试错误"]
assert not window._scheme2_formula_monitor.isActive()

window._scheme2_add_after_calculate = True
window._pending_formula_calculation = True
errors.clear()
scheme2_ui._monitor_formula_calculation(window)
QTest.qWait(250)
app.processEvents()
assert not errors and window._scheme2_formula_monitor.isActive()
window._scheme2_formula_monitor.stop()
print("scheme2 formula monitor contract passed")
