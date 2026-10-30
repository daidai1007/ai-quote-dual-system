"""Actual horizontal cost UI: gross excludes fees; net includes the same fees."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui, app
from profit_metrics import production_total, rate, percentage

OUT=Path(os.environ.get('AI_QUOTE_MARGIN_QA_DIR',fixture.ROOT/'test-output/gross-net-margin'))

def item(name='柜体', price=1000, production=600, freight=100, quantity=1):
    return dict(name=name,product_code='JP',quantity=quantity,quick_discount=1,
                specification='800*600*1800',freight_fee=freight,freight_mode='MANUAL',attachments=[],
                quick=dict(base_price=price,total_cost=price,attachment_fee=0),
                formula=dict(material_cost=production,auxiliary_cost=0,labor_cost=0,spray_cost=0,attachment_fee=0))

class GrossNetMargin(unittest.TestCase):
    setUp=fixture.CostCombinedLayout.setUp

    def test_one_line_fee_meanings_and_quote_cost_amounts_are_unchanged(self):
        row=item();self.window.draft_items=[row];self.window.refresh_summary()
        # Revenue includes the existing undiscounted freight: 1000 + 100.
        values=ui._row_values(row)
        self.assertEqual(values[16],1100)
        self.assertEqual(values[17],859)
        self.assertEqual(values[19],'32.36%')
        self.assertEqual(values[26],'21.91%')
        self.assertEqual(self.window.summary_table.item(0,21).text(),'32.36%')
        self.assertEqual(self.window.summary_table.item(0,ui.NET_MARGIN_COLUMN).text(),'21.91%')
        self.assertEqual(row['formula']['material_cost'],600)
        self.assertEqual(row['formula']['management_fee'],55)

    def test_quantity_and_weighted_summary_do_not_average_percentages(self):
        rows=[item('小单',price=95,production=50,freight=5,quantity=2),item('大单',price=990,production=900,freight=10)]
        self.window.draft_items=rows;self.window.refresh_summary()
        table=self.window.summary_table
        self.assertEqual(table.item(2,11).text(),'1,200.00')
        self.assertEqual(table.item(2,21).text(),'11.00%')
        self.assertEqual(table.item(2,ui.NET_MARGIN_COLUMN).text(),'3.75%')
        self.assertEqual(table.item(0,21).text(),'41.00%')
        self.assertEqual(table.item(1,21).text(),'5.00%')
        self.assertEqual(table.item(2,20).text(),'1,155.00')
        before=deepcopy(rows)
        for _ in range(3):self.window.refresh_summary()
        self.assertEqual(rows,before)

    def test_two_profit_leaves_are_adjacent_and_details_follow_selected_row(self):
        w=self.window;w.draft_items=[item('正毛利负净利',price=100,production=95,freight=0)];w.refresh_summary()
        w.summary_table.selectRow(0);app.processEvents()
        h=w.summary_table.horizontalHeader();net=ui.NET_MARGIN_COLUMN
        self.assertEqual(h.visualIndex(net),h.visualIndex(21)+1)
        self.assertEqual(h.visualIndex(22),h.visualIndex(net)+1)
        self.assertEqual(w.summary_table.item(0,21).text(),'1.00%')
        self.assertEqual(w.summary_table.item(0,net).text(),'-4.75%')
        self.assertEqual(w.scheme2_cost_selection_values[net].text(),'-4.75%')
        OUT.mkdir(parents=True,exist_ok=True)
        for width,height in ((1517,984),(1024,768)):
            w.resize(width,height);ui._apply_responsive(w);app.processEvents()
            w.summary_table.scrollToItem(w.summary_table.item(0,net));app.processEvents()
            self.assertGreater(w.scheme2_cost_selection_detail.width(),0)
            self.assertTrue(w.grab().save(str(OUT/f'profit-columns-{width}.png')))

    def test_zero_revenue_and_missing_production_do_not_fabricate_zero_margin(self):
        row=item(price=0,production=10,freight=0)
        values=ui._row_values(row)
        self.assertEqual(values[19],'—');self.assertEqual(values[26],'—')
        self.assertIsNone(production_total({'material_cost':10}))
        row['formula'].pop('spray_cost')
        self.assertEqual(ui._row_values(row)[19],'—')
        self.assertEqual(ui._row_values(row)[26],'—')

    def test_negative_margin_and_quantity_dont_double_count_formula_attachment_allocation(self):
        row=item(price=100,production=120,freight=10,quantity=3)
        row['attachments']=[dict(item_name='公式附件',status='CALCULATED',cost_method='FORMULA',quantity=1,
            formula_amount=20,quick_amount=0,material_cost=10,spray_cost=5,auxiliary_cost=3,labor_cost=2)]
        row['formula'].update(material_cost=0,labor_cost=120,attachment_fee=20)
        self.window.draft_items=[row];self.window.refresh_summary()
        values=ui._row_values(row)
        self.assertEqual(values[19],percentage((330-463.2)/330))
        self.assertEqual(values[26],percentage((330-values[18])/330))
        self.assertEqual(production_total(row['formula'],3),433.2)

    def test_gross_deducts_cost_freight_not_the_independent_quick_freight(self):
        row=item(price=900);row.update(quick_freight_basis=ui.QUICK_FREIGHT_BASIS,quick_freight_mode='MANUAL',quick_freight_fee=200)
        self.window.draft_items=[row];self.window.refresh_summary()
        before=deepcopy(row)
        self.assertEqual(self.window.summary_table.item(0,10).text(),'1,100.00')
        self.assertEqual(self.window.summary_table.item(0,21).text(),'32.36%')
        self.assertEqual(self.window.summary_table.item(0,ui.NET_MARGIN_COLUMN).text(),'21.91%')
        self.assertEqual(self.window.summary_table.item(0,12).text(),'859.00')
        for _ in range(3):self.window.refresh_summary()
        self.assertEqual(row,before)

    def test_legacy_readonly_margin_stays_on_its_recorded_basis(self):
        row=item(price=900);before=deepcopy(row)
        self.window._quote_scheme_read_only=True;self.window.draft_items=[row];self.window.refresh_summary()
        self.assertEqual(self.window.summary_table.item(0,21).text(),'40.00%')
        self.assertIn('历史',self.window.summary_table.item(0,21).toolTip())
        self.assertIn('历史',self.window.summary_table.item(1,21).toolTip())
        self.assertEqual(row,before)

if __name__=='__main__':unittest.main()
