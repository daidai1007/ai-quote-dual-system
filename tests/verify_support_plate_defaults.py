"""Offline catalogue/default/popup contracts for perforated and solid plates."""
from __future__ import annotations

import copy
from decimal import Decimal, ROUND_HALF_UP
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import attachment_v2_client as v2
from attachment_category_browser import SUPPORT_PLATE_DEFAULT_MODELS, SUPPORT_PLATE_MODELS
import scheme2_ui as ui
import v3_launcher

BUNDLE = json.loads((ROOT / "database/attachment-v2/generated/attachment-bundle.json").read_text(encoding="utf-8"))
CATALOG = [
    {**row, "attachment_price_id": int(row["import_key"][1:]), "face_price": row["price"]}
    for row in BUNDLE["catalog"] if row.get("item_name") in SUPPORT_PLATE_MODELS
]
app = QApplication.instance() or QApplication([])


def choice(name, **extra):
    return dict(category_level1="控制柜附件", item_name=name, quantity=1, **extra)


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.001)
    raise AssertionError("offline callback did not complete")


class SupportPlateMatching(unittest.TestCase):
    def test_known_models_match_imported_catalogue_and_requested_defaults(self):
        self.assertEqual(SUPPORT_PLATE_DEFAULT_MODELS, {"有孔承板": "JP791164", "无孔承板": "JP791064"})
        for name, models in SUPPORT_PLATE_MODELS.items():
            self.assertEqual(len(models), 16)
            self.assertEqual(models, tuple(row["model_code"] for row in CATALOG if row["item_name"] == name))

    def test_name_only_defaults_ignore_cabinet_dimensions_and_catalogue_order(self):
        for name, model in SUPPORT_PLATE_DEFAULT_MODELS.items():
            for dimensions in (None, (300, 300, 300), (1600, 2100, 800)):
                for catalog in (CATALOG, list(reversed(CATALOG))):
                    match = v2.match_catalog_attachment(choice(name), catalog, target_dimensions=dimensions)
                    self.assertEqual(match["model_code"], model)
                    self.assertEqual(match["price"], 97.885125 if name == "有孔承板" else 116.722125)
                    self.assertNotIn("unit_price_override", match)

    def test_every_explicit_model_wins_over_default_including_lowercase(self):
        for row in CATALOG:
            for field in ("model_code", "specification"):
                selected = choice(row["item_name"], **{field: row["model_code"].lower()})
                self.assertEqual(v2.match_catalog_attachment(selected, CATALOG)["attachment_price_id"], row["attachment_price_id"])

    def test_missing_or_duplicate_default_never_uses_arbitrary_other_model(self):
        for name, model in SUPPORT_PLATE_DEFAULT_MODELS.items():
            rows = [row for row in CATALOG if row["model_code"] != model]
            self.assertIsNone(v2.match_catalog_attachment(choice(name), rows))
            default = next(row for row in CATALOG if row["model_code"] == model)
            self.assertIsNone(v2.match_catalog_attachment(choice(name), CATALOG + [{**default, "attachment_price_id": 9999}]))

    def test_unknown_explicit_model_never_reverts_to_default(self):
        for name in SUPPORT_PLATE_MODELS:
            self.assertIsNone(v2.match_catalog_attachment(choice(name, model_code="NOT-IN-CATALOG"), CATALOG))

    def test_other_attachment_families_and_source_inputs_are_not_changed(self):
        before = copy.deepcopy(CATALOG)
        source = choice("有孔承板", manual_inputs={"孔承板高度": 400, "孔承板宽度": 600})
        original = copy.deepcopy(source)
        v2.match_catalog_attachment(source, CATALOG)
        self.assertEqual(source, original)
        self.assertEqual(CATALOG, before)
        self.assertIsNone(v2.match_catalog_attachment(dict(category_level1="其他附件", item_name="有孔承板"), CATALOG))


class SupportPlateRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = v3_launcher.load_v3_namespace()
        cls.Window = cls.namespace["MainWindow"]
        cls.Worker = cls.namespace["ApiWorker"]
        cls.namespace["install_application_font"](app)

    def setUp(self):
        self.requests, self.warnings = [], []
        self.catalog = copy.deepcopy(CATALOG)
        original_init = self.Worker.__init__

        def capture(worker, url, payload, parent=None, *args, **kwargs):
            original_init(worker, url, payload, parent, *args, **kwargs)
            worker.test_url, worker.test_payload = url, copy.deepcopy(payload)

        def start(worker):
            self.requests.append((worker.test_url, worker.test_payload))
            def respond():
                if "catalog?v=2" in worker.test_url:
                    worker.succeeded.emit({"items": copy.deepcopy(self.catalog), "data_version": "offline-plates"})
                elif worker.test_url.endswith("/preview"):
                    selected = worker.test_payload["attachments"][0]
                    matched = next(row for row in self.catalog if row["attachment_price_id"] == selected["attachment_price_id"])
                    amount = Decimal(str(matched["face_price"])) * Decimal(str(selected["quantity"]))
                    worker.succeeded.emit({"attachments": [{**matched, **selected, "status": "OK",
                        "matched_price": matched["face_price"], "formula_unit_cost": 5,
                        "formula_amount": 5 * selected["quantity"],
                        "quick_amount": float(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))}]})
                else:
                    worker.failed.emit("unexpected offline request")
                worker.finished.emit()
            QTimer.singleShot(0, respond)

        for mock in (
            patch.object(self.Window, "load_catalogs", lambda self: None),
            patch.object(self.Window, "refresh_formula_inputs", lambda self, *args: None),
            patch.object(self.Worker, "__init__", capture), patch.object(self.Worker, "start", start),
            patch.object(QMessageBox, "warning", lambda _p, _t, message: self.warnings.append(message)),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        self.window = self.Window()
        self.addCleanup(self.window.close)
        self.window.api_url.setText("http://127.0.0.1:1/api/quotes/calculate-dual")
        self.window.quote_spec_edit.setText("800*600*(2000+100)")
        self.item = dict(product_code="JP", material_code="SECC", width_mm=800, height_mm=2000,
                         depth_mm=600, quantity=1,
                         formula=dict(material_cost=100, auxiliary_cost=10, labor_cost=20,
                                      spray_cost=30, attachment_fee=10, management_fee=10.2, total_cost=180.2),
                         quick=dict(base_price=1000, attachment_fee=100, total_cost=1100))

    def test_ordinary_and_ganged_quote_resolution_uses_defaults_and_keeps_inputs(self):
        for product in ("JS", "JP", "JP_SINGLE"):
            with self.subTest(product=product):
                self.window.ganged_cabinets = ([dict(width_mm=800, height_mm=2000, depth_mm=600)] * 2 if product == "JP_SINGLE" else [])
                self.window.attachments = [choice(name, model_code="", manual_inputs={"孔承板高度": 400}, selection_source="manual") for name in SUPPORT_PLATE_MODELS]
                done, errors = [], []
                self.window.resolve_attachments_for_quote(lambda: done.append(True), errors.append)
                wait_for(lambda: done or errors)
                self.assertEqual(errors, [])
                self.assertEqual(done, [True])
                for row in self.window.attachments:
                    self.assertEqual(row["model_code"], SUPPORT_PLATE_DEFAULT_MODELS[row["item_name"]])
                    self.assertEqual(row["manual_inputs"], {"孔承板高度": 400})
                    self.assertEqual(row["selection_source"], "manual")
                    self.assertIsNotNone(row["attachment_price_id"])

    def test_popup_can_switch_every_catalogue_model_and_save_repriced_selection(self):
        for name in SUPPORT_PLATE_MODELS:
            rows = [row for row in self.catalog if row["item_name"] == name]
            initial = {**rows[0], "quantity": 2, "quick_amount": 999, "quick_amount_override": 999,
                       "custom_amount_edited": True, "formula_amount": 10,
                       "manual_inputs": {"孔承板高度": 400, "孔承板宽度": 600}}
            self.item["attachments"] = [initial]
            editor = ui.AttachmentEditor(self.window, self.item)
            self.addCleanup(editor.close)
            for row in rows[1:] + rows[:1]:
                editor._begin_model_edit(0, editor.COL_SPECIFICATION)
                combo = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
                self.assertIsNotNone(combo)
                self.assertEqual([combo.itemData(i) for i in range(1, combo.count())], list(SUPPORT_PLATE_MODELS[name]))
                combo.setCurrentIndex(combo.findData(row["model_code"]))
                wait_for(lambda: bool(self.warnings) or (
                    editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW).get("attachment_price_id") == row["attachment_price_id"]
                    and editor.table.cellWidget(0, editor.COL_SPECIFICATION) is None))
                self.assertEqual(self.warnings, [])
                selected = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
                self.assertEqual(selected["quantity"], 2)
                self.assertEqual(selected["manual_inputs"], initial["manual_inputs"])
                self.assertFalse(selected.get("custom_amount_edited"))
                self.assertNotIn("quick_amount_override", selected)
                self.assertEqual(selected["face_price"], row["price"])
                self.assertAlmostEqual(editor.table.cellWidget(0, editor.COL_AMOUNT).value(), round(row["price"] * 2, 2))
            editor.accept()
            self.assertEqual(self.item["attachments"][0]["model_code"], SUPPORT_PLATE_DEFAULT_MODELS[name])
            self.assertEqual(v2.selected_input(self.item["attachments"][0])["attachment_price_id"], rows[0]["attachment_price_id"])
            editor.close()

    def test_explicit_reprice_uses_catalogue_price_without_resetting_manual_sale(self):
        source = choice("无孔承板", model_code="JP791084",
                        quick_amount_override=123.45, custom_amount_edited=True,
                        manual_inputs={"孔承板高度": 450, "孔承板宽度": 800})
        results, errors = [], []
        self.window.recalculate_draft_attachment(self.item, source, results.append, errors.append)
        wait_for(lambda: results or errors)
        self.assertEqual(errors, [])
        self.assertEqual(results[0]["model_code"], "JP791084")
        self.assertEqual(results[0]["quick_amount"], 123.45)
        self.assertEqual(results[0]["manual_inputs"], source["manual_inputs"])

    def test_custom_named_plates_keep_their_manual_price_and_no_model_selector(self):
        self.item["attachments"] = [dict(custom=True, item_name="有孔承板", quantity=1, quick_amount=80, formula_amount=50)]
        editor = ui.AttachmentEditor(self.window, self.item)
        self.addCleanup(editor.close)
        editor._begin_model_edit(0, editor.COL_SPECIFICATION)
        self.assertIsNone(editor.table.cellWidget(0, editor.COL_SPECIFICATION))
        self.assertEqual(self.requests, [])

    def test_pending_formula_dimensions_do_not_overwrite_selected_model(self):
        initial = {**self.catalog[0], "quantity": 1, "quick_amount": 0, "formula_amount": 0,
                   "pending_manual_dimensions": ["孔承板高度", "孔承板宽度"]}
        self.item["attachments"] = [initial]
        editor = ui.AttachmentEditor(self.window, self.item)
        self.addCleanup(editor.close)
        dimension_editor = SimpleNamespace(exec=lambda: QDialog.DialogCode.Accepted,
            values=lambda: {"孔承板高度": 400.0, "孔承板宽度": 600.0})
        with patch.object(ui, "_SchemeDimensionEditor", return_value=dimension_editor):
            editor.edit_missing_dimensions(0, editor.COL_SPECIFICATION)
        wait_for(lambda: not getattr(editor, "_pending_reprices", {}))
        self.assertEqual(editor.table.item(0, editor.COL_SPECIFICATION).text(), initial["model_code"])
        self.assertIn("孔承板高度", editor.table.item(0, editor.COL_SPECIFICATION).toolTip())
        editor.accept()
        saved = self.item["attachments"][0]
        self.assertEqual(saved["model_code"], initial["model_code"])
        self.assertEqual(saved["manual_inputs"], dimension_editor.values())

    def test_popup_reuses_existing_dropdown_and_includes_new_catalogue_models(self):
        self.item["attachments"] = [{**self.catalog[-16], "quantity": 1}]
        self.window._attachment_catalog_cache = [{**self.catalog[-16], "model_code": "JP791199"}]
        editor = ui.AttachmentEditor(self.window, self.item)
        self.addCleanup(editor.close)
        editor.show()
        app.processEvents()
        editor._begin_model_edit(0, editor.COL_SPECIFICATION)
        selector = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
        self.assertEqual(selector.objectName(), "scheme2AttachmentModelCombo")
        self.assertEqual(selector.view().objectName(), "scheme2AttachmentModelDropdown")
        self.assertGreaterEqual(selector.findData("JP791199"), 0)
        selector.showPopup()
        app.processEvents()
        output = ROOT / "outputs" / "support-plate-qa"
        output.mkdir(parents=True, exist_ok=True)
        editor.grab().save(str(output / "support-plate-model-editor.png"))
        selector.view().grab().save(str(output / "support-plate-model-options.png"))
        selector.hidePopup()


if __name__ == "__main__":
    unittest.main()
