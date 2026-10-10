"""Offline regression: size-scaled prices must survive the V2/UI merge."""
import copy
from decimal import Decimal, ROUND_HALF_UP
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtWidgets import QApplication
from attachment_category_browser import match_attachment_size, match_named_quick_attachment_size
from attachment_v2_client import merge_cost
import scheme2_ui as ui
import v3_launcher

app=QApplication.instance() or QApplication([])
NAMES=('固定底座','活动底座','内门','玻璃门','JP控制柜侧板','分段板','固定立柱','三排安装梁','防雨顶','通风顶罩')

def selected(name):
    source=dict(attachment_price_id=1,category_level1='底座' if '底座' in name else '控制柜附件',
                item_name=name,width_mm=600,height_mm=80 if '底座' in name else 1600,depth_mm=500,price=100)
    target=(800,100 if '底座' in name else 1800,700)
    return match_attachment_size([source],source,target)

def money(price,quantity):
    return float((Decimal(str(price))*Decimal(str(quantity))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

class SizedPrices(unittest.TestCase):
    def test_old_and_new_api_prices_exact_sizes_and_manual_overrides(self):
        for name in NAMES:
            with self.subTest(name=name):
                row=selected(name)
                original=copy.deepcopy(row)
                raw=dict(quick_amount=300,quantity=3,matched_price=100,formula_unit_cost=7,formula_amount=21)
                merged=merge_cost(row,raw)
                amount=money(row['unit_price_override'],3)
                self.assertEqual(merged['quick_amount'],amount)
                self.assertEqual(merge_cost(merged,raw)['quick_amount'],amount)
                self.assertEqual(ui.AttachmentEditor._display_amounts(merged),(21,amount))
                self.assertEqual(merged['formula_amount'],21)
                self.assertEqual(row,original)
                fresh={**raw,'quick_amount':amount,'size_match_ratio':row['size_match_ratio'],
                       'unit_price_override':row['unit_price_override']}
                self.assertEqual(merge_cost(row,fresh)['quick_amount'],amount)
                manual={**row,'unit_price_override':123,'quick_amount_override':369}
                self.assertEqual(merge_cost(manual,fresh)['quick_amount'],369)
                self.assertEqual(merge_cost(manual,fresh)['unit_price_override'],123)
                unit_only={**row,'unit_price_override':123}
                self.assertEqual(merge_cost(unit_only,fresh)['quick_amount'],369)
                exact={**fresh,'quick_amount':300,'size_match_ratio':1,'size_match_exact':True}
                exact.pop('unit_price_override')
                self.assertNotIn('unit_price_override',merge_cost(row,exact))
                pending={**raw,'status':'PENDING_MANUAL','quick_amount':0,'formula_amount':0,
                         'pending_manual_dimensions':['高度']}
                self.assertEqual(merge_cost(row,pending)['quick_amount'],0)

    def test_model_encoded_beam_price_survives_raw_api(self):
        source=dict(attachment_price_id=1,category_level1='安装附件',category_level2='三排纵梁',
                    item_name='三排安装梁',model_code='JP760260',price=100)
        row=match_named_quick_attachment_size([source],'安装附件','三排纵梁','三排安装梁',(800,1800,700))
        self.assertEqual(row['unit_price_override'],103.125)
        self.assertEqual(merge_cost(row,dict(quantity=2,quick_amount=200))['quick_amount'],206.25)

    def test_actual_v3_popup_and_quote_total_receive_scaled_amount(self):
        ns=v3_launcher.load_v3_namespace()
        Window=ns['MainWindow']
        with patch.object(Window,'load_catalogs',lambda self:None), \
             patch.object(Window,'refresh_formula_inputs',lambda self,*args:None):
            window=Window()
            self.addCleanup(window.close)
            window.attachments=[{**selected('内门'),'quantity':2}]
            window.pending_quote_signature=window.quote_input_signature()
            window._v2_request_environment=None
            window.show_result(dict(quote_id='offline',attachment_contract=2,quote_line_id='offline-line',
                attachments=[dict(attachment_price_id=1,item_name='内门',quantity=2,matched_price=100,
                                  face_price=100,quick_amount=200,formula_amount=14)],
                formula_cost=dict(material_cost=100,auxiliary_cost=10,labor_cost=20,spray_cost=30,
                                  management_fee=2.6,attachment_fee=14,total_cost=176.6,
                                  corrected_material_weight_kg=66.1,net_material_weight_kg=55,product_area_m2=4),
                quick_quote=dict(base_price=1000,attachment_fee=200,total_cost=1200,
                                 matched_experience={},match_method='exact'),risk_flags=[]))
            expected=money(window.attachments[0]['unit_price_override'],2)
            self.assertEqual(window.current_result['quick']['attachment_fee'],expected)
            self.assertEqual(window.current_result['quick']['total_cost'],1000+expected)
            self.assertEqual(ui.AttachmentEditor._display_amounts(window.attachments[0]),(14,expected))

if __name__=='__main__':
    unittest.main()
