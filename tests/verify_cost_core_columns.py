import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QTableWidget, QWidget

import scheme2_ui


app = QApplication.instance() or QApplication([])
window = QWidget()
window.summary_table = QTableWidget(0, len(scheme2_ui.HEADERS))
scheme2_ui._set_cost_column_mode(window, False)
visible = {column for column in range(len(scheme2_ui.HEADERS)) if not window.summary_table.isColumnHidden(column)}
expected = set(range(len(scheme2_ui.HEADERS)))
assert visible == expected
assert scheme2_ui.HEADERS[10] == "成本单价"
assert scheme2_ui.HEADERS[11:19] == (
    "材料成本", "辅材成本", "人工成本", "附件成本", "喷涂费用", "管理费用", "运费", "成本总价",
)

scheme2_ui._set_cost_column_mode(window, True)
assert not any(window.summary_table.isColumnHidden(column) for column in range(len(scheme2_ui.HEADERS)))

window.close()
print("PASS: cost view always exposes all requested columns")
