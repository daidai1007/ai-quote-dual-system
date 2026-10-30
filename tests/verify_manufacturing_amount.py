"""Confirmed manufacturing arithmetic, independent of the pending fee-base choice."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop_client'))
from manufacturing_cost import manufacturing_unit_cost, manufacturing_cost_snapshot
from quick_discount_rules import money_product


class ManufacturingAmount(unittest.TestCase):
    def test_unit_quote_and_zero(self):
        self.assertEqual(manufacturing_unit_cost(1000),40)
        self.assertEqual(manufacturing_unit_cost(0),0)

    def test_quantity_is_not_part_of_the_unit_price_formula(self):
        unit=manufacturing_unit_cost(3149.94)
        self.assertEqual(unit,126)
        self.assertEqual(money_product(unit,3),378)

    def test_two_decimal_half_up_and_invalid_prices(self):
        self.assertEqual(manufacturing_unit_cost(0.125),.01)
        for value in (-1, None, True, float('nan'), float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                manufacturing_unit_cost(value)

    def test_each_fee_base_choice_is_explicit_and_refresh_doesnt_add_twice(self):
        base=dict(material_cost=600,auxiliary_cost=0,labor_cost=0,attachment_fee=0,spray_cost=0)
        excluded=manufacturing_cost_snapshot(base,1000,100,include_in_management=False)
        self.assertEqual(excluded['manufacturing_cost'],40)
        self.assertEqual(excluded['management_fee'],50)
        self.assertEqual(excluded['total_cost'],690)
        self.assertEqual(manufacturing_cost_snapshot(excluded,1000,100,include_in_management=False),excluded)
        with self.assertRaises(ValueError):manufacturing_cost_snapshot(base,1000,100,include_in_management=True)

if __name__=='__main__':unittest.main()
