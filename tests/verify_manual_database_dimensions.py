from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QLineEdit  # noqa: E402
import layout_refresh  # noqa: E402

app = QApplication.instance() or QApplication([])
spin = lambda value: (lambda field: (field.setValue(value), field)[1])(QDoubleSpinBox())
window = SimpleNamespace(
    risk_label=QLabel("所选型号没有数据库默认尺寸。请按原图填写 W、D、H 和正式规格，系统不会代填。"),
    quote_spec_edit=QLineEdit("1000*300*1000"),
    width_spin=spin(1000), depth_spin=spin(300), height_spin=spin(1000),
)
assert layout_refresh._clear_missing_default_dimension_notice(window)
assert "可正常计算报价" in window.risk_label.text()
window.quote_spec_edit.clear()
window.risk_label.setText("所选型号没有数据库默认尺寸")
assert not layout_refresh._clear_missing_default_dimension_notice(window)
print("manual database dimensions contract passed")
