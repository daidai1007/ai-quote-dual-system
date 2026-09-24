"""Focused coverage for resize recovery and portable order workspace files."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import zipfile


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

    # A workspace moved from the former AppData directory must still find and
    # package drawings that now live under the configured cache root.
    migrated_dir = scheme2_ui._order_workspace_cache_dir("124") / "drawings"
    migrated_dir.mkdir(parents=True)
    migrated_drawing = migrated_dir / "legacy.pdf"
    migrated_drawing.write_bytes(b"legacy-drawing")
    migrated_payload = {
        "drawing_pages": [{
            "source_path": r"C:\old-app-data\order-workspaces\hash\drawings\legacy.pdf",
            "page_index": 0, "page_count": 1,
        }],
    }
    migrated_file = scheme2_ui._write_order_workspace_file(
        "124", migrated_payload, folder / "迁移订单.aiquote"
    )
    migrated_order, migrated_restored = scheme2_ui._read_order_workspace_file(migrated_file)
    assert migrated_order == "124"
    assert Path(migrated_restored["drawing_pages"][0]["source_path"]).read_bytes() == b"legacy-drawing"

    # Exercise the actual save button flow: the path chosen by the operator
    # must receive a portable file with the drawing embedded.
    manual_drawing = folder / "manual-choice.pdf"
    manual_drawing.write_bytes(b"manual-choice-drawing")
    chosen_path = folder / "人工选择位置" / "订单MANUAL.aiquote"
    window.scheme2_order_number.setText("MANUAL")
    window._scheme2_drawing_pages = [{
        "source_path": str(manual_drawing), "page_index": 0, "page_count": 1,
        "item": {},
    }]
    window._scheme2_drawing_page_index = 0
    window._scheme2_api_worker_class = None
    original_save_dialog = scheme2_ui.QFileDialog.getSaveFileName
    scheme2_ui.QFileDialog.getSaveFileName = staticmethod(
        lambda *_args, **_kwargs: (str(chosen_path), "AI 双报价订单 (*.aiquote)")
    )
    try:
        scheme2_ui._manual_save_order_workspace(window)
    finally:
        scheme2_ui.QFileDialog.getSaveFileName = original_save_dialog
    assert chosen_path.is_file()
    with zipfile.ZipFile(chosen_path) as archive:
        drawing_entries = [name for name in archive.namelist() if name.startswith("drawings/")]
        assert len(drawing_entries) == 1
        assert archive.read(drawing_entries[0]) == b"manual-choice-drawing"

window.close()
print("WORKSPACE_FILE_AND_RESIZE=PASS")
