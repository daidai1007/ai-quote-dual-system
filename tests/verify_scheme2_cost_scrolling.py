"""Real Qt regression checks for the cost page's independent scrolling regions."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))

from PySide6.QtCore import QPoint, QSignalBlocker, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QTableWidgetItem
import layout_refresh
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns = v3_launcher.load_v3_namespace()
ns['install_application_font'](app)
Window = ns['MainWindow']
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline scrolling test')


class CostScrolling(unittest.TestCase):
    def setUp(self):
        # The offscreen plugin advertises an 800px monitor. Let these tests
        # exercise the requested logical work areas instead of clamping to it.
        for module in (layout_refresh, ui):
            patcher = patch.object(module, '_fit_window_minimum_to_screen', lambda window: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.window.setMinimumSize(1, 1)
        self.addCleanup(self.window.close)
        self.window.show()
        self.window.show_section(ui.COST_ROUTE)
        self.outer = self.window.findChild(QScrollArea, 'mainScroll')
        self.table = self.window.summary_table

    def settle(self, width, height):
        self.window.resize(width, height)
        QTest.qWait(40)
        ui._apply_responsive(self.window)
        QTest.qWait(40)
        self.assertEqual(self.window.size().toTuple(), (width, height))

    def rows(self, count):
        with QSignalBlocker(self.table):
            self.table.setRowCount(count)
            for row in range(count):
                for column, text in enumerate((str(row + 1), '测试柜', 'JP', '800*600*1800', '1')):
                    self.table.setItem(row, column, QTableWidgetItem(text))
        self.window.scheme2_cost_empty.hide()
        app.processEvents()

    def assert_page_fits(self):
        self.assertFalse(self.outer.verticalScrollBar().isVisible())
        self.assertEqual(self.outer.verticalScrollBar().maximum(), 0)
        canvas = self.outer.widget()
        self.assertLessEqual(canvas.height(), self.outer.viewport().height())
        page = self.window.scheme2_cost_page
        self.assertGreater(self.table.viewport().height(), 30)
        for button in self.window.scheme2_cost_action_buttons[:-1]:
            point = button.mapTo(page, QPoint(0, 0))
            self.assertGreaterEqual(point.y(), 0)
            self.assertLessEqual(point.y() + button.height(), page.height())
            visible = button.mapTo(self.outer.viewport(), QPoint(0, 0))
            self.assertGreaterEqual(visible.x(), 0)
            self.assertLessEqual(visible.x() + button.width(), self.outer.viewport().width())
            self.assertLessEqual(visible.y() + button.height(), self.outer.viewport().height())
        dock = self.window.scheme2_action_dock
        self.assertTrue(dock.isVisible())
        self.assertLessEqual(dock.mapTo(self.window, QPoint(0, 0)).y() + dock.height(), self.window.height())

    def test_few_rows_hide_table_scrollbar_at_common_window_sizes(self):
        self.rows(5)
        for size in ((1536, 960), (1280, 720), (1024, 620)):
            with self.subTest(size=size):
                self.settle(*size)
                self.assertEqual(self.table.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                self.assertFalse(self.table.verticalScrollBar().isVisible())
                self.assertTrue(self.table.horizontalScrollBar().isVisible())
                self.assert_page_fits()
                sidebar_scroll = self.window.findChild(QScrollArea, 'scheme2CoefficientScroll')
                self.assertFalse(sidebar_scroll.verticalScrollBar().isVisible())
        self.assertTrue(self.window.grab().save(str(ROOT / 'outputs/cost-scroll-few-rows.png')))

    def test_empty_table_has_no_vertical_scrollbar(self):
        self.rows(0)
        self.settle(1280, 720)
        self.assertFalse(self.table.verticalScrollBar().isVisible())
        self.assert_page_fits()

    def test_many_rows_scroll_without_moving_actions_or_page(self):
        self.rows(160)
        self.settle(1280, 720)
        self.assertTrue(self.table.verticalScrollBar().isVisible())
        self.assertGreater(self.table.verticalScrollBar().maximum(), 0)
        before = [button.mapTo(self.window, QPoint(0, 0)) for button in self.window.scheme2_cost_action_buttons]
        self.table.scrollToBottom()
        app.processEvents()
        self.assertTrue(self.table.visualItemRect(self.table.item(159, 0)).intersects(self.table.viewport().rect()))
        self.assertEqual(before, [button.mapTo(self.window, QPoint(0, 0)) for button in self.window.scheme2_cost_action_buttons])
        self.assert_page_fits()
        self.assertTrue(self.window.grab().save(str(ROOT / 'outputs/cost-scroll-many-rows.png')))

    def test_resize_with_progress_and_undo_stays_inside_viewport(self):
        self.rows(160)
        self.window._scheme2_document_controller.widgets['generate'][0].show()
        self.window._scheme2_document_controller.widgets['generate'][2].show()
        self.window.scheme2_cost_undo.show()
        for size in ((1468, 970), (1024, 620), (840, 600), (1536, 960), (1280, 720)):
            with self.subTest(size=size):
                self.settle(*size)
                self.assert_page_fits()

    def test_coefficient_modal_and_other_routes_restore_outer_scrolling(self):
        self.settle(1024, 620)
        self.assertTrue(self.window.scheme2_cost_sidebar.isHidden())
        dialog = ui._CostCoefficientDialog(self.window)
        dialog.show()
        QTest.qWait(40)
        self.assertTrue(all(control.isVisible() for control in dialog.controls.values()))
        dialog.reject()
        self.assert_page_fits()
        self.window.show_section(ui.OPTION_ROUTE)
        self.settle(840, 600)
        self.assertEqual(self.outer.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.assertGreater(self.outer.verticalScrollBar().maximum(), 0)
        self.window.show_section(ui.COST_ROUTE)
        self.settle(1024, 620)
        self.assert_page_fits()
        self.assertTrue(self.window.scheme2_cost_sidebar.isHidden())
        self.window.show_section(ui.QUOTE_ROUTE)
        self.settle(1024, 620)
        self.assertEqual(self.outer.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)


if __name__ == '__main__':
    unittest.main()
