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
selector = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
assert isinstance(selector, scheme2_ui.QComboBox)
assert [selector.itemData(index) for index in range(1, selector.count())] == list(scheme2_ui.THREE_ROW_BEAM_MODELS)
assert selector.currentData() == "JP760260"
selector.setCurrentIndex(selector.findData("JP760280"))
assert selector.isEnabled()
assert editor.table.cellWidget(0, editor.COL_AMOUNT).value() == 80
assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).text() == "32.00"
editor.accept()
assert item["attachments"][0]["model_code"] == "JP760280"
assert item["attachments"][0]["attachment_price_id"] == 280
editor.close()
window.close()

print("PASS: three-row beam model dropdown reprices the selected model")
