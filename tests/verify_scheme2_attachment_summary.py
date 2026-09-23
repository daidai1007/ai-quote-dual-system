from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402

core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window.attachments = [
    {"category_level1": "安装附件", "item_name": "三排安装梁", "quantity": 1},
    {"category_level1": "侧板", "item_name": "侧板", "quantity": 1},
    {"item_name": "加强条", "quantity": 2, "custom": True},
]
window._scheme2_attachments_manual = True
scheme2_ui._refresh_scheme2_attachment_summary(window)
app.processEvents()

chips = [label.text() for label in window.scheme2_attachment_summary.findChildren(QLabel, "scheme2AttachmentChip")]
assert chips == ["安装附件：三排安装梁", "侧板 ✓", "临时：加强条 ×2"]
assert window.scheme2_attachment_status.text() == "人工修改 ✎"
assert window.scheme2_attachment_card.property("provenanceState") == "manual"
assert window.scheme2_attachment_button.text() == "修改…"

window.close()
app.processEvents()
print("scheme2 attachment summary contract passed")
