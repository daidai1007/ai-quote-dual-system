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
assert amount.value() == 12
amount.setValue(15)
editor.accept()
assert item["attachments"][0]["formula_amount"] == 10
assert item["attachments"][0]["quick_amount"] == 15
print("PASS: custom attachment is selectable and cost editor has no image column")
