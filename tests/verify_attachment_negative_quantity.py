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
    "attachments": [{"item_name": "安装板", "category_level1": "安装板", "quantity": 1,
                     "matched_price": 10, "quick_amount": 10, "formula_amount": 4}],
    "formula": {"attachment_fee": 4, "total_cost": 100},
    "quick": {"attachment_fee": 10, "total_cost": 200},
}
editor = scheme2_ui.AttachmentEditor(window, item)
assert editor.table.horizontalHeaderItem(4).text() == "金额"
assert "快速金额" not in [editor.table.horizontalHeaderItem(column).text() for column in range(editor.table.columnCount())]
quantity = editor.table.cellWidget(0, editor.COL_QUANTITY)
assert quantity.minimum() < 0
quantity.setValue(-2)
editor.accept()

assert item["attachments"][0]["quantity"] == 2
assert item["attachments"][0]["attachment_price_sign"] == -1
assert item["attachments"][0]["quick_amount"] == -20
assert item["attachments"][0]["formula_amount"] == -8
assert item["quick"]["attachment_fee"] == -20
assert item["quick"]["total_cost"] == 170
assert item["formula"]["attachment_fee"] == -8
assert item["formula"]["total_cost"] == 88

temporary_item = {"attachments": [], "formula": {"attachment_fee": 0, "total_cost": 0}, "quick": {"attachment_fee": 0, "total_cost": 0}}
temporary_editor = scheme2_ui.AttachmentEditor(window, temporary_item)
temporary_editor.add_row()
assert temporary_editor.table.columnCount() == 5
assert "单价" not in [temporary_editor.table.horizontalHeaderItem(column).text() for column in range(temporary_editor.table.columnCount())]
temporary_quantity = temporary_editor.table.cellWidget(0, temporary_editor.COL_QUANTITY)
assert temporary_quantity.minimum() > 0
temporary_quantity.setValue(-2)
assert temporary_quantity.value() > 0
temporary_editor.close()

other_item = {"attachments": [{"item_name": "风机", "category_level1": "风机", "quantity": 1}],
              "formula": {}, "quick": {}}
other_editor = scheme2_ui.AttachmentEditor(window, other_item)
assert other_editor.table.cellWidget(0, other_editor.COL_QUANTITY).minimum() > 0
other_editor.close()

window.close()
print("PASS: only installation boards accept negative counts, encoded as positive quantity plus deduction")
