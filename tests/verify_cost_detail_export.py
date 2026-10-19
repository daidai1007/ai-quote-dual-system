"""Offline Excel export equals the live cost-detail table, not a fresh quote."""
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
import cost_detail_export as exporter
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline cost detail export test')
NS = {'m': exporter.MAIN}


def item():
    return dict(name='测试订单', product_code='JA', material_code='SECC',
                specification='590*230*600', quantity=1, freight_fee=5,
                attachments=[dict(custom=True, item_name='人工附件', quantity=1,
                                  formula_amount=10, quick_amount=20)],
                quick={'total_cost': 500, 'attachment_fee': 20},
                formula=dict(material_cost=100, auxiliary_cost=20, labor_cost=50,
                             attachment_fee=10, spray_cost=30, total_cost=210,
                             cabinet_auxiliary_lines=[dict(item_name=f'辅材{i:02d}', internal_quantity=1,
                                                           unit='件', unit_price=1, line_total=1,
                                                           notes='备注完整保留') for i in range(20)]))


def cells(path):
    with ZipFile(path) as package:
        assert package.testzip() is None
        assert b'<Types xmlns="' in package.read('[Content_Types].xml')
        assert b'<Relationships xmlns="' in package.read('_rels/.rels')
        root = ET.fromstring(package.read('xl/worksheets/sheet1.xml'))
        styles = ET.fromstring(package.read('xl/styles.xml'))
    result = {}
    for cell in root.findall('.//m:sheetData/m:row/m:c', NS):
        result[cell.get('r')] = cell
    return result, root, styles


def text(cell):
    return ''.join(cell.find('m:is', NS).itertext()) if cell.get('t') == 'inlineStr' else cell.find('m:v', NS).text


class CostDetailExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cost-detail-export-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / '成本明细.xlsx'
        self.window = ns['MainWindow']()
        self.addCleanup(self.window.close)
        self.item = item()
        self.window.draft_items = [self.item]
        ui._show_detail(self.window, self.item)
        self.table = self.window.scheme2_detail_table

    def save(self):
        snapshot = ui._cost_detail_export_snapshot(self.window)
        exporter.write_cost_detail_xlsx(self.path, snapshot)
        return snapshot, cells(self.path)

    def test_every_header_row_total_and_meta_matches_current_table(self):
        before = copy.deepcopy(self.item)
        snapshot, (output, root, styles) = self.save()
        self.assertEqual(text(output['A1']), '成本明细')
        self.assertEqual(text(output['A2']), self.window.scheme2_detail_meta.text())
        self.assertEqual(len(root.findall('m:sheetData/m:row', NS)), self.table.rowCount() + 3)
        for column in range(11):
            self.assertEqual(text(output[f'{exporter._column(column + 1)}3']),
                             self.table.horizontalHeaderItem(column).text())
        for row_index, values in enumerate(snapshot['rows'], 4):
            for column, expected in enumerate(values):
                cell = output[f'{exporter._column(column + 1)}{row_index}']
                if column in exporter.NUMERIC_COLUMNS:
                    self.assertEqual(cell.get('t'), 'n')
                    self.assertEqual(Decimal(text(cell)), Decimal(expected.replace(',', '')))
                else:
                    self.assertEqual(text(cell), expected)
        self.assertEqual(self.item, before)
        self.assertEqual(root.find('m:sheetViews/m:sheetView/m:pane', NS).get('topLeftCell'), 'D4')
        self.assertEqual(root.find('m:pageSetup', NS).get('orientation'), 'landscape')
        self.assertEqual(len(styles.find('m:cellXfs', NS)), int(styles.find('m:cellXfs', NS).get('count')))
        self.assertTrue(all(cell.find('m:f', NS) is None for cell in output.values()))

    def test_pending_manual_factor_is_committed_and_zero_is_not_lost(self):
        factor = self.table.cellWidget(0, 8)
        factor.lineEdit().setText('1.25')
        factor.lineEdit().setModified(True)
        snapshot, (output, _, _) = self.save()
        self.assertEqual(self.item['cost_detail_rows'][0]['factor'], 1.25)
        self.assertEqual(text(output['I4']), '1.25')
        self.assertEqual(text(output['J4']), self.table.item(0, 9).text().replace(',', ''))
        factor.setValue(0)
        _, (output, _, _) = self.save()
        self.assertEqual(Decimal(text(output['I4'])), 0)
        self.assertEqual(Decimal(text(output['J4'])), 0)
        self.assertEqual(Decimal(text(output[f'J{self.table.rowCount() + 3}'])),
                         Decimal(self.table.item(self.table.rowCount() - 1, 9).text().replace(',', '')))

    def test_export_does_not_round_an_unedited_four_decimal_factor(self):
        factor = self.table.cellWidget(0, 8)
        factor.setValue(1.2345)
        self.assertFalse(factor.lineEdit().isModified())
        before = copy.deepcopy(self.item)
        snapshot, (output, _, _) = self.save()
        self.assertEqual(factor.value(), 1.2345)
        self.assertEqual(self.item, before)
        self.assertEqual(text(output['I4']), factor.text())
        self.assertEqual(text(output['J4']), '123.45')

    def test_negative_zero_precision_and_formula_like_text_are_literal(self):
        for column, value in ((1, '=SUM(A1:A9)'), (2, '0'), (3, '材料<公式>&\n完整说明'),
                              (4, '1,234.5678'), (6, '0.00'), (7, '-123.45'), (9, '-123.45')):
            self.table.item(0, column).setText(value)
        _, (output, _, styles) = self.save()
        self.assertEqual(output['B4'].get('t'), 'inlineStr')
        self.assertEqual(text(output['B4']), '=SUM(A1:A9)')
        self.assertEqual(text(output['D4']), '材料<公式>&\n完整说明')
        self.assertEqual(text(output['E4']), '1234.5678')
        self.assertEqual(text(output['G4']), '0.00')
        self.assertEqual(text(output['H4']), '-123.45')
        quantity_format = styles.find('m:cellXfs', NS)[int(output['E4'].get('s'))].get('numFmtId')
        self.assertEqual(quantity_format, '168')

    def test_button_exports_locally_without_confirming_or_repricing_order(self):
        before = copy.deepcopy(self.item)
        with patch.object(ui.QFileDialog, 'getSaveFileName', return_value=(str(self.path), '')), \
             patch.object(ui.QMessageBox, 'information') as success, \
             patch.object(ui.QMessageBox, 'warning') as warning, \
             patch.object(self.window, 'confirm_and_export') as quote_export, \
             patch.object(ui, '_detail_rows', side_effect=AssertionError('must not recalculate')):
            self.window.scheme2_detail_export.click()
            success.assert_called_once()
            warning.assert_not_called()
            quote_export.assert_not_called()
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.item, before)
        self.assertTrue(self.window.scheme2_detail_export.isEnabled())

    def test_cancel_creates_no_file_and_changes_no_order(self):
        before = copy.deepcopy(self.item)
        with patch.object(ui.QFileDialog, 'getSaveFileName', return_value=('', '')), \
             patch.object(ui, 'write_cost_detail_xlsx') as writer:
            self.window.scheme2_detail_export.click()
            writer.assert_not_called()
        self.assertEqual(self.item, before)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_locked_target_failure_keeps_old_file_and_removes_only_own_temp(self):
        self.path.write_bytes(b'previous file')
        with patch.object(exporter.os, 'replace', side_effect=PermissionError('file in use')):
            with self.assertRaises(PermissionError):
                self.save()
        self.assertEqual(self.path.read_bytes(), b'previous file')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        with patch.object(ui.QFileDialog, 'getSaveFileName', return_value=(str(self.path), '')), \
             patch.object(ui, 'write_cost_detail_xlsx', side_effect=PermissionError('file in use')), \
             patch.object(ui.QMessageBox, 'warning') as warning, self.assertLogs(ui.LOGGER, 'ERROR'):
            self.window.scheme2_detail_export.click()
            self.assertIn('关闭正在打开的同名文件', warning.call_args.args[2])
        self.assertTrue(self.window.scheme2_detail_export.isEnabled())

    def test_extension_normalization_checks_collision_and_cancel_keeps_file(self):
        self.path.write_bytes(b'previous file')
        with patch.object(ui.QFileDialog, 'getSaveFileName', return_value=(str(self.path.with_suffix('')), '')), \
             patch.object(ui.QMessageBox, 'question', return_value=ui.QMessageBox.StandardButton.No), \
             patch.object(ui, 'write_cost_detail_xlsx') as writer:
            self.window.scheme2_detail_export.click()
            writer.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b'previous file')

    def test_empty_detail_is_disabled_and_switching_orders_exports_current_one(self):
        second = item()
        second.update(name='第二个订单', product_code='JP', specification='(800+800)*600*2000')
        ui._show_detail(self.window, second)
        snapshot, _ = self.save()
        self.assertIn('第二个订单', snapshot['meta'])
        self.window.scheme2_close_detail()
        self.assertFalse(self.window.scheme2_detail_export.isEnabled())
        with patch.object(ui.QMessageBox, 'warning') as warning, \
             patch.object(ui.QFileDialog, 'getSaveFileName') as choose:
            ui._export_cost_detail(self.window)
            warning.assert_called_once()
            choose.assert_not_called()

    def test_ganged_child_labels_and_shared_attachment_are_not_flattened(self):
        ganged = item()
        child = {key: value for key, value in ganged['formula'].items()
                 if key not in ('cabinet_auxiliary_lines',)}
        child['attachment_fee'] = 0
        ganged['formula']['ganged_cabinet_costs'] = [
            dict(cabinet_index=1, model_code='800*600*2000', formula_cost=copy.deepcopy(child)),
            dict(cabinet_index=2, model_code='1000*600*2000', formula_cost=copy.deepcopy(child))]
        ui._show_detail(self.window, ganged)
        snapshot, (output, root, _) = self.save()
        types = [row[0] for row in snapshot['rows']]
        self.assertTrue(any(value.startswith('柜体1\n') for value in types))
        self.assertTrue(any(value.startswith('柜体2\n') for value in types))
        self.assertEqual(types.count('并柜附件'), 1)
        for index, row in enumerate(snapshot['rows'], 4):
            self.assertEqual(text(output[f'A{index}']), row[0])
            self.assertEqual(text(output[f'C{index}']), row[2])
        self.assertGreaterEqual(float(root.find('m:sheetData/m:row[@r="4"]', NS).get('ht')), 38)

    def test_visual_header_button_resize_and_generate_qa_workbook(self):
        screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        with patch.object(type(self.window), 'screen', return_value=screen):
            self.window.show()
            button = self.window.scheme2_detail_export
            for width, height in ((1024, 720), (1560, 900)):
                self.window.resize(width, height)
                app.processEvents()
                self.assertTrue(button.isVisible())
                self.assertGreater(button.width(), button.fontMetrics().horizontalAdvance(button.text()))
                self.assertLessEqual(button.geometry().right(), self.window.scheme2_detail_page.width())
            app.processEvents()
            target = ROOT / '.codex-tmp' / f'cost-detail-export-{os.environ.get("QT_SCALE_FACTOR", "1")}'
            target.mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.window.scheme2_detail_page.grab().save(str(target / 'page.png')))
            snapshot = ui._cost_detail_export_snapshot(self.window)
            exporter.write_cost_detail_xlsx(target / '成本明细.xlsx', snapshot)
            (target / 'expected.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
