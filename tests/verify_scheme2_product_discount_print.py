"""Focused contract for product-wide discounts and direct printing."""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QComboBox, QWidget  # noqa: E402
import scheme2_ui  # noqa: E402


class Window(QWidget):
    def __init__(self, items):
        super().__init__()
        self.draft_items = items
        self.refresh_count = 0
        self.scheme2_company = QComboBox(self)
        self.scheme2_company.addItem("示例<&公司")

    def refresh_summary(self):
        self.refresh_count += 1


app = QApplication.instance() or QApplication([])
js1 = {"name": "柜1", "scheme2_selected_product_code": "JS", "quick": {"total_cost": 100}, "quantity": 2}
js2 = {"name": "柜2", "scheme2_selected_product_code": "JS", "quick": {"total_cost": 200}, "quantity": 1}
jp = {"name": "柜3", "scheme2_selected_product_code": "JP", "quick": {"total_cost": 300}, "quantity": 1}
window = Window([js1, js2, jp])

editor = scheme2_ui.FaceDiscountEditor(window, js1, [js1, js2])
assert editor.windowTitle() == "面价折扣"
assert editor.findChild(QWidget, "scheme2DiscountShell") is not None
editor.discount.setValue(0.8)
editor.accept()
assert js1["quick_discount"] == 0.8 and js2["quick_discount"] == 0.8
assert "quick_discount" not in jp and window.refresh_count == 1
assert scheme2_ui._row_values(js1)[13] == 80 and scheme2_ui._row_values(js2)[13] == 160

quote = scheme2_ui._printable_quote_html(window)
assert "示例&lt;&amp;公司" in quote and "JS" in quote and "JP" in quote
assert "合计：620.00 元" in quote

source = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
assert 'print_button = QPushButton("打印")' in source
assert "print_button.clicked.connect(lambda: _print_quote(window))" in source
assert "action_buttons = (delete, up, down, back, print_button, export)" in source

print("scheme2 product discount and print contract passed")
