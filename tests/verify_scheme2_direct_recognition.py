"""Focused checks for direct recognition-to-options flow (no API or build)."""

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication
import scheme2_ui


app = QApplication.instance() or QApplication([])


class Window:
    _scheme2_attachments_manual = False

    def __init__(self):
        self.attachments = []
        self.recommended_attachments = []
        self.refreshed = 0

    @staticmethod
    def recommend_attachment_names(text):
        assert "侧板" in text and "接地线" in text
        return ["侧板", "接地线"]

    def update_attachment_view(self):
        self.refreshed += 1


item = {"raw_text": "柜体含侧板和接地线", "dimensions": [(600, 1800, 400)]}
assert scheme2_ui._confirm_scheme2_recognition(item) is item
assert item["review_status"] == "confirmed"
assert item["confirmed"] and item["verified"]
assert item["manual_reviewed"] and item["manual_confirmation_checked"]
assert item["classification"] == "cabinet" and item["manual_reviewed_at"]
assert item["specification"] == "600*1800*400"
assert item["remark_review_required"] is False

window = Window()
scheme2_ui._apply_recognized_attachments(window, item)
assert [row["item_name"] for row in window.attachments] == ["侧板", "接地线"]
assert all(row["quantity"] == 1 and row["recognized"] for row in window.attachments)
assert window.refreshed == 1

window._scheme2_attachments_manual = True
scheme2_ui._apply_recognized_attachments(window, {"raw_text": "侧板"})
assert [row["item_name"] for row in window.attachments] == ["侧板", "接地线"]

print("PASS: current drawing recognition is quote-ready and fills attachment selections")

workflow_source = (ROOT / "desktop_client" / "drawing_workflow.py").read_text(encoding="utf-8")
install_source = workflow_source.split("def install_drawing_workflow", 1)[1]
assert "build_summary(window)" not in install_source
