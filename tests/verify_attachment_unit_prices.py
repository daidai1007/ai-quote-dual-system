"""Selected-attachment unit editing, saved prices and calculation boundaries."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import scheme2_ui as ui
import attachment_v2_client as v2
from quick_discount_rules import formula_attachment_line_amount

app = QApplication.instance() or QApplication([])


class AttachmentUnitPrices(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.refresh_summary = lambda:None
        self.addCleanup(self.owner.close)
        self.source = dict(item_name='并柜件', attachment_price_id=1001, quantity=2,
            formula_amount=62.96, formula_unit_cost=31.48, quick_amount=120,
            matched_price=60, catalog_version='synthetic', status='FIXED')

    def editor(self, source=None, order_quantity=7):
        self.item = dict(quantity=order_quantity, attachments=[copy.deepcopy(source or self.source)],
            formula=dict(attachment_fee=62.96,total_cost=162.96),
            quick=dict(attachment_fee=120,total_cost=620))
        dialog = ui.AttachmentEditor(self.owner,self.item)
        self.addCleanup(dialog.reject)
        dialog.show()
        app.processEvents()
        return dialog

    def total(self, d, column, row=0):
        return float(d.table.item(row,column).text().replace(',',''))

    def test_catalogue_cost_readonly_editable_sale_unit_and_readonly_totals(self):
        d=self.editor()
        self.assertEqual([d.table.horizontalHeaderItem(i).text() for i in range(7)],
            ['名称','尺寸 / 规格','数量','成本单价','成本','面价单价','面价'])
        for column in (d.COL_FORMULA_AMOUNT,d.COL_AMOUNT):
            self.assertIsNone(d.table.cellWidget(0,column))
            self.assertFalse(d.table.item(0,column).flags() & Qt.ItemFlag.ItemIsEditable)
        cost=d.table.cellWidget(0,d.COL_UNIT_COST)
        face=d.table.cellWidget(0,d.COL_UNIT_AMOUNT)
        self.assertEqual((cost.value(),face.value()),(31.48,60))
        QTest.mouseDClick(cost.lineEdit(),Qt.MouseButton.LeftButton)
        self.assertTrue(cost.lineEdit().isReadOnly())
        QTest.keyClicks(cost.lineEdit(),'35.25')
        QTest.keyClick(cost.lineEdit(),Qt.Key.Key_Return)
        self.assertEqual(cost.value(),31.48)
        cost.setValue(35.25)
        self.assertEqual(cost.value(),31.48)
        cost.stepUp()
        self.assertEqual(cost.value(),31.48)
        face.setValue(72.5)
        d.table.cellWidget(0,d.COL_QUANTITY).setValue(3)
        self.assertEqual((self.total(d,d.COL_FORMULA_AMOUNT),self.total(d,d.COL_AMOUNT)),(94.44,217.5))
        self.assertEqual((cost.value(),face.value()),(31.48,72.5))
        d.accept()
        self.assertEqual(self.item['formula']['attachment_fee'],94.44)
        self.assertEqual(self.item['quick']['attachment_fee'],217.5)
        self.assertEqual(self.item['formula']['total_cost'],194.44)
        self.assertEqual(self.item['quick']['total_cost'],717.5)

    def test_save_reopen_and_reprice_keep_readonly_cost_and_manual_sale_unit(self):
        d=self.editor()
        d.table.cellWidget(0,d.COL_UNIT_COST).setValue(0)
        d.table.cellWidget(0,d.COL_UNIT_AMOUNT).setValue(17.25)
        d.accept()
        row=json.loads(json.dumps(self.item['attachments'][0]))
        refreshed=v2.merge_cost(row,{**self.source,'quantity':3,'formula_amount':94.44,'quick_amount':180})
        self.assertEqual(refreshed['formula_unit_cost'],31.48,'catalogue provenance is retained')
        self.assertEqual((refreshed['formula_amount'],refreshed['quick_amount']),(94.44,51.75))
        reopened=self.editor(refreshed)
        self.assertEqual(reopened.table.cellWidget(0,reopened.COL_UNIT_COST).value(),31.48)
        self.assertTrue(reopened.table.cellWidget(0,reopened.COL_UNIT_COST).lineEdit().isReadOnly())
        self.assertEqual(reopened.table.cellWidget(0,reopened.COL_UNIT_AMOUNT).value(),17.25)
        reopened.table.cellWidget(0,reopened.COL_QUANTITY).setValue(4)
        reopened.accept()
        self.assertEqual(self.item['attachments'][0]['quick_amount'],69)
        self.assertEqual(v2.confirmation_inputs([refreshed]),v2.confirmation_inputs([{**refreshed,
            'formula_unit_cost_override':999,'formula_cost_edited':False}]))

    def test_negative_installation_board_and_quick_only_cost(self):
        row={**self.source,'item_name':'安装板','category_level1':'安装板','quantity':2,
             'attachment_price_sign':-1,'formula_amount':-62.96,'quick_amount':-120}
        d=self.editor(row)
        self.assertEqual(d.table.cellWidget(0,d.COL_QUANTITY).value(),-2)
        d.table.cellWidget(0,d.COL_UNIT_COST).setValue(12.5)
        d.table.cellWidget(0,d.COL_UNIT_AMOUNT).setValue(20)
        d.table.cellWidget(0,d.COL_QUANTITY).setValue(-3)
        d.accept()
        saved=self.item['attachments'][0]
        self.assertEqual((saved['quantity'],saved['attachment_price_sign']),(3,-1))
        self.assertEqual((saved['formula_amount'],saved['quick_amount']),(-94.44,-60))
        quick=self.editor({**self.source,'status':'QUICK_ONLY','formula_amount':0})
        quick.table.cellWidget(0,quick.COL_UNIT_COST).setValue(15)
        quick.accept()
        self.assertEqual(formula_attachment_line_amount(self.item['attachments'][0]),0)
        self.assertNotIn('formula_cost_edited',self.item['attachments'][0])

    def test_fractional_units_do_not_compound_rounding(self):
        d=self.editor({**self.source,'quantity':3,'formula_amount':1,'quick_amount':1})
        quantity=d.table.cellWidget(0,d.COL_QUANTITY)
        for n,expected in ((2,.67),(3,1),(10,3.33),(3,1)):
            quantity.setValue(n)
            self.assertEqual(self.total(d,d.COL_AMOUNT),expected)
            self.assertEqual(self.total(d,d.COL_FORMULA_AMOUNT),expected)
        d.accept()
        self.assertFalse(self.item['attachments'][0]['custom_amount_edited'])

    def test_legacy_edited_total_wins_over_stale_sale_unit(self):
        d=self.editor({**self.source,'custom_amount_edited':True,'unit_price_override':60,
                       'quick_amount_override':90,'quick_amount':90})
        self.assertEqual(d.table.cellWidget(0,d.COL_UNIT_AMOUNT).value(),45)
        d.accept()
        self.assertEqual(self.item['attachments'][0]['quick_amount'],90)

    def test_pending_and_busy_disable_both_unit_prices(self):
        d=self.editor({**self.source,'pending_manual_dimensions':['玻璃门高度'],'status':'PENDING_MANUAL'})
        for column in (d.COL_UNIT_COST,d.COL_UNIT_AMOUNT):
            self.assertFalse(d.table.cellWidget(0,column).isEnabled())
        callbacks=[]
        self.owner.recalculate_draft_attachment=lambda item,row,ok,fail:callbacks.append((row,ok,fail))
        source={**self.source,'item_name':'玻璃门'}
        d._reprice_row(0,source)
        for column in (d.COL_QUANTITY,d.COL_UNIT_COST,d.COL_UNIT_AMOUNT):
            self.assertFalse(d.table.cellWidget(0,column).isEnabled())
        callbacks[0][1](source)
        for column in (d.COL_QUANTITY,d.COL_UNIT_COST,d.COL_UNIT_AMOUNT):
            self.assertTrue(d.table.cellWidget(0,column).isEnabled())
        cost=d.table.cellWidget(0,d.COL_UNIT_COST)
        QTest.mouseDClick(cost.lineEdit(),Qt.MouseButton.LeftButton)
        self.assertTrue(cost.lineEdit().isReadOnly())

    def test_removing_row_keeps_edit_callbacks_on_correct_attachment(self):
        d=self.editor()
        d.add_row({**self.source,'item_name':'另一附件'})
        d.table.removeRow(0)
        app.processEvents()
        d.table.cellWidget(0,d.COL_UNIT_COST).setValue(10)
        d.table.cellWidget(0,d.COL_UNIT_AMOUNT).setValue(30)
        d.table.cellWidget(0,d.COL_QUANTITY).setValue(4)
        d.accept()
        self.assertEqual(self.item['attachments'][0]['formula_amount'],125.92)
        self.assertEqual(self.item['attachments'][0]['quick_amount'],120)

    def test_custom_link_and_new_quote_reset(self):
        d=self.editor(dict(custom=True,item_name='临时附件',quantity=2,formula_amount=20,quick_amount=24))
        cost=d.table.cellWidget(0,d.COL_UNIT_COST)
        QTest.mouseDClick(cost.lineEdit(),Qt.MouseButton.LeftButton)
        self.assertFalse(cost.lineEdit().isReadOnly())
        cost.setValue(15)
        self.assertEqual(d.table.cellWidget(0,d.COL_UNIT_AMOUNT).value(),18)
        d.table.cellWidget(0,d.COL_UNIT_AMOUNT).setValue(25)
        d.table.cellWidget(0,d.COL_UNIT_COST).setValue(20)
        d.accept()
        self.assertEqual((self.item['attachments'][0]['formula_amount'],self.item['attachments'][0]['quick_amount']),(40,50))
        fresh=v2.new_quote_attachment_selection({**self.source,'formula_cost_edited':True,'formula_unit_cost_override':0})
        self.assertNotIn('formula_cost_edited',fresh)
        self.assertNotIn('formula_unit_cost_override',fresh)

    def test_popup_added_temporary_row_saves_quantity_and_both_units(self):
        d=self.editor()
        d.add_row()
        d.table.cellWidget(1,d.COL_QUANTITY).setValue(3)
        d.table.cellWidget(1,d.COL_UNIT_COST).setValue(2)
        d.table.cellWidget(1,d.COL_UNIT_AMOUNT).setValue(4)
        d.accept()
        row=self.item['attachments'][1]
        self.assertTrue(row['custom'])
        self.assertEqual((row['quantity'],row['formula_amount'],row['quick_amount']),(3,6,12))


if __name__=='__main__':
    unittest.main()
