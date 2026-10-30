"""Confirmed 06/07 rules against real persisted-field shapes; no business IO."""
from copy import deepcopy
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop_client'))
from quote_configuration_remark import build_configuration_remark as build,configuration_remark_review_issues as review,source_configuration

class ConfirmedRemarkRules(unittest.TestCase):
    def test_confirmed_JS_JP_and_wide_do_not_repeat_or_follow_old_conflicting_structure(self):
        for family,fixed in [('JS','侧板不可拆，后背板可拆'),('JP','侧板、后背板可拆'),('JP_WIDE_EXP','侧板、后背板可拆'),('JS WIDE','侧板不可拆，后背板可拆')]:
            item=dict(product_family=family,quote_configuration=dict(side_panel_removable=False,rear_panel_removable=False))
            old=deepcopy(item);result=build(item)
            self.assertEqual(result.count(fixed),1);self.assertNotIn('后背板不可拆',result)
            self.assertTrue(review(item));self.assertEqual(item,old)

    def test_only_quantity_fields_trigger_dash_and_remove_supply_and_duplicate_exclusion(self):
        for dash in ('-','－','—'):
            for shape in ('field','row'):
                item=dict(product_family='JP',quote_configuration=dict(excluded_items=['安装板','空调']))
                if shape=='field':item['installation_plate_quantity']=dash
                else:item['attachments']=[dict(item_name='安装板',quantity=dash)]
                before=deepcopy(item);result=build(item)
                self.assertEqual(result.count('不含安装板'),1);self.assertNotIn('配2.5',result);self.assertIn('不含空调',result)
                self.assertEqual(item,before)
        self.assertNotIn('不含安装板',build(dict(product_family='JP',quote_remark_source='按图X-01开孔')))

    def test_numeric_deduction_is_not_dash_and_conflict_is_reviewed(self):
        item=dict(attachments=[dict(item_name='安装板',quantity=2,attachment_price_sign=-1),dict(item_name='安装板',quantity=1)])
        self.assertEqual(build(item),'扣减安装板2块，配安装板1块。')
        self.assertTrue(review(dict(product_family='JP',installation_plate_quantity=-1)))
        self.assertNotIn('不含安装板',build(dict(product_family='JP',installation_plate_quantity='-1')))
        conflict=dict(product_family='JS',installation_plate_quantity='—',attachments=[dict(item_name='安装板',quantity=2)])
        self.assertTrue(review(conflict));self.assertNotIn('配安装板',build(conflict))

    def test_explicit_positive_material_and_thickness_are_used_without_pricing_mutation(self):
        item=dict(product_family='JP',quantity=20,cabinet_body_thickness_mm=2,
            quote_configuration=dict(door_thickness_mm=3,installation_plate_quantity=3,installation_plate_thickness_mm=2.2,installation_plate_material='不锈钢304'),
            formula=dict(total_cost=123.45),freight_fee=50,quick_discount=.8)
        old=deepcopy(item);result=build(item)
        for phrase in ('柜体2mm','门板3mm','配2.2mm不锈钢304安装板3块'):self.assertIn(phrase,result)
        self.assertEqual(item,old)
        self.assertEqual(build(json.loads(json.dumps(item))),result)
        actual=dict(product_family='JA',formula=dict(cabinet_material_part_details=[dict(part_name='柜体',sheet_thickness_mm=2.2,internal_quantity=1)]))
        self.assertIn('柜体2.2mm',build(actual))
        self.assertTrue(review(dict(product_family='JA',cabinet_body_thickness_mm=2,quote_remark_source='柜体1.5mm')))

    def test_blank_does_not_become_one_and_source_roundtrip_preserves_dash(self):
        for blank in ('',None):
            item=source_configuration(dict(installation_plate_quantity=blank));item['product_family']='JP'
            self.assertIn('安装板数量待确认',build(item));self.assertNotIn('安装板1块',build(item));self.assertTrue(review(item))
        item=source_configuration(dict(安装板数量='－'));item['product_family']='JS'
        self.assertIn('不含安装板',build(item))

    def test_JM_unconfirmed_and_other_standard_structures_remain_explicit(self):
        self.assertNotIn('侧板、后背板不可拆',build(dict(product_family='JM')))
        for family in ('AE','JA','JE','PS','JK','JM'):
            item=dict(product_family=family,quote_configuration=dict(side_panel_removable=True,rear_panel_removable=False,front_door='玻璃门'))
            result=build(item)
            for text in ('侧板可拆','后背板不可拆','前玻璃门'):self.assertIn(text,result)
        self.assertTrue(review(dict(product_family='JM',quote_configuration=dict(side_panel_removable=True))))
        self.assertTrue(review(dict(product_family='JS',quote_remark_source='侧板、后背板均可拆')))
        self.assertIn('侧板不可拆',build(dict(product_family='JM',quote_remark_source='后背板侧板都不可拆')))

    def test_nonstandard_components_consoles_do_not_borrow_unconfirmed_defaults(self):
        for family in ('FB','非标箱','MNS','悬臂系统','某设备改造','柜型不明'):
            result=build(dict(product_family=family,quote_configuration=dict(component_list=['控制箱1件','连接管2根'])))
            self.assertNotIn('仿威图',result);self.assertNotIn('柜体1.5mm',result);self.assertNotIn('安装板1块',result)
            self.assertIn('控制箱1件',result)
        self.assertIn('JQ1斜面操作台',build(dict(product_family='JQ1')))
        self.assertIn('JQ2琴式操作台',build(dict(product_family='JQ2')))
        self.assertNotIn('安装板2块',build(dict(product_family='JQ2')))

    def test_fan_filter_and_actual_base_units_remain_distinct_and_no_business_terms(self):
        item=dict(product_family='JS',quote_remark_source='不含税，不含运费，付款月结；不配风机',
            attachments=[dict(item_name='固定底座',quantity=2,height_mm=150),dict(item_name='滤网',model_code='F-1',quantity=4)])
        result=build(item)
        self.assertIn('150mm高固定底座2件',result);self.assertIn('配F-1滤网4只',result);self.assertIn('不含风机',result)
        for wrong in ('税','运费','月结','配风机','配。、','，。'):self.assertNotIn(wrong,result)

if __name__=='__main__':unittest.main(verbosity=2)
