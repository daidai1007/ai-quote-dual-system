"""Saved-version amounts and margins: no catalogue calls or historical repricing."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop_client'))
from quote_version_comparison import comparison_groups,change_details,line_metrics


def item(name,unit,cost,quantity=1,line_id=None):
    row=dict(name=name,quantity=quantity,specification=name+'尺寸',
        quote_display=dict(unit_price=unit,total=unit*quantity,quantity=quantity),
        formula=dict(total_cost=cost),freight_fee=0)
    if line_id:row['quote_line_id']=line_id
    return row


class VersionComparison(unittest.TestCase):
    def test_every_version_including_first_compares_with_its_previous_and_uses_weighted_margin(self):
        versions=[dict(version=1,items=[item('甲',100,60,2),item('乙',200,100)]),
                  dict(version=2,items=[item('甲',90,60,2),item('乙',200,100)]),
                  dict(version=3,items=[item('甲',95,65,3),item('乙',200,100)])]
        before=deepcopy(versions);groups=comparison_groups(versions)
        self.assertEqual([(g['previous'],g['current']) for g in groups],[(None,1),(1,2),(2,3)])
        self.assertIn('首次报价',change_details(None,groups[0]['rows'][0]['right'],initial=True))
        row=groups[1]['rows'][0]
        text=change_details(row['left'],row['right'])
        self.assertIn('金额：-20.00',text);self.assertIn('40.00% → 33.33%（-6.67 个百分点）',text)
        total=groups[1]['rows'][-1]
        self.assertTrue(total['summary']);self.assertAlmostEqual(total['left']['margin'],.45)
        self.assertIn('45.00% → 42.11%（-2.89 个百分点）',change_details(total['left'],total['right']))
        self.assertEqual(versions,before)

    def test_arbitrary_reverse_and_same_version_pairs_and_pending_placeholders(self):
        versions=[dict(version=1,items=[item('甲',100,60)]),dict(version=2,items=[item('甲',80,60)]),
                  dict(version=3,items=[item('甲',999,60)],pending_confirmation=True)]
        self.assertEqual(len(comparison_groups(versions)),2)
        reverse=comparison_groups(versions,2,1)
        self.assertEqual(len(reverse),1)
        self.assertIn('金额：+20.00',change_details(reverse[0]['rows'][0]['left'],reverse[0]['rows'][0]['right']))
        same=comparison_groups(versions,2,2)[0]['rows'][0]
        self.assertIn('金额：+0.00',change_details(same['left'],same['right']))
        self.assertIn('+0.00 个百分点',change_details(same['left'],same['right']))

    def test_reordered_added_removed_and_duplicate_source_ids_do_not_pair_unrelated_products(self):
        a,b=item('甲',100,60,1,'a'),item('乙',200,80,1,'b')
        versions=[dict(version=1,items=[a,b]),dict(version=2,items=[b,a]),
                  dict(version=3,items=[item('丙',50,20)])]
        same=comparison_groups(versions,1,2)[0]['rows']
        self.assertEqual([r['right']['name'] for r in same[:-1]],['乙','甲'])
        self.assertTrue(all('金额：+0.00' in change_details(r['left'],r['right']) for r in same[:-1]))
        changed=comparison_groups(versions,2,3)[0]['rows']
        self.assertIn('新增产品',change_details(changed[0]['left'],changed[0]['right']))
        self.assertTrue(all('移除产品' in change_details(r['left'],r['right']) for r in changed[1:-1]))
        b['quote_line_id']='a'
        self.assertEqual([r['left']['name'] for r in comparison_groups(versions,1,2)[0]['rows'][:-1]],['乙','甲'])

    def test_frozen_costs_override_new_formula_and_missing_costs_are_not_zero(self):
        row=item('甲',100,999,2)
        row['quote_cost_display']=dict(schema=1,values={'成本总价':'120.00','毛利率':'40.00%'})
        self.assertEqual(line_metrics(row)['margin'],.4)
        del row['quote_cost_display'];row['formula']={}
        self.assertIsNone(line_metrics(row)['margin'])
        self.assertIn('未记录',change_details(line_metrics(row),line_metrics(row)))
        row['formula']['total_cost']=0
        self.assertEqual(line_metrics(row)['margin'],1)
        row['quote_display'].update(unit_price=0,total=0)
        self.assertIsNone(line_metrics(row)['margin'])

    def test_cost_only_changes_and_reordered_identical_copies(self):
        a,b=item('甲',100,60,1,'same'),item('甲',200,120,1,'same')
        newer=deepcopy(a);newer['formula']['total_cost']=70
        versions=[dict(version=1,items=[a,b]),dict(version=2,items=[b,newer])]
        rows=comparison_groups(versions,1,2)[0]['rows']
        self.assertEqual(rows[0]['left']['unit'],200)
        self.assertEqual(rows[1]['left']['unit'],100)
        self.assertIn('金额：+0.00',change_details(rows[1]['left'],rows[1]['right']))
        self.assertIn('40.00% → 30.00%（-10.00 个百分点）',change_details(rows[1]['left'],rows[1]['right']))

    def test_legacy_recorded_components_sum_without_inventing_a_new_management_rate(self):
        row=item('甲',100,None,2)
        row['formula']=dict(material_cost=20,auxiliary_cost=10,labor_cost=5,attachment_fee=20,spray_cost=3,management_fee=2)
        self.assertEqual(line_metrics(row)['cost'],120)
        self.assertEqual(line_metrics(row)['margin'],.4)
        row['freight_fee']=10
        self.assertEqual(line_metrics(row)['margin'],.3)
        row['formula']['management_fee']=None
        self.assertIsNone(line_metrics(row)['margin'])


if __name__=='__main__':unittest.main(verbosity=2)
