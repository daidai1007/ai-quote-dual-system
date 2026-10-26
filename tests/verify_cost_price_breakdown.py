"""Category explanations must preserve every existing quick-quote amount."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop_client'))
from cost_price_breakdown import quick_price_components
from quick_discount_rules import money_sum, quick_order_line_breakdown


class PriceComponents(unittest.TestCase):
    def test_categories_fixed_freight_material_difference_and_negative_board(self):
        rows=[dict(category_level1='内门',quick_amount=100), dict(category_level1='风机',quick_amount=30),
              dict(category_level1='其他附件',item_name='安装板',quick_amount=20),
              dict(item_name='填充安装板',quick_amount=15), dict(item_name='安装板',quick_amount=-5)]
        quote=dict(base_price=1000,attachment_fee=160,total_cost=1160)
        before=deepcopy((quote,rows))
        value=quick_price_components(quote,rows,.8,9,7)
        self.assertEqual(value['fixed']['total'],81)
        self.assertEqual(value['discounted']['total'],876)
        self.assertEqual(value['total'],957)
        self.assertEqual([r['category'] for r in value['fixed']['rows']],['风机','其他附件','填充安装板','运费','材料差价'])
        self.assertEqual([r['category'] for r in value['discounted']['rows']],['柜体','内门','安装板'])
        for group in ('fixed','discounted'):
            self.assertEqual(money_sum(r['amount'] for r in value[group]['rows']),value[group]['total'])
        for count in (1,2,7):
            current=quick_order_line_breakdown(quote,rows,.8,count,2,9,7)
            self.assertEqual(value['total'],current['equivalent_unit_total'])
        self.assertEqual((quote,rows),before)

    def test_rounding_matches_existing_bucket_rounding_at_every_factor(self):
        for factor in (0,.5,.85,1,1.2345):
            quote=dict(base_price=.01,total_cost=.03,attachment_fee=.02)
            rows=[dict(item_name='内门',quick_amount=.01),dict(item_name='底座',quick_amount=.01)]
            value=quick_price_components(quote,rows,factor)
            current=quick_order_line_breakdown(quote,rows,factor,3)
            self.assertEqual(value['total'],current['equivalent_unit_total'])
            self.assertEqual(money_sum(r['amount'] for r in value['discounted']['rows']),value['discounted']['total'])

    def test_empty_fixed_bucket_and_legacy_base_recovery(self):
        value=quick_price_components(dict(total_cost=120,attachment_fee=20),[dict(item_name='内门',quick_amount=30)],.8)
        self.assertEqual(value['fixed'],dict(rows=[],total=0))
        self.assertEqual(value['discounted']['rows'][0]['original'],100)
        self.assertEqual(value['total'],104)


if __name__=='__main__':unittest.main(verbosity=2)
