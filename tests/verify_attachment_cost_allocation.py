from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'desktop_client'))
from attachment_cost_allocation import allocate_attachment_costs,with_cost_allocation,attachment_detail_rows
from quick_discount_rules import money_sum
FIXTURE=json.loads((ROOT/'tests/fixtures/formula_attachment_allocation.json').read_text(encoding='utf-8'))


class AllocationTests(unittest.TestCase):
    def test_manual_cost_units_are_fixed_costs_with_formula_allocations(self):
        rows=deepcopy(FIXTURE['attachments'])
        rows.append(dict(item_name='人工成本公式附件',status='CALCULATED',cost_method='FORMULA',quantity=2,
            formula_cost_edited=True,formula_unit_cost_override=7.5,formula_amount=15,
            material_cost=1,spray_cost=1,auxiliary_cost=1,labor_cost=1))
        rows.append(dict(item_name='人工成本快速附件',status='QUICK_ONLY',quantity=2,
            formula_cost_edited=True,formula_unit_cost_override=2.5,formula_amount=5))
        result=allocate_attachment_costs({**FIXTURE['formula'],'attachment_fee':82},rows,strict=True)
        self.assertEqual(result['fixed_cost'],32);self.assertEqual(result['attachment_total'],82)
        self.assertEqual([r['method'] for r in result['lines'][-2:]],['FIXED','FIXED'])
        self.assertEqual(result['attachment_parts'],dict(material_cost=35,spray_cost=5,auxiliary_cost=3,labor_cost=7))
        self.assertEqual(FIXTURE['formula']['attachment_fee'],62)

    def test_shared_fixture_classification_is_idempotent_and_keeps_original_cost(self):
        before=deepcopy(FIXTURE)
        result=with_cost_allocation(FIXTURE['formula'],FIXTURE['attachments'],strict=True)
        self.assertEqual(result['cost_allocation']['totals'],FIXTURE['expected'])
        self.assertEqual(result['attachment_fee'],62)
        self.assertEqual(money_sum(result['cost_allocation']['totals'].values()),result['total_cost'])
        self.assertEqual(with_cost_allocation(result,FIXTURE['attachments'],strict=True),result)
        self.assertEqual(FIXTURE,before)
        details=attachment_detail_rows(result['cost_allocation'])
        self.assertEqual(len(details),9)
        self.assertEqual(money_sum(r['base_amount'] for r in details),62)

    def test_decimal_rounding_and_negative_quantity_match_node_fixture(self):
        for sign in (1,-1):
            row=dict(status='CALCULATED',quantity=3,attachment_price_sign=sign,formula_amount=.06*sign,
                material_cost=.005,spray_cost=.005,auxiliary_cost=.005,labor_cost=.005)
            result=allocate_attachment_costs(dict(attachment_fee=row['formula_amount']),[row],strict=True)
            self.assertEqual(list(result['attachment_parts'].values()),[.02*sign,.01*sign,.02*sign,.01*sign])

    def test_missing_costs_and_fixed_only_legacy(self):
        rows=deepcopy(FIXTURE['attachments']);rows[0].pop('material_cost')
        self.assertFalse(allocate_attachment_costs(FIXTURE['formula'],rows)['complete'])
        with self.assertRaisesRegex(ValueError,'重新计算'):with_cost_allocation(FIXTURE['formula'],rows,strict=True)
        self.assertIsNone(allocate_attachment_costs(FIXTURE['formula'],[rows[1]]))
        with self.assertRaisesRegex(ValueError,'不一致'):
            allocate_attachment_costs(dict(attachment_fee=.01),[dict(status='CALCULATED',quantity=1,formula_amount=.01,
                material_cost=0,spray_cost=0,auxiliary_cost=0,labor_cost=0)],strict=True)


if __name__=='__main__':unittest.main(verbosity=2)
