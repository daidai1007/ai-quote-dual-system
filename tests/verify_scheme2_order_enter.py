import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import scheme2_ui
import v3_launcher

namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window._scheme2_api_worker_class = None
window.show()
window.scheme2_order_number.setText("123")
window.scheme2_order_number.setFocus()
app.processEvents()
called = []
scheme2_ui._calculate_and_add = lambda _window: called.append(True)
QTest.keyClick(window.scheme2_order_number, Qt.Key.Key_Return)
app.processEvents()
assert not called
window.close()
print("SCHEME2_ORDER_ENTER=PASS")
