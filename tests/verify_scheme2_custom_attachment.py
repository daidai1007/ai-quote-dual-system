"""Focused custom-attachment picker/editor regression."""

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLineEdit, QPushButton, QWidget
import scheme2_ui

app = QApplication.instance() or QApplication([])
dialog = scheme2_ui._SchemeAttachmentDialog([], "JP")
dialog.findChild(QPushButton, "scheme2AddAttachment").click()
name = dialog.findChild(QLineEdit, "scheme2CustomAttachmentName")
name.setText("自定义附件（新增）")
dialog.findChild(QPushButton, "scheme2CustomAttachmentConfirm").click()
rows = dialog.collect_attachments()
custom = next(row for row in rows if row.get("custom"))
assert custom["item_name"] == "自定义附件（新增）"
assert custom["category_level1"] == "其他附件" and custom["quantity"] == 1

owner = QWidget()
owner.refresh_summary = lambda: None
item = {"attachments": rows, "formula": {"attachment_fee": 0, "total_cost": 0}, "quick": {"attachment_fee": 0, "total_cost": 0}}
editor = scheme2_ui.AttachmentEditor(owner, item)
assert editor.table.columnCount() == 5
assert [editor.table.horizontalHeaderItem(i).text() for i in range(5)] == [
    "名称", "尺寸 / 规格", "数量", "成本", "金额"
]
assert editor.table.item(0, editor.COL_NAME).text() == "自定义附件（新增）"
cost = editor.table.cellWidget(0, editor.COL_FORMULA_AMOUNT)
amount = editor.table.cellWidget(0, editor.COL_AMOUNT)
assert isinstance(cost, QDoubleSpinBox) and isinstance(amount, QDoubleSpinBox)
cost.setValue(10)
assert amount.value() == 12, "unmodified temporary amounts follow cost x 1.2"
amount.setValue(15)
cost.setValue(20)
assert amount.value() == 15, "manual amount is independent of manual cost"
cost.setValue(10)
editor.accept()
assert item["attachments"][0]["formula_amount"] == 10
assert item["attachments"][0]["quick_amount"] == 15
assert item["attachments"][0]["custom"] is True
assert item["attachments"][0].get("attachment_price_id") is None
editor = scheme2_ui.AttachmentEditor(owner, item)
cost = editor.table.cellWidget(0, editor.COL_FORMULA_AMOUNT)
amount = editor.table.cellWidget(0, editor.COL_AMOUNT)
assert amount.value() == 15
cost.setValue(12)
assert amount.value() == 15, "reopening must preserve the previous manual amount"
editor.table.cellWidget(0, editor.COL_QUANTITY).setValue(2)
assert cost.value() == 24 and amount.value() == 30
amount.setValue(17)
cost.setValue(10)
assert amount.value() == 17
editor.accept()
assert item["attachments"][0]["formula_amount"] == 10
assert item["attachments"][0]["quick_amount"] == 17
assert scheme2_ui.AttachmentEditor._display_amounts({"custom": True, "formula_amount": 8}) == (8, 9.6)
# Closing an automatically calculated row must keep automatic linkage enabled.
automatic_item = {"attachments": [{"custom": True, "item_name": "自动金额临时附件", "quantity": 1,
                                   "formula_amount": 0, "quick_amount": 0}],
                  "formula": {"attachment_fee": 0, "total_cost": 0},
                  "quick": {"attachment_fee": 0, "total_cost": 0}}
automatic = scheme2_ui.AttachmentEditor(owner, automatic_item)
automatic.table.cellWidget(0, automatic.COL_FORMULA_AMOUNT).setValue(10)
automatic.accept()
assert automatic_item["attachments"][0]["custom_amount_edited"] is False
automatic = scheme2_ui.AttachmentEditor(owner, automatic_item)
automatic.table.cellWidget(0, automatic.COL_FORMULA_AMOUNT).setValue(20)
assert automatic.table.cellWidget(0, automatic.COL_AMOUNT).value() == 24
automatic.accept()
print("PASS: temporary attachments need no ID; cost x 1.2 remains automatic unless amount is manually edited, including after reopen")
