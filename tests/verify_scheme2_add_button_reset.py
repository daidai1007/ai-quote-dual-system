from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
import scheme2_ui  # noqa: E402

app = QApplication.instance() or QApplication([])
button = QPushButton("已加入")
button.setEnabled(False)
window = SimpleNamespace(scheme2_add_button=button)
scheme2_ui._set_dirty(window, True)
assert window._scheme2_dirty is True
assert button.text() == "加入报价清单" and button.isEnabled()
scheme2_ui._set_dirty(window, False)
assert button.text() == "加入报价清单"
print("scheme2 add button reset contract passed")
