"""Offline regression: a popup option change must resolve its new catalogue ID."""
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
from PySide6.QtWidgets import QApplication, QMessageBox
import scheme2_ui as ui
import attachment_v2_client as v2
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
Window, Worker = ns["MainWindow"], ns["ApiWorker"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
catalog = [dict(attachment_price_id=index + 10, category_level1="照明灯/行程开关",
                item_name=name, face_price=20 + index)
           for index, name in enumerate(ui.LIGHT_SWITCH_OPTIONS)]
catalog.append(dict(attachment_price_id=30, category_level1="安装附件",
                    item_name="三排安装梁", model_code="JP760250", face_price=60))
trays = [dict(attachment_price_id=183 + index, category_level1="控制柜附件",
              category_level2="电脑托盘", item_name="电脑托盘", model_code=model,
              price=200 + index * 20, face_price=200 + index * 20)
         for index, model in enumerate(ui.COMPUTER_TRAY_MODELS)]
catalog.extend(trays)
requests, warnings = [], []
original_init = Worker.__init__


def capture_init(self, url, payload, parent=None, *args, **kwargs):
    original_init(self, url, payload, parent, *args, **kwargs)
    self.test_url, self.test_payload = url, copy.deepcopy(payload)


def start(self):
    requests.append((self.test_url, self.test_payload))

    def respond():
        if "catalog?v=2" in self.test_url:
            self.succeeded.emit({"items": copy.deepcopy(catalog), "data_version": "offline"})
        elif self.test_url.endswith("/preview"):
            selected = self.test_payload["attachments"][0]
            match = next((row for row in catalog
                          if row["attachment_price_id"] == selected["attachment_price_id"]), None)
            if match is None:
                self.failed.emit('{"error":"attachment_preview_failed","message":"必须提供有效 attachment_price_id"}')
            else:
                quantity = selected["quantity"]
                self.succeeded.emit({"attachments": [{**match, **selected, "status": "OK",
                    "matched_price": match["face_price"], "formula_unit_cost": 5,
                    "formula_amount": 5 * quantity, "quick_amount": match["face_price"] * quantity}]})
        else:
            self.failed.emit("unexpected offline request")
        self.finished.emit()

    QTimer.singleShot(0, respond)


Worker.__init__, Worker.start = capture_init, start
QMessageBox.warning = lambda _parent, _title, message: warnings.append(message)


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.001)
    raise AssertionError("callback did not complete")


