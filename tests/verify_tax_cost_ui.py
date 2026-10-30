"""Actual Qt tax column, cost/profit policy and negative-tax error recovery."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import Mock
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui,app
from quick_discount_rules import apply_management_fee
from contract_management import freeze_contract_quote

OUT=Path(os.environ.get('AI_QUOTE_TAX_QA_DIR',fixture.ROOT/'test-output/tax-cost'))
def item(quantity=1):
 return dict(name='税费测试柜',product_code='JP',quantity=quantity,quick_discount=1,specification='800*600*1800',
  freight_fee=100,freight_mode='MANUAL',attachments=[],quick=dict(base_price=900,total_cost=900,attachment_fee=0),
  formula=dict(material_cost=600,auxiliary_cost=0,labor_cost=0,spray_cost=0,attachment_fee=0))

class TaxCostUI(unittest.TestCase):
 setUp=fixture.CostCombinedLayout.setUp
 def fill(self,quantity=1):
  self.window.show_error=Mock();self.window.draft_items=[item(quantity)];self.window.refresh_summary()
  return self.window.draft_items[0]
 def test_tax_in_unit_total_and_net_but_not_gross(self):
  row=self.fill(3);grid=self.window.summary_table
  for column,value in ((ui.TAX_COST_COLUMN,'45.00'),(12,'835.00'),(20,'2,505.00'),(21,'26.00%'),(ui.NET_MARGIN_COLUMN,'16.50%')):
   self.assertEqual(grid.item(0,column).text(),value)
  self.assertEqual(grid.item(1,ui.TAX_COST_COLUMN).text(),'135.00')
  before=deepcopy(row)
  for _ in range(3):self.window.refresh_summary()
  self.assertEqual(row,before);self.window.show_error.assert_not_called()
 def test_negative_tax_popup_blocks_output_and_recovers_without_spam(self):
  row=self.fill();w=self.window;grid=w.summary_table
  grid.item(0,9).setText('0.5');app.processEvents()
  w.show_error.assert_called_once();self.assertIn('税费计算失败',w.show_error.call_args.args[0])
  self.assertEqual(grid.item(0,ui.TAX_COST_COLUMN).text(),'待核对')
  self.assertEqual(grid.item(0,12).text(),'待核对')
  self.assertFalse(w.scheme2_cost_generate.isEnabled())
  w._scheme2_document_controller.sync_buttons();self.assertFalse(w.scheme2_quote_export.isEnabled())
  with self.assertRaisesRegex(ValueError,'税费计算失败'):ui._quote_export_items_snapshot(w)
  w.refresh_summary();w.show_error.assert_called_once()
  grid.item(0,9).setText('1');app.processEvents()
  self.assertEqual(grid.item(0,12).text(),'835.00');self.assertTrue(w.scheme2_cost_generate.isEnabled())
  grid.item(0,9).setText('0.5');app.processEvents();self.assertEqual(w.show_error.call_count,2)
 def test_quick_freight_is_distinct_from_tax_cost_freight(self):
  row=self.fill();w=self.window
  w.summary_table.item(0,ui.QUICK_FREIGHT_COLUMN).setText('200');app.processEvents()
  self.assertEqual(row['formula']['tax_cost'],60);self.assertEqual(row['formula']['tax_cost_inputs']['freight_fee'],100)
  self.assertEqual(w.summary_table.item(0,12).text(),'859.00')
  self.assertEqual(row['formula']['management_fee'],55)
 def test_single_ganged_tax_detail_and_fixed_factor(self):
  row=self.fill();w=self.window
  row['ganged_cabinet_count']=2
  row['formula']['ganged_cabinet_costs']=[dict(cabinet_index=i,formula_cost=dict(material_cost=300,auxiliary_cost=0,labor_cost=0,spray_cost=0,attachment_fee=0)) for i in (1,2)]
  w.refresh_summary();ui._show_detail(w,row)
  rows=[(i,r) for i,r in enumerate(row['cost_detail_rows']) if r.get('category')=='tax_cost']
  self.assertEqual(len(rows),1);index,detail=rows[0]
  self.assertEqual(detail['base_amount'],45);self.assertIsNone(w.scheme2_detail_table.cellWidget(index,8))
 def test_old_readonly_snapshot_keeps_costs_and_missing_tax(self):
  row=item();row['formula']=apply_management_fee(row['formula'],100);before=deepcopy(row)
  w=self.window;w._quote_scheme_read_only=True;w.draft_items=[row];w.refresh_summary()
  self.assertEqual(row,before);self.assertEqual(w.summary_table.item(0,ui.TAX_COST_COLUMN).text(),'未记录')
  self.assertEqual(row['formula']['management_fee'],42)
 def test_snapshot_column_position_and_actual_screenshots(self):
  row=self.fill(2);w=self.window;grid=w.summary_table;col=ui.TAX_COST_COLUMN;header=grid.horizontalHeader()
  self.assertEqual(header.visualIndex(col),header.visualIndex(18)+1)
  self.assertEqual(header.visualIndex(19),header.visualIndex(col)+1)
  ui._refresh_quote_page(w)
  frozen=freeze_contract_quote(w,{})['contract_quote_snapshot']['items'][0]
  self.assertEqual(frozen['quote_display']['formula_unit_price'],835)
  self.assertEqual(frozen['quote_cost_display']['values']['税费'],'45.00')
  grid.selectRow(0);app.processEvents();self.assertEqual(w.scheme2_cost_selection_values[col].text(),'45.00')
  OUT.mkdir(parents=True,exist_ok=True)
  for width,height in ((1517,984),(1024,768)):
   w.resize(width,height);ui._apply_responsive(w);app.processEvents();grid.scrollToItem(grid.item(0,col));app.processEvents()
   self.assertTrue(w.grab().save(str(OUT/f'tax-cost-{width}.png')))

if __name__=='__main__':unittest.main()
