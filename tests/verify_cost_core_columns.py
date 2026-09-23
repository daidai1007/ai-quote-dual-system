import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QWidget

import scheme2_ui


app = QApplication.instance() or QApplication([])
window = QWidget()
window.summary_table = QTableWidget(0, len(scheme2_ui.HEADERS))
window.scheme2_cost_page = QWidget()
toggle = QPushButton("完整 16 列", window.scheme2_cost_page)

scheme2_ui._set_cost_column_mode(window, False)
visible = {column for column in range(len(scheme2_ui.HEADERS)) if not window.summary_table.isColumnHidden(column)}
expected = {0, 1, 2, 3, 10, 11, 12, 13, 14, 15}
assert visible == expected
assert scheme2_ui.HEADERS[10] == "运费"
assert scheme2_ui.HEADERS[14] == "已选附件"

scheme2_ui._set_cost_column_mode(window, True)
assert toggle.text() == "核心 10 列"
assert not any(window.summary_table.isColumnHidden(column) for column in range(len(scheme2_ui.HEADERS)))

window.close()
print("PASS: core cost view exposes ten columns including freight and selected attachments")
