import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

import scheme2_ui


app = QApplication.instance() or QApplication([])
window = QWidget()
window.stack = QStackedWidget()
for _ in range(scheme2_ui.DETAIL_ROUTE + 1):
    window.stack.addWidget(QWidget())
page = scheme2_ui._build_detail_page(window)
item = {"formula": {"material_cost": 100}}
scheme2_ui._apply_responsive = lambda _window: None
scheme2_ui._show_detail(window, item)
factor = window.scheme2_detail_table.cellWidget(0, 8)
assert factor.minimum() == 0
factor.setValue(0)
assert item["cost_detail_rows"][0]["factor"] == 0
assert window.scheme2_detail_table.item(0, 9).text() == "0.00"

page.close()
window.close()
print("PASS: cost detail factor accepts zero and recalculates the row to zero")
