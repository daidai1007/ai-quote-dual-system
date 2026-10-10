"""Offline popup regression: manual glass sizes must reprice each saved child."""
import copy
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
import attachment_v2_client as v2
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
app.setFont(QFont("Microsoft YaHei", 9))
namespace = v3_launcher.load_v3_namespace()
Window, Worker = namespace["MainWindow"], namespace["ApiWorker"]
CHILDREN = [dict(width_mm=800, height_mm=1800, depth_mm=500),
            dict(width_mm=600, height_mm=1800, depth_mm=500)]
PARAMETERS = [dict(name=name, source="MANUAL") for name in ("玻璃门高度", "玻璃门宽度")]


def pending(index):
    return dict(item_name="玻璃门", category_level1="控制柜附件", attachment_price_id=122,
                quantity=1, status="PENDING_MANUAL", ganged_cabinet_index=index,
                ganged_glass_door_match=True, size_match_ratio=1, matched_price=100,
                pending_manual_dimensions=[p["name"] for p in PARAMETERS],
                required_parameters=copy.deepcopy(PARAMETERS), manual_inputs={},
                formula_amount=0, formula_unit_cost=0, quick_amount=0)


class GlassReprice(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.warnings = []
        original_init = Worker.__init__

        def capture(worker, url, payload, parent=None, *args, **kwargs):
            original_init(worker, url, payload, parent, *args, **kwargs)
            worker.test_payload = copy.deepcopy(payload)

        def start(worker):
            payload = worker.test_payload
            self.requests.append(payload)

            def respond():
                selection = payload["attachments"][0]
                index = selection.get("ganged_cabinet_index")
                children = payload.get("ganged_cabinet_inputs", payload.get("ganged_cabinets", []))
                if index is not None and index >= len(children):
                    worker.failed.emit(f"第 {index + 1} 个子柜不存在")
                else:
                    manual = selection["manual_inputs"]
                    cost = manual["玻璃门高度"] * manual["玻璃门宽度"] / 1e6 * 55
                    worker.succeeded.emit({"attachments": [{**selection, "status": "CALCULATED",
                        "required_parameters": PARAMETERS, "formula_unit_cost": cost,
                        "formula_amount": cost * selection["quantity"], "quick_amount": 100 * selection["quantity"]}]})
                worker.finished.emit()
            QTimer.singleShot(0, respond)

        for target, name, value in ((Window, "load_catalogs", lambda self: None),
                (Window, "refresh_formula_inputs", lambda self, *args: None),
                (Worker, "__init__", capture), (Worker, "start", start),
                (QMessageBox, "warning", lambda parent, title, message: self.warnings.append(message))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = Window()
        self.addCleanup(self.window.close)
        # The visible editor belongs to another product, not the saved row.
        self.window.ganged_cabinets = [dict(width_mm=999, height_mm=999, depth_mm=999)]
        self.item = dict(product_code="JP", material_code="SECC", width_mm=1400,
            height_mm=1800, depth_mm=500, quantity=3, ganged_cabinet_count=2,
            ganged_cabinets=copy.deepcopy(CHILDREN), coating_type="橘纹",
            attachments=[pending(0), pending(1)], formula={"attachment_fee": 0, "total_cost": 200},
            quick={"attachment_fee": 0, "total_cost": 500})

    def test_both_child_sizes_reprice_and_refresh_popup_totals(self):
        editor = ui.AttachmentEditor(self.window, self.item)
        self.addCleanup(editor.close)
        for index, (height, width) in enumerate(((500, 400), (600, 300))):
            source = {**pending(index), "manual_inputs": {"玻璃门高度": height, "玻璃门宽度": width},
                      "quick_amount_override": 0}
            editor._reprice_row(index, source, editor.table.item(index, editor.COL_SPECIFICATION))
            deadline = time.monotonic() + 2
            while not editor.table.cellWidget(index, editor.COL_AMOUNT).isEnabled() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            self.assertEqual(editor.table.item(index, editor.COL_FORMULA_AMOUNT).text(), f"{height*width/1e6*55*3:.2f}")
            self.assertEqual(editor.table.cellWidget(index, editor.COL_AMOUNT).value(), 300)
            self.assertEqual(self.warnings, [])
            self.assertEqual(editor.table.item(index, editor.COL_SPECIFICATION).text(), f"宽 {width} × 高 {height} mm")
            self.assertFalse(editor.table.cellWidget(index, editor.COL_AMOUNT).property("pending"))
            self.assertEqual(self.requests[-1]["ganged_cabinets"], CHILDREN)
        editor.accept()
        self.assertEqual(self.item["quick"]["attachment_fee"], 200)
        self.assertAlmostEqual(self.item["formula"]["attachment_fee"], 20.9)
        self.assertTrue(all(row["status"] == "CALCULATED" for row in self.item["attachments"]))
        editor.show()
        app.processEvents()
        output = ROOT / "outputs" / "glass-manual-reprice.png"
        output.parent.mkdir(exist_ok=True)
        self.assertTrue(editor.grab().save(str(output)))

    def test_pending_placeholder_is_not_saved_as_manual_zero(self):
        editor = ui.AttachmentEditor(self.window, self.item)
        editor.accept()
        self.assertTrue(all("quick_amount_override" not in row for row in self.item["attachments"]))
        editor.close()

    def test_explicit_manual_zero_remains_valid(self):
        source = {**pending(0), "quick_amount_override": 0, "custom_amount_edited": True}
        calculated = v2.merge_cost(source, {"status": "CALCULATED", "quick_amount": 100,
            "formula_amount": 11, "quantity": 1})
        self.assertEqual(calculated["quick_amount"], 0)

    def test_legacy_row_uses_its_saved_environment_not_visible_editor(self):
        source = {**pending(1), "manual_inputs": {"玻璃门高度": 600, "玻璃门宽度": 300},
                  "environment": {"ganged_cabinets": copy.deepcopy(CHILDREN)}}
        self.item.pop("ganged_cabinets")
        results, errors = [], []
        self.window.recalculate_draft_attachment(self.item, source, results.append, errors.append)
        deadline = time.monotonic() + 2
        while not results and not errors and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.001)
        self.assertEqual(errors, [])
        self.assertEqual(self.requests[-1]["ganged_cabinets"], CHILDREN)
        self.assertAlmostEqual(results[0]["formula_amount"], 9.9)

    def test_missing_child_context_reports_error_without_request(self):
        self.item.pop("ganged_cabinets")
        results, errors = [], []
        self.window.recalculate_draft_attachment(self.item, pending(1), results.append, errors.append)
        self.assertEqual(results, [])
        self.assertIn("子柜尺寸缺失", errors[0])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
