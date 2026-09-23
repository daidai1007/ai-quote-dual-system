import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication

import v3_launcher


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
combo = window.product_combo
placeholder = int(combo.property("schemePlaceholderIndex"))
assert combo.objectName() == "scheme2ProductCombo"
assert hasattr(combo, "_scheme2_popup_filter")
assert combo.view().itemDelegate().objectName() == "scheme2DropdownItemDelegate"
assert combo.property("placeholderActive") is True
combo.blockSignals(True)
combo.addItem("JA", "JA")
combo.addItem("JP", "JP")
combo.blockSignals(False)
combo.showPopup()
app.processEvents()
assert combo.property("popupOpen") is True
assert combo.view().isRowHidden(placeholder)
assert combo.view().sizeHintForRow(1) >= 40
combo.hidePopup()
window.close()
print("PASS: product model dropdown uses the scheme popup, hidden placeholder and selected-state styling")
