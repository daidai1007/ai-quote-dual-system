"""JP accepted auxiliary weight aggregation; no production data or network."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop_client'))
from freight_state import (self_made_weight,jp_auxiliary_weight,sync_item_freight,
                          AUTO_FREIGHT_BASIS,JP_AUXILIARY_WEIGHT_BASIS)

def formula(weight):
    return {'corrected_material_weight_kg':40,'cabinet_auxiliary_weight_basis':JP_AUXILIARY_WEIGHT_BASIS,
            'cabinet_auxiliary_self_made_weight_kg':weight}


class JPAuxiliaryWeight(unittest.TestCase):
    def test_bom_adds_once_without_order_or_waste_multiplier(self):
        item={'product_code':'JP','quantity':9,'formula':formula(12.345),'attachments':[{'weight_kg':2,'quantity':2}],
              'freight_mode':'AUTO','freight_basis':AUTO_FREIGHT_BASIS}
        item['formula']['waste_factor']=1.2
        self.assertEqual(self_made_weight(item),Decimal('56.345'))
        sync_item_freight(item);self.assertEqual(item['freight_fee'],56.35)
        item['quantity']=20;sync_item_freight(item);self.assertEqual(item['freight_fee'],56.35)

    def test_ganged_children_and_parent_totals_are_not_double_counted(self):
        item={'formula':{'corrected_material_weight_kg':80,'ganged_cabinet_costs':[
            {'formula_cost':formula(5)},{'formula_cost':formula(7)}]},
              'ganged_cabinet_results':[{'formula_cost':formula(5)},{'formula_cost':formula(7)}]}
        self.assertEqual(jp_auxiliary_weight(item),12);self.assertEqual(self_made_weight(item),92)
        item['formula'].update(cabinet_auxiliary_weight_basis=JP_AUXILIARY_WEIGHT_BASIS,cabinet_auxiliary_self_made_weight_kg=12)
        self.assertEqual(self_made_weight(item),92)

    def test_no_accepted_metadata_means_no_auxiliary_estimate_and_manual_freight_stays(self):
        item={'formula':{'corrected_material_weight_kg':40,'cabinet_auxiliary_self_made_weight_kg':999},
              'freight_mode':'MANUAL','freight_fee':0}
        self.assertEqual(self_made_weight(item),40);before=deepcopy(item)
        self.assertFalse(sync_item_freight(item));self.assertEqual(item,before)
        for value in [-1,float('nan'),float('inf')]:
            item['formula']=formula(value);self.assertEqual(jp_auxiliary_weight(item),0)


if __name__=='__main__':unittest.main(verbosity=2)
