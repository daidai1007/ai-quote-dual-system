"""Matched cabinet sizes come only from the saved price-lookup snapshot."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline matched-size test')


def match(width, depth, height):
    return dict(reference_width_mm=width, reference_depth_mm=depth, reference_height_mm=height)


def quote(matched=None, **overrides):
    item = dict(name='尺寸匹配测试', product_code='JE', specification='590*230*600', quantity=1,
                attachments=[], quick=dict(attachment_fee=0, total_cost=627.67,
                                          match_method='nearest', matched_experience=matched),
                formula=dict(total_cost=300), quick_discount=1)
    item.update(overrides)
    return item


class MatchedSizeTests(unittest.TestCase):
    def test_nearest_is_actual_snapshot_not_entered_specification(self):
        item = quote(match(600, 250, 600))
        before = copy.deepcopy(item)
        self.assertEqual(ui._attachment_summary_matched_size(item), '600*250*600')
        values = ui._attachment_summary_product_values(item, 1)
        self.assertEqual(values[2], '590*230*600')
        self.assertEqual(values[9], '600*250*600')
        self.assertAlmostEqual(sum(values[10:-1]), values[5])
        self.assertEqual(item, before)

    def test_exact_and_decimal_dimensions_keep_w_d_h_order(self):
        item = quote(match('590.00', '230.0', 600))
        item['quick']['match_method'] = 'exact'
        self.assertEqual(ui._attachment_summary_matched_size(item), item['specification'])
        item['quick']['matched_experience'] = match('1234.56789012', '300.12500', '2.0001E+3')
        self.assertEqual(ui._attachment_summary_matched_size(item), '1234.56789012*300.125*2000.1')

    def test_missing_or_invalid_history_never_invents_a_match(self):
        bad_matches = (None, [], '590*230*600', {}, {'items': []}, match(0, 300, 600),
                       match(-600, 300, 600), match('NaN', 300, 600),
                       match(600, float('inf'), 600), match(600, None, 600))
        for matched in bad_matches:
            with self.subTest(matched=matched):
                self.assertEqual(ui._attachment_summary_matched_size(quote(matched)), '—')
        self.assertEqual(ui._attachment_summary_matched_size({}), '—')

    def test_ganged_snapshot_keeps_order_duplicates_and_missing_children(self):
        item = quote({'ganged_cabinet_count': 4,
                      'items': [match(800, 600, 2000), match(600, 500, 1800),
                                match(800, 600, 2000), None]},
                     specification='(800+600+800+700)*600*(2000+100)')
        item['quick']['match_method'] = 'ganged_cabinet_sum'
        self.assertEqual(ui._attachment_summary_matched_size(item),
                         '柜体1：800*600*2000\n柜体2：600*500*1800\n柜体3：800*600*2000\n柜体4：—')
        restored = json.loads(json.dumps(item))
        self.assertEqual(ui._attachment_summary_matched_size(restored),
                         ui._attachment_summary_matched_size(item))

    def make_dialog(self, items):
        window = ns['MainWindow']()
        self.addCleanup(window.close)
        window.draft_items = items
        window.refresh_summary()
        window._matched_size_test_before_summary = copy.deepcopy(items)
        dialog = ui.AttachmentSummaryDialog(window)
        self.addCleanup(dialog.close)
        return window, dialog

    def test_readonly_column_position_footer_and_snapshot_unchanged(self):
        item = quote(match(600, 250, 600))
        window, dialog = self.make_dialog([item])
        before = window._matched_size_test_before_summary[0]
        table = dialog.product_table
        self.assertEqual([table.horizontalHeaderItem(c).text() for c in (8, 9, 10)],
                         ['原价总价', '匹配尺寸', '柜体原价'])
        self.assertEqual(table.item(0, 9).text(), '600*250*600')
        self.assertFalse(table.item(0, 9).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertIn('宽*深*高', table.horizontalHeaderItem(9).toolTip())
        self.assertEqual(table.item(1, 9).text(), '')
        self.assertEqual(item, before)

    def test_original_cabinet_price_ignores_discount_freight_and_order_quantity(self):
        item = quote(match(300, 210, 300), quantity=3, quick_discount=.68, freight_fee=10.36,
                     material_code='SUS316', scheme2_cost_settings={'material_difference': 2},
                     attachments=[dict(custom=True,item_name='人工附件',quantity=1,formula_amount=10,
                                       quick_amount=363.83,quick_amount_override=363.83,custom_amount_edited=True)],
                     formula=dict(material_cost=100,auxiliary_cost=10,labor_cost=20,spray_cost=30,
                                  attachment_fee=10,corrected_material_weight_kg=5),
                     quick=dict(base_price=323.333333,attachment_fee=363.83,total_cost=687.16))
        window, dialog = self.make_dialog([item])
        before = copy.deepcopy(item)
        prices = ui._row_values(item)
        table = dialog.product_table
        self.assertEqual(table.item(0,10).text(),'323.33')
        self.assertIn('折前',table.horizontalHeaderItem(10).toolTip())
        self.assertIn('不含附件',table.item(0,10).toolTip())
        self.assertFalse(table.item(0,10).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(table.item(0,7).text(),ui._money(prices[13]))
        for discount in (0, .5, 1):
            item['quick_discount']=discount
            dialog._refresh_product_table()
            self.assertEqual(table.item(0,10).text(),'323.33')
        item['quick_discount']=before['quick_discount']
        self.assertEqual(item,before)
        self.assertEqual(ui._row_values(item),prices)

    def test_original_ganged_set_and_legacy_base_are_not_discounted_or_multiplied(self):
        item = quote(quantity=4,ganged_cabinet_count=2,quick_discount=.5,freight_fee=100,
                     attachments=[dict(custom=True,item_name='人工附件',quantity=1,quick_amount=25)],
                     quick=dict(base_price=5991.515331,attachment_fee=25,total_cost=6016.52))
        self.assertEqual(ui._attachment_summary_product_values(item,1)[10],5991.52)
        item['quick']=dict(total_cost=325,attachment_fee=25)
        self.assertEqual(ui._attachment_summary_product_values(item,1)[10],300)
        item['quick']['base_price']=0
        self.assertEqual(ui._attachment_summary_product_values(item,1)[10],0)

    def test_manual_attachment_price_refresh_preserves_match_and_cost(self):
        item = quote(match(600, 250, 600))
        item['attachments'] = [dict(custom=True, item_name='人工附件', quantity=1,
                                    formula_amount=10, quick_amount=20)]
        item['quick'].update(attachment_fee=20, total_cost=647.67)
        _, dialog = self.make_dialog([item])
        before = copy.deepcopy(item)
        price = dialog.table.cellWidget(0, 5)
        price.setValue(35)
        self.assertEqual(dialog.product_table.item(0, 9).text(), '600*250*600')
        self.assertEqual(dialog.product_table.item(0, 5).text(), '662.67')
        self.assertEqual(item['quick']['matched_experience'], before['quick']['matched_experience'])
        self.assertEqual(item['formula'], before['formula'])
        self.assertEqual(item['attachments'][0]['formula_amount'], 10)

    def test_resize_multiline_ganged_and_visual_evidence(self):
        items = [quote(match(600, 250, 600)),
                 quote({'ganged_cabinet_count': 3,
                        'items': [match(800, 600, 2000), match(800, 600, 2000), match(1000, 600, 2000)]},
                       name='并柜尺寸匹配', specification='(800+800+1000)*600*(2000+100)'),
                 quote(None, name='旧订单未保存匹配')]
        _, dialog = self.make_dialog(items)
        table = dialog.product_table
        expected = ui._attachment_summary_matched_size(items[1])
        dialog.show()
        for width in (760, 1560):
            dialog.resize(width, 720)
            table.setColumnWidth(9, 130 if width == 760 else 180)
            app.processEvents()
            self.assertEqual(table.item(1, 9).text(), expected)
            self.assertTrue(table.item(1, 9).toolTip().startswith(expected))
            self.assertGreaterEqual(table.rowHeight(1), table.fontMetrics().lineSpacing() * 3)
            self.assertEqual(table.item(2, 9).text(), '—')
        target = ROOT / '.codex-tmp' / f'matched-size-{os.environ.get("QT_SCALE_FACTOR", "1")}'
        target.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dialog.grab().save(str(target / 'attachment-summary.png')))


if __name__ == '__main__':
    unittest.main()
