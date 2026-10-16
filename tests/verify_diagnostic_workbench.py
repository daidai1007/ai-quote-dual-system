"""Focused actual V3-workbench smoke test for the diagnostic action."""
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
import v3_launcher  # noqa: E402


namespace = v3_launcher.load_v3_namespace()
app = QApplication.instance() or QApplication([])
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
app.processEvents()
button = window.scheme2_nav.findChild(QPushButton, "scheme2PrimaryGhost")
assert window.scheme2_diagnostic_button.text() == "提交诊断报告"
assert window.scheme2_diagnostic_button.parentWidget() is window.scheme2_nav
assert callable(window._scheme2_diagnostic_headers_factory)
assert window._scheme2_diagnostic_api_url
assert window._diagnostic_events[0]["action"] == "client_opened"
window.close()
print("diagnostic workbench smoke test passed")
