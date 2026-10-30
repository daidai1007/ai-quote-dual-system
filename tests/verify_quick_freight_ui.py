"""Independent per-unit quick freight through real Qt, snapshots and editing."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui,app
from quick_discount_rules import quick_freight_fee
from quote_management_model import set_unit_price
from contract_management import freeze_contract_quote

OUT=Path(os.environ.get('QUICK_FREIGHT_QA_DIR',fixture.ROOT.parent/'task-A-quick-freight-handoff-20261030/qa'))

def item(quantity=1):
    return dict(name='运费分离测试柜',product_code='JP',quantity=quantity,quick_discount=1,
        specification='800*600*1800',freight_fee=100,freight_mode='MANUAL',attachments=[],
        quick=dict(base_price=900,total_cost=900,attachment_fee=0),
        formula=dict(material_cost=600,auxiliary_cost=0,labor_cost=0,spray_cost=0,attachment_fee=0))

class QuickFreightUI(unittest.TestCase):
    setUp=fixture.CostCombinedLayout.setUp
    def fill(self,quantity=1):
        self.window.draft_items=[item(quantity)];self.window.refresh_summary()
        return self.window.draft_items[0]
    def edit(self,column,text):
        self.window.summary_table.item(0,column).setText(text);app.processEvents()

    def test_default_follows_cost_but_manual_freight_stays_independent(self):
        row=self.fill(3);grid=self.window.summary_table;q=ui.QUICK_FREIGHT_COLUMN
        self.assertEqual(grid.item(0,q).text(),'100.00')
        self.edit(19,'120');self.assertEqual(grid.item(0,q).text(),'120.00')
        self.edit(q,'200');self.assertEqual(row['freight_fee'],120)
        self.edit(19,'100');self.assertEqual(grid.item(0,q).text(),'200.00')
        self.assertEqual(grid.item(0,10).text(),'1,100.00')
        self.assertEqual(grid.item(0,11).text(),'3,300.00')
        self.assertEqual(grid.item(1,q).text(),'600.00')
        self.assertEqual(grid.item(0,12).text(),'859.00')
        self.assertEqual(grid.item(0,ui.MANUFACTURING_COLUMN).text(),'44.00')
        self.assertEqual(grid.item(0,18).text(),'55.00')
        self.assertEqual(row['freight_mode'],'MANUAL')
        before=deepcopy(row)
        for _ in range(3):self.window.refresh_summary()
        self.assertEqual(row,before)

    def test_zero_reset_and_invalid_edit_do_not_rewrite_cost(self):
        row=self.fill();q=ui.QUICK_FREIGHT_COLUMN
        self.edit(q,'0');self.assertEqual(quick_freight_fee(row),0)
        self.assertEqual(self.window.summary_table.item(0,10).text(),'900.00')
        for bad in ('-1','NaN','abc'):
            self.edit(q,bad);self.assertEqual(quick_freight_fee(row),0)
        self.edit(19,'120');self.assertEqual(quick_freight_fee(row),0)
        self.edit(q,'');self.assertEqual(quick_freight_fee(row),120)
        self.assertEqual(row['freight_fee'],120)
        self.edit(19,'130');self.assertEqual(quick_freight_fee(row),130)

    def test_quote_price_reverse_copy_and_reopen_preserve_quick_override(self):
        row=self.fill(2);self.edit(ui.QUICK_FREIGHT_COLUMN,'200')
        set_unit_price(row,1200);self.window.refresh_summary()
        self.assertEqual(ui._row_values(row)[15:17],(1200,2400))
        self.assertEqual(row['freight_fee'],100)
        self.window.summary_table.selectRow(0);ui._duplicate_selected(self.window)
        self.window.summary_table.item(1,ui.QUICK_FREIGHT_COLUMN).setText('0');app.processEvents()
        self.assertEqual(quick_freight_fee(row),200)
        self.assertEqual(quick_freight_fee(self.window.draft_items[1]),0)
        saved=deepcopy(self.window.draft_items)
        self.window.draft_items=deepcopy(saved);self.window.refresh_summary()
        self.assertEqual(self.window.draft_items,saved)

    def test_auto_cost_weight_change_does_not_override_manual_quick_freight(self):
        row=self.fill();q=ui.QUICK_FREIGHT_COLUMN
        row.update(freight_mode='AUTO',freight_basis=ui.AUTO_FREIGHT_BASIS)
        row['formula']['corrected_material_weight_kg']=150;self.window.refresh_summary()
        self.assertEqual(quick_freight_fee(row),150)
        self.edit(q,'200')
        row['formula']['corrected_material_weight_kg']=250;self.window.refresh_summary()
        self.assertEqual(row['freight_fee'],250)
        self.assertEqual(quick_freight_fee(row),200)

    def test_frozen_snapshot_quote_and_cost_freight_are_distinct(self):
        row=self.fill(2);self.edit(ui.QUICK_FREIGHT_COLUMN,'200')
        ui._refresh_quote_page(self.window)
        frozen=freeze_contract_quote(self.window,{})['contract_quote_snapshot']['items'][0]
        self.assertEqual(frozen['quote_display']['unit_price'],1100)
        self.assertEqual(frozen['quote_display']['formula_unit_price'],859)
        self.assertEqual(frozen['quote_cost_display']['values']['运费'],'100.00')
        self.assertEqual(frozen['quote_cost_display']['values']['报价运费'],'200.00')
        self.assertEqual(frozen['quick_freight_fee'],200)

    def test_full_window_summary_and_visible_quote_agree(self):
        row=self.fill(2);self.edit(ui.QUICK_FREIGHT_COLUMN,'200')
        fixture.Window.refresh_summary(self.window)
        app.processEvents()
        self.assertEqual(self.window.summary_table.item(0,10).text(),'1,100.00')
        self.assertEqual(self.window.summary_table.item(0,11).text(),'2,200.00')
        ui._refresh_quote_page(self.window)
        self.assertEqual(self.window.scheme2_quote_preview.item(10,5).text(),'1,100.00')
        self.assertEqual(self.window.scheme2_quote_preview.item(10,6).text(),'2,200.00')
        self.assertEqual(row['freight_fee'],100)

    def test_column_position_readonly_and_actual_screenshots(self):
        row=self.fill();self.edit(ui.QUICK_FREIGHT_COLUMN,'200');w=self.window;grid=w.summary_table
        header=grid.horizontalHeader();q=ui.QUICK_FREIGHT_COLUMN
        self.assertEqual(header.visualIndex(q),header.visualIndex(10)+1)
        self.assertEqual(header.visualIndex(11),header.visualIndex(q)+1)
        self.assertEqual(grid.horizontalHeaderItem(q).text(),'运费')
        grid.selectRow(0);app.processEvents()
        self.assertEqual(w.scheme2_cost_selection_values[q].text(),'200.00')
        OUT.mkdir(parents=True,exist_ok=True)
        for width,height in ((1517,984),(1024,768)):
            w.resize(width,height);ui._apply_responsive(w);app.processEvents()
            grid.scrollToItem(grid.item(0,q));app.processEvents()
            self.assertTrue(w.grab().save(str(OUT/f'quick-freight-{width}.png')))
        w._quote_scheme_read_only=True;w.refresh_summary();before=deepcopy(row)
        self.edit(q,'500');self.assertEqual(row,before)

if __name__=='__main__':unittest.main()
