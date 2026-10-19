"""All edited rows reprice as new; copying alone preserves the saved row."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import verify_drawing_workflow as base
import verify_quote_request_lifecycle as lifecycle
from PySide6.QtCore import QDate, QTimer
import attachment_v2_client as attachments
import layout_refresh as client
import scheme2_ui as ui
from quote_request_context import stamp_quote_response


class CopiedQuoteReprice(unittest.TestCase):
    setUp = lifecycle.QuoteLifecycle.setUp
    tearDown = lifecycle.QuoteLifecycle.tearDown

    def sample(self, ganged=False):
        self.w.attachments = [dict(attachment_price_id=101, item_name="风机测试", model_code="FAN-X",
            category_level1="风机", quantity=2, catalog_version="old-version", matched_price=999,
            price=999, unit_price_override=999, quick_amount=1998, quick_amount_override=1998,
            custom_amount_edited=True, formula_amount=1554, formula_unit_cost=777,
            quote_line_id="old-line", attachment_selection_id=88, manual_inputs={"风机开孔":100}),
            dict(custom=True, item_name="木托", quantity=1, formula_amount=8, custom_cost=8,
                 quick_amount=37, quick_amount_override=37, custom_amount_edited=True)]
        base.DrawingWorkflowTests.accept(self, base.response())
        self.w.add_current_to_summary()
        self.assertEqual(len(self.w.draft_items), 1)
        item = self.w.draft_items[0]
        item.update(attachment_contract=2, quote_line_id="old-line", quote_date="2020-01-01",
                    attachment_confirmation_inputs=[dict(attachment_price_id=101, quantity=2)],
                    scheme2_cost_settings={**self.w.scheme2_defaults, "carbon_price":999})
        if ganged:
            item.update(specification="(800+800)*600*1800", model_code="(800+800)*600*1800",
                        ganged_cabinet_count=2, ganged_cabinets=[dict(width_mm=800, depth_mm=600,
                            height_mm=1800, single_door_count=1, double_door_count=0)] * 2)
        self.w.refresh_summary()
        return item

    def copy_and_edit(self, item):
        with patch.object(ui, "_selected_row", return_value=self.w.draft_items.index(item)):
            ui._duplicate_selected(self.w)
        copied = self.w.draft_items[-1]
        with patch.object(ui, "_selected_item", return_value=copied):
            ui._edit_selected(self.w)
        return copied

    def catalog(self):
        return dict(data_version="new-db-version", items=[dict(attachment_price_id=101,
            item_name="风机测试", model_code="FAN-X", category_level1="风机", price=25, unit="个")])

    def response(self, quote_id, rows):
        result = base.response()
        result.update(quote_id=quote_id, attachment_contract=2, quote_line_id="new-line",
            attachments=[dict(attachment_price_id=101, item_name="风机测试", model_code="FAN-X",
                category_level1="风机", quantity=2, formula_unit_cost=11, formula_amount=22,
                face_price=25, quick_amount=50, status="FIXED", catalog_version="new-db-version",
                manual_inputs={"风机开孔":100})])
        result["quick_quote"].update(base_price=321, attachment_fee=50, total_cost=371)
        return result

    def transport(self, worker):
        self.calls.append((worker.url, deepcopy(worker.payload)))
        def reply():
            if worker.url.endswith("catalog?v=2"):
                if self.catalog_failure:
                    worker.failed.emit("offline catalogue unavailable")
                    worker.finished.emit()
                    return
                result = self.catalog()
            else:
                result = self.response(worker.payload["quote_id"], worker.payload.get("attachments"))
            worker.succeeded.emit(stamp_quote_response(worker, result))
            worker.finished.emit()
        QTimer.singleShot(5, reply)

    def submit_ordinary(self):
        self.calls = []
        self.catalog_failure = False
        def calculate():
            worker = base.ns["ApiWorker"]("https://offline.invalid/api/quotes/calculate-dual",
                dict(quote_id="new-copy-request", attachments=self.w.attachments, attachment_contract=2), self.w)
            worker.succeeded.connect(self.w.show_result)
            worker.failed.connect(self.w.show_error)
            worker.start()
        self.w.calculate = calculate
        with patch.object(base.ns["ApiWorker"], "start", lambda worker:self.transport(worker)):
            # bind a function, not a bound method (the fake transport owns self).
            ui._calculate_and_add(self.w)
            base.pump(lambda: not self.w._scheme2_add_after_calculate)
            base.app.processEvents()

    def test_copy_edit_invalidates_old_snapshots_prices_and_date_but_not_configuration(self):
        original = self.sample()
        before = deepcopy(original)
        self.copy_and_edit(original)
        self.assertIsNone(self.w.current_result)
        self.assertIsNone(self.w._formula_base_result)
        self.assertIsNone(self.w._attachment_v2_line_id)
        self.assertEqual(self.w._v2_confirmation_inputs, [])
        self.assertIsNone(self.w._scheme2_active_settings)
        self.assertEqual(self.w.quote_date.date(), QDate.currentDate())
        selected = self.w.attachments[0]
        self.assertTrue(selected["quote_catalog_refresh_required"])
        self.assertEqual((selected["model_code"], selected["quantity"]), ("FAN-X",2))
        self.assertNotIn("unit_price_override", selected)
        self.assertNotIn("formula_amount", selected)
        self.assertNotIn("quick_amount_override", selected)
        self.assertEqual(self.w.attachments[-1]["custom_cost"], 8)
        self.assertEqual(original, before)

    def test_ordinary_copy_uses_live_catalogue_and_new_cabinet_quote_replacing_only_copy(self):
        original = self.sample()
        before = deepcopy(original)
        self.copy_and_edit(original)
        self.submit_ordinary()
        self.assertEqual([url.rsplit("/",1)[-1] for url,_ in self.calls],
                         ["catalog?v=2", "calculate-dual"])
        self.assertNotIn("unit_price_override", self.calls[-1][1]["attachments"][0])
        self.assertEqual(len(self.w.draft_items), 2)
        self.assertIsNone(self.w._scheme2_edit_item)
        saved = self.w.draft_items[1]
        self.assertEqual(saved["quote_line_id"], "new-line")
        self.assertEqual(saved["attachments"][0]["quick_amount"], 50)
        self.assertEqual(saved["attachments"][0]["formula_amount"], 22)
        self.assertEqual(saved["attachments"][-1]["quick_amount"], 37)
        self.assertFalse(self.w._scheme2_new_quote_required)
        self.assertEqual(original, before)
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())

    def test_new_popup_edit_after_copy_wins_over_new_catalogue_price(self):
        original = self.sample()
        self.copy_and_edit(original)
        self.w.attachments[0].update(custom_amount_edited=True, quick_amount_override=0,
                                     unit_price_override=0, quick_amount=0)
        self.submit_ordinary()
        self.assertEqual(self.w.draft_items[1]["attachments"][0]["quick_amount"], 0)

    def test_catalogue_failure_never_falls_back_to_old_quote_and_manual_retry_refetches(self):
        original = self.sample()
        copied = self.copy_and_edit(original)
        before = deepcopy(copied)
        self.calls, self.catalog_failure = [], True
        self.w.calculate = lambda: self.fail("old quote must not be used after catalogue failure")
        with patch.object(base.ns["ApiWorker"], "start", lambda worker:self.transport(worker)):
            ui._calculate_and_add(self.w)
            base.pump(lambda:not self.w._scheme2_add_after_calculate)
        self.assertEqual(copied, before)
        self.assertIsNone(self.w.current_result)
        self.assertTrue(self.w._scheme2_new_quote_required)
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")
        self.submit_ordinary()
        self.assertTrue(self.calls[0][0].endswith("catalog?v=2"))
        self.assertIsNone(self.w._scheme2_edit_item)

    def test_non_copied_edit_also_reprices_as_new_and_replaces_old_row(self):
        original = self.sample()
        before = deepcopy(original)
        with patch.object(ui, "_selected_item", return_value=original):
            ui._edit_selected(self.w)
        self.assertTrue(self.w._scheme2_new_quote_required)
        self.assertNotIn("quick_amount_override", self.w.attachments[0])
        self.assertIsNone(self.w._attachment_v2_line_id)
        self.assertIsNone(self.w.current_result)
        self.submit_ordinary()
        self.assertEqual(len(self.w.draft_items), 1)
        self.assertIsNot(self.w.draft_items[0], original)
        self.assertEqual(self.w.draft_items[0]["quote_line_id"], "new-line")
        self.assertEqual(self.w.draft_items[0]["attachments"][0]["quick_amount"], 50)
        self.assertEqual(original, before)

    def test_ganged_copy_fetches_catalogue_before_a_new_ganged_request(self):
        original = self.sample(ganged=True)
        before = deepcopy(original)
        self.copy_and_edit(original)
        self.submit_ganged()
        self.assertEqual(len(self.w.draft_items), 2)
        self.assertEqual(self.w.draft_items[1]["quote_line_id"], "new-line")
        self.assertEqual(self.w.draft_items[1]["ganged_cabinet_count"], 2)
        self.assertEqual(self.w.draft_items[1]["attachments"][0]["quick_amount"], 50)
        self.assertEqual(original, before)

    def submit_ganged(self):
        self.calls, self.catalog_failure = [], False
        worker_class = lifecycle.LocalGangedWorker
        worker_class.response = self.response("new-ganged-copy", [])
        worker_class.mutate = None
        self.w.calculate = lambda:client._start_ganged_calculation(self.w, lambda *_:{})
        payloads = [dict(quote_id="new-ganged-copy", product_code="JP"),
                    dict(quote_id="new-child", product_code="JP")]
        with patch.object(base.ns["ApiWorker"], "start", lambda worker:self.transport(worker)), \
             patch.object(client, "_missing_ganged_formula_product_codes", return_value=[]), \
             patch.object(client, "_build_ganged_quote_payloads", return_value=(payloads,66.1,4)), \
             patch.object(client, "_ensure_window_ganged_fixed_bases", return_value=False), \
             patch.object(client, "_build_ganged_attachment_payload", return_value={"quote_id":"new-ganged-copy"}), \
             patch.object(client, "_GangedQuoteWorker", worker_class):
            ui._calculate_and_add(self.w)
            base.pump(lambda:self.w._scheme2_edit_item is None)
        self.assertTrue(self.calls[0][0].endswith("catalog?v=2"))
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())

    def test_non_copied_ganged_edit_also_reprices_and_replaces_old_row(self):
        original = self.sample(ganged=True)
        before = deepcopy(original)
        with patch.object(ui, "_selected_item", return_value=original):
            ui._edit_selected(self.w)
        self.submit_ganged()
        self.assertEqual(len(self.w.draft_items), 1)
        self.assertEqual(self.w.draft_items[0]["quote_line_id"], "new-line")
        self.assertEqual(self.w.draft_items[0]["attachments"][0]["quick_amount"], 50)
        self.assertEqual(original, before)

    def test_edit_second_identical_copy_replaces_by_identity_not_dictionary_equality(self):
        original = self.sample()
        first = self.copy_and_edit(original)
        second = deepcopy(first)
        self.w.draft_items.append(second)
        with patch.object(ui, "_selected_item", return_value=second):
            ui._edit_selected(self.w)
        self.submit_ordinary()
        self.assertEqual(len(self.w.draft_items), 3)
        self.assertIs(self.w.draft_items[1], first)
        self.assertEqual(self.w.draft_items[2]["quote_line_id"], "new-line")

    def test_copy_new_order_never_uses_signature_cache_even_if_signature_is_unchanged(self):
        original = self.sample()
        self.copy_and_edit(original)
        self.w.attachments = []
        self.w.current_result = {"input_signature":self.w.quote_input_signature()}
        with patch.object(self.w, "calculate") as calculate, patch.object(ui, "_finish_add") as cached_add:
            ui._calculate_and_add(self.w)
        calculate.assert_called_once()
        cached_add.assert_not_called()

    def test_sized_attachment_uses_new_catalogue_price_and_new_dimensions(self):
        old = dict(item_name="侧板", category_level1="侧板", attachment_price_id=1,
                   model_code="OLD", quantity=2, price=100, quick_amount=200,
                   size_match_original_price=100, size_match_ratio=2,
                   size_match_target_height_mm=2000, unit_price_override=200)
        selected = attachments.new_quote_attachment_selection(old)
        live = [dict(attachment_price_id=2, item_name="侧板", category_level1="侧板",
                     model_code="NEW", height_mm=1800, depth_mm=400, price=530)]
        matched = attachments.match_catalog_attachment(selected, live, target_dimensions=(1400,1700,420))
        self.assertEqual(matched["attachment_price_id"], 2)
        self.assertAlmostEqual(matched["unit_price_override"], 530 * (1700+420)/(1800+400), places=5)
        self.assertEqual(selected["quantity"], 2)
        self.assertEqual(old["unit_price_override"], 200)


if __name__ == "__main__":
    unittest.main()
