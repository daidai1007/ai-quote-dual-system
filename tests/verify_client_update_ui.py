"""Real Qt update controls, async checks, close guards and shared styling."""
from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from update_test_support import LocalSource, ROOT
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QFrame, QMainWindow, QVBoxLayout, QWidget, QPushButton
import client_update_ui as ui
from client_update_core import atomic_json, read_json
from progress_style import PROGRESS_COLORS

app = QApplication.instance() or QApplication([])
if Path('C:/Windows/Fonts/msyh.ttc').is_file():
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei', 10))


def wait_until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate(): return
        QTest.qWait(10)
    raise AssertionError("Qt condition timed out")


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setCentralWidget(QWidget())
        self.scheme2_nav = QFrame(self.centralWidget()); QVBoxLayout(self.scheme2_nav)
        self.scheme2_nav.layout().addWidget(QPushButton("成本计算"))
        self.draft_items = []


class UpdateUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quote-update-ui-")
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}); self.env.start(); self.addCleanup(self.env.stop)
        self.fixture = LocalSource(Path(self.temp.name)); self.addCleanup(self.fixture.close)
        # The fixture models .04 -> .05 independently of the shipped app version.
        self.version = patch.object(ui, "CLIENT_VERSION", "2026.10.20.04")
        self.version.start(); self.addCleanup(self.version.stop)
        self.window = TestWindow(); self.window.resize(1000, 700); self.window.show()
        self.c = ui.UpdateController(self.window, self.fixture.install, self.fixture.config, startup=False)
        self.addCleanup(self.close)

    def close(self):
        if self.c.worker:
            self.c.worker.requestInterruption()
            wait_until(lambda: self.c.worker is None)
        if self.c.dialog: self.c.dialog.hide()
        self.window.close(); app.processEvents()

    def checked(self):
        self.c.check(); wait_until(lambda: self.c.worker is None)
        self.assertEqual(self.c.state, "available")

    def test_background_check_is_nonblocking_and_never_auto_downloads(self):
        counter = []
        timer = QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: counter.append(1)); timer.start()
        def slow(*_): time.sleep(.2); return self.fixture.envelope
        with patch.object(ui, "check_release", side_effect=slow):
            self.c.check(); self.assertEqual(self.c.state, "checking")
            wait_until(lambda: self.c.worker is None)
        timer.stop()
        self.assertGreater(len(counter), 3)
        self.assertEqual(self.c.state, "available")
        self.assertIsNone(self.c.dialog)
        self.assertIsNone(self.c.job_path)
        self.assertTrue(self.c.banner.isVisible())

    def test_same_release_version_does_not_offer_or_download_update(self):
        with patch.object(ui, "CLIENT_VERSION", self.fixture.envelope["release"]["version"]):
            self.c.check(); wait_until(lambda: self.c.worker is None)
        self.assertEqual(self.c.state, "current")
        self.assertIsNone(self.c.job_path)
        self.assertIsNone(self.c.dialog)

    def test_startup_timer_checks_locally_without_opening_dialog(self):
        window = TestWindow(); window.show()
        controller = ui.UpdateController(window, self.fixture.install, self.fixture.config, startup=True)
        self.assertEqual(controller.state, "idle")
        wait_until(lambda: controller.state == "available" and controller.worker is None)
        self.assertIsNone(controller.dialog); self.assertIsNone(controller.job_path)
        self.assertTrue(window.isVisible())
        window.close(); app.processEvents()

    def test_manual_check_later_and_shared_dialog_style(self):
        self.c.check(manual=True); wait_until(lambda: self.c.worker is None)
        d = self.c.dialog
        self.assertTrue(d.isVisible()); self.assertFalse(d.isModal())
        self.assertEqual(d.primary.text(), "下载更新")
        self.assertTrue(d.property("unifiedDialog"))
        self.assertIn(PROGRESS_COLORS["fill"], d.progress.styleSheet())
        self.c.secondary_action()
        self.assertFalse(d.isVisible()); self.assertFalse(self.c.banner.isVisible())

    def test_local_download_ready_without_close_or_install(self):
        self.checked(); self.c.show_dialog(); self.c.dialog.primary.click()
        wait_until(lambda: self.c.worker is None)
        self.assertEqual(self.c.state, "ready")
        self.assertTrue(self.window.isVisible())
        self.assertIn("保存进度并重启", self.c.dialog.primary.text())
        self.assertEqual((self.fixture.install / "_internal/version.txt").read_text(), "2026.10.20.04\nhealthy")
        self.c.dialog.secondary.click(); self.assertFalse(self.c.dialog.isVisible())

    def test_cancel_download_and_window_close_wait_for_worker(self):
        self.checked()
        def slow(config, envelope, install, version, progress, cancelled, **kwargs):
            while not cancelled(): time.sleep(.01)
            from client_update_core import Cancelled
            raise Cancelled("cancelled")
        with patch.object(ui, "download_update", side_effect=slow):
            self.c.start_download(); self.c.secondary_action()
            wait_until(lambda: self.c.worker is None)
        self.assertEqual(self.c.state, "available")
        self.assertIsNone(self.c.job_path)
        from PySide6.QtGui import QCloseEvent
        with patch.object(ui, "check_release", side_effect=lambda *_: (time.sleep(.1), None)[1]):
            self.c.check(); event = QCloseEvent()
            self.assertFalse(self.c.before_close(event)); self.assertFalse(event.isAccepted())
            wait_until(lambda: self.c.worker is None)

    def test_disabled_or_offline_check_keeps_program_available(self):
        self.c.config = {"enabled": False}
        self.c.check(manual=True); self.assertEqual(self.c.state, "disabled")
        self.assertIn("未启用", self.c.dialog.description.text())
        self.c.config = self.fixture.config
        with patch.object(ui, "check_release", side_effect=OSError("simulated offline")):
            self.c.check(manual=True); wait_until(lambda: self.c.worker is None)
        self.assertEqual(self.c.state, "error"); self.assertTrue(self.window.isVisible())
        self.assertEqual(self.c.dialog.primary.text(), "重新检查")

    def test_restart_blocks_business_tasks_and_source_mode(self):
        self.checked(); self.c.start_download(); wait_until(lambda: self.c.worker is None)
        self.c.restart(); self.assertIn("源码运行模式", self.c.error)
        self.c.frozen = True; self.window.quote_calculation_in_progress = True
        self.c.restart(); self.assertIn("报价计算", self.c.error)
        self.assertFalse(self.c.pending_restart); self.assertTrue(self.window.isVisible())

    def test_save_failure_never_closes_or_launches_updater(self):
        self.checked(); self.c.start_download(); wait_until(lambda: self.c.worker is None)
        self.c.frozen = True
        with patch("scheme2_ui._order_workspace_payload", return_value={}), patch("scheme2_ui._write_order_workspace_file", side_effect=OSError("disk full")):
            self.c.restart()
        self.assertEqual(self.c.state, "ready"); self.assertIn("保存失败", self.c.error)
        self.assertTrue(self.window.isVisible()); self.assertFalse(self.c.pending_restart)

    def test_successful_save_keeps_real_portable_workspace_with_drawing(self):
        self.checked(); self.c.start_download(); wait_until(lambda: self.c.worker is None)
        self.c.frozen = True; self.window._scheme2_dirty = True
        drawing = self.fixture.install / "drawings/图纸.pdf"
        payload = {"draft_items": [{"name": "人工修改", "price": 123.45}], "drawing_pages": [{"source_path": str(drawing)}],
                   "option_state": {"unfinished": "尚未加入报价的填写"}}
        with patch("scheme2_ui._order_workspace_payload", return_value=payload): self.c.restart()
        self.assertFalse(self.window.isVisible()); self.assertFalse(self.window._scheme2_dirty)
        job = read_json(self.c.job_path)
        self.assertTrue(Path(job["workspace"]).is_file())
        import zipfile
        with zipfile.ZipFile(job["workspace"]) as archive:
            self.assertTrue(any(name.startswith("drawings/") for name in archive.namelist()))
            self.assertIn("人工修改", archive.read("workspace.json").decode())

    def test_failure_and_success_feedback_read_once(self):
        from client_update_core import cache_root
        result = cache_root(self.fixture.install) / "last-result.json"
        atomic_json(result, {"status": "rolled_back", "message": "已恢复旧版本"})
        self.c.read_result(); self.assertEqual(self.c.state, "rolled_back")
        self.assertTrue(read_json(result)["seen"])
        atomic_json(result, {"status": "completed", "message": "成功"})
        self.c.read_result(); self.assertEqual(self.c.state, "completed")
        self.c.check()
        self.assertEqual(self.c.state, "completed")

    def test_dialog_fits_available_screen_and_buttons_work(self):
        self.checked(); self.c.show_dialog()
        d = self.c.dialog
        for width, height in ((1000, 700), (760, 600), (540, 480)):
            self.window.resize(width, height); app.processEvents(); d.refresh()
            self.assertTrue(d.rect().contains(d.primary.geometry().center()))
            self.assertTrue(d.rect().contains(d.secondary.geometry().center()))
            self.assertLessEqual(d.width(), d.screen().availableGeometry().width())
        output = ROOT / "outputs/client-update-qa"; output.mkdir(parents=True, exist_ok=True)
        d.grab().save(str(output / f"dialog-{os.getenv('QT_SCALE_FACTOR', '1')}.png"))


