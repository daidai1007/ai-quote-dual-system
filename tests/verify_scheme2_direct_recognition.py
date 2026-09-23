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


class Value:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class Text:
    def __init__(self, value):
        self._value = value

    def text(self):
        return self._value

    def toPlainText(self):
        return self._value


active = {"candidate_id": "page-1"}
quote_window = type("QuoteWindow", (), {})()
quote_window.active_drawing = active
quote_window.width_spin = Value(1250)
quote_window.height_spin = Value(2000)
quote_window.depth_spin = Value(400)
quote_window.quote_spec_edit = Text("1250*400*2000")
quote_window.notes_text = Text("JP 柜体")
scheme2_ui._synchronize_active_drawing_confirmation(quote_window)
assert active["dimensions"] == [(1250, 2000, 400)]
assert active["specification"] == "1250*400*2000"
assert active["reviewed_remark"] == "JP 柜体"
assert quote_window._quote_drawing is active

export_item = {"source_reviewed_remark": "旧图纸备注"}
scheme2_ui._synchronize_export_remark(export_item, "仿威图JP柜，SUS304，无，RAL7035，无附件。")
assert len({export_item[key] for key in (
    "final_remark", "notes", "source_ocr_remark", "source_reviewed_remark"
)}) == 1

workflow_source = (ROOT / "desktop_client" / "drawing_workflow.py").read_text(encoding="utf-8")
install_source = workflow_source.split("def install_drawing_workflow", 1)[1]
assert "build_summary(window)" not in install_source
scheme_source = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
retired_source = scheme_source.split("window._scheme2_retired_pages = [old_cost_page]", 1)[1].split("_install_shortcuts", 1)[0]
assert "retired.setParent(window)" in retired_source
assert "retired.deleteLater()" not in retired_source
assert "window._scheme2_retired_pages = [old_cost_page]" in scheme_source
