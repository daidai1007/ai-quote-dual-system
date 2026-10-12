"""Offline regression: missing base height must be entered before matching."""
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
from PySide6.QtWidgets import QApplication, QDialog
import attachment_v2_client as v2
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
Window, Worker = ns["MainWindow"], ns["ApiWorker"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
catalog = [dict(category_level1="底座", item_name=name, attachment_price_id=index * 10 + offset,
                width_mm=width, depth_mm=depth, height_mm=100, price=price)
           for index, name in enumerate(("固定底座", "活动底座"), 1)
           for offset, width, depth, price in ((1, 600, 400, 199.66), (2, 400, 300, 100))]
requests = []
original_init = Worker.__init__


def capture(self, url, payload, parent=None, *args, **kwargs):
    original_init(self, url, payload, parent, *args, **kwargs)
    self.test_url, self.test_payload = url, copy.deepcopy(payload)


def start(self):
    requests.append((self.test_url, self.test_payload))
    def respond():
        if "catalog?v=2" in self.test_url:
            self.succeeded.emit({"items": copy.deepcopy(catalog), "data_version": "offline"})
        elif self.test_url.endswith("/preview"):
            selection = self.test_payload["attachments"][0]
            row = next(row for row in catalog if row["attachment_price_id"] == selection["attachment_price_id"])
            assert selection["manual_inputs"]["底座高度"] > 0
            self.succeeded.emit({"attachments": [{**row, **selection, "status": "CALCULATED",
                "quick_amount": row["price"] * selection["quantity"],
                "formula_unit_cost": 10, "formula_amount": 10 * selection["quantity"]}]})
        else:
            self.failed.emit("unexpected request")
        self.finished.emit()
    QTimer.singleShot(0, respond)


Worker.__init__, Worker.start = capture, start


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.001)
    raise AssertionError("offline request did not finish")


