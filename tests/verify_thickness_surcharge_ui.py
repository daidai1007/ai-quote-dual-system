"""Arbitrary thickness and per-row coefficient through actual Qt, snapshots and prices."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui,app
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDoubleSpinBox
from thickness_surcharge import BASIS,amount


def item(rate=10):
    return dict(name='料厚补价测试',product_code='JS',material_code='SECC',cabinet_body_thickness_mm=2.375,
        quantity=3,width_mm=1000,height_mm=1000,depth_mm=600,specification='1000*600*1000',
        quick_discount=.5,freight_fee=30,freight_mode='MANUAL',attachments=[],
        thickness_surcharge_coefficient=rate,quick=dict(base_price=1000,total_cost=1000,attachment_fee=0),
        formula=dict(material_cost=100,auxiliary_cost=20,labor_cost=30,spray_cost=10,attachment_fee=0,
            thickness_comparison=dict(basis=BASIS,weight_basis='COST_WITH_WASTE',selected_thickness_mm=2.375,
                selected_cost_weight_kg=50.6325,reference_cost_weight_kg=42.39,weight_difference_kg=8.2425,waste_factor=1.2,cabinet_count=1)))


class ThicknessSurchargeUI(unittest.TestCase):
    setUp=fixture.CostCombinedLayout.setUp

    def test_coefficient_beside_free_thickness_and_page_state_keeps_manual_value(self):
        w=self.window;w.show_section(ui.OPTION_ROUTE);app.processEvents()
        thickness=w.cabinet_body_thickness_spin;coefficient=w.thickness_surcharge_coefficient_spin
        self.assertIsInstance(thickness,QDoubleSpinBox)
        thickness.setValue(2.375);coefficient.setValue(12)
        state=ui._capture_scheme2_page_state(w)
        self.assertEqual(state['spins']['thickness_surcharge_coefficient_spin'],12)
        thickness.setValue(3.2);self.assertEqual(coefficient.value(),10)
        thickness.setValue(1.5);self.assertFalse(coefficient.isEnabled())
        ui._restore_scheme2_page_state(w,state)
        self.assertEqual(thickness.value(),2.375);self.assertEqual(coefficient.value(),12)
        self.assertTrue(coefficient.isEnabled())
        left=thickness.mapTo(w,thickness.rect().topLeft());right=coefficient.mapTo(w,coefficient.rect().topLeft())
        self.assertLess(left.x(),right.x());self.assertLessEqual(abs(left.y()-right.y()),2)
        output=Path(os.environ.get('THICKNESS_QA_DIR',fixture.ROOT.parent/'task-A-thickness-weight-surcharge-handoff-20261030/qa'))
        output.mkdir(parents=True,exist_ok=True)
        self.assertTrue(w.grab().save(str(output/'free-thickness-coefficient.png')))
        w._scheme2_dirty=False

    def test_summary_quote_preview_and_fixed_breakdown_do_not_discount_surcharge(self):
        w=self.window;row=item();w.draft_items=[row];fixture.Window.refresh_summary(w)
        self.assertEqual(amount(row),82.43)
        self.assertEqual(w.summary_table.item(0,ui.MATERIAL_DIFFERENCE_COLUMN).text(),'82.43')
        self.assertIn('8.2425',w.summary_table.item(0,ui.MATERIAL_DIFFERENCE_COLUMN).toolTip())
        self.assertEqual(w.summary_table.item(0,10).text(),'612.43')
        self.assertEqual(w.summary_table.item(0,11).text(),'1,837.29')
        components=ui._cost_price_components(row)
        self.assertIn('料厚差价',[r['category'] for r in components['fixed']['rows']])
        before=deepcopy(row)
        for _ in range(3):fixture.Window.refresh_summary(w)
        self.assertEqual(row,before)
        ui._refresh_quote_page(w)
        self.assertEqual(w.scheme2_quote_preview.item(10,5).text(),'612.43')
        frozen=ui._quote_export_items_snapshot(w)[0]
        self.assertEqual(frozen['quote_display']['thickness_surcharge'],82.43)
        self.assertEqual(frozen['thickness_surcharge_coefficient'],10)
        for discount in (.8,1):
            row['quick_discount']=discount;w.refresh_summary()
            self.assertEqual(amount(row),82.43)
            self.assertAlmostEqual(ui._row_values(row)[15],1000*discount+30+82.43,places=2)

    def test_zero_custom_rate_copy_and_legacy_snapshots(self):
        row=item(12);self.assertEqual(amount(row),98.91)
        clone=deepcopy(row);clone['thickness_surcharge_coefficient']=0
        self.assertEqual(amount(clone),0);self.assertEqual(amount(row),98.91)
        old=deepcopy(row);old['formula'].pop('thickness_comparison')
        self.assertEqual(amount(old),0)
        self.assertEqual(amount({**row,'item_type':'standalone_attachment'}),0)

    def test_custom_rate_survives_core_reset_while_adding(self):
        w=self.window;w.cabinet_body_thickness_spin.setValue(2.375)
        w.thickness_surcharge_coefficient_spin.setValue(12)
        w.scheme2_name_edit.setText('保留人工系数')
        original=w.add_current_to_summary
        def fake_add():
            w.draft_items.append(item())
            w.thickness_surcharge_coefficient_spin.setValue(10)
        w.draft_items=[];w.add_current_to_summary=fake_add
        try:
            with patch.object(ui,'_clear_scheme2_attachments'),patch.object(ui,'_refresh_quote_page'):
                ui._finish_add(w)
        finally:w.add_current_to_summary=original
        self.assertEqual(w.draft_items[0]['thickness_surcharge_coefficient'],12)
        self.assertEqual(amount(w.draft_items[0]),98.91)
        w._scheme2_dirty=False


if __name__=='__main__':unittest.main(verbosity=2)
