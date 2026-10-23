"""Actual Qt forms cover every manual-dimension attachment family; offline."""
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtWidgets import QApplication,QDialog,QWidget
import scheme2_ui as ui
from attachment_v2_client import missing_manual_dimensions,selected_input,merge_cost

app=QApplication.instance() or QApplication([])
FAMILIES={
    '分段板':('分段板高度',), '固定底座':('底座高度',), '活动底座':('底座高度',),
    '玻璃门':('玻璃门高度','玻璃门宽度'), '无孔承板':('孔承板高度','孔承板宽度'),
    '有孔承板':('孔承板高度','孔承板宽度'), '通风顶罩':('通风顶罩高度',),
    '外部眉头(柜体顶板上方)':('眉头高度',), '侧门':('侧门高度','侧门宽度'),
}

class ManualDimensionForms(unittest.TestCase):
    def test_every_family_accepts_updates_and_roundtrips_both_cabinet_contexts(self):
        parent=QWidget();parent.resize(650,400)
        self.addCleanup(parent.close)
        for family,names in FAMILIES.items():
            for child in (None,1):
                source=dict(item_name=family,attachment_price_id=7,quantity=2,manual_inputs={},
                    category_level1='底座' if '底座' in family else '控制柜附件',
                    required_parameters=[dict(name=name,source='MANUAL') for name in names])
                if child is not None:source['ganged_cabinet_index']=child
                self.assertEqual(missing_manual_dimensions(source),list(names))
                for edit in (0,1):
                    with self.subTest(family=family,child=child,edit=edit):
                        values={name:100.125+edit*50+index*10 for index,name in enumerate(names)}
                        dialog=ui._SchemeDimensionEditor(parent,family+' · 补充尺寸',names,source['manual_inputs'])
                        self.assertEqual(set(dialog.fields),set(names))
                        for name,value in values.items():dialog.fields[name].setText(str(value))
                        self.assertTrue(dialog.confirm_button.isEnabled())
                        dialog.confirm_button.click()
                        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
                        self.assertEqual(dialog.values(),values)
                        source['manual_inputs']=dialog.values()
                        self.assertEqual(missing_manual_dimensions(source),[])
                        request=selected_input(source)
                        self.assertEqual(request['manual_inputs'],values)
                        calculated={**copy.deepcopy(source),'status':'CALCULATED',
                            'formula_unit_cost':10,'formula_amount':20,'quick_amount':40}
                        merged=merge_cost(source,calculated)
                        self.assertEqual(merged['manual_inputs'],values)
                        self.assertEqual(merged.get('ganged_cabinet_index'),child)
                        source=merged;dialog.close()

    def test_every_required_field_blocks_empty_zero_and_negative_values(self):
        for family,names in FAMILIES.items():
            for invalid_name in names:
                for invalid in ('','0','-1'):
                    with self.subTest(family=family,field=invalid_name,value=invalid):
                        values={name:100 for name in names};values[invalid_name]=invalid
                        dialog=ui._SchemeDimensionEditor(None,family,names,values)
                        self.assertFalse(dialog.confirm_button.isEnabled())
                        dialog.reject();self.assertEqual(dialog.result(),QDialog.DialogCode.Rejected)
                        dialog.close()

if __name__=='__main__':unittest.main(verbosity=2)
