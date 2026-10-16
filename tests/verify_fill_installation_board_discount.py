"""Focused Python discount contract: only 填充安装板 stops taking a discount."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop_client'))
from quick_discount_rules import (
    attachment_excluded_from_discount, formula_attachment_line_amount,
    quick_discount_category, quick_discount_breakdown, quick_order_line_breakdown,
)


class FillingBoardDiscount(unittest.TestCase):
    def test_filling_board_identity_and_legacy_fields_stay_at_original_price(self):
        for key in ('item_name', 'category_level1', 'category_level2', 'category_level3',
                    'attachment_category', 'category', 'model_code'):
            with self.subTest(key=key):
                row = {'item_name': '安装板', 'category_level1': '安装板', key: ' 填充安装板 '}
                self.assertIsNone(quick_discount_category(row))
                self.assertTrue(attachment_excluded_from_discount(row))

    def test_all_other_approved_names_keep_their_rules(self):
        names = {'安装板': '安装板', 'JK安装板': 'JK安装板', '填充板': '安装板',
                 '填充安装板固定件': '安装板', 'JP控制柜侧板': '侧板', '固定底座': '底座',
                 '活动底座': '底座', '内门': '内门', '玻璃门': '玻璃门', '分段板': '分段板',
                 '无孔承板': '无孔承板', '有孔承板': '有孔承板', '通风顶罩': '通风顶罩', '防雨顶': '防雨顶'}
        for name, category in names.items():
            with self.subTest(name=name):
                self.assertEqual(quick_discount_category({'item_name': name}), category)
                self.assertFalse(attachment_excluded_from_discount({'item_name': name}))

    def test_other_original_price_and_formula_exceptions_are_unchanged(self):
        for name in ('安装板单发', 'JK安装板单发', '固定立柱', '三排安装梁', '铜排', '风机', '门安装条'):
            self.assertIsNone(quick_discount_category({'item_name': name}))
        self.assertTrue(attachment_excluded_from_discount({'item_name': '门安装条'}))
        self.assertFalse(attachment_excluded_from_discount({'item_name': '风机'}))
        self.assertIsNone(quick_discount_category({'item_name': '安装板', 'category_level1': '其他附件'}))

    def test_mixed_order_and_deduction_preserve_prices_costs_and_quantity(self):
        for sign in (1, -1):
            with self.subTest(sign=sign):
                fill = dict(item_name='填充安装板', category_level1='配置变形', quantity=2,
                            catalog_version='offline', quick_amount=200 * sign, formula_amount=120 * sign,
                            attachment_price_sign=sign)
                attachments = [fill, dict(item_name='安装板', quantity=1, unit_price=100),
                               dict(item_name='风机', quantity=1, unit_price=50)]
                before = copy.deepcopy(attachments)
                quote = dict(base_price=1000, attachment_fee=150 + 200 * sign, total_cost=1150 + 200 * sign)
                unit = quick_discount_breakdown(quote, attachments, .5)
                self.assertEqual(unit['eligible_attachment_total'], 100)
                self.assertEqual(unit['original_price_attachment_total'], 50 + 200 * sign)
                self.assertEqual(unit['discounted_total'], 600 + 200 * sign)
                order = quick_order_line_breakdown(quote, attachments, .5, 3, 2, 10)
                self.assertEqual(order['line_total'], (600 + 200 * sign) * 3 + 30)
                self.assertEqual(formula_attachment_line_amount(fill), 120 * sign)
                self.assertEqual(attachments, before)

    def test_formula_quote_keeps_filling_board_original_without_changing_other_rows(self):
        from layout_refresh import _formula_order_line_breakdown
        fill = dict(item_name='填充安装板', category_level1='配置变形', quantity=2,
                    formula_amount=120, quick_amount=200, catalog_version='offline', status='CALCULATED')
        item = dict(quantity=3, formula_discount=.5, freight_fee=10,
                    formula={'total_cost': 1180, 'attachment_fee': 180}, attachments=[fill,
                        dict(item_name='安装板', quantity=1, formula_amount=40),
                        dict(item_name='风机', quantity=1, formula_amount=20)])
        before = copy.deepcopy(item)
        result = _formula_order_line_breakdown(item)
        self.assertEqual(result['original_price_attachment_total'], 360)
        self.assertEqual(result['discounted_attachment_total'], 180)
        self.assertEqual(result['line_total'], 1980)
        self.assertEqual(item, before)


if __name__ == '__main__':
    unittest.main()