class WorkbenchIntegrationTests(unittest.TestCase):
    def test_updater_launch_only_after_existing_close_guard_accepts(self):
        class GuardWindow(QMainWindow):
            allow_close = False
            def __init__(self):
                super().__init__(); self.setCentralWidget(QWidget())
            def closeEvent(self, event):
                if self.allow_close: event.accept()
                else: event.ignore()
        ui.install_client_updates({"MainWindow": GuardWindow})
        with patch.object(ui, "load_config", return_value={"enabled": False}):
            window = GuardWindow()
        window.show(); app.processEvents(); window.client_updates.pending_restart = True
        with patch.object(window.client_updates, "launch_pending") as launch:
            self.assertFalse(window.close()); launch.assert_not_called()
            window.allow_close = True; self.assertTrue(window.close()); launch.assert_called_once()
        app.processEvents()

    def test_real_window_pages_and_close_guards(self):
        import v3_launcher
        namespace = v3_launcher.load_v3_namespace()
        cls = namespace["MainWindow"]
        cls.load_catalogs = lambda *_: None
        cls.refresh_formula_inputs = lambda *_: None
        with patch.object(ui, "load_config", return_value={"enabled": False}):
            window = cls()
        from PySide6.QtCore import QRect
        class ScreenArea:
            def availableGeometry(self): return QRect(0, 0, 1920, 1080)
        window.screen = lambda: ScreenArea()
        window.resize(1360, 800); window.show(); app.processEvents()
        self.assertIsNotNone(window.client_updates)
        self.assertEqual(len(window.findChildren(QPushButton, "clientCheckUpdateButton")), 1)
        for route in (1, 3, 2):
            window.show_section(route); app.processEvents()
            window.client_updates.state = "available"
            window.client_updates.envelope = {"release": {"version": "2026.10.20.05", "notes": "本地测试"}}
            window.client_updates.refresh()
            self.assertEqual(window.stack.currentIndex(), route)
        window.client_updates.show_dialog(); app.processEvents()
        output = ROOT / "outputs/client-update-qa"; output.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(output / f"workbench-{os.getenv('QT_SCALE_FACTOR', '1')}.png"))
        window.client_updates.dialog.hide(); window._scheme2_dirty = False
        self.assertTrue(window.close()); app.processEvents()


if __name__ == "__main__": unittest.main(verbosity=2)
