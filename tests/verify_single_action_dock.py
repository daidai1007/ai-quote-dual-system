"""Actual recovered client: one footer, physical hit tests and Qt DPI rendering."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))


def run_dpi_matrix():
    for scale in ("1", "1.25", "1.5", "2"):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale,
                   QT_FONT_DPI="96", PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, __file__, "--dpi-case"], cwd=ROOT,
                                env=env, capture_output=True, text=True, encoding="utf-8",
                                timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print(f"Qt scale {scale}:\n{result.stdout}{result.stderr}", flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__" and "--dpi-case" not in sys.argv:
    run_dpi_matrix()
    raise SystemExit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QFrame, QMainWindow, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
import layout_refresh as layout
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
if Path("C:/Windows/Fonts/msyh.ttc").is_file():
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
ns["install_application_font"](app)
Window = ns["MainWindow"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None


def settle():
    for _ in range(5):
        app.processEvents()


class ScreenArea:
    def __init__(self, width, height):
        self.area = QRect(0, 0, width, height)

    def availableGeometry(self):
        return self.area


class SingleActionDockTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window.screen = lambda: ScreenArea(1920, 1080)
        self.window.resize(1360, 800)
        self.window.show()
        settle()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.window._scheme2_dirty = False
        self.window.close()
        settle()

    def assert_single_dock(self, route):
        w = self.window
        dock, old = w.scheme2_action_dock, getattr(w, "quote_action_dock", None)
        self.assertTrue(dock.isVisible())
        self.assertTrue(w._quote_action_dock_retired)
        if old is not None:
            self.assertTrue(old.isHidden(), "legacy callback resurrected the old footer")
            self.assertEqual((old.minimumHeight(), old.maximumHeight()), (0, 0))
            self.assertEqual(w.quote_action_dock_host.layout().indexOf(old), -1)
        host_layout = w.quote_action_dock_host.layout()
        footer_slots = [host_layout.itemAt(index).widget() for index in range(host_layout.count())
                        if host_layout.itemAt(index).widget() is not None
                        and host_layout.itemAt(index).widget().objectName()
                        in {"quoteActionDock", "scheme2ActionDock"}]
        self.assertEqual(footer_slots, [dock])
        self.assertEqual(dock.minimumHeight(), dock.maximumHeight())
        self.assertEqual(dock.width(), w.quote_action_dock_host.width())
        self.assertTrue(w.rect().contains(QRect(dock.mapTo(w, QPoint()), dock.size())))
        scroll = w.findChild(QScrollArea, "mainScroll")
        self.assertLess(scroll.mapTo(w, scroll.rect().bottomLeft()).y(), dock.mapTo(w, QPoint()).y())
        for button, routes in w._scheme2_action_dock_entries:
            self.assertEqual(button.isVisible(), route in routes)
            self.assertIs(button.parentWidget(), dock)
            if button.isVisible():
                self.assertTrue(dock.rect().contains(QRect(button.mapTo(dock, QPoint()), button.size())))
                self.assertGreaterEqual(button.height(), 28)
                self.assertLessEqual(button.fontMetrics().height(), button.height())
                center = button.mapTo(w, button.rect().center())
                target = w.childAt(center)
                self.assertTrue(target is button or button.isAncestorOf(target),
                                (route, button.text(), target.objectName() if target else None))

    def test_stale_callbacks_cannot_restore_old_footer(self):
        w = self.window
        # Also cover an existing footer from an earlier initialization pass.
        old = QFrame(w.quote_action_dock_host)
        old.setObjectName("quoteActionDock")
        old.setFixedHeight(layout.QUOTE_ACTION_DOCK_HEIGHT)
        w.quote_action_dock_host.layout().addWidget(old)
        w.quote_action_dock = old
        old.show()
        # Reproduce the exact callback ordering from the reported overlap.
        ui._apply_responsive(w)
        layout._position_quote_action_dock(w)
        self.assert_single_dock(ui.OPTION_ROUTE)
        for _ in range(3):
            layout._ensure_quote_action_dock(w)
            QTimer.singleShot(0, lambda: layout._position_quote_action_dock(w))
            for bar in (w.findChild(QScrollArea, "mainScroll").horizontalScrollBar(),
                        w.findChild(QScrollArea, "mainScroll").verticalScrollBar()):
                bar.valueChanged.emit(bar.value())
            settle()
            self.assert_single_dock(ui.OPTION_ROUTE)
        self.assertEqual(getattr(w, "_quote_action_dock_connections", []), [])

    def test_routes_sizes_minimize_restore_and_dpi_have_one_clickable_footer(self):
        w = self.window
        scale = float(os.environ.get("QT_SCALE_FACTOR", "1"))
        available = (round(1920 / scale), round(1040 / scale))
        w.screen = lambda: ScreenArea(*available)
        for width, height in ((1360, 800), (980, 620), (760, 470), (1600, 920)):
            layout._fit_window_minimum_to_screen(w)
            w.resize(min(width, available[0] - 32), min(height, available[1] - 48))
            for route in (ui.OPTION_ROUTE, ui.COST_ROUTE, ui.QUOTE_ROUTE,
                          ui.COST_ROUTE, ui.OPTION_ROUTE):
                w.show_section(route)
                settle()
                layout._position_quote_action_dock(w)
                self.assert_single_dock(route)
                folder = ROOT / ".codex-tmp" / "single-action-dock"
                folder.mkdir(parents=True, exist_ok=True)
                if width == 1360:
                    w.grab().save(str(folder / f"scale-{scale}-route-{route}.png"))
            w.showMinimized()
            settle()
            w.showNormal()
            settle()
            self.assert_single_dock(ui.OPTION_ROUTE)
        print(json.dumps({"scale": scale, "device_pixel_ratio": w.devicePixelRatioF(),
                          "logical_window": [w.width(), w.height()]}, ensure_ascii=False))

    def test_visible_buttons_still_dispatch_original_actions_once(self):
        w = self.window
        cases = [(ui.OPTION_ROUTE, w.scheme2_add_button, "add"),
                 (ui.COST_ROUTE, w.scheme2_cost_generate, "generate"),
                 (ui.QUOTE_ROUTE, w.scheme2_quote_print, "print"),
                 (ui.QUOTE_ROUTE, w.scheme2_quote_export, "export")]
        calls = []
        with patch.object(ui, "_calculate_and_add", side_effect=lambda window: calls.append("add")), \
             patch.object(w._scheme2_document_controller, "generate", side_effect=lambda: calls.append("generate")), \
             patch.object(ui, "_print_quote", side_effect=lambda window: calls.append("print")), \
             patch.object(w, "confirm_and_export", side_effect=lambda: calls.append("export")):
            for route, button, name in cases:
                w.show_section(route)
                settle()
                button.setEnabled(True)
                self.assert_single_dock(route)
                point = button.mapTo(w, button.rect().center())
                target = w.childAt(point)
                QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFrom(w, point))
                settle()
                self.assertEqual(calls[-1:], [name])
            self.assertEqual(calls, [name for _route, _button, name in cases])

    def test_small_laptop_work_area_keeps_actions_in_view(self):
        w = self.window
        scale = float(os.environ.get("QT_SCALE_FACTOR", "1"))
        area = (round(1366 / scale), round(728 / scale))
        w.screen = lambda: ScreenArea(*area)
        layout._fit_window_minimum_to_screen(w)
        w.resize(area[0] - 32, area[1] - 48)
        for route in (ui.OPTION_ROUTE, ui.COST_ROUTE, ui.QUOTE_ROUTE, ui.OPTION_ROUTE):
            w.show_section(route)
            settle()
            self.assert_single_dock(route)
            self.assertLessEqual(w.height(), area[1])
            folder = ROOT / ".codex-tmp" / "single-action-dock"
            folder.mkdir(parents=True, exist_ok=True)
            w.grab().save(str(folder / f"scale-{scale}-laptop-route-{route}.png"))

    def test_standalone_legacy_dock_remains_usable(self):
        legacy = QMainWindow()
        scroll = QScrollArea()
        scroll.setObjectName("mainScroll")
        canvas = QWidget()
        body = QVBoxLayout(canvas)
        legacy.stack = QStackedWidget()
        legacy.stack.addWidget(QWidget())
        page = QWidget()
        row = QVBoxLayout(page)
        for name in ("primaryQuoteAction", "secondaryQuoteAction", "quietQuoteAction"):
            button = QPushButton(name)
            button.setObjectName(name)
            row.addWidget(button)
        legacy.stack.addWidget(page)
        legacy.stack.setCurrentIndex(1)
        body.addWidget(legacy.stack)
        scroll.setWidget(canvas)
        legacy.setCentralWidget(scroll)
        legacy.resize(1100, 700)
        legacy.show()
        try:
            layout._ensure_quote_action_dock(legacy)
            settle()
            layout._position_quote_action_dock(legacy)
            self.assertTrue(legacy.quote_action_dock.isVisible())
            self.assertEqual(legacy.quote_action_dock.height(), layout.QUOTE_ACTION_DOCK_HEIGHT)
            self.assertTrue(legacy._quote_action_dock_connections)
            layout._retire_quote_action_dock(legacy)
            layout._position_quote_action_dock(legacy)
            self.assertEqual(legacy._quote_action_dock_connections, [])
            self.assertTrue(legacy.quote_action_dock.isHidden())
            self.assertEqual(legacy.quote_action_dock.minimumHeight(), 0)
        finally:
            legacy.close()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
