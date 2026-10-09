"""Cost-page cabinet quantities project to attachment order totals only once."""

import copy
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QWidget
import scheme2_ui


app = QApplication.instance() or QApplication([])
window = QWidget()
window.refresh_summary = lambda: None
window._scheme2_refreshing = False
window.summary_table = QTableWidget(1, len(scheme2_ui.HEADERS))

catalog_row = {
    "attachment_price_id": 34,
    "item_name": "接地线-编织带",
    "quantity": 2,
    "matched_price": 10,
    "quick_amount": 20,
    "formula_unit_cost": 4,
    "formula_amount": 8,
    "manual_inputs": {},
}
item = {
    "quantity": 1,
    "attachments": [catalog_row],
    "formula": {"attachment_fee": 8, "total_cost": 108},
    "quick": {"attachment_fee": 20, "total_cost": 220},
    "attachment_confirmation_inputs": [{
        "attachment_price_id": 34, "quantity": 2,
        "attachment_price_sign": 1, "manual_inputs": {},
    }],
}
window.draft_items = [item]
frozen = copy.deepcopy(item["attachment_confirmation_inputs"])


def set_cabinet_quantity(quantity):
    window.summary_table.setItem(0, 4, QTableWidgetItem(str(quantity)))
    scheme2_ui._cost_cell_changed(window, 0, 4)


def check_editor(quantity, cost, amount):
    editor = scheme2_ui.AttachmentEditor(window, item)
    assert editor.table.cellWidget(0, editor.COL_QUANTITY).value() == quantity
    assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).text() == f"{cost:.2f}"
    assert editor.table.cellWidget(0, editor.COL_AMOUNT).value() == amount
    return editor


for cabinets in (3, 2, 1, 3):
    set_cabinet_quantity(cabinets)
    editor = check_editor(2 * cabinets, 8 * cabinets, 20 * cabinets)
    editor.accept()
    # Closing/reopening never converts stored per-cabinet data to order totals.
    assert item["attachments"][0]["quantity"] == 2
    assert item["formula"]["total_cost"] == 108
    assert item["quick"]["total_cost"] == 220
    assert item["attachment_confirmation_inputs"] == frozen

# Editing total quantity recomputes both money columns immediately and stores
# per-cabinet values, including after repeated edits and manual price changes.
editor = check_editor(6, 24, 60)
quantity_editor = editor.table.cellWidget(0, editor.COL_QUANTITY)
amount_editor = editor.table.cellWidget(0, editor.COL_AMOUNT)
quantity_editor.setValue(9)
assert amount_editor.value() == 90
assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).text() == "36.00"
amount_editor.setValue(108)
quantity_editor.setValue(12)
assert amount_editor.value() == 144
assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).text() == "48.00"
editor.accept()
assert item["attachments"][0]["quantity"] == 4
assert item["attachments"][0]["quick_amount"] == 48
assert item["formula"]["total_cost"] == 116
assert item["quick"]["total_cost"] == 248
assert scheme2_ui._row_values(item)[18] == 348
set_cabinet_quantity(2)
check_editor(8, 32, 96).reject()

# Each independently matched ganged base scales by order quantity once, even
# when two differently sized bases are present. Custom costs scale as well.
item = {
    "quantity": 3,
    "ganged_cabinet_count": 2,
    "attachments": [
        {**catalog_row, "item_name": "固定底座", "quantity": 1,
         "ganged_fixed_base_match": True, "ganged_cabinet_index": 0,
         "width_mm": 1000, "depth_mm": 600, "height_mm": 100,
         "quick_amount": 10, "formula_amount": 4},
        {**catalog_row, "item_name": "固定底座", "quantity": 1,
         "ganged_fixed_base_match": True, "ganged_cabinet_index": 1,
         "width_mm": 800, "depth_mm": 600, "height_mm": 100,
         "quick_amount": 10, "formula_amount": 4},
        {"custom": True, "item_name": "木托", "quantity": 2,
         "quick_amount": 24, "formula_amount": 20},
    ],
    "formula": {"attachment_fee": 28, "total_cost": 128},
    "quick": {"attachment_fee": 44, "total_cost": 244},
}
editor = scheme2_ui.AttachmentEditor(window, item)
for row in (0, 1):
    assert editor.table.cellWidget(row, editor.COL_QUANTITY).value() == 3
    assert editor.table.item(row, editor.COL_FORMULA_AMOUNT).text() == "12.00"
    assert editor.table.cellWidget(row, editor.COL_AMOUNT).value() == 30
assert editor.table.cellWidget(2, editor.COL_QUANTITY).value() == 6
assert editor.table.cellWidget(2, editor.COL_FORMULA_AMOUNT).value() == 60
assert editor.table.cellWidget(2, editor.COL_AMOUNT).value() == 72
editor.table.cellWidget(2, editor.COL_QUANTITY).setValue(9)
editor.table.cellWidget(2, editor.COL_QUANTITY).setValue(12)
assert editor.table.cellWidget(2, editor.COL_FORMULA_AMOUNT).value() == 120
assert editor.table.cellWidget(2, editor.COL_AMOUNT).value() == 144
editor.accept()
assert item["attachments"][2]["quantity"] == 4
assert item["attachments"][2]["formula_amount"] == 40
assert item["attachments"][2]["quick_amount"] == 48
assert item["formula"]["total_cost"] == 148

print("PASS: cost-page quantities update attachment quantities, costs and amounts without repeated multiplication")