class MissingBaseHeight(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window.api_url.setText("http://127.0.0.1:1/api/quotes/calculate-dual")
        self.window.quote_spec_edit.setText("400*300*400")
        self.window.model_edit.setText("400*300*400")
        self.window.width_spin.setValue(400)
        self.window.height_spin.setValue(400)
        self.window.depth_spin.setValue(300)
        self.window.refresh_summary = lambda: None
        app.processEvents()
        requests.clear()
        self.addCleanup(self.window.close)

    def test_missing_height_cannot_match_even_single_catalogue_row_or_model(self):
        for row in catalog:
            for value in (None, 0, -1, float("nan"), float("inf")):
                selection = {**row, "model_code": "explicit", "manual_inputs": {"底座高度": value}}
                self.assertIsNone(v2.match_catalog_attachment(selection, [row], (400,400,300)))
        self.assertIsNone(v2.base_height(self.window))

    def test_manual_and_specification_heights_match_real_dimensions(self):
        for name in ("固定底座", "活动底座"):
            selection = dict(item_name=name, category_level1="底座")
            for manual in ({}, {"底座高度": 100}):
                result = v2.match_catalog_attachment({**selection, "manual_inputs": manual}, catalog,
                                                     (400,400,300), base_height_mm=100)
                self.assertEqual((result["width_mm"], result["depth_mm"], result["height_mm"]), (400,300,100))
        self.window.quote_spec_edit.setText("400*300*(400+100)")
        self.window.attachments = [catalog[0]]
        self.assertFalse(v2.needs_base_height_resolution(self.window))
        successes = []
        with patch.object(ui.AttachmentEditor, "exec", side_effect=AssertionError("height already specified")):
            self.window.resolve_attachments_for_quote(lambda:successes.append(True), self.fail)
        self.assertEqual(successes, [True])
        self.assertEqual(self.window.attachments[0]["manual_inputs"], {"底座高度":100})

    def test_legacy_wrong_match_is_pending_and_does_not_preview(self):
        source = {**catalog[0], "quantity": 1, "quick_amount": 199.66, "formula_amount": 20}
        item = dict(attachments=[source], width_mm=400, height_mm=400, depth_mm=300, quantity=1,
                    quick={"attachment_fee": 199.66, "total_cost": 500}, formula={"attachment_fee":20,"total_cost":200})
        editor = ui.AttachmentEditor(self.window, item)
        self.addCleanup(editor.close)
        pending = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
        self.assertIsNone(pending.get("attachment_price_id"))
        self.assertIn("底座高度", editor.table.item(0, editor.COL_SPECIFICATION).text())
        self.assertEqual(editor.table.cellWidget(0, editor.COL_AMOUNT).value(), 0)
        self.assertFalse(editor.table.cellWidget(0, editor.COL_AMOUNT).isEnabled())
        errors = []
        self.window.recalculate_draft_attachment(item, pending, self.fail, errors.append)
        self.assertIn("底座高度", errors[0])
        self.assertEqual(requests, [])
        def enter(dlg):
            dlg.fields["底座高度"].setText("100")
            return QDialog.DialogCode.Accepted
        with patch.object(ui._SchemeDimensionEditor, "exec", enter):
            editor.edit_missing_dimensions(0, editor.COL_SPECIFICATION)
        wait_for(lambda: editor.table.cellWidget(0, editor.COL_AMOUNT).isEnabled())
        calculated = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
        self.assertEqual(calculated["attachment_price_id"], catalog[1]["attachment_price_id"])
        self.assertEqual(calculated["manual_inputs"], {"底座高度":100})
        self.assertNotIn("pending_manual_dimensions", calculated)
        editor.accept()
        self.assertEqual(item["quick"]["total_cost"], 400.34)

    def test_add_flow_requires_popup_height_even_for_previously_matched_id(self):
        for source in (dict(category_level1="底座", item_name="固定底座", quantity=1), catalog[0]):
            self.window.attachments = [copy.deepcopy(source)]
            self.assertTrue(v2.needs_base_height_resolution(self.window))
            successes, failures = [], []
            def complete(editor):
                pending = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
                self.assertEqual(requests, [])
                self.assertIsNone(pending.get("attachment_price_id"))
                pending["manual_inputs"] = {"底座高度":100}
                editor._reprice_row(0, pending)
                wait_for(lambda: editor.table.cellWidget(0, editor.COL_AMOUNT).isEnabled())
                editor.accept()
                return QDialog.DialogCode.Accepted
            with patch.object(ui.AttachmentEditor, "exec", complete):
                self.window.resolve_attachments_for_quote(lambda:successes.append(True), failures.append)
            self.assertEqual(failures, [])
            self.assertEqual(successes, [True])
            self.assertEqual(self.window.attachments[0]["attachment_price_id"], catalog[1]["attachment_price_id"])
            requests.clear()

    def test_close_without_height_blocks_calculation(self):
        self.window.attachments = [copy.deepcopy(catalog[0])]
        failures = []
        with patch.object(ui.AttachmentEditor, "exec", return_value=QDialog.DialogCode.Accepted):
            self.window.resolve_attachments_for_quote(self.fail, failures.append)
        self.assertIn("底座高度", failures[0])
        self.assertEqual(requests, [])

    def test_ganged_missing_height_never_borrows_cabinet_height(self):
        from types import SimpleNamespace
        children = [dict(width_mm=400, height_mm=400, depth_mm=300),
                    dict(width_mm=600, height_mm=700, depth_mm=400)]
        window = SimpleNamespace(ganged_cabinets=children, selected_product_code=lambda:"JP")
        choice = dict(category_level1="底座", item_name="固定底座")
        rows, missing = v2.expand_ganged_fixed_bases_for_quote(window, [choice], catalog)
        self.assertEqual(rows, [])
        self.assertEqual(len(missing), 2)
        rows, missing = v2.expand_ganged_fixed_bases_for_quote(window,
                    [{**choice, "manual_inputs":{"底座高度":100}}], catalog)
        self.assertEqual(missing, [])
        self.assertEqual([row["manual_inputs"]["底座高度"] for row in rows], [100,100])
        self.assertEqual([row["size_match_target_height_mm"] for row in rows], [100,100])
        self.assertEqual([row["size_match_target_width_mm"] for row in rows], [400,600])


if __name__ == "__main__":
    unittest.main()
