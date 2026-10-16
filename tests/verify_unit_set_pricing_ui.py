"""Offline recovered-client contracts for unit/set accessories and monetary totals."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import scheme2_ui as ui
import layout_refresh
import quick_discount_rules as pricing
import v3_launcher

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns = v3_launcher.load_v3_namespace()
ns['install_application_font'](app)
Window = ns['MainWindow']
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline unit-set test')


def product(quantity=1):
    return dict(name='测试柜', product_code='JP', specification='800*600*1800',
        material_code='SECC', width_mm=800, height_mm=1800, depth_mm=600,
        coating_type='橘纹', quote_date='2026-10-16', quantity=quantity, quick_discount=1,
        freight_fee=3, attachments=[dict(item_name='JP控制柜侧板', attachment_price_id=101,
            quantity=1, quick_amount=12, matched_price=10, formula_amount=5, formula_unit_cost=5)],
        quick=dict(base_price=100, attachment_fee=12, total_cost=112),
        formula=dict(attachment_fee=5, total_cost=65))


class UnitSetPricing(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.addCleanup(self.window.close)
        self.item = product(10)
        self.window.draft_items = [self.item]
        self.window.refresh_summary()

    def editor(self, item=None):
        dialog = ui.AttachmentEditor(self.window, item or self.item)
        self.addCleanup(dialog.close)
        return dialog

    def test_new_column_and_batch_quantity_do_not_change_unit_set_popup(self):
        table = self.window.summary_table
        self.assertEqual(ui.HEADERS[5:8], ('已选附件', '附件面价', '面价'))
        face = ui.HEADERS.index('附件面价')
        self.assertEqual(table.item(0, face).text(), '12.00')
        self.assertFalse(table.item(0, face).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(table.item(1, face).text(), '—')
        before = copy.deepcopy(self.item['attachments'])
        table.item(0, ui.HEADERS.index('数量')).setText('20')
        dialog = self.editor()
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_QUANTITY).value(), 1)
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_AMOUNT).value(), 12)
        self.assertEqual(dialog.table.item(0, dialog.COL_FORMULA_AMOUNT).text(), '5.00')
        self.assertEqual(self.item['attachments'], before)
        self.assertEqual(ui._row_values(self.item)[16], 115 * 20)

    def test_attachment_own_quantity_still_scales_cost_and_amount_for_a_complete_ganged_set(self):
        self.item.update(ganged_cabinet_count=4, ganged_cabinets=[{}] * 4)
        dialog = self.editor()
        dialog.table.cellWidget(0, dialog.COL_QUANTITY).setValue(10)
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_AMOUNT).value(), 120)
        self.assertEqual(dialog.table.item(0, dialog.COL_FORMULA_AMOUNT).text(), '50.00')
        dialog.accept()
        self.assertEqual(self.item['quantity'], 10)
        self.assertEqual(self.item['attachments'][0]['quantity'], 10)
        self.assertEqual(self.item['attachments'][0]['quick_amount'], 120)
        self.assertEqual(ui._row_values(self.item)[23], 120)
        self.assertEqual(ui._row_values(self.item)[15:17], (223, 2230))

    def test_manual_amount_and_zero_survive_reopening_without_batch_division(self):
        dialog = self.editor()
        dialog.table.cellWidget(0, dialog.COL_AMOUNT).setValue(77.77)
        dialog.accept()
        self.assertEqual(self.item['attachments'][0]['quick_amount_override'], 77.77)
        self.assertEqual(self.item['attachments'][0]['formula_amount'], 5)
        reopened = self.editor()
        self.assertEqual(reopened.table.cellWidget(0, reopened.COL_AMOUNT).value(), 77.77)
        reopened.table.cellWidget(0, reopened.COL_AMOUNT).setValue(0)
        reopened.accept()
        self.assertEqual(ui._row_values(self.item)[23], 0)
        self.assertEqual(self.item['attachments'][0]['quick_amount_override'], 0)

    def test_repeated_quantity_changes_do_not_compound_rounding(self):
        self.item['attachments'] = [dict(custom=True, item_name='临时附件', quantity=3,
            quick_amount=1, formula_amount=1, custom_amount_edited=True, quick_amount_override=1)]
        dialog = self.editor()
        quantity = dialog.table.cellWidget(0, dialog.COL_QUANTITY)
        quantity.setValue(2)
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_AMOUNT).value(), .67)
        quantity.setValue(3)
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_AMOUNT).value(), 1)
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_FORMULA_AMOUNT).value(), 1)

    def test_pending_reprice_blocks_confirmation_and_ignores_superseded_callback(self):
        callbacks = []
        self.window.recalculate_draft_attachment = lambda item, source, ok, fail: callbacks.append((ok, fail))
        dialog = self.editor()
        source = copy.deepcopy(self.item['attachments'][0])
        dialog._reprice_row(0, source)
        self.assertFalse(dialog.table.cellWidget(0, dialog.COL_QUANTITY).isEnabled())
        with patch.object(ui.QMessageBox, 'warning') as warning:
            dialog.accept()
            warning.assert_called_once()
        self.assertEqual(dialog.result(), 0)
        dialog._reprice_row(0, source)
        callbacks[0][0]({**source, 'quick_amount': 99})
        self.assertFalse(dialog.table.cellWidget(0, dialog.COL_QUANTITY).isEnabled())
        callbacks[1][0]({**source, 'quick_amount': 15})
        self.assertTrue(dialog.table.cellWidget(0, dialog.COL_QUANTITY).isEnabled())
        self.assertEqual(dialog.table.cellWidget(0, dialog.COL_AMOUNT).value(), 15)
        dialog.accept()
        self.assertEqual(self.item['attachments'][0]['quick_amount'], 15)

    def test_manual_summary_price_is_pre_discount_and_only_changes_its_members(self):
        other = copy.deepcopy(self.item)
        other['material_code'] = 'SUS304'
        other['attachments'][0]['formula_amount'] = 8
        self.window.draft_items.append(other)
        self.window.refresh_summary()
        dialog = ui.AttachmentSummaryDialog(self.window)
        self.addCleanup(dialog.close)
        dialog.table.cellWidget(0, 5).setValue(30)
        self.assertEqual(self.item['attachments'][0]['quick_amount'], 30)
        self.assertEqual(other['attachments'][0]['quick_amount'], 12)
        self.assertEqual(dialog.table.item(0, 4).text(), '300.00')
        self.assertEqual(self.item['attachments'][0]['formula_amount'], 5)
        self.assertEqual(ui._row_values(self.item)[23], 30)

    def test_half_up_unit_price_before_quantity_and_footer_matches_visible_lines(self):
        self.window.draft_items = [dict(product(10), attachments=[],
            quick={'base_price': 12.34, 'total_cost': 12.34}, quick_discount=.1, freight_fee=0),
            dict(product(3), attachments=[], quick={'base_price': 10.05, 'total_cost': 10.05},
                 quick_discount=.1, freight_fee=0)]
        self.window.refresh_summary()
        col = ui.HEADERS.index('报价总价')
        self.assertEqual(self.window.summary_table.item(0, col).text(), '12.30')
        self.assertEqual(self.window.summary_table.item(1, col).text(), '3.03')
        self.assertEqual(self.window.summary_table.item(2, col).text(), '15.33')
        self.assertEqual(pricing.money('1.005'), 1.01)
        self.assertEqual(pricing.money('-1.005'), -1.01)
        self.assertEqual(self.window.scheme2_quote_preview.item(10, 5).text(), '1.23')

    def test_material_surcharge_added_once_and_quote_unit_edit_deducts_fixed_amounts(self):
        self.item.update(material_code='SUS316', scheme2_cost_settings={'material_difference': 2})
        self.item['formula']['corrected_material_weight_kg'] = 1
        self.item['attachments'][0]['item_name'] = '铜排'
        self.window.refresh_summary()
        self.assertEqual(ui._row_values(self.item)[13], 117)
        self.window.scheme2_quote_preview.item(10, 5).setText('67.00')
        self.assertEqual(self.item['quick_discount'], .5)
        self.assertEqual(ui._row_values(self.item)[15:17], (67, 670))

    def test_negative_quantity_only_installation_board_and_no_double_multiplication(self):
        self.item['attachments'][0].update(item_name='安装板', quick_amount=20, formula_amount=5)
        dialog = self.editor()
        dialog.table.cellWidget(0, dialog.COL_QUANTITY).setValue(-2)
        dialog.accept()
        row = self.item['attachments'][0]
        self.assertEqual(row['quantity'], 2)
        self.assertEqual(row['attachment_price_sign'], -1)
        self.assertEqual(ui._row_values(self.item)[23], -40)
        other = self.editor(product())
        self.assertEqual(other.table.cellWidget(0, other.COL_QUANTITY).minimum(), 1)

    def test_export_freezes_exact_ui_prices_and_detects_stale_screen(self):
        frozen = ui._quote_export_items_snapshot(self.window)
        self.assertEqual(frozen[0]['pricing_basis'], pricing.PRICING_BASIS)
        self.assertEqual(frozen[0]['quote_display']['attachment_face_price'], 12)
        self.assertEqual(frozen[0]['quote_display']['total'], 1150)
        self.window._scheme2_refreshing_quote = True
        self.window.scheme2_quote_preview.item(10, 6).setText('999.00')
        self.window._scheme2_refreshing_quote = False
        with self.assertRaisesRegex(ValueError, '第1行'):
            ui._quote_export_items_snapshot(self.window)

    def test_save_reload_and_copy_keep_basis_and_independent_per_set_attachments(self):
        self.item['pricing_basis'] = pricing.PRICING_BASIS
        payload = ui._order_workspace_payload(self.window)
        self.assertEqual(payload['pricing_basis'], pricing.PRICING_BASIS)
        ui._apply_order_workspace_payload(self.window, payload, 'offline restore')
        self.assertEqual(self.window.draft_items[0]['attachments'][0]['quantity'], 1)
        self.window.summary_table.selectRow(0)
        ui._duplicate_selected(self.window)
        self.window.draft_items[1]['attachments'][0]['quick_amount'] = 7
        self.assertEqual(self.window.draft_items[0]['attachments'][0]['quick_amount'], 12)

    def test_real_cost_page_shows_attachment_face_next_to_attachment_count(self):
        with patch.object(ui, '_fit_window_minimum_to_screen', lambda window: None), \
             patch.object(layout_refresh, '_fit_window_minimum_to_screen', lambda window: None):
            self.window.setMinimumSize(1, 1)
            self.window.resize(1500, 900)
            self.window.show()
            self.window.show_section(ui.COST_ROUTE)
            self.window.refresh_summary()
            QTest.qWait(60)
            table = self.window.summary_table
            self.assertFalse(table.isColumnHidden(6))
            self.assertEqual(table.columnViewportPosition(6),
                             table.columnViewportPosition(5) + table.columnWidth(5))
            self.assertEqual(table.item(0, 6).text(), '12.00')
            self.assertEqual(table.item(0, 11).text(), '1,150.00')
            self.assertLess(table.columnViewportPosition(6) + table.columnWidth(6), table.viewport().width())
            output = ROOT / 'outputs' / 'unit-set-attachment-face-price.png'
            self.assertTrue(self.window.grab().save(str(output)))

    def test_actual_ui_snapshot_survives_server_hydration_and_excel_roundtrip(self):
        self.item.update(attachment_contract=2, quote_line_id='11111111-1111-4111-8111-111111111111')
        self.item['attachments'][0].update(catalog_version='test', status='OK')
        self.item['attachments'][0].update(quick_amount=15, quick_amount_override=15, custom_amount_edited=True)
        self.item['quick'].update(attachment_fee=15, total_cost=115)
        self.window.refresh_summary()
        frozen = ui._quote_export_items_snapshot(self.window)
        environment = {key: self.item[key] for key in ('product_code', 'material_code', 'width_mm', 'height_mm',
                       'depth_mm', 'coating_type', 'quote_date')}
        environment['quote_result'] = {'formula_cost': product()['formula'], 'quick_quote': product()['quick']}
        saved_row = dict(self.item['attachments'][0], quick_amount=12,
                         attachment_selection_id='22222222-2222-4222-8222-222222222222',
                         quote_line_id=self.item['quote_line_id'])
        saved_row.pop('custom_amount_edited')
        saved_row.pop('quick_amount_override')
        request = dict(payload={'items': frozen}, snapshots={self.item['quote_line_id']:
                       dict(environment=environment, attachments=[saved_row])})
        def hydrate(body):
            return subprocess.run(['node', 'tests/attachment_export_snapshot_bridge.mjs'], cwd=ROOT,
                input=json.dumps(body), text=True, encoding='utf-8', capture_output=True)
        response = hydrate(request)
        self.assertEqual(response.returncode, 0, response.stderr)
        body = json.loads(response.stdout)
        self.assertEqual(body['items'][0]['quick']['attachment_fee'], 15)
        self.assertEqual(body['items'][0]['attachments'][0]['formula_amount'], 5)
        bad = copy.deepcopy(request)
        bad['payload']['items'][0]['quote_display']['total'] = 1
        self.assertNotEqual(hydrate(bad).returncode, 0)
        with tempfile.TemporaryDirectory(dir=ROOT/'outputs', prefix='unit-set-export-') as directory:
            # Test artifacts are disposable, not an application build/install.
            payload = Path(directory)/'quote.json'
            payload.write_text(json.dumps(body), encoding='utf-8')
            workbook = Path(directory)/'quote.xlsx'
            export = subprocess.run(['node', 'export_dual_quote_workbook.mjs', str(payload), str(workbook)],
                cwd=ROOT, text=True, encoding='utf-8', capture_output=True)
            self.assertEqual(export.returncode, 0, export.stderr)
            result = subprocess.run(['node', '--input-type=module', '-e',
                "import ExcelJS from '@excel.js/exceljs'; const w=new ExcelJS.Workbook();"
                "await w.xlsx.readFile(process.argv[1]);const s=w.getWorksheet('快速报价单');"
                "console.log(JSON.stringify([s.getCell('F11').value,s.getCell('G11').value,s.getCell('G12').value,"
                "s.getCell('J11').value.result,s.getCell('K11').value.result,"
                "s.getCell('K10').value,s.getCell('K11').value.formula]));",
                str(workbook)], cwd=ROOT, text=True, encoding='utf-8', capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [118, 1180, 1180, 118, 1180,
                                                       '原价总价', 'ROUND(J11*D11,2)'])


if __name__ == '__main__':
    unittest.main()
