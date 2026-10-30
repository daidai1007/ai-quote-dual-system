"""Fixed configuration ordering, per-cabinet counts, no guessed requirements."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from quote_configuration_remark import build_configuration_remark as build, source_configuration


def product():
    return dict(product_family='JP',material_code='SUS304',coating_type='橘纹',display_color='RAL7035',
        quantity=9,cabinet_body_thickness_mm=1.5,single_door_count=1,double_door_count=0,
        quote_configuration=dict(drawing_number='D-001',material_number='M-01',door_thickness_mm=2,
            side_panel_removable=True,rear_panel_removable=False,processing_requirements='开孔、丝印',
            excluded_items=['空调'],protection_rating='IP54',packaging_requirements='木箱包装',
            installation_plate_delivery='安装板先发'),
        attachments=[dict(item_name='安装板',quantity=1,thickness_mm=2.5,material_name='镀锌',position='后部'),
            dict(item_name='固定底座',height_mm=100,color='黑色',quantity=1),
            dict(item_name='门锁',model_code='MS821',quantity=2,unit='把'),
            dict(item_name='220V照明灯及行程开关',quantity=1),
            dict(item_name='门限位器',quantity=2,unit='套'),dict(item_name='接地线',quantity=3),
            dict(item_name='文件夹',specification='A4',quantity=1),
            dict(item_name='风机',brand='国产',voltage='220V',model_code='SG220',quantity=2),
            dict(item_name='滤网',brand='国产',model_code='FU9804',quantity=4),
            dict(item_name='三排安装梁',quantity=4,position='左右各2根'),
            dict(item_name='木托',custom=True,specification='按图',quantity=1,unit='件')])


class ConfigurationFormat(unittest.TestCase):
    def test_full_template_exact_order_units_and_single_cabinet_counts(self):
        item=product();before=deepcopy(item)
        expected=('D-001/M-01，仿威图JP柜，侧板、后背板可拆。不锈钢304，喷塑RAL7035橘纹，柜体1.5mm，门板2mm，配2.5mm镀锌安装板1块（后部）。'
            '前单开门，后背板；配100mm高黑色固定底座1件。'
            '配MS821门锁2把，配220V照明灯及行程开关1套，配门限位器2套，配接地线3根，配A4文件夹1个，'
            '配国产220VSG220风机2只，配国产FU9804滤网4只，配三排纵梁4根（左右各2根），配木托（按图）1件。'
            '按图开孔、丝印；不含空调；IP54；木箱包装；安装板先发。')
        self.assertEqual(build(item),expected)
        self.assertEqual(item,before)
        for quantity in (1,2,20):
            item['quantity']=quantity;self.assertEqual(build(item),expected)

    def test_unknown_fields_are_omitted_and_no_common_defaults_are_invented(self):
        self.assertEqual(build({}), '')
        self.assertEqual(build(dict(material_code='SUS316',attachments=[])),'不锈钢316。')
        actual=build(dict(product_family='JP',attachments=[dict(item_name='风机')]))
        self.assertEqual(actual,'仿威图JP柜，侧板、后背板可拆。柜体1.5mm，门板2mm，安装板数量待确认。')
        for value in ('2.5','RAL7035','IP54','不可拆','不含','【'):
            self.assertNotIn(value,actual)

    def test_source_requirements_are_copied_and_parsed_without_business_terms(self):
        source=dict(drawing_number='X-01',reviewed_remark='柜体1.2mm，门板1.8mm；侧板可拆，后背板不可拆；'
            '按图开孔300×70mm、丝印；不配风机但配滤网；IP65，木箱包装，安装板先发；付款月结，报价7天有效')
        item=source_configuration(source)
        source['reviewed_remark']='后来改过的图纸'
        item.update(product_family='JE',material_code='SECC',attachments=[dict(item_name='滤网',quantity=2,model_code='F1')])
        actual=build(item)
        for part in ('X-01','柜体1.2mm','门板1.8mm','侧板可拆','后背板不可拆','配F1滤网2只',
                     '按图开孔300×70mm、丝印','不含风机','IP65','木箱包装','安装板先发'):
            self.assertIn(part,actual)
        for part in ('付款','7天','后来改过','不含风机但配滤网'):
            self.assertNotIn(part,actual)

    def test_operator_fields_win_over_source_and_no_spray_does_not_claim_color(self):
        item=product();item['coating_type']='不喷塑';item['quote_remark_source']='柜体9mm，门板9mm'
        self.assertIn('柜体1.5mm，门板2mm',build(item))
        self.assertNotIn('喷塑RAL7035',build(item))
        self.assertNotIn('橘纹',build(item))

    def test_front_rear_choices_and_ambiguous_legacy_counts(self):
        cases=[('SINGLE','PANEL',(1,0),'前单开门，后背板'),('SINGLE','SINGLE',(2,0),'前单开门，后单开门'),
               ('SINGLE','DOUBLE',(1,1),'前单开门，后双开门'),('DOUBLE','PANEL',(0,1),'前双开门，后背板'),
               ('DOUBLE','SINGLE',(1,1),'前双开门，后单开门'),('DOUBLE','DOUBLE',(0,2),'前双开门，后双开门')]
        for front,rear,counts,expected in cases:
            item=dict(single_door_count=counts[0],double_door_count=counts[1],door_position=dict(front=front,rear=rear))
            self.assertEqual(build(item),expected+'。')
        self.assertEqual(build(dict(single_door_count=1,double_door_count=1)),'')

    def test_ganged_child_and_shared_counts_are_not_multiplied_or_divided(self):
        item=dict(product_family='JP',quantity=10,ganged_cabinet_count=2,
            ganged_cabinets=[dict(width_mm=800,door_position=dict(front='SINGLE',rear='DOUBLE')),
                            dict(width_mm=600,door_position=dict(front='DOUBLE',rear='SINGLE'))],
            attachments=[dict(item_name='风机',quantity=2,ganged_cabinet_index=0),
                         dict(item_name='风机',quantity=3,ganged_cabinet_index=1),
                         dict(item_name='接地线',quantity=4)])
        actual=build(item)
        for part in ('2并柜，宽800mm＋600mm','柜体1：前单开门，后双开门','柜体2：前双开门，后单开门',
                     '配风机2只（柜体1，单台）','配风机3只（柜体2，单台）','配接地线4根（每组）'):
            self.assertIn(part,actual)
        self.assertEqual(build(json.loads(json.dumps(item))),actual)

    def test_deduction_is_not_claimed_as_supply_or_an_invented_exclusion(self):
        item=dict(attachments=[dict(item_name='安装板',quantity=2,attachment_price_sign=-1),
                               dict(item_name='安装板',quantity=1)])
        self.assertEqual(build(item),'扣减安装板2块，配安装板1块。')
        self.assertNotIn('不含',build(item))

    def test_active_cost_part_thickness_can_supply_door_and_plate_without_default(self):
        item=dict(formula=dict(cabinet_material_part_details=[
            dict(part_name='前门板',sheet_thickness_mm=1.8,internal_quantity=1),
            dict(part_name='安装板',sheet_thickness_mm=2.2,material_code='SECC',internal_quantity=1),
            dict(part_name='后门板',sheet_thickness_mm=3,internal_quantity=0)]),
            attachments=[dict(item_name='安装板',quantity=1)])
        self.assertEqual(build(item),'门板1.8mm，配2.2mmSECC安装板1块。')

    def test_catalogue_fan_and_filter_details_are_kept_separately(self):
        item=dict(attachments=[dict(item_name='风机SG22060HA2/220V（国产）',quantity=2),
                               dict(item_name='过滤网FU9804（国产）',quantity=4)])
        self.assertEqual(build(item),'配SG22060HA2/220V（国产）风机2只，配FU9804（国产）滤网4只。')

    def test_business_exclusions_are_not_product_supply_exclusions(self):
        item=dict(quote_remark_source='不含税，不含运费；报价7个工作日有效；不含空调；按图开孔，交期15天')
        self.assertEqual(build(item),'按图开孔；不含空调。')


if __name__=='__main__':unittest.main(verbosity=2)
