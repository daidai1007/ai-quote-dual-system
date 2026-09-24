import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QTableWidget
import scheme2_ui

app = QApplication.instance() or QApplication([])
table = QTableWidget(0, len(scheme2_ui.HEADERS))
header = scheme2_ui._GroupedCostHeader(table)
table.setHorizontalHeader(header)
table.setHorizontalHeaderLabels(scheme2_ui.HEADERS)
assert scheme2_ui.COST_HEADER_GROUPS == (
    ("柜体信息", 0, 3), ("数量", 4, 4), ("附件", 5, 5), ("报价结果", 6, 9),
    ("成本数据", 10, 18), ("利润率", 19, 19), ("自制件重量", 20, 20), ("操作", 21, 21),
)
assert header.minimumHeight() == 76
assert isinstance(scheme2_ui._CostCellDelegate(table), scheme2_ui.QStyledItemDelegate)
table.close()
print("PASS: cost table has grouped two-tier header and quantity borders")
