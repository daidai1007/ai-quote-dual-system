import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import scheme2_ui


app = QApplication.instance() or QApplication([])
window = QWidget()
window.refresh_summary = lambda: None
window.recalculate_draft_attachment = lambda _quote, attachment, succeeded, _failed: succeeded({
    **attachment,
    "attachment_price_id": 280,
    "quantity": 1,
    "quick_amount": 80,
    "formula_amount": 32,
})
item = {
    "attachments": [{"item_name": "三排安装梁", "model_code": "JP760260", "quantity": 1, "matched_price": 60}],
    "formula": {"attachment_fee": 60, "total_cost": 60},
    "quick": {"attachment_fee": 60, "total_cost": 60},
}
editor = scheme2_ui.AttachmentEditor(window, item)
editor.show(); app.processEvents()
specification = editor.table.item(0, editor.COL_SPECIFICATION)
assert specification.text() == "JP760260"
assert editor.table.cellWidget(0, editor.COL_SPECIFICATION) is None
point = editor.table.visualItemRect(specification).center()
QTest.mouseClick(editor.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
assert editor.table.cellWidget(0, editor.COL_SPECIFICATION) is None
QTest.mouseDClick(editor.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
app.processEvents()
selector = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
assert isinstance(selector, scheme2_ui.QComboBox)
assert [selector.itemData(index) for index in range(1, selector.count())] == list(scheme2_ui.THREE_ROW_BEAM_MODELS)
assert selector.currentData() == "JP760260"
selector.setCurrentIndex(selector.findData("JP760280"))
app.processEvents()
assert editor.table.cellWidget(0, editor.COL_SPECIFICATION) is None
assert specification.text() == "JP760280"
assert editor.table.cellWidget(0, editor.COL_AMOUNT).value() == 80
assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).text() == "32.00"
editor.accept()
assert item["attachments"][0]["model_code"] == "JP760280"
assert item["attachments"][0]["attachment_price_id"] == 280
editor.close()

tray = scheme2_ui.AttachmentEditor(window, {"attachments": [
    {"category_level1": "控制柜附件", "item_name": "电脑托盘", "model_code": "JP930060", "quantity": 1}
], "formula": {}, "quick": {}})
tray.show(); app.processEvents()
tray_spec = tray.table.item(0, tray.COL_SPECIFICATION)
assert tray_spec.text() == "JP930060"
assert tray.table.cellWidget(0, tray.COL_SPECIFICATION) is None
tray_point = tray.table.visualItemRect(tray_spec).center()
QTest.mouseClick(tray.table.viewport(), Qt.MouseButton.LeftButton, pos=tray_point)
assert tray.table.cellWidget(0, tray.COL_SPECIFICATION) is None
QTest.mouseDClick(tray.table.viewport(), Qt.MouseButton.LeftButton, pos=tray_point)
app.processEvents()
tray_selector = tray.table.cellWidget(0, tray.COL_SPECIFICATION)
assert isinstance(tray_selector, scheme2_ui.QComboBox)
assert [tray_selector.itemData(index) for index in range(1, tray_selector.count())] == list(scheme2_ui.COMPUTER_TRAY_MODELS)
QTest.mouseClick(tray.table.viewport(), Qt.MouseButton.LeftButton,
                 pos=tray.table.visualItemRect(tray.table.item(0, tray.COL_NAME)).center())
app.processEvents()
assert tray.table.cellWidget(0, tray.COL_SPECIFICATION) is None
assert tray_spec.text() == "JP930060"
tray.close()
window.close()

print("PASS: beam and tray show plain models until double click; beam selection reprices")
