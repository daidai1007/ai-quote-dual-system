"""Approved two-group selected-item panel: real Qt selection and frozen values."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLabel
import verify_formula_attachment_allocation_ui as allocation_fixture
from verify_formula_attachment_allocation_ui import fixture, app, ui

OUT = Path(os.environ.get('AI_QUOTE_SELECTED_DETAIL_SCREENSHOT_DIR', fixture.ROOT/'test-output/selected-detail'))


class SelectedDetail(unittest.TestCase):
    clean_window = fixture.ExportCustomer.clean_window
    posts = fixture.ExportCustomer.posts
    setUp = allocation_fixture.AllocationUI.setUp

    def panel(self):
        return self.w.scheme2_cost_selection_detail

    def select(self, row):
        self.w.summary_table.selectRow(row)
        app.processEvents()

    def test_groups_follow_row_and_updated_discount_quantity_without_changing_ledger(self):
        self.w.show_section(ui.COST_ROUTE)
        second = deepcopy(self.w.draft_items[0])
        second.update(name='合成第二条目',quantity=2,quick_discount=.5)
        self.w.draft_items.append(second);self.w.refresh_summary()
        self.select(1)
        values = self.w.scheme2_cost_selection_values
        for column in (7,24,9,10,11,12,13,14,15,16,17,18,19,20,21,25,26,27,28):
            self.assertEqual(values[column].text(),self.w.summary_table.item(1,column).text())
        self.assertEqual(values[16].text(),'12.00')
        self.assertIn('公式成本附件',values[16].toolTip())
        self.assertIn('合成第二条目',self.w.scheme2_cost_selection_context.text())
        self.assertTrue(values[22].text().endswith(' kg'))
        self.w.summary_table.item(1,4).setText('4');app.processEvents()
        self.assertEqual(values[11].text(),self.w.summary_table.item(1,11).text())
        self.assertEqual(values[20].text(),self.w.summary_table.item(1,20).text())
        self.select(0)
        self.assertEqual(values[11].text(),'1,863.00')
        self.assertEqual(self.w.draft_items[0]['formula']['attachment_fee'],62)

    def test_both_clickable_prices_use_existing_readonly_category_dialog(self):
        self.w.show_section(ui.COST_ROUTE);self.select(0)
        before=deepcopy(self.w.draft_items);opened=[]
        def inspect(dialog):
            opened.append((dialog.windowTitle(),dialog.table.item(dialog.table.rowCount()-1,3).text()))
            return QDialog.DialogCode.Accepted
        with patch.object(ui.QuickPriceBreakdownDialog,'exec',inspect):
            for column in (7,24):
                button=self.w.scheme2_cost_selection_values[column]
                self.assertTrue(button.isEnabled())
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        self.assertEqual(opened,[('固定报价明细','141.00'),('折扣面价明细','480.00')])
        self.assertEqual(self.w.draft_items,before)

    def test_missing_snapshot_fields_clear_and_disable_without_fabricating_zero(self):
        self.w.show_section(ui.COST_ROUTE);self.select(0)
        grid=self.w.summary_table
        grid.item(0,7).setText('未记录');grid.item(0,22).setText('未记录')
        ui._sync_cost_selection_detail(self.w)
        values=self.w.scheme2_cost_selection_values
        self.assertEqual(values[7].text(),'—');self.assertFalse(values[7].isEnabled())
        self.assertEqual(values[22].text(),'—');self.assertIn('未记录',values[7].toolTip())
        self.w.draft_items=[];self.w.refresh_summary()
        self.assertTrue(all(value.text()=='—' for value in values.values()))
        self.assertFalse(values[24].isEnabled())

    def test_approved_group_order_and_actual_layout_at_multiple_sizes(self):
        self.w.show_section(ui.COST_ROUTE);self.select(0)
        groups=self.w.scheme2_cost_selection_groups
        self.assertEqual([label.text() for label in self.panel().findChildren(QLabel)
                          if label.objectName() in ('scheme2CostSelectionQuickTitle','scheme2CostSelectionFormulaTitle')],
                         ['快速报价','成本报价'])
        captions=lambda group:[tile.findChild(QLabel,'scheme2CostSelectionMetricLabel').text() for tile in group[2]]
        self.assertEqual(captions(groups[0]),['尺寸','数量','已选附件','附件面价','固定报价','折扣面价','折扣系数','报价','运费','报价总价'])
        self.assertEqual(captions(groups[1]),['成本单价','材料差价','材料成本','辅材成本','制造成本','人工成本','附件成本','喷涂费用','管理费用','税费','运费','成本总价','毛利率','净利率','自制件重量'])
        OUT.mkdir(parents=True,exist_ok=True)
        for width,height in ((1560,960),(1280,800),(1024,700),(840,620)):
            self.w.resize(width,height)
            for _ in range(4):app.processEvents()
            ui._apply_responsive(self.w);app.processEvents()
            self.assertLess(groups[0][0].x(),groups[1][0].x())
            self.assertGreater(self.w.summary_table.viewport().height(),80)
            for group,_grid,tiles in groups:
                self.assertTrue(self.panel().rect().contains(group.mapTo(self.panel(),QPoint(0,0))))
                for tile in tiles:
                    self.assertTrue(group.rect().contains(tile.geometry()),(width,tile.geometry(),group.rect()))
            dock_top=self.w.scheme2_action_dock.mapTo(self.w,QPoint(0,0)).y()
            for value in self.w.scheme2_cost_selection_values.values():
                value_bottom=value.mapTo(self.w,value.rect().bottomRight()).y()
                self.assertLess(value_bottom,dock_top,(width,height,value_bottom,dock_top))
            self.assertTrue(self.w.grab().save(str(OUT/f'cost-selected-detail-{width}.png')))
        self.assertTrue(self.panel().grab().save(str(OUT/'selected-detail-panel.png')))


if __name__=='__main__':unittest.main(verbosity=2)
