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
    **attachment, "attachment_price_id": 24, "quantity": 1,
    "quick_amount": 50, "formula_amount": 40.06,
})
item = {
    "attachments": [{"item_name": "照明灯/行程开关", "model_code": "220V", "quantity": 1}],
    "formula": {"attachment_fee": 27.56, "total_cost": 27.56},
    "quick": {"attachment_fee": 50, "total_cost": 50},
}
editor = scheme2_ui.AttachmentEditor(window, item)
selector = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
assert isinstance(selector, scheme2_ui.QComboBox)
assert [selector.itemData(index) for index in range(1, selector.count())] == list(scheme2_ui.LIGHT_SWITCH_MODELS)
assert selector.currentData() == "220V"
selector.setCurrentIndex(selector.findData("24V-0.6m"))
editor.accept()
assert item["attachments"][0]["model_code"] == "24V-0.6m"
assert item["attachments"][0]["attachment_price_id"] == 24
editor.close(); window.close()
print("PASS: light switch model dropdown matches three-row beam behavior")
