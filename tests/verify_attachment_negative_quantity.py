import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QWidget

import scheme2_ui


app = QApplication.instance() or QApplication([])
window = QWidget()
window.refresh_summary = lambda: None
item = {
    "attachments": [{"item_name": "附件", "quantity": 1, "matched_price": 10, "quick_amount": 10, "formula_amount": 4}],
    "formula": {"attachment_fee": 4, "total_cost": 100},
    "quick": {"attachment_fee": 10, "total_cost": 200},
}
editor = scheme2_ui.AttachmentEditor(window, item)
assert editor.table.horizontalHeaderItem(4).text() == "金额"
assert "快速金额" not in [editor.table.horizontalHeaderItem(column).text() for column in range(editor.table.columnCount())]
quantity = editor.table.cellWidget(0, 3)
assert quantity.minimum() < 0
quantity.setValue(-2)
editor.accept()

assert item["attachments"][0]["quantity"] == -2
assert item["attachments"][0]["quick_amount"] == -20
assert item["attachments"][0]["formula_amount"] == -8
assert item["quick"]["attachment_fee"] == -20
assert item["quick"]["total_cost"] == 170
assert item["formula"]["attachment_fee"] == -8
assert item["formula"]["total_cost"] == 88

temporary_item = {"attachments": [], "formula": {"attachment_fee": 0, "total_cost": 0}, "quick": {"attachment_fee": 0, "total_cost": 0}}
temporary_editor = scheme2_ui.AttachmentEditor(window, temporary_item)
temporary_editor.add_row()
assert temporary_editor.table.columnCount() == 6
assert "单价" not in [temporary_editor.table.horizontalHeaderItem(column).text() for column in range(temporary_editor.table.columnCount())]
temporary_editor.table.cellWidget(0, 4).setValue(37.5)
temporary_editor.accept()
assert temporary_item["attachments"][0]["quick_amount"] == 37.5
assert temporary_item["attachments"][0]["formula_amount"] == 37.5
assert temporary_item["quick"]["attachment_fee"] == 37.5
assert temporary_item["formula"]["attachment_fee"] == 37.5

window.close()
print("PASS: attachment editor accepts negative quantities and applies them to both amount paths")
