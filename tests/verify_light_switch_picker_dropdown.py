import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication
import scheme2_ui

app = QApplication.instance() or QApplication([])
dialog = scheme2_ui._SchemeAttachmentDialog([], "JP")
assert "照明灯/行程开关" in dialog.category_combos
combo = dialog.category_combos["照明灯/行程开关"]
assert [combo.itemText(index) for index in range(1, combo.count())] == list(scheme2_ui.LIGHT_SWITCH_OPTIONS)
combo.set_selected_texts(["行程开关", "照明灯24V-0.6m"])
dialog.category_checks["照明灯/行程开关"].setChecked(True)
selected = dialog.collect_attachments()
assert [row["item_name"] for row in selected] == ["行程开关", "照明灯24V-0.6m"]
dialog.close()
print("PASS: option-page light switch picker exposes five database items")
