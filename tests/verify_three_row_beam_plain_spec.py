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
    "attachments": [{"item_name": "三排安装梁", "model_code": "JP760260", "quantity": 1, "matched_price": 60}],
    "formula": {"attachment_fee": 60, "total_cost": 60},
    "quick": {"attachment_fee": 60, "total_cost": 60},
}
editor = scheme2_ui.AttachmentEditor(window, item)
assert editor.table.cellWidget(0, 1) is None
assert editor.table.item(0, 1).text() == "—"
editor.close()
window.close()

print("PASS: three-row beam no longer has a dedicated model dropdown")
