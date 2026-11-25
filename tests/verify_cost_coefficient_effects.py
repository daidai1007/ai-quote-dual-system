"""Exercise every cost coefficient through the real modal and visible table."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import app, ui
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from thickness_surcharge import BASIS


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def cabinet(code='SUS316'):
    price = {'SECC': 4.2, 'SUS304': 16, 'SUS316': 32.4}[code]
    parts = [dict(part_name='柜体', material_code=code, billable_weight_kg=10,
                  material_unit_price=price, material_cost=money(10 * price)),
             dict(part_name='固定镀锌件', material_code='SGCC', billable_weight_kg=2,
                  material_unit_price=4.55, material_cost=9.1)]
    return dict(name='系数验证柜', product_code='JS', material_code=code, quantity=2,
        specification='800*600*1800', width_mm=800, depth_mm=600, height_mm=1800,
        cabinet_body_thickness_mm=1.5, waste_factor=1.2, labor_multiplier=1,
        coating_type='橘纹', quick_discount=.5, freight_fee=30, freight_mode='MANUAL',
        attachments=[], quick=dict(base_price=1000, attachment_fee=0, total_cost=1000),
        formula_base=dict(labor_cost=40),
        formula=dict(material_cost=money(10 * price + 9.1), auxiliary_cost=20,
            labor_cost=40, spray_cost=52, attachment_fee=0, corrected_material_weight_kg=12,
            product_area_m2=2, material_details=deepcopy(parts),
            cabinet_material_part_details=deepcopy(parts)))


class CostCoefficientEffects(unittest.TestCase):
    def setUp(self):
        fixture.CostCombinedLayout.setUp(self)
        self.addCleanup(lambda: setattr(self.window, '_scheme2_dirty', False))

    def prepare(self, code='SUS316', *, select=True):
        self.item = cabinet(code)
        self.window.draft_items = [self.item, cabinet('SECC')]
        self.window.refresh_summary()
        table = self.window.summary_table
        if select:
            table.selectRow(0)
        else:
            table.clearSelection()
            table.setCurrentCell(-1, -1)
        ui._sync_sidebar(self.window)
        return self.item

    def change(self, values, *, cancel=False):
        errors = []
        def interact():
            try:
                dialog = app.activeModalWidget()
                self.assertIsNotNone(dialog)
                for key, value in values.items():
                    control = dialog.controls[key]
                    self.assertTrue(control.isEnabled(), key)
                    control.setFocus()
                    control.selectAll()
                    QTest.keyClicks(control, str(value))
                    QTest.keyClick(control, Qt.Key.Key_Tab)
                    self.assertAlmostEqual(control.value(), value, places=4)
                name = 'scheme2CoefficientCancel' if cancel else 'scheme2CoefficientConfirm'
                QTest.mouseClick(dialog.findChild(QPushButton, name), Qt.MouseButton.LeftButton)
            except BaseException as error:
                errors.append(error)
                if dialog is not None:
                    dialog.reject()
        QTimer.singleShot(0, interact)
        self.window.scheme2_cost_edit_coefficients.click()
        app.processEvents()
        if errors:
            raise errors[0]

    def assert_visible(self, column, value):
        self.assertEqual(self.window.summary_table.item(0, column).text(), ui._money(value))
        label = self.window.scheme2_cost_selection_values.get(column)
        if label is not None:
            self.assertEqual(label.text(), ui._money(value))

    def assert_consistent(self):
        values = ui._row_values(self.item)
        self.assert_visible(10, values[15])
        self.assert_visible(11, money(values[15] * 2))
        self.assert_visible(12, values[17])
        self.assert_visible(20, money(values[17] * 2))
        self.assert_visible(ui.MANUFACTURING_COLUMN, money(values[15] * .04))
        self.assert_visible(18, money(values[15] * .05))
        snapshot = ui._quote_export_items_snapshot(self.window)[0]
        self.assertEqual(snapshot['quote_display']['unit_price'], values[15])
        self.assertEqual(snapshot['quote_display']['total'], money(values[15] * 2))
        self.assertEqual(ui._row_values(snapshot)[17], values[17])

    def test_four_material_prices_update_costs_without_changing_other_row(self):
        cases = [('SUS316', 'galvanized_price', 9.1, 342.2),
                 ('SECC', 'carbon_price', 5.2, 61.1),
                 ('SUS304', 'stainless_304_price', 20, 209.1),
                 ('SUS316', 'stainless_316_price', 40, 409.1)]
        for code, key, price, expected in cases:
            with self.subTest(coefficient=key):
                self.prepare(code)
                other = deepcopy(self.window.draft_items[1])
                self.change({key: price})
                self.assert_visible(13, expected)
                self.assertEqual(self.window.draft_items[1], other)
                self.assert_consistent()

    def test_material_difference_updates_surcharge_quote_expenses_and_snapshot(self):
        self.prepare()
        self.change({'material_difference': 35})
        self.assert_visible(ui.MATERIAL_DIFFERENCE_COLUMN, 350)
        self.assert_visible(10, 880)
        self.assert_consistent()
        self.change({'material_difference': 0})
        self.assert_visible(ui.MATERIAL_DIFFERENCE_COLUMN, 0)
        self.assert_visible(10, 530)

    def test_waste_factor_updates_weight_material_and_surcharge_without_compounding(self):
        self.prepare()
        for factor, material, difference in ((1.5, 416.38, 312.5), (1.2, 333.1, 250)):
            self.change({'waste_factor': factor})
            self.assert_visible(13, material)
            self.assert_visible(ui.MATERIAL_DIFFERENCE_COLUMN, difference)
            self.assert_consistent()

    def test_labor_and_surface_update_cached_cost_details(self):
        self.prepare()
        ui._detail_rows(self.item)
        self.change({'labor_discount': .8, 'surface_price': 30})
        self.assert_visible(15, 32)
        self.assert_visible(17, 60)
        self.assert_consistent()
        self.change({'labor_discount': .5, 'surface_price': 0})
        self.assert_visible(15, 20)
        self.assert_visible(17, 0)
        self.change({'surface_price': 26})
        self.assert_visible(17, 52)

    def test_labor_only_invalidates_existing_detail_rows(self):
        self.prepare()
        ui._detail_rows(self.item)
        self.change({'labor_discount': .5})
        rows = ui._detail_rows(self.item)
        labor = [row for row in rows if row['category'] == 'labor_cost']
        self.assertEqual(money(sum(row['base_amount'] * row.get('factor', 1) for row in labor)), 20)

    def test_thickness_coefficient_uses_current_weight_difference(self):
        self.prepare()
        self.item['cabinet_body_thickness_mm'] = 2
        self.item['formula']['thickness_comparison'] = dict(basis=BASIS,
            selected_cost_weight_kg=12, reference_cost_weight_kg=10, waste_factor=1.2)
        self.window.refresh_summary()
        self.change({ui.THICKNESS_COEFFICIENT_KEY: 15})
        self.assertEqual(ui.thickness_surcharge_amount(self.item), 30)
        self.assert_visible(ui.MATERIAL_DIFFERENCE_COLUMN, 280)
        self.assert_visible(10, 810)
        self.assert_consistent()

    def test_no_selected_row_does_not_silently_edit_only_future_defaults(self):
        self.prepare(select=False)
        self.change({'material_difference': 35})
        self.assert_visible(ui.MATERIAL_DIFFERENCE_COLUMN, 350)
        self.assertEqual(ui._selected_row(self.window), 0)

    def test_cancel_leaves_quotes_and_defaults_unchanged(self):
        self.prepare()
        before = deepcopy(self.window.draft_items)
        defaults = deepcopy(self.window.scheme2_defaults)
        self.change({'material_difference': 35, 'labor_discount': .8}, cancel=True)
        self.assertEqual(self.window.draft_items, before)
        self.assertEqual(self.window.scheme2_defaults, defaults)

    def test_repeated_labor_edit_without_legacy_base_is_not_compounded(self):
        self.prepare()
        self.item.pop('formula_base')
        self.change({'labor_discount': .8})
        self.change({'labor_discount': .5})
        self.assert_visible(15, 20)

    def test_material_difference_does_not_surcharge_other_materials(self):
        for code in ('SECC', 'SUS304'):
            with self.subTest(material=code):
                self.prepare(code)
                before = ui._row_values(self.item)[15]
                self.change({'material_difference': 35})
                self.assertEqual(ui._material_difference_amount(self.item), 0)
                self.assert_visible(10, before)

    def test_ganged_labor_and_surface_details_follow_the_changed_coefficients(self):
        self.prepare()
        formula = self.item['formula']
        child = deepcopy(formula)
        formula['ganged_cabinet_costs'] = [dict(cabinet_index=index, formula_cost=deepcopy(child))
                                            for index in (1, 2)]
        for key in ('material_cost', 'auxiliary_cost', 'labor_cost', 'spray_cost',
                    'corrected_material_weight_kg', 'product_area_m2'):
            formula[key] *= 2
        for rows in (formula['material_details'], formula['cabinet_material_part_details']):
            for row in rows:
                row['billable_weight_kg'] *= 2
                row['material_cost'] *= 2
        self.item['formula_base']['labor_cost'] *= 2
        self.item.update(ganged_cabinet_count=2, ganged_cabinets=[{}, {}])
        self.window.refresh_summary()
        self.change({'labor_discount': .5, 'surface_price': 30})
        rows = ui._detail_rows(self.item)
        for category, expected in (('labor_cost', 40), ('spray_cost', 120)):
            actual = money(sum(row['base_amount'] * row.get('factor', 1)
                               for row in rows if row['category'] == category))
            self.assertEqual(actual, expected, category)

    def test_ganged_waste_factor_updates_child_material_details(self):
        self.prepare()
        formula = self.item['formula']
        child = deepcopy(formula)
        formula['ganged_cabinet_costs'] = [dict(cabinet_index=index, formula_cost=deepcopy(child))
                                            for index in (1, 2)]
        for key in ('material_cost', 'auxiliary_cost', 'labor_cost', 'spray_cost',
                    'corrected_material_weight_kg', 'product_area_m2'):
            formula[key] *= 2
        for rows in (formula['material_details'], formula['cabinet_material_part_details']):
            for row in rows:
                row['billable_weight_kg'] *= 2
                row['material_cost'] *= 2
        self.item['formula_base']['labor_cost'] *= 2
        self.item.update(ganged_cabinet_count=2, ganged_cabinets=[{}, {}])
        self.window.refresh_summary()
        self.change({'waste_factor': 1.5})
        self.assert_visible(13, 832.75)
        child = formula['ganged_cabinet_costs'][0]['formula_cost']
        self.assertEqual(child['corrected_material_weight_kg'], 15)
        rows = ui._detail_rows(self.item)
        self.assertEqual(money(sum(row['base_amount'] for row in rows
                                   if row['category'] == 'material_cost')), 832.75)

    def test_spray_detail_unit_price_follows_the_coefficient(self):
        self.prepare()
        self.item['formula']['spray_unit_price'] = 26
        self.item['formula']['cabinet_spray_part_details'] = [dict(part_name='柜体', total_area_m2=2)]
        self.change({'surface_price': 30})
        rows = [row for row in ui._detail_rows(self.item) if row['category'] == 'spray_cost']
        self.assertEqual([(row['unit_price'], row['base_amount']) for row in rows], [(30, 60)])

    def test_all_coefficients_in_one_confirmation_and_real_excel(self):
        self.prepare()
        self.item['cabinet_body_thickness_mm'] = 2
        self.item['formula']['thickness_comparison'] = dict(basis=BASIS,
            selected_cost_weight_kg=12, reference_cost_weight_kg=10, waste_factor=1.2)
        self.window.refresh_summary()
        self.change(dict(galvanized_price=9.1, carbon_price=5.2, stainless_304_price=20,
            stainless_316_price=40, material_difference=35, waste_factor=1.5,
            labor_discount=.8, surface_price=30, thickness_surcharge_coefficient=15))
        for column, amount in ((13, 522.75), (15, 32), (17, 60), (10, 1005),
                               (11, 2010), (12, 811.04), (20, 1622.08),
                               (ui.TAX_COST_COLUMN, 55.84)):
            self.assert_visible(column, amount)
        self.assert_consistent()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(os.environ.get('AI_QUOTE_COEFFICIENT_EVIDENCE_DIR', folder))
            output.mkdir(parents=True, exist_ok=True)
            source, xlsx = output / 'coefficient-payload.json', output / 'coefficient-quote.xlsx'
            source.write_text(json.dumps(dict(quote_id='OFFLINE-COEFFICIENT-TEST',
                company='合成系数测试客户', items=ui._quote_export_items_snapshot(self.window)),
                ensure_ascii=False), encoding='utf-8')
            result = subprocess.run(['node', str(fixture.ROOT / 'export_dual_quote_workbook.mjs'),
                str(source), str(xlsx)], cwd=fixture.ROOT, capture_output=True, text=True,
                encoding='utf-8', timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            with ZipFile(xlsx) as book:
                self.assertIsNone(book.testzip())
                wb = ET.fromstring(book.read('xl/workbook.xml'))
                rel = next(s for s in wb.findall('s:sheets/s:sheet', ns)
                    if s.get('name') == '报价').get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                target = next(r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))
                    if r.get('Id') == rel)
                sheet = ET.fromstring(book.read(target.lstrip('/') if target.startswith('/') else 'xl/' + target))
                for address, amount in (('F11', 1005), ('G11', 2010)):
                    self.assertEqual(float(sheet.find(f'.//s:c[@r="{address}"]/s:v', ns).text), amount)
            self.assertTrue(self.window.grab().save(str(output / 'coefficient-cost-table.png')))

    def test_automatic_freight_follows_weight_after_waste_edit(self):
        self.prepare()
        self.item.update(freight_mode='AUTO', freight_basis='self_made_weight_v1')
        self.window.refresh_summary()
        self.change({'waste_factor': 1.5})
        self.assert_visible(19, 15)
        self.assert_visible(ui.QUICK_FREIGHT_COLUMN, 15)
        self.assert_visible(10, 827.5)
        self.assert_consistent()

    def test_empty_list_edits_defaults_without_creating_quote_rows(self):
        self.window.draft_items = []
        self.window.refresh_summary()
        self.change({'material_difference': 35})
        self.assertEqual(self.window.scheme2_defaults['material_difference'], 35)
        self.assertEqual(self.window.draft_items, [])

    def test_coated_zero_price_can_be_restored_using_saved_area(self):
        self.prepare()
        self.item['scheme2_cost_settings']['surface_price'] = 0
        self.item['formula']['spray_cost'] = 0
        self.window.refresh_summary()
        self.change({'surface_price': 26})
        self.assert_visible(17, 52)

    def test_read_only_cannot_change_coefficients_or_history(self):
        self.prepare()
        self.window._quote_scheme_read_only = True
        self.addCleanup(lambda: setattr(self.window, '_quote_scheme_read_only', False))
        before = deepcopy(self.window.draft_items)
        with patch.object(ui._CostCoefficientDialog, 'exec', side_effect=AssertionError('opened read-only editor')):
            ui._show_cost_coefficients(self.window)
        self.assertEqual(self.window.draft_items, before)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # The recovered V3 installs process-global Qt filters. Keep independent
        # windows/closures from accumulating across an entire modal test suite,
        # and require each native process to exit successfully as well.
        names = unittest.defaultTestLoader.getTestCaseNames(CostCoefficientEffects)
        started, failed = time.monotonic(), []
        for name in names:
            case = f'CostCoefficientEffects.{name}'
            run = subprocess.run([sys.executable, __file__, case], capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=90)
            print(run.stdout, end='')
            print(run.stderr, end='')
            if run.returncode:
                failed.append((case, run.returncode))
        print(f'Ran {len(names)} tests in {time.monotonic() - started:.3f}s (isolated Qt processes)')
        print('FAILED ' + repr(failed) if failed else 'OK')
        raise SystemExit(1 if failed else 0)
    result = unittest.main(verbosity=2, exit=False)
    gc.collect()
    raise SystemExit(0 if result.result.wasSuccessful() else 1)
