import copy
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from attachment_v2_client import provisionalize_manual_dimension_result
import scheme2_ui


missing = dict(attachment_price_id=123,quantity=1,status="ERROR",quick_amount=199.66,
               formula_amount=None,attachment_price_sign=1,catalog_version="synthetic")
missing.update(item_name="分段板", category_level1="安装附件", category_level2="分段板",
               required_parameters=[{"name":"分段板高度","source":"MANUAL"}],
               error="人工尺寸 分段板高度必须为正数", manual_inputs={})
result = provisionalize_manual_dimension_result({
    "attachment_contract": 2,
    "attachments": [missing],
    "formula_cost": {
        "material_cost": 100, "auxiliary_cost": 20, "labor_cost": 30,
        "spray_cost": 10, "management_fee": 5, "attachment_fee": None, "total_cost": None,
    },
    "quick_quote": {"base_price": 300, "attachment_fee": missing["quick_amount"], "total_cost": 499.66},
    "risk_flags": [{"code": "attachment_error", "severity": "blocker", "message": "分段板：" + missing["error"]}],
})
row = result["attachments"][0]
assert row["status"] == "PENDING_MANUAL"
assert row["quick_amount"] == 0 and row["formula_amount"] == 0
assert row["pending_manual_dimensions"] == ["分段板高度"]
assert result["quick_quote"]["attachment_fee"] == 0
assert result["formula_cost"]["attachment_fee"] == 0
assert result["formula_cost"]["management_fee"] == 9.6
assert result["formula_cost"]["total_cost"] == 169.6
assert result["risk_flags"] == []

app = QApplication.instance() or QApplication([])
window = QWidget()
window.refresh_summary = lambda: None
item = {"attachments": [row], "formula": result["formula_cost"], "quick": result["quick_quote"]}
editor = scheme2_ui.AttachmentEditor(window, item)
assert editor.table.columnCount() == editor.COL_AMOUNT + 1
assert editor.table.horizontalHeaderItem(editor.COL_NAME).text() == "名称"
assert editor.table.item(0, editor.COL_SPECIFICATION).text().startswith("点击补充")
assert float(editor.table.item(0, editor.COL_AMOUNT).text().replace(",", "")) == 0
assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).text() == "0.00"
assert editor.table.item(0, editor.COL_FORMULA_AMOUNT).data(Qt.ItemDataRole.ForegroundRole) is not None
dimension_dialog = scheme2_ui._SchemeDimensionEditor(editor, "分段板 · 补充尺寸", ["分段板高度"], {})
assert dimension_dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
assert not dimension_dialog.confirm_button.isEnabled()
dimension_dialog.fields["分段板高度"].setText("100")
assert dimension_dialog.confirm_button.isEnabled()
assert dimension_dialog.values() == {"分段板高度": 100.0}
dimension_dialog.close()
editor.close()
window.close()

print("PASS: missing manual dimensions remain addable at red zero amounts until database repricing")
