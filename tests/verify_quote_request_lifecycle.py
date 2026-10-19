"""Offline regression: edited quotes must settle, without losing popup edits."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import verify_drawing_workflow as base
from PySide6.QtCore import QObject, QTimer, Signal
import attachment_v2_client as attachments
import layout_refresh as client
import scheme2_ui as ui
from quote_request_context import bind_quote_request, check_quote_response, stamp_quote_response, retire_quote_request


class LocalGangedWorker(QObject):
    succeeded = Signal(dict)
    failed = Signal(str)
    progress = Signal(dict)
    finished = Signal()
    response = None
    mutate = None

    def __init__(self, *args, **kwargs):
        super().__init__(args[6])
        self.window = args[6]
        self.running = False

    def isRunning(self):
        return self.running

    def isInterruptionRequested(self):
        return False

    def start(self):
        self.running = True
        def complete():
            self.progress.emit({"stage": "snapshot"})
            if type(self).mutate:
                type(self).mutate(self.window)
            if type(self).response is not None:
                self.succeeded.emit(stamp_quote_response(self, deepcopy(type(self).response)))
            self.running = False
            self.finished.emit()
        QTimer.singleShot(10, complete)


class QuoteLifecycle(unittest.TestCase):
    def setUp(self):
        base.DrawingWorkflowTests.setUp(self)
        self.w.width_spin.setValue(800)
        self.w.depth_spin.setValue(600)
        self.w.height_spin.setValue(1800)
        self.w.quote_spec_edit.setText("800*600*1800")
        self.messages = []
        self.dialog_patch = patch.object(base.QMessageBox, "warning", side_effect=lambda *args:self.messages.append(args[2]))
        self.dialog_patch.start()
        self.addCleanup(self.dialog_patch.stop)
    tearDown = base.DrawingWorkflowTests.tearDown

    def arm(self):
        self.w._scheme2_calculation_epoch = getattr(self.w, "_scheme2_calculation_epoch", 0) + 1
        self.w._scheme2_calculation_paused = False
        self.w._scheme2_add_after_calculate = True
        self.w.scheme2_add_button.setText("暂停")
        ui._set_add_progress(self.w, 5, "保存报价快照")
        self.w._scheme2_add_elapsed_timer.start()

    def rows(self):
        return [dict(item_name="风机", attachment_price_id=101, catalog_version="offline",
                     quantity=2, custom_amount_edited=True, quick_amount_override=0,
                     unit_price_override=0, quick_amount=0, formula_unit_cost=10, formula_amount=20,
                     manual_inputs={"宽度": 50}, model_code="人工型号"),
                dict(custom=True, item_name="木托", quantity=1, formula_amount=8,
                     custom_cost=8, custom_cost_edited=True, quick_amount=37,
                     quick_amount_override=37, custom_amount_edited=True)]

    def result(self, quote_id="fresh", v2=True):
        result = base.response()
        result["quote_id"] = quote_id
        if v2:
            result.update(attachment_contract=2, quote_line_id="new-line",
                          attachments=[dict(item_name="风机", attachment_price_id=101,
                              quantity=2, formula_unit_cost=10, formula_amount=20,
                              quick_amount=100, status="FIXED", manual_inputs={"宽度":50})])
        return result

    def start_ganged(self, result, mutate=None):
        self.w.quote_spec_edit.setText("(800+800)*600*1800")
        self.w.ganged_cabinet_specification = "(800+800)*600*1800"
        self.w.ganged_cabinets = [dict(width_mm=800, depth_mm=600, height_mm=1800)] * 2
        self.w.attachments = self.rows()
        self.w.current_result = None
        self.arm()
        self.w._v2_request_environment = "old ordinary environment"
        self.w._v2_request_quote_id = "old ordinary quote"
        LocalGangedWorker.response = result
        LocalGangedWorker.mutate = mutate
        payloads = [dict(quote_id="fresh", product_code="JP"), dict(quote_id="child", product_code="JP")]
        with patch.object(client, "_missing_ganged_formula_product_codes", return_value=[]), \
             patch.object(client, "_build_ganged_quote_payloads", return_value=(payloads, 66.1, 4)), \
             patch.object(client, "_ensure_window_ganged_fixed_bases", return_value=False), \
             patch.object(client, "_build_ganged_attachment_payload", return_value={"quote_id":"fresh"}), \
             patch.object(client, "_GangedQuoteWorker", LocalGangedWorker):
            self.assertTrue(client._start_ganged_calculation(self.w, lambda *_:{}))
        ui._monitor_formula_calculation(self.w)
        base.pump(lambda: not self.w._scheme2_add_after_calculate and self.w.worker is None)
        base.app.processEvents()

    def test_ganged_after_ordinary_guard_finishes_edit_and_preserves_manual_rows(self):
        self.w.draft_items = [{"name":"old edited row"}]
        self.w._scheme2_edit_item = self.w.draft_items[0]
        self.start_ganged(self.result())
        self.assertEqual(len(self.w.draft_items), 1)
        self.assertIsNone(self.w._scheme2_edit_item, (self.w.risk_label.text(), self.messages))
        self.assertEqual(self.w.scheme2_add_progress.property("stepLabel"), "已完成")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())
        saved = self.w.draft_items[0]["attachments"]
        self.assertEqual(saved[0]["quick_amount"], 0)
        self.assertEqual(saved[0]["model_code"], "人工型号")
        self.assertEqual(saved[0]["quantity"], 2)
        self.assertEqual(saved[-1]["formula_amount"], 8)
        self.assertEqual(saved[-1]["quick_amount"], 37)
        self.assertTrue(saved[-1]["custom"])

    def test_ganged_response_rejected_after_manual_change_stops_at_retry(self):
        self.start_ganged(self.result(), lambda w: w.attachments[0].update(quantity=99))
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())
        self.assertFalse(self.w.draft_items)
        self.assertEqual(self.w.attachments[0]["quantity"], 99)

    def test_ganged_no_result_ends_wait(self):
        self.start_ganged(None)
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())

    def test_ordinary_constructor_replaces_ganged_context_and_preview_cannot_erase_customs(self):
        self.w.attachments = self.rows()
        old = bind_quote_request(self.w, SimpleNamespace(), "ganged", True)
        worker = base.ns["ApiWorker"]("https://offline.invalid/api/quotes/calculate-dual",
                                     dict(quote_id="ordinary", attachment_contract=2, attachments=self.rows()), self.w)
        self.assertNotEqual(old["token"], worker._client_request_token)
        self.assertEqual(self.w._quote_request_context["quote_id"], "ordinary")
        custom = deepcopy(self.w._v2_custom_attachments)
        base.ns["ApiWorker"]("https://offline.invalid/api/attachments/preview", {"attachments":[]}, self.w)
        self.assertEqual(self.w._v2_custom_attachments, custom)
        self.assertIsNone(self.w._v2_request_environment)

    def test_ordinary_success_uses_same_guard_and_finishes(self):
        self.w.attachments = self.rows()
        self.arm()
        worker = base.ns["ApiWorker"]("https://offline.invalid/api/quotes/calculate-dual",
                    dict(quote_id="fresh", attachment_contract=2, attachments=self.rows()), self.w)
        self.w.show_result(stamp_quote_response(worker, self.result()))
        self.assertIsInstance(self.w.current_result, dict, (self.w.risk_label.text(), self.w.scheme2_add_progress.property("stepLabel")))
        base.pump(lambda: bool(self.w.draft_items) or self.w.scheme2_add_button.text() == "重试")
        self.assertTrue(self.w.draft_items, self.messages)
        self.assertEqual(self.w.scheme2_add_progress.property("stepLabel"), "已完成")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())
        self.assertEqual(self.w.draft_items[0]["attachments"][-1]["custom_cost"], 8)

    def test_real_edit_load_and_ordinary_rejoin_replace_row_not_append(self):
        self.test_ordinary_success_uses_same_guard_and_finishes()
        saved = self.w.draft_items[0]
        expected = deepcopy(saved["attachments"])
        with patch.object(ui, "_selected_item", return_value=saved):
            ui._edit_selected(self.w)
        self.assertIsNone(self.w._quote_request_context)
        self.assertEqual(self.w.attachments[0]["model_code"], expected[0]["model_code"])
        self.assertEqual(self.w.attachments[-1], expected[-1])
        self.assertNotIn("quick_amount_override", self.w.attachments[0])
        # An edit made in this new popup session still has final authority.
        self.w.attachments[0].update(custom_amount_edited=True, quick_amount_override=0,
                                     unit_price_override=0, quick_amount=0)
        self.w.depth_spin.setValue(650)
        self.w.quote_spec_edit.setText("800*650*1800")
        self.arm()
        worker = base.ns["ApiWorker"]("https://offline.invalid/api/quotes/calculate-dual",
                    dict(quote_id="edited", attachment_contract=2, attachments=self.w.attachments), self.w)
        self.w.show_result(stamp_quote_response(worker, self.result("edited")))
        base.pump(lambda: self.w._scheme2_edit_item is None)
        self.assertEqual(len(self.w.draft_items), 1)
        updated = self.w.draft_items[0]
        self.assertIsNot(updated, saved)
        self.assertEqual(updated["depth_mm"], 650)
        self.assertEqual(updated["attachments"][0]["quick_amount"], 0)
        self.assertEqual(updated["attachments"][-1]["custom_cost"], 8)
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())

    def test_rejected_response_never_stamps_or_adds_previous_result(self):
        self.w.attachments = self.rows()
        self.arm()
        old = {"quote_id":"old-result", "input_signature":"old-signature"}
        self.w.current_result = old
        worker = SimpleNamespace()
        bind_quote_request(self.w, worker, "fresh", True)
        self.w.attachments[0]["quick_amount_override"] = 42
        self.w.show_result(stamp_quote_response(worker, self.result()))
        self.assertEqual(old["input_signature"], "old-signature")
        self.assertFalse(self.w.draft_items)
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())

    def test_old_token_same_epoch_cannot_end_new_request(self):
        self.w.attachments = self.rows()
        self.arm()
        old, current = SimpleNamespace(), SimpleNamespace()
        bind_quote_request(self.w, old, "old", True)
        bind_quote_request(self.w, current, "fresh", True)
        self.w.show_result(stamp_quote_response(old, self.result("old")))
        self.assertTrue(self.w._scheme2_add_after_calculate)
        self.assertIsNone(self.w.current_result)
        self.assertEqual(self.w.scheme2_add_button.text(), "暂停")

    def test_monitor_remains_until_worker_ends_without_a_result(self):
        self.arm()
        self.w.worker = SimpleNamespace(isRunning=lambda: True)
        ui._monitor_formula_calculation(self.w)
        base.QTest.qWait(230)
        self.assertTrue(self.w._scheme2_formula_monitor.isActive())
        self.w.worker = None
        base.pump(lambda: not self.w._scheme2_add_after_calculate)
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")

    def test_missing_v2_is_actionable_and_add_failure_stops_timer(self):
        self.w.attachments = self.rows()
        self.arm()
        worker = SimpleNamespace()
        bind_quote_request(self.w, worker, "fresh", True)
        self.w.show_result(stamp_quote_response(worker, self.result(v2=False)))
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())
        self.arm()
        with patch.object(self.w, "add_current_to_summary", return_value=None):
            ui._finish_add(self.w)
        self.assertEqual(self.w.scheme2_add_button.text(), "重试")
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())

    def test_guard_rejects_dimension_and_custom_cost_changes_in_both_modes(self):
        for mode in ("ordinary", "ganged"):
            for mutate in (lambda w:w.depth_spin.setValue(w.depth_spin.value()+1),
                           lambda w:w.quote_date.setDate(w.quote_date.date().addDays(1)),
                           lambda w:w.waste_factor_spin.setValue(w.waste_factor_spin.value()+.1),
                           lambda w:w.attachments[-1].update(custom_cost=9)):
                self.w.attachments = self.rows()
                worker = SimpleNamespace()
                bind_quote_request(self.w, worker, mode, True)
                mutate(self.w)
                current, reason = check_quote_response(self.w, stamp_quote_response(worker, self.result(mode)))
                self.assertTrue(current)
                self.assertIn("变化", reason)

    def test_retired_context_rejects_late_response_after_edit_or_reset(self):
        worker = SimpleNamespace()
        bind_quote_request(self.w, worker, "fresh", True)
        response = stamp_quote_response(worker, self.result())
        retire_quote_request(self.w)
        self.assertEqual(check_quote_response(self.w, response), (False, None))

    def test_old_preview_cannot_replace_manual_rows_or_new_quote_status(self):
        self.w.attachments = self.rows()
        workers = []
        with patch.object(base.ns["ApiWorker"], "start", lambda worker: workers.append(worker)):
            self.w._v2_environment_timer.timeout.emit()
        self.assertEqual(len(workers), 1)
        preview = workers[0]
        self.arm()
        bind_quote_request(self.w, SimpleNamespace(), "fresh", True)
        original = deepcopy(self.w.attachments)
        self.w.risk_label.setText("新报价正在计算")
        preview.succeeded.emit({"attachments":self.result()["attachments"]})
        preview.failed.emit("旧预览失败")
        self.assertEqual(self.w.attachments, original)
        self.assertEqual(self.w.risk_label.text(), "新报价正在计算")
        preview.finished.emit()

    def test_no_background_preview_is_dispatched_while_quote_pending(self):
        self.w.attachments = self.rows()
        bind_quote_request(self.w, SimpleNamespace(), "fresh", True)
        with patch.object(base.ns["ApiWorker"], "start") as start:
            self.w._v2_environment_timer.timeout.emit()
        start.assert_not_called()

    def test_preview_ignores_manual_cost_edit_even_without_a_quote_dispatch(self):
        self.w.attachments = self.rows()
        workers = []
        with patch.object(base.ns["ApiWorker"], "start", lambda worker: workers.append(worker)):
            self.w._v2_environment_timer.timeout.emit()
        self.w.attachments[-1]["custom_cost"] = 19
        self.w.attachments[-1]["formula_amount"] = 19
        expected = deepcopy(self.w.attachments)
        workers[0].succeeded.emit({"attachments":self.result()["attachments"]})
        self.assertEqual(self.w.attachments, expected)
        workers[0].finished.emit()


if __name__ == "__main__":
    unittest.main()
