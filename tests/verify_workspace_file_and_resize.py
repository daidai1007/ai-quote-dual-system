"""Focused coverage for resize recovery and portable order workspace files."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402


assert scheme2_ui.ORDER_WORKSPACE_ROOT == Path(r"G:\gongsi\banjinxitong\板件后续二次修改")


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()

window.show_section(scheme2_ui.COST_ROUTE)
window.resize(1680, 980)
app.processEvents()
window.resize(1024, 700)
app.processEvents()
scheme2_ui._apply_responsive(window)
main_scroll = window.findChild(scheme2_ui.QScrollArea, "mainScroll")
assert main_scroll.verticalScrollBar().value() == 0
assert window.stack.currentWidget() is window.scheme2_cost_page
assert window.scheme2_cost_page.geometry().top() == 0

with tempfile.TemporaryDirectory(prefix="aiquote-workspace-") as folder:
    folder = Path(folder)
    os.environ["AI_QUOTE_ORDER_CACHE_ROOT"] = str(folder / "cache")
    drawing = folder / "drawing.png"
    drawing.write_bytes(b"drawing-content")
    payload = {
        "option_state": {},
        "drawing_pages": [{
            "source_path": str(drawing), "page_index": 0, "page_count": 1,
        }],
        "drawing_page_index": 0,
        "draft_items": [{"name": "test"}],
        "active_route": scheme2_ui.COST_ROUTE,
    }
    saved = scheme2_ui._write_order_workspace_file("123", payload, folder / "订单123")
    assert saved.suffix == scheme2_ui.ORDER_WORKSPACE_SUFFIX and saved.is_file()
    order_number, restored = scheme2_ui._read_order_workspace_file(saved)
    restored_drawing = Path(restored["drawing_pages"][0]["source_path"])
    assert order_number == "123"
    assert restored_drawing.read_bytes() == b"drawing-content"
    assert restored["active_route"] == scheme2_ui.COST_ROUTE

window.close()
print("WORKSPACE_FILE_AND_RESIZE=PASS")
