"""Real Qt model changes keep manufacturing snapshots; parameter edits reprice."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

import verify_support_plate_defaults as base
import scheme2_ui as ui
import attachment_v2_client as v2
import support_plate_pricing as pricing
from quick_discount_rules import money_product

ROOT = Path(__file__).resolve().parents[1]


class CostIsolation(base.SupportPlateRuntime):
    def plate(self, name="有孔承板"):
        catalog = next(row for row in self.catalog if row["item_name"] == name)
        return {**copy.deepcopy(catalog), "quantity": 2, "status": "CALCULATED", "status_text": "已计算",
                "manual_inputs": {"孔承板高度": 400, "孔承板宽度": 600},
                "formula_unit_cost": 45.67, "formula_amount": 91.34, "weight_kg": 2.826,
                "material_cost": 11.87, "spray_area_m2": 0, "spray_cost": 0,
                "auxiliary_cost": 0, "labor_cost": 33.8, "rule_id": "R47" if name == "有孔承板" else "R46",
                "rule_version": "original-cost-rule", "quick_amount": money_product(catalog["price"], 2)}

    def editor(self, source=None):
        self.item["attachments"] = [source or self.plate()]
        ui._recalculate_item_management(self.item)
        self.window.draft_items = [self.item]
        editor = ui.AttachmentEditor(self.window, self.item)
        self.addCleanup(editor.close)
        return editor

    def switch(self, editor, model):
        editor._begin_model_edit(0, editor.COL_SPECIFICATION)
        combo = editor.table.cellWidget(0, editor.COL_SPECIFICATION)
        combo.setCurrentIndex(combo.findData(model))
        base.wait_for(lambda: bool(self.warnings) or (
            editor.table.cellWidget(0, editor.COL_SPECIFICATION) is None
            and not getattr(editor, "_pending_reprices", {})))
        self.assertEqual(self.warnings, [])
        return editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)

    def reprice(self, source):
        results, errors = [], []
        self.window.recalculate_draft_attachment(self.item, source, results.append, errors.append)
        base.wait_for(lambda: results or errors)
        self.assertEqual(errors, [])
        return results[0]

    def test_all_32_models_update_sales_without_previewing_or_changing_costs(self):
        for name, models in base.SUPPORT_PLATE_MODELS.items():
            initial = self.plate(name)
            editor = self.editor(initial)
            self.requests.clear()
            for model in models[1:] + models[:1]:
                selected = self.switch(editor, model)
                for key in pricing.COST_FIELDS:
                    self.assertEqual(selected.get(key), initial.get(key), (model, key))
                self.assertEqual(selected["manual_inputs"], initial["manual_inputs"])
                catalog = next(row for row in self.catalog if row["model_code"] == model)
                self.assertEqual(selected["quick_amount"], money_product(catalog["price"], 2))
                self.assertEqual(editor.table.item(0, editor.COL_FORMULA_AMOUNT).text(), "91.34")
            self.assertTrue(self.requests)
            self.assertTrue(all("catalog?v=2" in url for url, _ in self.requests))
            editor.accept()

    def test_close_reopen_and_json_restore_keep_cost_and_refresh_detail_cache(self):
        initial = self.plate()
        editor = self.editor(initial)
        old_management = self.item["formula"]["management_fee"]
        self.item["cost_detail_rows"] = [{"category": "attachment_fee", "base_amount": -1, "_scheme2_version": 3}]
        self.item["quote_display"] = {"old": True}
        self.switch(editor, "JP791184")
        editor.accept()
        self.assertNotIn("cost_detail_rows", self.item)
        self.assertNotIn("quote_display", self.item)
        self.assertEqual(self.item["formula"]["attachment_fee"], 91.34)
        self.assertEqual(self.item["formula"]["management_fee"], old_management)
        details = ui._detail_rows(self.item)
        allocated=[row for row in details if row.get('attachment_cost_source')]
        self.assertEqual(ui.money_sum(row['base_amount'] for row in allocated),91.34)
        self.assertEqual({row['category'] for row in allocated},{'material_cost','spray_cost','auxiliary_cost','labor_cost'})
        self.assertFalse(any(row['category']=='attachment_fee' for row in allocated))
        self.item = json.loads(json.dumps(self.item, ensure_ascii=False))
        reopened = self.editor(self.item["attachments"][0])
        result = self.switch(reopened, "JP791164")
        self.assertEqual(result["formula_amount"], initial["formula_amount"])
        reopened.accept()
        self.assertEqual(self.item["formula"]["management_fee"], old_management)

    def test_changed_dimensions_force_full_cost_calculation_and_new_baseline(self):
        original = pricing.remember_cost(self.plate(), self.item, self.window.scheme2_defaults)
        for field in ("孔承板高度", "孔承板宽度"):
            source = copy.deepcopy(original)
            source["manual_inputs"][field] = 900
            source = pricing.prepare_model_change(source, self.item, self.window.scheme2_defaults)
            source.pop("attachment_price_id")
            source["model_code"] = "JP791184"
            self.requests.clear()
            result = self.reprice(source)
            self.assertEqual(result["formula_amount"], 10)
            self.assertTrue(any(url.endswith("/preview") for url, _ in self.requests))
            self.assertEqual(result[pricing.COST_SNAPSHOT]["context"], pricing.cost_context(self.item, result, self.window.scheme2_defaults))
            self.assertNotIn(pricing.MODEL_ONLY, result)

    def test_changed_material_price_and_other_cost_inputs_do_not_freeze_cost(self):
        original = pricing.remember_cost(self.plate(), self.item, self.window.scheme2_defaults)
        changes = (
            ("material_code", "SUS304"), ("coating_type", "不喷塑"),
            ("cabinet_body_thickness_mm", 2.5),
            ("scheme2_cost_settings", {**self.window.scheme2_defaults, "carbon_price": 8.4}),
            ("scheme2_cost_settings", {**self.window.scheme2_defaults, "waste_factor": 1.5}),
        )
        saved = copy.deepcopy(self.item)
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.item = {**copy.deepcopy(saved), key: value}
                source = pricing.prepare_model_change(original, self.item, self.window.scheme2_defaults)
                source.pop("attachment_price_id")
                source["model_code"] = "JP791184"
                self.requests.clear()
                result = self.reprice(source)
                self.assertEqual(result["formula_amount"], 10)
                preview = next(payload for url, payload in self.requests if url.endswith("/preview"))
                self.assertEqual(preview["pricing_basis"], "per_unit_set_v1")

    def test_quantity_change_recalculates_instead_of_reusing_old_line_cost(self):
        source = pricing.remember_cost(self.plate(), self.item, self.window.scheme2_defaults)
        source["quantity"] = 3
        source = pricing.prepare_model_change(source, self.item, self.window.scheme2_defaults)
        source.pop("attachment_price_id")
        source["model_code"] = "JP791184"
        result = self.reprice(source)
        self.assertEqual(result["formula_amount"], 15)

    def test_left_click_dimension_action_recalculates_completed_plate(self):
        editor = self.editor()
        editor.table.selectRow(0)
        self.assertTrue(editor.dimensions_button.isEnabled())
        fields = {"孔承板高度": 750.0, "孔承板宽度": 900.0}
        dialog = SimpleNamespace(exec=lambda: QDialog.DialogCode.Accepted, values=lambda: fields)
        self.requests.clear()
        with patch.object(ui, "_SchemeDimensionEditor", return_value=dialog) as factory:
            editor.dimensions_button.click()
        base.wait_for(lambda: not getattr(editor, "_pending_reprices", {}))
        self.assertEqual(factory.call_args.args[2], ["孔承板高度", "孔承板宽度"])
        source = editor.table.item(0, editor.COL_NAME).data(ui.ROLE_ROW)
        self.assertEqual(source["manual_inputs"], fields)
        self.assertEqual(source["formula_amount"], 10)
        self.assertTrue(any(url.endswith("/preview") for url, _ in self.requests))
        selected = self.switch(editor, "JP791184")
        self.assertEqual(selected["manual_inputs"], fields)
        self.assertEqual(selected["formula_amount"], 10)

    def test_dimension_action_is_unavailable_for_other_or_custom_attachments(self):
        for source in (dict(item_name="电脑托盘", category_level1="控制柜附件", quantity=1),
                       {**self.plate(), "custom": True}):
            editor = self.editor(source)
            editor.table.selectRow(0)
            self.assertFalse(editor.dimensions_button.isEnabled())
            editor.close()

    def test_incomplete_cost_cannot_be_frozen_as_zero(self):
        for extra in ({"pending_manual_dimensions": ["孔承板高度"]}, {"status": "ERROR"},
                      {"formula_amount": None}, {"manual_inputs": {"孔承板高度": 0, "孔承板宽度": 600}}):
            source = pricing.prepare_model_change({**self.plate(), **extra}, self.item, self.window.scheme2_defaults)
            self.assertFalse(pricing.reusable_cost(source, self.item, self.window.scheme2_defaults))
            self.assertNotIn(pricing.COST_SNAPSHOT, source)

    def test_legacy_calculation_environment_detects_changed_sidebar_price(self):
        source = self.plate()
        source["environment"] = {"material_unit_price": 1.2}
        source = pricing.prepare_model_change(source, self.item, self.window.scheme2_defaults)
        self.assertFalse(pricing.reusable_cost(source, self.item, self.window.scheme2_defaults))

    def test_pinned_cost_does_not_survive_new_order_repricing(self):
        source = pricing.prepare_model_change(self.plate(), self.item, self.window.scheme2_defaults)
        fresh = v2.new_quote_attachment_selection(source)
        for key in (pricing.COST_SNAPSHOT, pricing.MODEL_ONLY, "formula_amount", "formula_unit_cost"):
            self.assertNotIn(key, fresh)
        self.assertTrue(fresh["quote_catalog_refresh_required"])

    def test_ganged_child_model_change_keeps_cost_and_child_context(self):
        self.item.update(product_code="JP_SINGLE", ganged_cabinet_count=2,
                         ganged_cabinets=[dict(width_mm=800, height_mm=2000, depth_mm=600)] * 2)
        source = {**self.plate(), "ganged_cabinet_index": 1}
        editor = self.editor(source)
        selected = self.switch(editor, "JP791184")
        self.assertEqual(selected["formula_amount"], 91.34)
        self.assertEqual(selected["ganged_cabinet_index"], 1)
        editor.accept()

    def test_server_snapshot_repair_does_not_overwrite_pinned_cost(self):
        editor = self.editor()
        self.switch(editor, "JP791184")
        editor.accept()
        self.item.update(attachment_contract=2, quote_line_id="old-line", attachment_snapshot_dirty=True)
        row = copy.deepcopy(self.item["attachments"][0])
        body = {"attachment_contract": 2, "quote_line_id": "new-line",
                "attachments": [{**row, "formula_unit_cost": 999, "formula_amount": 1998, "material_cost": 998}],
                "formula_cost": copy.deepcopy(self.item["formula"])}
        old_start = self.Worker.start
        def start(worker):
            if worker.test_url.endswith("/recalculate-line"):
                QTimer.singleShot(0, lambda: (worker.succeeded.emit(copy.deepcopy(body)), worker.finished.emit()))
            else:
                old_start(worker)
        done, errors = [], []
        with patch.object(self.Worker, "start", start):
            self.window.refresh_draft_attachment_snapshot(self.item, lambda: done.append(True), errors.append)
            base.wait_for(lambda: done or errors)
        self.assertEqual(errors, [])
        self.assertEqual(self.item["quote_line_id"], "new-line")
        self.assertEqual(self.item["attachments"][0]["formula_amount"], 91.34)
        self.assertEqual(self.item["formula"]["attachment_fee"], 91.34)
        self.assertEqual(self.item["formula"]["management_fee"], 15.08)
        self.assertEqual(self.item["attachment_confirmation_inputs"][0]["attachment_price_id"], row["attachment_price_id"])

    def test_catalogue_cost_stays_readonly_through_model_change_and_snapshot_repair(self):
        editor = self.editor()
        self.switch(editor, "JP791184")  # Pin the original manufacturing snapshot.
        editor.table.cellWidget(0, editor.COL_UNIT_COST).setValue(19.25)
        selected = self.switch(editor, base.SUPPORT_PLATE_MODELS["有孔承板"][2])
        self.assertEqual(selected["formula_amount"], 91.34)
        self.assertTrue(editor.table.cellWidget(0, editor.COL_UNIT_COST).lineEdit().isReadOnly())
        editor.accept()
        self.item.update(attachment_contract=2, quote_line_id="old-line", attachment_snapshot_dirty=True)
        row = copy.deepcopy(self.item["attachments"][0])
        body = {"attachment_contract":2,"quote_line_id":"new-line",
                "attachments":[{**row,"formula_amount":1998,"formula_unit_cost":999}],
                "formula_cost":copy.deepcopy(self.item["formula"])}
        old_start = self.Worker.start
        def start(worker):
            if worker.test_url.endswith("/recalculate-line"):
                QTimer.singleShot(0, lambda:(worker.succeeded.emit(copy.deepcopy(body)),worker.finished.emit()))
            else:
                old_start(worker)
        done, errors = [], []
        with patch.object(self.Worker,"start",start):
            self.window.refresh_draft_attachment_snapshot(self.item,lambda:done.append(True),errors.append)
            base.wait_for(lambda:done or errors)
        self.assertEqual(errors,[])
        self.assertEqual(self.item["attachments"][0]["formula_amount"],91.34)
        self.assertNotIn("formula_unit_cost_override",self.item["attachments"][0])
        self.assertEqual(self.item["formula"]["attachment_fee"],91.34)

    def test_real_api_document_hydration_and_workbook_use_pinned_cost(self):
        editor = self.editor()
        self.switch(editor, "JP791184")
        editor.accept()
        self.item.update(attachment_contract=2, quote_line_id="12345678-1234-1234-1234-123456789001",
                         name="承板型号换价回归", specification="800*600*2000", quote_date="2026-10-20")
        exported = ui._quote_export_items_snapshot(self.window, [self.item])
        payload = v2.confirmation_payload(dict(quote_id="OFFLINE-PLATES", quote_date="2026-10-20", items=exported), validate=True)
        row = exported[0]["attachments"][0]
        self.assertEqual(row["formula_amount"], 91.34)
        self.assertEqual(exported[0]["quote_display"]["attachments"][0]["formula_amount"], 91.34)
        environment = {key: exported[0].get(key) for key in (
            "product_code", "material_code", "width_mm", "height_mm", "depth_mm", "coating_type",
            "quote_date", "cabinet_body_thickness_mm", "waste_factor", "ganged_cabinet_count", "ganged_cabinets")}
        environment["quote_result"] = {"formula_cost": self.item["formula"], "quick_quote": self.item["quick"]}
        snapshot = dict(environment=environment, attachments=[])
        request = dict(payload=payload, snapshots={self.item["quote_line_id"]: snapshot})
        result = subprocess.run(["node", "tests/attachment_export_snapshot_bridge.mjs"], input=json.dumps(request),
                                text=True, encoding="utf-8", cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        hydrated = json.loads(result.stdout)
        item = hydrated["items"][0]
        self.assertEqual(item["formula"]["attachment_fee"], 91.34)
        self.assertEqual(item["formula"]["management_fee"], 15.08)
        self.assertEqual(item["attachments"][0]["model_code"], "JP791184")
        self.assertEqual(item["attachments"][0]["formula_amount"], 91.34)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs", prefix="support-plate-export-") as folder:
            path = Path(folder) / "quote.xlsx"
            source = Path(folder) / "generated-payload.json"
            source.write_text(json.dumps(hydrated, ensure_ascii=False), encoding="utf-8")
            workbook = subprocess.run(["node", "export_dual_quote_workbook.mjs", str(source), str(path)],
                text=True, encoding="utf-8", cwd=ROOT, capture_output=True)
            self.assertEqual(workbook.returncode, 0, workbook.stderr)
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                sheets = "".join(archive.read(name).decode("utf-8") for name in archive.namelist()
                                 if name.startswith("xl/worksheets/") and name.endswith(".xml"))
                self.assertIn("91.34", sheets)


if __name__ == "__main__":
    unittest.main()
