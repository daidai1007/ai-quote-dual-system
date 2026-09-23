from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QLineEdit  # noqa: E402
import layout_refresh  # noqa: E402

app = QApplication.instance() or QApplication([])
company, product = QComboBox(), QComboBox()
company.addItem("示例科技有限公司")
product.addItem("JA")
window = SimpleNamespace(company_combo=company, product_combo=product, quote_spec_edit=QLineEdit("600*600*500"))
result = {"matched": True, "payload": {"quote_date": "2026-08-14", "quote_id": "Q20260814-03", "item": {"variant_name": "变体 A"}}}
summary = layout_refresh._history_order_summary(window, result)
assert "示例科技有限公司 · JA · 600*600*500 · 变体 A" in summary
assert "2026-08-14" in summary and "Q20260814-03" in summary
dialog = layout_refresh._HistoryOrderDialog(summary)
assert dialog.size().width() == 490 and dialog.size().height() == 330
assert dialog.findChild(QLabel, "historyOrderSummary").text() == summary
assert {button.text() for button in dialog.findChildren(QPushButton)} >= {"不带入，继续填写", "带入历史设置", "×"}
print("history order dialog contract passed")
