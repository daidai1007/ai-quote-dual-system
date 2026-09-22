import os
from pathlib import Path
from types import SimpleNamespace
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import scheme2_ui


app = QApplication.instance() or QApplication([])
progress = scheme2_ui._ClickableProgressBar()
progress.resize(190, 24)
progress.show()
window = SimpleNamespace(scheme2_add_progress=progress)
shown = []
original_warning = QMessageBox.warning
QMessageBox.warning = lambda parent, title, message: shown.append((parent, title, message))
try:
    progress.clicked.connect(lambda: scheme2_ui._show_add_failure_reason(window))
    scheme2_ui._set_add_progress(window, 3, "失败：价格库中未找到唯一匹配项：侧板", failed=True)
    QTest.mouseClick(progress, Qt.MouseButton.LeftButton)
    assert shown == [(window, "失败原因", "价格库中未找到唯一匹配项：侧板")]
    assert progress.toolTip() == "点击查看完整失败原因"
    scheme2_ui._set_add_progress(window, 2, "附件价格已就绪")
    QTest.mouseClick(progress, Qt.MouseButton.LeftButton)
    assert len(shown) == 1
finally:
    QMessageBox.warning = original_warning
    progress.close()

print("PASS: failed progress click shows the complete failure reason only in failed state")
