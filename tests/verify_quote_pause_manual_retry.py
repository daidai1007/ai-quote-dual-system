"""Offline Qt: Pause is clickable, late work is discarded, retries are manual."""
import http.client
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
import layout_refresh as client
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
ns["install_application_font"](app)
Window = ns["MainWindow"]
actual_formula_refresh = Window.refresh_formula_inputs
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None


def wait_for(predicate):
    for _ in range(300):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("operation did not complete")


class DeferredWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)
    progress = Signal(dict)

    def __init__(self, window):
        super().__init__(window)
        self.release = threading.Event()
        self.entered = threading.Event()
        self.epoch = window._scheme2_calculation_epoch

    def run(self):
        self.entered.set()
        self.release.wait(3)
        self.progress.emit({"stage":"snapshot"})
        self.succeeded.emit({"_client_calculation_epoch":self.epoch})
        self.failed.emit("old task failure must not replace Retry")


class PauseManualRetry(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window.attachments = []
        self.window.current_result = None
        self.workers = []
        self.calls = 0
        def calculate():
            self.calls += 1
            worker = DeferredWorker(self.window)
            self.workers.append(worker)
            self.window.worker = worker
            self.window.quote_calculation_in_progress = True
            worker.succeeded.connect(self.window.show_result)
            worker.failed.connect(self.window.show_error)
            worker.progress.connect(lambda event: client._update_calculation_progress(self.window, event))
            worker.finished.connect(lambda: None)
            worker.start()
        self.window.calculate = calculate
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for worker in self.workers:
            worker.release.set()
            try:
                worker.wait(2000)
            except RuntimeError:
                pass
        app.processEvents()
        self.window._scheme2_dirty = False
        self.window.close()

    def start_and_pause(self):
        QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)
        wait_for(lambda:self.workers[0].entered.is_set())
        self.assertEqual(self.window.scheme2_add_button.text(), "暂停")
        self.assertTrue(self.window.scheme2_add_button.isEnabled())
        started = time.monotonic()
        QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)
        self.assertLess(time.monotonic() - started, .3, "pause must not wait for socket I/O")
        self.assertEqual(self.window.scheme2_add_button.text(), "重试")
        self.assertTrue(self.window.scheme2_add_button.isEnabled())

    def test_pause_is_immediate_and_old_worker_cannot_overwrite_ui(self):
        self.start_and_pause()
        label = self.window.risk_label.text()
        self.assertIn("已暂停", self.window.scheme2_add_progress.format())
        first = self.window.scheme2_add_progress.format()
        QTest.qWait(100)
        ui._refresh_add_progress_display(self.window)
        self.assertEqual(self.window.scheme2_add_progress.format(), first)
        self.assertEqual(self.calls, 1)
        self.workers[0].release.set()
        wait_for(lambda:not self.window._scheme2_paused_quote_workers)
        self.assertEqual(self.window.scheme2_add_button.text(), "重试")
        self.assertEqual(self.window.risk_label.text(), label)
        self.assertIsNone(self.window.current_result)
        self.assertFalse(self.window.draft_items)

    def test_manual_retry_starts_new_flow_and_rejects_old_epoch(self):
        self.start_and_pause()
        epoch = self.workers[0].epoch
        QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.window.scheme2_add_button.text(), "暂停")
        self.assertFalse(self.window._scheme2_calculation_paused)
        self.window.show_result({"_client_calculation_epoch":epoch})
        self.assertIsNone(self.window.current_result)
        self.workers[0].release.set()
        wait_for(lambda:not self.window._scheme2_paused_quote_workers)
        self.assertIs(self.window.worker, self.workers[1])
        self.assertEqual(self.window.scheme2_add_button.text(), "暂停")
        QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)

    def test_template_and_ganged_preparation_are_cancelled_too(self):
        self.window._scheme2_add_after_calculate = True
        self.window._scheme2_calculation_epoch = 1
        for name in ("template_worker", "ganged_template_worker", "_scheme2_attachment_catalog_worker"):
            worker = DeferredWorker(self.window)
            self.workers.append(worker)
            setattr(self.window, name, worker)
            worker.succeeded.connect(lambda _data: self.fail("cancelled template callback ran"))
            worker.failed.connect(lambda _error: self.fail("cancelled error callback ran"))
            worker.progress.connect(lambda _event: None)
            worker.finished.connect(lambda: None)
            worker.start()
        wait_for(lambda:all(worker.entered.is_set() for worker in self.workers))
        QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window._pending_formula_calculation)
        for name in ("template_worker", "ganged_template_worker", "_scheme2_attachment_catalog_worker"):
            self.assertIsNone(getattr(self.window, name))
        for worker in self.workers:
            worker.release.set()
        wait_for(lambda:not self.window._scheme2_paused_quote_workers)

    def test_formula_failure_does_not_retry_for_single_or_ganged(self):
        for worker in (client._FormulaTemplateWorker("https://offline/formula-template", "JP", lambda _json:{}),
                       client._GangedFormulaTemplateWorker("https://offline", ["JP","JS"], lambda _json:{})):
            failures, retry_events = [], []
            worker.failed.connect(failures.append)
            worker.retrying.connect(lambda *args:retry_events.append(args))
            with patch.object(client, "_fetch_formula_template", side_effect=http.client.IncompleteRead(b"",1)) as fetch:
                worker.run()
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(retry_events, [])

    def test_real_formula_flow_shows_retry_after_first_failure(self):
        del self.window.calculate
        self.window.refresh_formula_inputs = actual_formula_refresh.__get__(self.window, Window)
        self.window.product_catalog = {"JP":{"method":"formula","codes":{"SINGLE":"JP_SINGLE"}}}
        self.window.product_combo.blockSignals(True)
        self.window.product_combo.clear()
        self.window.product_combo.addItem("JP", "JP")
        self.window.product_combo.blockSignals(False)
        self.window.selected_product_code = lambda:"JP_SINGLE"
        self.window.weight_edit.clear()
        self.window.area_edit.clear()
        client._FORMULA_TEMPLATE_CACHE.clear()
        with patch.object(client, "_fetch_formula_template", side_effect=http.client.IncompleteRead(b"",1)) as fetch:
            QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)
            self.assertEqual(self.window.scheme2_add_button.text(), "暂停")
            wait_for(lambda:self.window.scheme2_add_button.text()=="重试")
            self.assertEqual(fetch.call_count, 1)
            QTest.qWait(200)
            self.assertEqual(fetch.call_count, 1)
            QTest.mouseClick(self.window.scheme2_add_button, Qt.MouseButton.LeftButton)
            wait_for(lambda:self.window.scheme2_add_button.text()=="重试")
            self.assertEqual(fetch.call_count, 2)

    def test_interrupted_template_never_emits_success_or_continues_next_child(self):
        for worker in (client._FormulaTemplateWorker("https://offline", "JP", lambda _json:{}),
                       client._GangedFormulaTemplateWorker("https://offline", ["JP","JS"], lambda _json:{})):
            results = []
            worker.succeeded.connect(results.append)
            with patch.object(type(worker), "isInterruptionRequested", side_effect=[False, True]), \
                 patch.object(client, "_fetch_formula_template", return_value={"template":{"template_code":"JP"}}) as fetch:
                worker.run()
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(results, [])

    def test_paused_footer_layout(self):
        self.start_and_pause()
        self.window.resize(1519,987)
        self.window.show()
        app.processEvents()
        footer = self.window.scheme2_add_progress.parentWidget()
        for width in (footer.width(),620):
            footer.setFixedWidth(width)
            ui._refresh_add_progress_display(self.window)
            app.processEvents()
            self.assertFalse(self.window.scheme2_add_progress.geometry().intersects(self.window.scheme2_add_button.geometry()))
        footer.grab().save(str(ROOT / ".codex-tmp" / "quote-paused-preview.png"))


if __name__ == "__main__":
    unittest.main()
