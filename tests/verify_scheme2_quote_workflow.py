"""Focused runtime coverage for quote navigation, add timing and background OCR."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
from pypdf import PdfWriter  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()


def wait_until(predicate, attempts=500):
    for _ in range(attempts):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("timed out waiting for focused UI state")


assert [button.text() for button in window.nav_buttons] == ["选项配置", "成本计算", "报价单"]
assert window.stack.widget(scheme2_ui.QUOTE_ROUTE).objectName() == "scheme2QuotePage"
assert [button.text() for button in window.scheme2_cost_page.findChildren(QPushButton)].count("打印") == 0
assert [button.text() for button in window.scheme2_cost_page.findChildren(QPushButton)].count("导出报价单") == 0
assert window.scheme2_cost_generate.text() == "生成报价单"
assert window.scheme2_quote_print.text() == "打印"
assert window.scheme2_quote_export.text() == "导出报价单"

window._scheme2_add_started_at = time.monotonic() - 1.2
scheme2_ui._set_add_progress(window, 2, "后台处理")
assert "秒" in window.scheme2_add_progress.format()


class FakeRecognition:
    @classmethod
    def recognize_document(cls, path):
        time.sleep(0.03)
        return {"cabinet_candidates": [{
            "product_code": "JP", "specification": "800*600*2000",
            "material_code": "SECC", "coating": "橘纹", "color": "RAL7035 浅灰",
        }]}


with tempfile.TemporaryDirectory(prefix="scheme2-background-") as folder:
    source = Path(folder) / "two-pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as stream:
        writer.write(stream)
    writer.close()
    window._scheme2_recognition_tools = FakeRecognition
    scheme2_ui._import_scheme2_drawings(window, [str(source)])
    assert window._scheme2_page_worker is not None
    assert window.scheme2_page_selector.isEnabled()
    window.scheme2_page_selector.setValue(2)
    assert window._scheme2_drawing_page_index == 1
    window.quote_spec_edit.setText("人工输入保留")
    window.quote_spec_edit.textEdited.emit(window.quote_spec_edit.text())
    wait_until(lambda: window._scheme2_page_worker is None and all(
        entry.get("item") is not None for entry in window._scheme2_drawing_pages
    ))
    assert window._scheme2_drawing_page_index == 1
    assert window.quote_spec_edit.text() == "人工输入保留"
    assert "2 / 2" in window.scheme2_recognition_status.text()
    wait_until(lambda: not window.quote_drawing_preview._workers)

window.draft_items = []
window.add_current_to_summary = lambda: window.draft_items.append({
    "name": "JP 测试", "product_code": "JP", "specification": "800*600*2000",
    "quantity": 1, "formula": {"total_cost": 80}, "quick": {"total_cost": 100},
    "attachments": [],
})
window.show_section(scheme2_ui.OPTION_ROUTE)
scheme2_ui._finish_add(window)
app.processEvents()
assert window.stack.currentIndex() == scheme2_ui.OPTION_ROUTE
assert window._scheme2_drawing_pages[1]["quoted"] is True
assert window.scheme2_quoted_badge.isVisibleTo(window)
assert len(window.draft_items) == 1

window.show_section(scheme2_ui.COST_ROUTE)
window.scheme2_cost_generate.click()
app.processEvents()
assert window.stack.currentIndex() == scheme2_ui.QUOTE_ROUTE
quote_text = " ".join(
    window.scheme2_quote_preview.item(row, column).text()
    for row in range(window.scheme2_quote_preview.rowCount())
    for column in range(window.scheme2_quote_preview.columnCount())
    if window.scheme2_quote_preview.item(row, column) is not None
)
assert "报价单" in quote_text and "100.00" in quote_text
assert window.scheme2_quote_print.isEnabled() and window.scheme2_quote_export.isEnabled()

window.close()
print("SCHEME2_QUOTE_WORKFLOW=PASS")