class DraftAttachmentRepriceId(unittest.TestCase):
    def setUp(self):
        requests.clear()
        warnings.clear()
        self.window = Window()
        self.window.api_url.setText("http://127.0.0.1:1/api/quotes/calculate-dual")
        self.item = dict(product_code="JP", material_code="SECC", width_mm=1000,
                         height_mm=2100, depth_mm=600, quantity=3,
                         formula={"attachment_fee": 10, "total_cost": 110},
                         quick={"attachment_fee": 40, "total_cost": 140})
        app.processEvents()
        requests.clear()
        self.addCleanup(self.window.close)

    def test_real_popup_option_changes_resolve_every_light_switch(self):
        for name in ui.LIGHT_SWITCH_OPTIONS:
            with self.subTest(name=name):
                initial = catalog[0] if name != catalog[0]["item_name"] else catalog[1]
                self.item["attachments"] = [{**initial, "quantity": 2, "formula_amount": 10,
                                              "quick_amount": 40, "manual_inputs": {"长度": 120}}]
                editor = ui.AttachmentEditor(self.window, self.item)
                selector = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
                selector.setCurrentIndex(selector.findData(name))
                wait_for(lambda: selector.isEnabled() or bool(warnings))
                self.assertEqual(warnings, [])
                source = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
                chosen = next(row for row in catalog if row["item_name"] == name)
                self.assertEqual(source["attachment_price_id"], chosen["attachment_price_id"])
                payload = requests[-1][1]["attachments"][0]
                self.assertEqual(payload["quantity"], 2)
                self.assertEqual(payload["manual_inputs"], {"长度": 120})
                self.assertEqual(editor.table.cellWidget(0, editor.COL_AMOUNT).value(), chosen["face_price"] * 2 * 3)
                self.assertEqual(editor.table.item(0, editor.COL_FORMULA_AMOUNT).text(), "30.00")
                editor.accept()
                self.assertEqual(self.item["attachments"][0]["attachment_price_id"], chosen["attachment_price_id"])
                editor.close()

    def reprice(self, source):
        results, errors = [], []
        self.window.recalculate_draft_attachment(self.item, source, results.append, errors.append)
        wait_for(lambda: results or errors)
        return results, errors

    def test_missing_or_invalid_ids_are_resolved_before_preview(self):
        for invalid in (None, "", 0, True, "not-an-id"):
            with self.subTest(invalid=invalid):
                source = {**catalog[1], "attachment_price_id": invalid, "quantity": 2}
                before = copy.deepcopy(source)
                results, errors = self.reprice(source)
                self.assertEqual(errors, [])
                self.assertEqual(results[0]["attachment_price_id"], catalog[1]["attachment_price_id"])
                self.assertEqual(source, before)

    def test_unknown_selection_never_sends_invalid_id_to_preview(self):
        results, errors = self.reprice(dict(category_level1="其他附件", item_name="未入库附件", quantity=1))
        self.assertFalse(results)
        self.assertIn("未入库附件", errors[0])
        self.assertFalse(any(url.endswith("/preview") for url, _ in requests))

    def test_catalogue_with_invalid_id_fails_locally(self):
        broken = dict(attachment_price_id=0, category_level1="其他附件", item_name="损坏目录项")
        catalog.append(broken)
        try:
            results, errors = self.reprice(dict(category_level1="其他附件", item_name="损坏目录项"))
            self.assertFalse(results)
            self.assertIn("损坏目录项", errors[0])
            self.assertFalse(any(url.endswith("/preview") for url, _ in requests))
        finally:
            catalog.remove(broken)

    def test_existing_id_and_beam_model_paths_remain_supported(self):
        for source in ({**catalog[2], "quantity": 1}, dict(item_name="三排安装梁",
                category_level1="安装附件", model_code="JP760250", quantity=2)):
            results, errors = self.reprice(source)
            self.assertEqual(errors, [])
            self.assertTrue(results)
            self.assertIn(results[0]["attachment_price_id"], [row["attachment_price_id"] for row in catalog])

    def test_temporary_attachment_never_looks_up_catalogue_or_previews(self):
        source = dict(custom=True, item_name="临时木托", quantity=2,
                      formula_amount=10, quick_amount=17, unit_price_override=8.5)
        before = copy.deepcopy(source)
        results, errors = self.reprice(source)
        self.assertEqual(errors, [])
        self.assertEqual(results, [before])
        self.assertIsNot(results[0], source)
        self.assertEqual(source, before)
        self.assertEqual(requests, [])

    def test_catalogue_price_edit_is_quote_local_and_retains_id(self):
        before_catalog = copy.deepcopy(catalog)
        self.item["attachments"] = [{**catalog[1], "quantity": 2,
                                      "formula_amount": 10, "quick_amount": 42}]
        frozen = [dict(attachment_price_id=catalog[1]["attachment_price_id"],
                       quantity=2, attachment_price_sign=1, manual_inputs={})]
        self.item["attachment_confirmation_inputs"] = copy.deepcopy(frozen)
        editor = ui.AttachmentEditor(self.window, self.item)
        editor.table.cellWidget(0, editor.COL_AMOUNT).setValue(150)
        editor.accept()
        source = self.item["attachments"][0]
        self.assertEqual(source["attachment_price_id"], catalog[1]["attachment_price_id"])
        self.assertEqual(source["quick_amount"], 50)
        self.assertEqual(source["formula_amount"], 10)
        self.assertEqual(source["quick_amount_override"], 50)
        self.assertEqual(self.item["attachment_confirmation_inputs"], frozen)
        self.assertEqual(catalog, before_catalog)
        self.assertEqual(requests, [])
        fresh = ui.AttachmentEditor(self.window, {"attachments": [{**catalog[1], "quantity": 2,
                                             "formula_amount": 10, "quick_amount": 42}]})
        self.assertEqual(fresh.table.cellWidget(0, fresh.COL_AMOUNT).value(), 42)
        fresh.close()
        editor.close()

    def test_computer_tray_exact_nearest_depth_and_manual_model(self):
        choice = dict(category_level1="控制柜附件", item_name="电脑托盘")
        before = copy.deepcopy(trays)
        for depth, model in ((400,"JP930040"),(500,"JP930050"),(600,"JP930060"),
                (800,"JP930080"),(1000,"JP930010"),(620,"JP930060"),
                (720,"JP930080"),(450,"JP930040"),(1300,"JP930010")):
            match = v2.match_catalog_attachment(choice, trays, (1000, 2100, depth))
            self.assertEqual(match["model_code"], model)
            self.assertTrue(match["computer_tray_auto_match"])
            self.assertEqual(match["computer_tray_target_depth_mm"], depth)
        manual = v2.match_catalog_attachment({**choice, "model_code":"JP930040"}, trays, (1000,2100,1000))
        self.assertEqual(manual["model_code"], "JP930040")
        self.assertFalse(manual["computer_tray_auto_match"])
        # Names outside the requested category, unapproved models and missing
        # depth must never fall back to an arbitrary same-name catalogue row.
        self.assertIsNone(v2.match_catalog_attachment(choice, [{**trays[0], "category_level2":"其他"}], (1000,2100,400)))
        self.assertIsNone(v2.match_catalog_attachment(choice, [{**trays[0], "model_code":"JP930099"}], (1000,2100,400)))
        self.assertIsNone(v2.match_catalog_attachment(choice, trays, (1000,2100,0)))
        self.assertEqual(trays, before)

    def test_computer_tray_popup_switches_every_model_and_refreshes_prices(self):
        self.item["attachments"] = [{**trays[-1], "quantity":2, "formula_amount":0,
            "quick_amount":0, "quick_amount_override":0, "computer_tray_auto_match":True}]
        editor = ui.AttachmentEditor(self.window, self.item)
        self.addCleanup(editor.close)
        selector = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
        self.assertEqual(editor.table.columnCount(), 5)
        self.assertEqual(editor.table.item(0, editor.COL_NAME).text(), "电脑托盘")
        self.assertEqual([selector.itemData(index) for index in range(1,selector.count())], list(ui.COMPUTER_TRAY_MODELS))
        for tray in trays:
            selector.setCurrentIndex(selector.findData(tray["model_code"]))
            wait_for(lambda: selector.isEnabled() or bool(warnings))
            self.assertEqual(warnings, [])
            source = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
            self.assertEqual(source["attachment_price_id"], tray["attachment_price_id"])
            self.assertFalse(source["computer_tray_auto_match"])
            self.assertNotIn("quick_amount_override", source)
            self.assertEqual(editor.table.cellWidget(0, editor.COL_AMOUNT).value(), tray["face_price"] * 2 * 3)
            self.assertEqual(editor.table.item(0, editor.COL_FORMULA_AMOUNT).text(), "30.00")
            self.assertEqual(requests[-1][1]["attachments"][0]["attachment_price_id"], tray["attachment_price_id"])
        editor.accept()
        saved = self.item["attachments"][0]
        self.assertEqual(saved["model_code"], trays[-1]["model_code"])
        self.assertEqual(self.item["quick"]["attachment_fee"], trays[-1]["face_price"] * 2)
        self.assertEqual(self.item["quick"]["total_cost"], 100 + trays[-1]["face_price"] * 2)
        self.assertEqual(self.item["formula"]["attachment_fee"], 10)

    def test_auto_tray_rematches_changed_depth_and_manual_tray_is_kept(self):
        self.window.attachments = [dict(category_level1="控制柜附件", item_name="电脑托盘", quantity=2)]
        with patch.object(v2, "_visible_quote_dimensions", return_value=(1000,2100,400)) as dimensions:
            def resolve():
                success, errors = [], []
                self.window.resolve_attachments_for_quote(lambda: success.append(True), errors.append)
                wait_for(lambda: success or errors)
                self.assertEqual(errors, [])
            resolve()
            self.assertEqual(self.window.attachments[0]["model_code"], "JP930040")
            dimensions.return_value = (1000,2100,720)
            self.assertTrue(v2.needs_computer_tray_resolution(self.window))
            resolve()
            self.assertEqual(self.window.attachments[0]["model_code"], "JP930080")
            self.assertEqual(self.window.attachments[0]["quantity"], 2)
            self.window.attachments[0]["computer_tray_auto_match"] = False
            dimensions.return_value = (1000,2100,500)
            self.assertFalse(v2.needs_computer_tray_resolution(self.window))
            resolve()
            self.assertEqual(self.window.attachments[0]["model_code"], "JP930080")

    def test_custom_computer_tray_keeps_manual_cost_and_has_no_catalogue_dropdown(self):
        source = dict(custom=True, item_name="电脑托盘", quantity=2, formula_amount=10, quick_amount=12)
        self.item["attachments"] = [source]
        editor = ui.AttachmentEditor(self.window, self.item)
        self.assertIsNone(editor.table.cellWidget(0, editor.COL_SPECIFICATION))
        editor.close()
        results, errors = self.reprice(source)
        self.assertEqual(results, [source])
        self.assertEqual(errors, [])
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
