"""Real Qt product selection, request transport and saved-item restoration; offline."""
import copy
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
import v3_launcher
import jc_profiles
import layout_refresh
import scheme2_ui

# No live requests, including accidental background tasks.
def offline(*args, **kwargs):
    raise AssertionError('JC regression must not access a network')
socket.socket.connect = socket.socket.connect_ex = offline
app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei', 10))
ns = v3_launcher.load_v3_namespace()
Window = ns['MainWindow']
Window.load_catalogs = lambda self: None
Window.request_history_match = lambda *args: None
Window.refresh_formula_inputs = lambda *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline JC regression')
CASES = json.loads((ROOT / 'tests/fixtures/jc_profiles.json').read_text(encoding='utf-8'))
CATALOG = {'items': [
    {'product_code': 'JC_EXP', 'product_name': 'JC', 'product_method': 'experience',
     'default_width_mm': 600, 'default_height_mm': 1600, 'default_depth_mm': 600,
     'models': [{'model_code': row['model']} for row in CASES]},
    {'product_code': 'JA_SINGLE', 'product_name': 'JA', 'product_method': 'formula'}]}


class JcProfiles(unittest.TestCase):
    def setUp(self):
        for module in (layout_refresh, scheme2_ui):
            fit = patch.object(module, '_fit_window_minimum_to_screen', lambda window: None)
            fit.start()
            self.addCleanup(fit.stop)
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window.show_error = lambda message: setattr(self.window, '_test_error', message)
        self.window.product_catalog_loaded(copy.deepcopy(CATALOG))
        self.messages = []
        self.modal_guard = QTimer()
        def dismiss():
            for widget in app.topLevelWidgets():
                if isinstance(widget, QMessageBox) and widget.isVisible():
                    self.messages.append(widget.text())
                    widget.accept()
        self.modal_guard.timeout.connect(dismiss)
        self.modal_guard.start(25)
        self.addCleanup(self.close)

    def close(self):
        self.modal_guard.stop()
        worker = getattr(self.window, 'worker', None)
        if worker is not None and worker.isRunning():
            worker.wait(5000)
        self.window._scheme2_dirty = False
        self.window.close()

    def choose(self, label):
        combo = self.window.product_combo
        index = combo.findData(label)
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)
        combo.activated.emit(index)

    def test_two_choices_and_filtered_models(self):
        w = self.window
        self.assertEqual(w.product_combo.findData('JC'), -1)
        for profile, label in jc_profiles.LABELS.items():
            self.choose(label)
            self.assertEqual(w.selected_product_code(), 'JC_EXP')
            self.assertEqual(w.selected_variant_code(), profile)
            self.assertIn(label[3:], w.selected_variant_name())
            models = w.product_catalog[label]['models']
            self.assertEqual({row['model_code'] for row in models},
                             {row['model'] for row in CASES if row['profile'] == profile})
            self.assertEqual(layout_refresh._product_code_for_door_counts(w, 0, 1), ('JC_EXP', profile))
            if folder := os.environ.get('AI_QUOTE_JC_QA_OUTPUT'):
                Path(folder).mkdir(parents=True, exist_ok=True)
                w.show_section(scheme2_ui.OPTION_ROUTE)
                w.showNormal()
                w.resize(1440, 900)
                QTest.qWait(30)
                w.grab().save(str(Path(folder) / f'jc-{profile.lower()}.png'))

    def test_reload_retains_explicit_choice_without_duplicates(self):
        self.choose('JC 豪华型')
        for _ in range(2):
            self.window.product_catalog_loaded(copy.deepcopy(CATALOG))
            self.assertEqual(self.window.product_combo.currentData(), 'JC 豪华型')
            self.assertEqual(self.window.product_combo.count(), 4)

    def test_each_face_model_restores_its_type_without_mutating_history(self):
        for row in CASES:
            item = {'product_code': 'JC_EXP', 'product_family': 'JC', 'model_code': row['model'],
                    'width_mm': 600, 'height_mm': 1600, 'depth_mm': row['depth'],
                    'quantity': 1, 'material_code': 'SECC', 'quick': {'base_price': 1234.56},
                    'coating_type': '橘纹', 'variant_code': 'DEFAULT',
                    'formula_discount': 1, 'quick_discount': 0.5,
                    'formula': {}, 'attachments': []}
            before = copy.deepcopy(item)
            self.window.load_draft_item(item)
            self.assertEqual(self.window.product_combo.currentData(), row['label'])
            self.assertEqual(self.window._persistent_product_selection, row['label'])
            self.assertEqual(item, before)

    def test_unknown_old_jc_requires_explicit_selection(self):
        self.choose('JC 豪华型')
        jc_profiles.select_item_profile(self.window, {'product_code': 'JC_EXP', 'variant_code': 'DEFAULT'})
        self.assertIsNone(self.window.product_combo.currentData())
        self.assertIn('明确选择', self.window.risk_label.text())

    def test_added_row_label_retains_type_when_next_product_changes(self):
        self.choose('JC 标配型')
        item = {'product_code': 'JC_EXP', 'quick': {}, 'formula': {}}
        scheme2_ui._stamp_selected_product(self.window, item)
        self.choose('JC 豪华型')
        self.assertEqual(scheme2_ui._row_values(item)[2], 'JC 标配型')
        self.assertEqual(item['product_code'], 'JC_EXP')

    def test_real_calculate_dispatches_explicit_profile(self):
        w = self.window
        for row in CASES:
            self.choose(row['label'])
            w.width_spin.setValue(600)
            w.height_spin.setValue(1600)
            w.depth_spin.setValue(row['depth'])
            w.model_edit.setText(row['model'])
            w.quote_spec_edit.setText(f"600*{row['depth']}*1600")
            w.calculate()
            worker = getattr(w, 'worker', None)
            self.assertIsNotNone(worker, str(self.messages) + getattr(w, '_test_error', 'no worker'))
            worker.wait(5000)
            QTest.qWait(30)
            self.assertEqual(worker.payload['product_code'], 'JC_EXP')
            self.assertEqual(worker.payload['variant_code'], row['profile'])
            self.assertEqual(worker.payload['model_code'], row['model'])


if __name__ == '__main__':
    unittest.main()
