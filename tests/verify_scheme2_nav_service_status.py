from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QFrame, QLabel  # noqa: E402

import v3_launcher  # noqa: E402

core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window.show()
app.processEvents()

option_page = window.stack.widget(1)
assert option_page.findChild(QFrame, "scheme2TopBar") is None
assert option_page.findChild(QLabel, "scheme2SavedStatus") is None
service = window.scheme2_nav.findChild(QLabel, "scheme2ServiceStatus")
assert service is window.scheme2_service_status
assert "报价" in service.text()
assert service.y() > window.nav_buttons[-1].y()

window.close()
app.processEvents()
print("scheme2 navigation service status contract passed")
