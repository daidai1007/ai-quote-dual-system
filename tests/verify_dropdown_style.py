"""Offline Qt popup appearance, interactions and current-client DPI coverage."""
import gc
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))


if __name__ == '__main__' and '--dpi-case' not in sys.argv:
    for scale in ('1', '1.25', '1.5', '2'):
        result = subprocess.run(
            [sys.executable, '-X', 'faulthandler', __file__, '--dpi-case'], cwd=ROOT,
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=scale,
                     QT_FONT_DPI='96', PYTHONIOENCODING='utf-8'),
            capture_output=True, text=True, encoding='utf-8', timeout=60,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(f'Qt scale {scale}:\n{result.stdout}{result.stderr}', flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
    raise SystemExit(0)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (QApplication, QComboBox, QCompleter, QStyle,
                               QLineEdit, QStyleOptionViewItem, QVBoxLayout, QWidget)
from dropdown_style import ComboPopupDelegate, POPUP_COLORS, install_combo_popup_style
import quote_scheme_center as centre
from quote_scheme_widgets import SchemeComboBox
import scheme2_ui as ui
import v3_launcher

APP = QApplication.instance() or QApplication([])
NS = v3_launcher.load_v3_namespace()
NS['install_application_font'](APP)
NS['MainWindow'].load_catalogs = lambda self: None
NS['MainWindow'].refresh_formula_inputs = lambda self, *args: None
NS['ApiWorker'].run = lambda self: self.failed.emit('offline dropdown test')
centre.QuoteSchemeWorker.run = lambda self: self.succeeded.emit(
    dict(items=[], total=0, page=1, page_size=10))
install_combo_popup_style()


def settle():
    for _ in range(5):
        APP.processEvents()


class DropdownStyleTests(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(400, 340)
        self.layout = QVBoxLayout(self.host)
        self.host.show()

    def tearDown(self):
        for combo in self.host.findChildren(QComboBox):
            combo.hidePopup()
        self.host.close()
        self.host.deleteLater()
        settle()

    def combo(self, factory=QComboBox, values=('全部', '草稿', '已报价', '修订中', '已归档', '已作废')):
        combo = factory()
        for i, value in enumerate(values):
            combo.addItem(value, {'id': i})
        combo.setFixedSize(300, 40)
        self.layout.addWidget(combo)
        settle()
        return combo

    def assert_styled(self, combo, view=None):
        view = view if view is not None else combo.view()
        self.assertTrue(view.property('unifiedComboPopup'))
        self.assertIsInstance(view.itemDelegate(), ComboPopupDelegate)
        self.assertIn(POPUP_COLORS['selected'], view.styleSheet())
        self.assertIn('font-size:13px', view.styleSheet())
        if view.model().rowCount():
            self.assertEqual(view.sizeHintForRow(0), 40)

    def test_dynamic_plain_status_and_editable_popups_share_style_without_mutations(self):
        for factory in (QComboBox, SchemeComboBox):
            combo = self.combo(factory)
            before = (combo.geometry(), combo.font(), combo.currentData(), combo.count())
            changed = QSignalSpy(combo.currentIndexChanged)
            combo.showPopup()
            settle()
            self.assert_styled(combo)
            self.assertEqual((combo.geometry(), combo.font(), combo.currentData(), combo.count()), before)
            self.assertEqual(changed.count(), 0)
            row = combo.view().model().index(1, 0)
            QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                             pos=combo.view().visualRect(row).center())
            settle()
            self.assertEqual(combo.currentData(), {'id': 1})
            self.assertEqual(changed.count(), 1)
            combo.hidePopup()
        combo = self.combo(values=('JP760260', 'JP930060'))
        combo.setEditable(True)
        combo.setEditText('人工输入型号')
        combo.showPopup()
        settle()
        self.assert_styled(combo)
        self.assertEqual(combo.currentText(), '人工输入型号')
        self.assertFalse(combo.lineEdit().isReadOnly())

    def test_completer_and_replaced_view_are_styled_when_opened(self):
        combo = self.combo(values=('JP760260', 'JP930060'))
        combo.setEditable(True)
        completer = combo.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCompletionPrefix('JP')
        completer.complete()
        settle()
        self.assert_styled(combo, completer.popup())
        completer.popup().hide()
        # Native Qt editors may replace their view after initial construction.
        from PySide6.QtWidgets import QListView
        combo.setView(QListView())
        combo.showPopup()
        settle()
        self.assert_styled(combo)

    def test_database_model_suggestions_use_same_popup_without_changing_input(self):
        editor = QLineEdit()
        self.layout.addWidget(editor)
        settle()
        # Product changes install a new completer after the editor is visible.
        completer = QCompleter(['JP760260', 'JP930060'], editor)
        editor.setCompleter(completer)
        editor.setText('JP')
        completer.setCompletionPrefix('JP')
        completer.complete()
        settle()
        popup = completer.popup()
        self.assert_styled(None, popup)
        self.assertEqual(editor.text(), 'JP')
        self.assertEqual(completer.completionCount(), 2)
        index = popup.model().index(1, 0)
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton,
                         pos=popup.visualRect(index).center())
        settle()
        self.assertEqual(editor.text(), 'JP930060')

    def test_multiselect_checkbox_and_keep_open_behavior_survive(self):
        combo = self.combo(ui._SchemeAttachmentCombo, ('未选择', '行程开关', '照明灯220V长款', '照明灯24V-0.6m'))
        combo.set_selected_texts(['行程开关'])
        spy = QSignalSpy(combo.selectionChanged)
        combo.showPopup()
        settle()
        self.assert_styled(combo)
        index = combo.model().index(2, 0)
        QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                         pos=combo.view().visualRect(index).center())
        settle()
        self.assertEqual(combo.selected_texts(), ['行程开关', '照明灯220V长款'])
        self.assertEqual(spy.count(), 1)
        self.assertTrue(combo.view().isVisible())
        combo.hidePopup()

    def test_long_lists_keep_all_options_accessible_and_empty_lists_are_safe(self):
        combo = self.combo(values=tuple(f'型号 {i}' for i in range(80)))
        combo.showPopup()
        settle()
        self.assert_styled(combo)
        self.assertEqual(combo.maxVisibleItems(), 8)
        self.assertGreater(combo.view().verticalScrollBar().maximum(), 0)
        index = combo.model().index(79, 0)
        combo.view().scrollTo(index)
        settle()
        QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                         pos=combo.view().visualRect(index).center())
        settle()
        self.assertEqual(combo.currentData(), {'id': 79})
        empty = self.combo(values=())
        self.assert_styled(empty)
        self.assertEqual(empty.count(), 0)

    def test_reference_paint_colors_placeholder_separator_and_disabled_row(self):
        combo = self.combo(values=('未选择', 'SECC', 'SUS304', '自定义…'))
        combo.setProperty('schemePlaceholderIndex', 0)
        delegate = ui._SchemeComboItemDelegate(combo, separator_index=3)
        combo.view().setItemDelegate(delegate)
        combo.setCurrentIndex(1)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 300, 40)
        option.font = combo.view().font()
        for row, color in ((0, 'background'), (1, 'selected'), (2, 'hover')):
            option.state = QStyle.StateFlag.State_Enabled
            if row == 2:
                option.state |= QStyle.StateFlag.State_MouseOver
            image = QImage(300, 40, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            delegate.paint(painter, option, combo.model().index(row, 0))
            painter.end()
            self.assertEqual(image.pixelColor(280, 20), QColor(POPUP_COLORS[color]))
        combo.model().item(2).setEnabled(False)
        combo.showPopup()
        settle()
        self.assertIs(combo.view().itemDelegate(), delegate)
        self.assertEqual(delegate.separator_index, 3)
        self.assertFalse(combo.model().index(2, 0).flags() & Qt.ItemFlag.ItemIsEnabled)

    def test_actual_client_pages_and_reference_screenshots(self):
        window = NS['MainWindow']()
        window.resize(1500, 900)
        window.show()
        try:
            for route in (1, centre.SCHEME_ROUTE, 1, centre.SCHEME_ROUTE):
                window.show_section(route)
                settle()
                for combo in window.findChildren(QComboBox):
                    if combo.isVisible():
                        self.assert_styled(combo)
            output = ROOT / '.codex-tmp'
            output.mkdir(exist_ok=True)
            for route, name, combo in (
                (1, 'material', window.material_combo),
                (centre.SCHEME_ROUTE, 'status', window.quote_scheme_status_filter),
            ):
                window.show_section(route)
                settle()
                combo.showPopup()
                settle()
                self.assert_styled(combo)
                self.assertTrue(combo.view().isVisible())
                pixmap = combo.view().window().grab()
                self.assertFalse(pixmap.isNull())
                path = output / f"dropdown-style-{os.environ.get('QT_SCALE_FACTOR', '1')}-{name}.png"
                self.assertTrue(pixmap.save(str(path)))
                print(f'SCREENSHOT {path}', flush=True)
                combo.hidePopup()
        finally:
            for worker in list(getattr(window, '_quote_scheme_workers', [])):
                worker.wait(2000)
            window._quote_scheme_save_timer.stop()
            window._scheme2_dirty = False
            window.close()
            window.deleteLater()
            settle()

    def test_installation_is_idempotent_and_repeated_dynamic_dialogs_survive_gc(self):
        self.assertIs(install_combo_popup_style(), install_combo_popup_style())
        for _ in range(12):
            combo = self.combo()
            combo.showPopup()
            settle()
            self.assert_styled(combo)
            combo.hidePopup()
            self.layout.removeWidget(combo)
            combo.deleteLater()
            settle()
            gc.collect()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
