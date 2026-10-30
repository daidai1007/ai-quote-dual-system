"""Real Qt consumes API-adjusted face without a second thickness multiplier."""
from copy import deepcopy
import json
import subprocess
import unittest
from types import SimpleNamespace
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui,app
from quote_request_context import bind_quote_request

class QuickThicknessUI(unittest.TestCase):
    setUp=fixture.CostCombinedLayout.setUp
    def test_api_result_summary_preview_and_repeated_refresh(self):
        result=subprocess.run(['node','--input-type=module','-e',
            "import {applyQuickThicknessResult as f} from './api/quick_thickness_pricing.mjs';console.log(JSON.stringify(f({quick_quote:{base_price:1000,attachment_fee:0,total_cost:1000},formula_cost:{material_cost:100,auxiliary_cost:20,labor_cost:30,spray_cost:10,attachment_fee:0,total_cost:160}}, {product_code:'JS',cabinet_body_thickness_mm:2})));"],
            cwd=fixture.ROOT,capture_output=True,text=True,check=True)
        response=json.loads(result.stdout)
        w=self.window;w.cabinet_body_thickness_spin.setValue(2)
        w.attachments=[];w.freight_spin.setValue(50);w.quick_discount.setValue(.5)
        w._quote_request_context=None;w._scheme2_calculation_paused=False
        response['quote_id']='LOCAL-2MM-UI'
        bind_quote_request(w,SimpleNamespace(),response['quote_id'])
        w.show_result(response)
        self.assertEqual(w.quick_labels['base_price'].text().removesuffix(' 元'),'1,200.00',w.risk_label.text())
        row=dict(name='JS 2.0mm',product_code='JS',material_code='SECC',
            cabinet_body_thickness_mm=2,width_mm=800,height_mm=1800,depth_mm=600,
            specification='800*600*1800',quantity=3,quick_discount=.5,
            freight_fee=50,freight_mode='MANUAL',attachments=[],
            quick=deepcopy(response['quick_quote']),formula=deepcopy(response['formula_cost']))
        w.draft_items=[row];fixture.Window.refresh_summary(w);app.processEvents()
        self.assertEqual(w.summary_table.item(0,10).text(),'650.00')
        self.assertEqual(w.summary_table.item(0,11).text(),'1,950.00')
        before=deepcopy(row)
        for _ in range(3):fixture.Window.refresh_summary(w)
        self.assertEqual(row,before)
        ui._refresh_quote_page(w)
        self.assertEqual(w.scheme2_quote_preview.item(10,5).text(),'650.00')
        self.assertEqual(w.scheme2_quote_preview.item(10,6).text(),'1,950.00')
        w.cabinet_body_thickness_spin.setValue(1.5)
        self.assertIsNone(w.current_result)
        self.assertIn('重新计算',w.risk_label.text())

if __name__=='__main__':unittest.main()
