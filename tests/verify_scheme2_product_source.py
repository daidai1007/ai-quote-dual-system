"""Focused contract for the cost-table product source."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

import scheme2_ui  # noqa: E402
import layout_refresh  # noqa: E402


app = QApplication.instance() or QApplication([])
combo = QComboBox()
combo.addItem("JP 进线柜", {"product_code": "JP"})
combo.addItem("JA 控制箱", {"product_code": "JA"})
window = SimpleNamespace(product_combo=combo)
item = {
    "product_name": "API 返回的其他产品",
    "product_code": "JS_SINGLE",
    "formula": {},
    "quick": {},
}

scheme2_ui._stamp_selected_product(window, item)
assert item["product_code"] == "JS_SINGLE"  # 不改动计算/导出业务字段
assert item["scheme2_selected_product_code"] == "JP"
assert item["scheme2_selected_product_name"] == "JP 进线柜"
assert scheme2_ui._row_values(item)[2] == "JP 进线柜"

combo.setCurrentIndex(1)
assert scheme2_ui._row_values(item)[2] == "JP 进线柜"  # 已加入行保留当时选项
scheme2_ui._stamp_selected_product(window, item)
assert scheme2_ui._row_values(item)[2] == "JA 控制箱"

legacy = {"product_name": "不得采用", "product_code": "JE_SINGLE", "formula": {}, "quick": {}}
assert scheme2_ui._row_values(legacy)[2] == "JE_SINGLE"

# JA 0/1 still uses the sole JA formula template when no JA_DOUBLE row exists.
ja_combo = QComboBox()
ja_combo.addItem("JA", "JA")
ja_window = SimpleNamespace(
    product_combo=ja_combo,
    product_catalog={"JA": {"codes": {"SINGLE": "JA_SINGLE"}}},
)
assert layout_refresh._ja_product_code_fallback(ja_window) == "JA_SINGLE"
print("scheme2 product source contract passed")
