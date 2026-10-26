"""Offline real-Qt dialog appearance and unchanged action/keyboard semantics."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QInputDialog,
    QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from dialog_style import DIALOG_COLORS, install_dialog_style, style_dialog
import scheme2_ui as ui
import layout_refresh
import v3_launcher

APP = QApplication.instance() or QApplication([])
APP.setStyle('Fusion')
NS = v3_launcher.load_v3_namespace()
NS['install_application_font'](APP)
NS['MainWindow'].load_catalogs = lambda self: None
NS['MainWindow'].refresh_formula_inputs = lambda self, *args: None
NS['ApiWorker'].run = lambda self: self.failed.emit('offline dialog test')
install_dialog_style()
CAPTURE = Path(os.environ['DIALOG_STYLE_CAPTURE']) if os.environ.get('DIALOG_STYLE_CAPTURE') else None


def settle():
    for _ in range(4):
        APP.processEvents()


def capture(dialog, name):
    settle()
    if CAPTURE:
        CAPTURE.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(CAPTURE / f'{name}.png'))


class DialogStyleTests(unittest.TestCase):
    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget, QDialog):
                widget.hide()
                widget.deleteLater()
        settle()

    def assert_theme(self, dialog):
        self.assertTrue(dialog.property('unifiedDialog'))
        self.assertTrue(dialog.isVisible())
        self.assertIn('Microsoft YaHei UI', dialog.styleSheet())
        self.assertIn(DIALOG_COLORS['header'], dialog._unified_dialog_header.styleSheet())
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)

    def test_static_question_keeps_default_no_and_return_value(self):
        observed = []
        def respond():
            box = APP.activeModalWidget()
            try:
                self.assertIsInstance(box, QMessageBox)
                self.assert_theme(box)
                self.assertEqual(box.defaultButton(), box.button(QMessageBox.No))
                self.assertEqual(box.button(QMessageBox.Yes).text(), '确定')
                self.assertEqual(box.button(QMessageBox.No).text(), '取消')
                self.assertEqual(box.button(QMessageBox.Yes).property('dialogActionRole'), 'danger')
                self.assertEqual(box.button(QMessageBox.No).property('dialogActionRole'), 'secondary')
                capture(box, 'void-confirmation')
            except Exception as error:
                observed.append(error)
            finally:
                QTest.keyClick(box, Qt.Key.Key_Return)
        QTimer.singleShot(40, respond)
        result = QMessageBox.question(None, '作废', '确认作废方案 BJ-20261019-000004？该操作将记录审计信息。',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        self.assertFalse(observed, str(observed))
        self.assertEqual(result, QMessageBox.No)

    def test_message_accept_escape_close_and_reopen(self):
        box = QMessageBox(QMessageBox.Information, '提示', '报价单已生成。', QMessageBox.Ok | QMessageBox.Cancel)
        box.show()
        settle()
        self.assert_theme(box)
        initial = box.styleSheet()
        for _ in range(3):
            box.hide()
            box.show()
            settle()
        self.assertEqual(initial, box.styleSheet())
        self.assertEqual(len(box.findChildren(QLabel, 'unifiedDialogTitle')), 1)
        QTest.keyClick(box, Qt.Key.Key_Escape)
        self.assertEqual(box.result(), QMessageBox.Cancel)
        box.show()
        settle()
        box.button(QMessageBox.Ok).click()
        self.assertEqual(box.result(), QMessageBox.Ok)
        box.show()
        settle()
        box.findChild(QWidget, 'unifiedDialogClose').click()
        self.assertEqual(box.result(), QMessageBox.Cancel)

    def test_error_details_and_custom_retry_are_preserved(self):
        box = QMessageBox(QMessageBox.Warning, '报价处理失败详情', '附件数据不完整，请补全后重试。')
        retry = box.addButton('重试生成', QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.setDetailedText('测试详情\n' * 30)
        box.show()
        settle()
        self.assert_theme(box)
        self.assertEqual(retry.text(), '重试生成')
        details = next(button for button in box.findChildren(QPushButton) if '...' in button.text() or '…' in button.text())
        details.click()
        settle()
        self.assertTrue(box.isVisible())
        self.assertTrue(box.findChild(QLabel, 'unifiedDialogTitle').isVisible())
        capture(box, 'error-details')
        retry.click()
        self.assertIs(box.clickedButton(), retry)

    def test_generic_input_and_file_dialog_keep_modes_and_values(self):
        dialog = QInputDialog()
        dialog.setWindowTitle('输入名称')
        dialog.setLabelText('方案名称')
        dialog.setTextValue('测试名称')
        dialog.show()
        settle()
        self.assert_theme(dialog)
        self.assertEqual(dialog.textValue(), '测试名称')
        capture(dialog, 'input')
        dialog.reject()
        file = QFileDialog(None, '导出报价单')
        file.setAcceptMode(QFileDialog.AcceptSave)
        file.setNameFilter('Excel 工作簿 (*.xlsx)')
        file.setDefaultSuffix('xlsx')
        file.show()
        settle()
        self.assert_theme(file)
        self.assertEqual(file.acceptMode(), QFileDialog.AcceptSave)
        self.assertEqual(file.defaultSuffix(), 'xlsx')
        self.assertIn('*.xlsx', file.nameFilters()[0])
        self.assertTrue(APP.testAttribute(Qt.AA_DontUseNativeDialogs))
        capture(file, 'file-export')
        file.reject()

    def test_existing_dimension_validation_and_unsaved_confirmation(self):
        dimension = ui._SchemeDimensionEditor(None, '输入尺寸', ['宽度'], {'宽度': ''})
        dimension.show()
        settle()
        self.assertTrue(dimension.property('unifiedDialog'))
        self.assertFalse(dimension.confirm_button.isEnabled())
        dimension.fields['宽度'].setText('600')
        self.assertTrue(dimension.confirm_button.isEnabled())
        self.assertEqual(dimension.values(), {'宽度': 600})
        capture(dimension, 'dimension')
        confirm = ui._SchemeConfirmDialog(None, '有未保存变更', '当前配置尚未加入报价清单，关闭后将丢失本次填写的内容。', '放弃更改并关闭')
        confirm.show()
        settle()
        self.assertEqual(confirm.accept_button.property('dialogActionRole'), 'danger')
        self.assertFalse(confirm.accept_button.autoDefault())
        self.assertFalse(confirm.reject_button.autoDefault())
        capture(confirm, 'unsaved')
        confirm.reject_button.click()
        self.assertEqual(confirm.result(), QDialog.Rejected)

    def test_history_buttons_and_install_are_idempotent(self):
        self.assertIs(install_dialog_style(), install_dialog_style())
        history = layout_refresh._HistoryOrderDialog('测试公司 · JA · 已确认订单')
        history.show()
        settle()
        primary = history.findChild(QPushButton, 'historyOrderPrimary')
        secondary = history.findChild(QPushButton, 'historyOrderSecondary')
        self.assertEqual(primary.property('dialogActionRole'), 'primary')
        self.assertEqual(secondary.property('dialogActionRole'), 'secondary')
        capture(history, 'history')
        primary.click()
        self.assertEqual(history.result(), QDialog.Accepted)

    def test_information_warning_and_error_share_chrome(self):
        for icon, title in ((QMessageBox.Information, '提示'), (QMessageBox.Warning, '请检查输入'),
                            (QMessageBox.Critical, '导出失败')):
            with self.subTest(title=title):
                box = QMessageBox(icon, title, '请检查信息后重试。', QMessageBox.Ok)
                box.show()
                settle()
                self.assert_theme(box)
                self.assertEqual(box.icon(), icon)
                self.assertEqual(box.button(QMessageBox.Ok).property('dialogActionRole'), 'primary')
                capture(box, f'message-{icon.name}')
                box.button(QMessageBox.Ok).click()
                self.assertEqual(box.result(), QMessageBox.Ok)

    def test_actual_current_client_attachment_and_discount_dialogs(self):
        window = NS['MainWindow']()
        try:
            self.assertIsNotNone(getattr(APP, '_unified_dialog_style_filter', None))
            item = json.loads((ROOT / 'tests/fixtures/export_formula_cost_detail.json').read_text('utf-8'))['items'][0]
            ui._quote_item_remark(item)
            before = copy.deepcopy(item)
            discount = ui.FaceDiscountEditor(window, item)
            discount.show()
            settle()
            self.assertTrue(discount.property('unifiedDialog'))
            capture(discount, 'face-discount')
            discount.reject()
            editor = ui.AttachmentEditor(window, item)
            editor.show()
            settle()
            self.assertTrue(editor.property('unifiedDialog'))
            capture(editor, 'selected-attachments')
            editor.reject()
            self.assertEqual(before, item)
        finally:
            window._scheme2_dirty = False
            window._quote_scheme_dirty_seq = window._quote_scheme_saved_seq
            window.hide()
            window.deleteLater()
            settle()


if __name__ == '__main__':
    unittest.main()
