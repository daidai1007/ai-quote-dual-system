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


fixture = json.loads((ROOT / "test-output/attachment-cost-v2/api-client-fixtures.json").read_text(encoding="utf-8"))
missing = copy.deepcopy(fixture["missing"]["attachments"][0])
result = provisionalize_manual_dimension_result({
    "attachment_contract": 2,
    "attachments": [missing],
    "formula_cost": {
        "material_cost": 100, "auxiliary_cost": 20, "labor_cost": 30,
        "spray_cost": 10, "management_fee": 5, "attachment_fee": None, "total_cost": None,
    },
    "quick_quote": {"base_price": 300, "attachment_fee": missing["quick_amount"], "total_cost": 499.66},
    "risk_flags": [{"code": "attachment_error", "severity": "blocker", "message": "固定底座：" + missing["error"]}],
})
row = result["attachments"][0]
assert row["status"] == "PENDING_MANUAL"
assert row["quick_amount"] == 0 and row["formula_amount"] == 0
assert row["pending_manual_dimensions"] == ["底座高度"]
assert result["quick_quote"]["attachment_fee"] == 0
assert result["formula_cost"]["attachment_fee"] == 0
assert result["formula_cost"]["total_cost"] == 165
assert result["risk_flags"] == []

app = QApplication.instance() or QApplication([])
window = QWidget()
window.refresh_summary = lambda: None
item = {"attachments": [row], "formula": result["formula_cost"], "quick": result["quick_quote"]}
editor = scheme2_ui.AttachmentEditor(window, item)
assert editor.table.columnCount() == 6
assert editor.table.horizontalHeaderItem(0).text() == "图片"
assert editor.table.item(0, 2).text().startswith("点击补充")
assert editor.table.cellWidget(0, 4).value() == 0
assert editor.table.item(0, 5).text() == "0.00"
assert editor.table.item(0, 5).data(Qt.ItemDataRole.ForegroundRole) is not None
dimension_dialog = scheme2_ui._SchemeDimensionEditor(editor, "固定底座 · 补充尺寸", ["底座高度"], {})
assert dimension_dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
assert not dimension_dialog.confirm_button.isEnabled()
dimension_dialog.fields["底座高度"].setText("100")
assert dimension_dialog.confirm_button.isEnabled()
assert dimension_dialog.values() == {"底座高度": 100.0}
dimension_dialog.close()
editor.close()
window.close()

print("PASS: missing manual dimensions remain addable at red zero amounts until database repricing")
