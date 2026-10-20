"""Real Qt geometry and pointer checks for shared 3/4-size scrollbars."""
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
from PySide6.QtWidgets import QApplication, QScrollArea, QStyle, QStyleOptionSlider
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
ns['ApiWorker'].run = lambda self: self.failed.emit('offline scrollbar test')


class ScrollbarTargets(unittest.TestCase):
    def setUp(self):
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
        with QSignalBlocker(self.window.summary_table):
            self.window.summary_table.setRowCount(160)
        self.window.scheme2_cost_empty.hide()
        self.resize(1280, 720)

    def resize(self, width, height):
        self.window.resize(width, height)
        QTest.qWait(50)
        ui._apply_responsive(self.window)
        QTest.qWait(50)

    def assert_bar(self, bar):
        self.assertTrue(bar.isVisible())
        thickness = bar.width() if bar.orientation() == Qt.Orientation.Vertical else bar.height()
        self.assertEqual(thickness, 15)

    def slider_rect(self, bar):
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        return bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                          QStyle.SubControl.SC_ScrollBarSlider, bar)

    def test_table_both_axes_keep_target_size_when_window_shrinks_and_grows(self):
        table = self.window.summary_table
        for size in ((1536, 960), (1024, 620), (1280, 720)):
            with self.subTest(size=size):
                self.resize(*size)
                self.assert_bar(table.verticalScrollBar())
                self.assert_bar(table.horizontalScrollBar())
                self.assertGreaterEqual(self.slider_rect(table.verticalScrollBar()).height(), 30)
                self.assertGreaterEqual(self.slider_rect(table.horizontalScrollBar()).width(), 30)
        self.assertTrue(self.window.grab().save(str(ROOT / 'outputs/scrollbar-thicker-cost.png')))

    def test_handle_centers_are_clickable_and_drag_moves_both_axes(self):
        table = self.window.summary_table
        for bar in (table.verticalScrollBar(), table.horizontalScrollBar()):
            with self.subTest(orientation=bar.orientation()):
                bar.setValue(0)
                self.assert_bar(bar)
                rect = self.slider_rect(bar)
                option = QStyleOptionSlider()
                bar.initStyleOption(option)
                vertical = bar.orientation() == Qt.Orientation.Vertical
                start = rect.center()
                hit = bar.style().hitTestComplexControl(QStyle.ComplexControl.CC_ScrollBar, option, start, bar)
                self.assertEqual(hit, QStyle.SubControl.SC_ScrollBarSlider)
                target = start + (QPoint(0, 100) if vertical else QPoint(100, 0))
                QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
                QTest.mouseMove(bar, target, delay=20)
                QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=target)
                self.assertGreater(bar.value(), 0)

    def test_option_outer_and_option_panel_share_target_size(self):
        self.assertTrue(self.window.scheme2_cost_sidebar.isHidden())
        self.window.show_section(ui.OPTION_ROUTE)
        self.resize(840, 600)
        self.assert_bar(self.window.findChild(QScrollArea, 'mainScroll').verticalScrollBar())
        self.assert_bar(self.window.findChild(QScrollArea, 'scheme2OptionScroll').verticalScrollBar())

    def test_attachment_popup_and_combo_popup_inherit_shared_targets(self):
        attachment = dict(custom=True, item_name='临时附件', quantity=1, formula_amount=1, quick_amount=1)
        item = dict(quantity=1, attachments=[dict(attachment) for _ in range(40)],
                    formula={'attachment_fee': 40, 'total_cost': 140},
                    quick={'attachment_fee': 40, 'total_cost': 240})
        dialog = ui.AttachmentEditor(self.window, item)
        self.addCleanup(dialog.close)
        dialog.show()
        app.processEvents()
        self.assert_bar(dialog.table.verticalScrollBar())
        dialog.close()
        combo = self.window.scheme2_company
        for index in range(40):
            combo.addItem(f'测试公司 {index}')
        combo.showPopup()
        app.processEvents()
        try:
            self.assert_bar(combo.view().verticalScrollBar())
        finally:
            combo.hidePopup()

    def test_attachment_summary_both_tables_inherit_shared_targets(self):
        attachments = [dict(custom=True, item_name=f'临时附件 {index}', quantity=1,
                            formula_amount=1, quick_amount=1) for index in range(40)]
        self.window.draft_items = [dict(name=f'测试柜 {index}', product_code='JP',
            specification='800*600*1800', quantity=1, attachments=attachments,
            formula={'attachment_fee': 40, 'total_cost': 140},
            quick={'attachment_fee': 40, 'total_cost': 240}) for index in range(20)]
        dialog = ui.AttachmentSummaryDialog(self.window)
        self.addCleanup(dialog.close)
        dialog.resize(1000, 650)
        dialog.show()
        QTest.qWait(40)
        self.assert_bar(dialog.product_table.verticalScrollBar())
        self.assert_bar(dialog.product_table.horizontalScrollBar())
        self.assert_bar(dialog.table.verticalScrollBar())
        self.assertTrue(dialog.grab().save(str(ROOT / 'outputs/scrollbar-thicker-summary.png')))


if __name__ == '__main__':
    unittest.main()
