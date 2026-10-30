"""Real UI for manufacture 4% + management 5%, both of the quoted unit price."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui,app
from quick_discount_rules import apply_management_fee

OUT=Path(os.environ.get('AI_QUOTE_FACTORY_QA_DIR',fixture.ROOT/'test-output/manufacturing'))

def item(quantity=1):
    return dict(name='制造与管理费测试柜',product_code='JP',quantity=quantity,quick_discount=1,
        specification='800*600*1800',freight_fee=100,freight_mode='MANUAL',attachments=[],
        quick=dict(base_price=900,total_cost=900,attachment_fee=0),
        formula=dict(material_cost=600,auxiliary_cost=0,labor_cost=0,spray_cost=0,attachment_fee=0))

class ManufacturingUI(unittest.TestCase):
    setUp=fixture.CostCombinedLayout.setUp

    def fill(self,quantity=1):
        self.window.draft_items=[item(quantity)];self.window.refresh_summary()
        return self.window.draft_items[0]

    def test_factory40_management50_cost790_and_profit_rates(self):
        row=self.fill();grid=self.window.summary_table
        self.assertEqual(grid.item(0,10).text(),'1,000.00')
        self.assertEqual(grid.item(0,ui.MANUFACTURING_COLUMN).text(),'40.00')
        self.assertEqual(grid.item(0,18).text(),'50.00')
        self.assertEqual(grid.item(0,12).text(),'835.00')
        self.assertEqual(grid.item(0,21).text(),'26.00%')
        self.assertEqual(grid.item(0,ui.NET_MARGIN_COLUMN).text(),'16.50%')
        self.assertEqual(row['formula']['management_fee_base'],1000)
        before=deepcopy(row)
        for _ in range(3):self.window.refresh_summary()
        self.assertEqual(row,before)

    def test_order_quantity_and_discount_update_costs_once(self):
        row=self.fill(3);grid=self.window.summary_table
        self.assertEqual(grid.item(1,ui.MANUFACTURING_COLUMN).text(),'120.00')
        self.assertEqual(grid.item(0,20).text(),'2,505.00')
        grid.item(0,9).setText('0.8');app.processEvents()
        self.assertEqual(grid.item(0,10).text(),'820.00')
        self.assertEqual(grid.item(0,ui.MANUFACTURING_COLUMN).text(),'32.80')
        self.assertEqual(grid.item(0,18).text(),'41.00')
        self.assertEqual(grid.item(0,20).text(),'2,375.40')
        self.assertEqual(row['formula']['material_cost'],600)

    def test_column_position_detail_fixed_factors_and_actual_screenshots(self):
        row=self.fill();w=self.window;grid=w.summary_table
        header=grid.horizontalHeader()
        self.assertEqual(header.visualIndex(ui.MANUFACTURING_COLUMN),header.visualIndex(14)+1)
        self.assertEqual(header.visualIndex(15),header.visualIndex(ui.MANUFACTURING_COLUMN)+1)
        grid.selectRow(0);app.processEvents()
        self.assertEqual(w.scheme2_cost_selection_values[ui.MANUFACTURING_COLUMN].text(),'40.00')
        ui._show_detail(w,row)
        for index,detail in enumerate(row['cost_detail_rows']):
            if detail.get('category') in ('manufacturing_cost','management_fee'):
                self.assertIsNone(w.scheme2_detail_table.cellWidget(index,8))
        w.show_section(ui.COST_ROUTE)
        OUT.mkdir(parents=True,exist_ok=True)
        for width,height in ((1517,984),(1024,768)):
            w.resize(width,height);ui._apply_responsive(w);app.processEvents()
            grid.scrollToItem(grid.item(0,ui.MANUFACTURING_COLUMN));app.processEvents()
            self.assertTrue(w.grab().save(str(OUT/f'manufacture-management-{width}.png')))

    def test_history_without_feature_keeps_saved_costs_and_missing_column(self):
        row=item();row['formula']=apply_management_fee(row['formula'],100)
        before=deepcopy(row)
        self.window._quote_scheme_read_only=True
        self.window.draft_items=[row];self.window.refresh_summary()
        self.assertEqual(row,before)
        self.assertEqual(self.window.summary_table.item(0,ui.MANUFACTURING_COLUMN).text(),'未记录')
        self.assertEqual(self.window.summary_table.item(0,18).text(),'42.00')

    def test_export_snapshot_has_both_new_fees_and_copy_is_independent(self):
        row=self.fill(2);w=self.window
        ui._refresh_quote_page(w)
        frozen=ui._quote_export_items_snapshot(w)
        self.assertEqual(frozen[0]['formula']['manufacturing_cost'],40)
        self.assertEqual(frozen[0]['formula']['management_fee'],50)
        self.assertEqual(frozen[0]['formula']['total_cost'],735)
        self.assertEqual(frozen[0]['quote_display']['unit_price'],1000)
        w.summary_table.selectRow(0);ui._duplicate_selected(w)
        w.summary_table.item(1,9).setText('0.8');app.processEvents()
        self.assertEqual(row['formula']['manufacturing_cost'],40)
        self.assertEqual(w.draft_items[1]['formula']['manufacturing_cost'],32.8)

if __name__=='__main__':unittest.main()
