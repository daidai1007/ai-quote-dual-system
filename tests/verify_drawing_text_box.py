from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsTextItem  # noqa: E402

from quote_drawing_preview import QuoteDrawingPreview  # noqa: E402

app = QApplication.instance() or QApplication([])
preview = QuoteDrawingPreview(None, None)
preview.resize(800, 600)
preview.show()
preview.canvas.setEnabled(True)
preview.page_count = 1
preview.update_tools()
preview.text_button.click()
assert preview.canvas.text_enabled
QTest.mouseClick(preview.canvas.viewport(), Qt.MouseButton.LeftButton, pos=preview.canvas.viewport().rect().center())
app.processEvents()
texts = [item for item in preview.canvas.scene().items() if isinstance(item, QGraphicsTextItem)]
assert len(texts) == 1 and texts[0].toPlainText() == "请输入文字"
assert texts[0].defaultTextColor().name().lower() == "#d32f2f"
preview.close()
print("DRAWING_TEXT_BOX=PASS")
