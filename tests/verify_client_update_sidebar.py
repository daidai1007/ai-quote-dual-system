"""Task B: real workbench sidebar appearance and unchanged manual entry.

Offline, empty workspace only. No installed client/configuration is modified.
Run with QT_SCALE_FACTOR=1, 1.25, 1.5 and 2 for DPI screenshots.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
import client_update_ui as ui
import scheme2_ui
import v3_launcher
from dialog_style import button_style

app = QApplication.instance() or QApplication([])
if Path("C:/Windows/Fonts/msyh.ttc").is_file():
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
app.setFont(QFont("Microsoft YaHei", 10))


class SidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = v3_launcher.load_v3_namespace()
        cls.namespace["MainWindow"].load_catalogs = lambda *_: None
        cls.namespace["MainWindow"].refresh_formula_inputs = lambda *_: None
        cls.namespace["AttachmentDialog"].load_catalog = lambda *_: None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quote-update-sidebar-")
        self.addCleanup(self.temp.cleanup)
        for guard in (
            patch.dict(os.environ, LOCALAPPDATA=self.temp.name),
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden in sidebar tests")),
            patch.object(ui, "load_config", return_value={"enabled": False}),
            patch.object(ui, "acknowledge_startup"),
        ):
            guard.start(); self.addCleanup(guard.stop)
        self.window = self.namespace["MainWindow"]()
        class ScreenArea:
            def availableGeometry(self): return QRect(0, 0, 1920, 1080)
        self.window.screen = lambda: ScreenArea()
        self.window.resize(1360, 800)
        self.window.show(); app.processEvents()
        self.c = self.window.client_updates
        self.button = self.c.check_button
        self.addCleanup(self.close_window)

    def close_window(self):
        self.c.result_timer.stop()
        if self.c.dialog: self.c.dialog.close()
        self.window._scheme2_dirty = False
        self.window.close(); app.processEvents()

    def test_sidebar_uses_navigation_type_and_fits_on_all_routes_and_sizes(self):
        self.assertEqual(len(self.window.findChildren(QPushButton, "clientCheckUpdateButton")), 1)
        self.assertEqual(self.button.parentWidget(), self.window.scheme2_nav)
        self.assertFalse(self.button.isCheckable())
        self.assertEqual(self.button.font().pixelSize(), self.window.nav_buttons[0].font().pixelSize())
        self.assertEqual(self.button.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        self.assertIn(ui.CLIENT_VERSION, self.button.toolTip())
        self.assertEqual(self.button.accessibleName(), "检查软件更新")
        for size in ((1360, 800), (1920, 1080), (1092, 614), (910, 512)):
            self.window.resize(*size)
            scheme2_ui._set_nav_collapsed(self.window, False, manual=True)
            for route in (1, 3, 2):
                self.window.show_section(route); app.processEvents()
                nav = self.window.scheme2_nav
                self.assertEqual(self.button.font().pixelSize(), self.window.nav_buttons[0].font().pixelSize())
                self.assertTrue(self.button.isVisible())
                self.assertTrue(nav.rect().contains(self.button.geometry()))
                required = self.button.fontMetrics().horizontalAdvance(self.button.text())
                self.assertGreaterEqual(self.button.width(), required + 2 * ui.CHECK_BUTTON_METRICS["inset"])
                status = self.window.scheme2_service_status
                self.assertLess(status.geometry().bottom(), self.button.geometry().top())
                self.assertEqual(self.window.stack.currentIndex(), route)
        scheme2_ui._set_nav_collapsed(self.window, True, manual=True)
        self.assertFalse(self.button.isVisible())
        scheme2_ui._set_nav_collapsed(self.window, False, manual=True)
        self.assertTrue(self.button.isVisible())

    def test_mouse_and_keyboard_keep_existing_manual_check_callback(self):
        with patch.object(self.c, "check") as check:
            QTest.mouseClick(self.button, Qt.MouseButton.LeftButton)
            check.assert_called_once_with(manual=True)
            check.reset_mock()
            self.button.setFocus(); app.processEvents()
            QTest.keyClick(self.button, Qt.Key.Key_Space)
            check.assert_called_once_with(manual=True)
        self.button.click(); app.processEvents()
        self.assertEqual(self.c.state, "disabled")
        self.assertTrue(self.c.dialog.isVisible())
        self.assertTrue(self.c.dialog.property("unifiedDialog"))
        self.assertTrue(self.window.isVisible())

    def test_capture_before_after_hover_focus_and_disabled(self):
        output = Path(os.environ.get("AI_QUOTE_UI_ARTIFACT_DIR", ROOT / "outputs/task-B-update-sidebar"))
        output.mkdir(parents=True, exist_ok=True)
        scale = os.environ.get("QT_SCALE_FACTOR", "1")
        # Display a deterministic connected-state fixture without contacting API.
        self.window.scheme2_service_status.setText("报价服务已连接")
        self.window.setFocus(); app.processEvents()
        QTest.mouseMove(self.window, QPoint(self.window.width() - 20, 20))
        self.button.setStyleSheet(button_style("secondary")); app.processEvents()
        self.window.scheme2_nav.grab().save(str(output / f"sidebar-before-{scale}.png"))
        self.button.setStyleSheet(ui.check_button_style()); app.processEvents()
        self.window.scheme2_nav.grab().save(str(output / f"sidebar-after-{scale}.png"))
        nav = self.window.scheme2_nav
        footer = nav.rect()
        footer.setTop(max(0, self.window.scheme2_service_status.y() - 10))
        nav.grab(footer).save(str(output / f"footer-after-{scale}.png"))
        self.window.grab().save(str(output / f"workbench-after-{scale}.png"))
        QTest.mouseMove(self.button, self.button.rect().center()); app.processEvents()
        self.window.scheme2_nav.grab().save(str(output / f"sidebar-hover-{scale}.png"))
        self.button.setFocus(Qt.FocusReason.TabFocusReason); app.processEvents()
        self.assertTrue(self.button.hasFocus())
        self.window.scheme2_nav.grab().save(str(output / f"sidebar-focus-{scale}.png"))
        self.button.setEnabled(False); app.processEvents()
        with patch.object(self.c, "check") as check:
            self.button.click(); check.assert_not_called()
        self.window.scheme2_nav.grab().save(str(output / f"sidebar-disabled-{scale}.png"))


if __name__ == "__main__": unittest.main(verbosity=2)
