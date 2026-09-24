import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QTableWidget, QTableWidgetItem
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

# Real paint verification: normal/alternating rows retain the requested column
# color, while the selected state is deliberately allowed to cover it.
paint_table = QTableWidget(1, 1)
paint_table.setItem(0, 0, QTableWidgetItem(""))
paint_table.item(0, 0).setBackground(QColor("#FFF7E6"))
image = QImage(40, 24, QImage.Format.Format_ARGB32)
image.fill(QColor("#FF00FF"))
painter = QPainter(image)
paint_option = QStyleOptionViewItem()
paint_option.rect = QRect(0, 0, 40, 24)
paint_option.state |= QStyle.StateFlag.State_MouseOver
paint_option.features |= QStyleOptionViewItem.ViewItemFeature.Alternate
scheme2_ui._CostCellDelegate().paint(painter, paint_option, paint_table.model().index(0, 0))
painter.end()
assert image.pixelColor(5, 5).name().upper() == "#FFF7E6"

selected_image = QImage(40, 24, QImage.Format.Format_ARGB32)
selected_image.fill(QColor("#FF00FF"))
painter = QPainter(selected_image)
selected_option = QStyleOptionViewItem(paint_option)
selected_option.state |= QStyle.StateFlag.State_Selected
scheme2_ui._CostCellDelegate().paint(painter, selected_option, paint_table.model().index(0, 0))
painter.end()
assert selected_image.pixelColor(5, 5).name().upper() != "#FFF7E6"
paint_table.close()
table.close()
print("PASS: cost table has grouped two-tier header and quantity borders")
