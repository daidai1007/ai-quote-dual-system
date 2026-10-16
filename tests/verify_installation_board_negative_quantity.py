"""Offline Qt/API-boundary regression for installation-board deductions."""
import copy
import os
from pathlib import Path
import sys
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtWidgets import QApplication,QWidget
import attachment_v2_client as v2
import scheme2_ui as ui
app=QApplication.instance() or QApplication([])

class NegativeBoard(unittest.TestCase):
    def setUp(self):
        self.window=QWidget();self.window.refresh_summary=lambda:None
        self.addCleanup(self.window.close)
        self.row=dict(item_name='安装板',category_level1='安装板',attachment_price_id=1,
            quantity=1,attachment_price_sign=1,status='CALCULATED',catalog_version='offline',
            formula_unit_cost=4,formula_amount=4,quick_amount=10,matched_price=10)
        self.item=dict(quantity=3,attachments=[copy.deepcopy(self.row)],attachment_contract=2,
            quote_line_id='11111111-1111-4111-8111-111111111111',
            attachment_confirmation_inputs=v2.confirmation_inputs([self.row]),
            formula={'attachment_fee':4,'total_cost':100},quick={'attachment_fee':10,'total_cost':200})

    def editor(self):
        editor=ui.AttachmentEditor(self.window,self.item)
        self.addCleanup(editor.close)
        return editor

    def test_negative_quantity_is_visible_but_positive_quantity_and_deduction_are_saved(self):
        editor=self.editor()
        editor.table.cellWidget(0,editor.COL_QUANTITY).setValue(-2)
        self.assertEqual(editor.table.item(0,editor.COL_FORMULA_AMOUNT).text(),'-8.00')
        self.assertEqual(editor.table.cellWidget(0,editor.COL_AMOUNT).value(),-20)
        editor.accept()
        row=self.item['attachments'][0]
        self.assertEqual(row['quantity'],2)
        self.assertEqual(row['attachment_price_sign'],-1)
        self.assertEqual(row['formula_amount'],-8)
        self.assertEqual(row['quick_amount'],-20)
        self.assertEqual(self.item['formula']['total_cost'],88)
        self.assertEqual(self.item['quick']['total_cost'],170)
        self.assertTrue(self.item['attachment_snapshot_dirty'])
        self.assertEqual(v2.selected_input(row)['quantity'],2)
        reopened=self.editor()
        self.assertEqual(reopened.table.cellWidget(0,reopened.COL_QUANTITY).value(),-2)
        self.assertEqual(ui._all_attachment_rows([self.item])[0]['quantity'],-6)
        reopened.accept()
        self.assertEqual(self.item['attachments'][0]['formula_amount'],-8)
        calculated={**self.row,'quantity':2,'attachment_price_sign':-1,
                    'formula_amount':-8,'quick_amount':-20}
        self.item['attachments']=[v2.merge_cost(self.item['attachments'][0],calculated)]
        self.item['attachment_confirmation_inputs']=v2.confirmation_inputs([calculated])
        self.item.pop('attachment_snapshot_dirty',None)
        payload=v2.confirmation_payload({'items':[self.item]},validate=True)
        self.assertEqual(payload['items'][0]['attachments'][0]['quantity'],2)
        self.assertEqual(payload['items'][0]['attachments'][0]['attachment_price_sign'],-1)
        self.assertFalse(v2.attachment_snapshot_needs_refresh(self.item))

    def test_existing_deduction_can_switch_back_to_positive_without_double_negation(self):
        self.item['attachments']=[{**self.row,'quantity':2,'attachment_price_sign':-1,
            'formula_amount':-8,'quick_amount':-20}]
        editor=self.editor()
        self.assertEqual(editor.table.cellWidget(0,editor.COL_QUANTITY).value(),-2)
        editor.table.cellWidget(0,editor.COL_QUANTITY).setValue(2)
        editor.accept()
        row=self.item['attachments'][0]
        self.assertEqual(row['quantity'],2)
        self.assertEqual(row['attachment_price_sign'],1)
        self.assertEqual(row['formula_amount'],8)
        self.assertEqual(row['quick_amount'],20)

    def test_legacy_negative_board_input_and_manual_amount_survive_api_merge(self):
        source={**self.row,'quantity':-2,'quick_amount':-44,'quick_amount_override':-44,
                'custom_amount_edited':True,'formula_amount':-8}
        before=copy.deepcopy(source)
        self.assertEqual(v2.selected_input(source),dict(attachment_price_id=1,quantity=2,
            attachment_price_sign=-1,manual_inputs={}))
        calculated={**self.row,'quantity':2,'attachment_price_sign':-1,
                    'formula_amount':-8,'quick_amount':-20}
        merged=v2.merge_cost(source,calculated)
        self.assertEqual(merged['quick_amount'],-44)
        self.assertEqual(merged['formula_amount'],-8)
        self.assertEqual(source,before)
        ui._apply_attachment_summary_price([dict(attachments=[merged],quick={'attachment_fee':-44,'total_cost':156})],
                                          ui._attachment_summary_identity(merged),30)
        self.assertEqual(merged['quick_amount'],-60)

    def test_only_catalogue_installation_boards_are_normalized(self):
        for name in ('安装板','JK安装板'):
            row={**self.row,'item_name':name,'quantity':-2}
            self.assertEqual(v2.selected_input(row)['quantity'],2)
            self.assertEqual(v2.selected_input(row)['attachment_price_sign'],-1)
        for row in ({**self.row,'item_name':'安装板单发','quantity':-2},
                    {**self.row,'item_name':'风机','category_level1':'风机','quantity':-2},
                    {**self.row,'custom':True,'quantity':-2}):
            with self.assertRaisesRegex(ValueError,'仅安装板允许负数量'):
                v2.selected_input(row)

    def test_other_attachment_quantity_widgets_cannot_accept_negative_values(self):
        for name,custom in (('风机',False),('玻璃门',False),('固定底座',False),
                            ('分段板',False),('安装板单发',False),('临时附件',True),('安装板',True)):
            with self.subTest(name=name,custom=custom):
                self.item['attachments']=[{**self.row,'item_name':name,'category_level1':name,'custom':custom}]
                editor=self.editor()
                quantity=editor.table.cellWidget(0,editor.COL_QUANTITY)
                self.assertGreaterEqual(quantity.minimum(),0)
                quantity.setValue(-2)
                self.assertGreaterEqual(quantity.value(),0)
                self.assertIn('仅安装板允许负数量',quantity.toolTip())

    def test_confirm_rejects_legacy_negative_nonboard_and_temporary_rows_locally(self):
        for row in ({**self.row,'item_name':'风机','category_level1':'风机','quantity':-2},
                    {**self.row,'item_name':'临时附件','custom':True,'quantity':-2}):
            self.item['attachments']=[row]
            with self.assertRaisesRegex(ValueError,'仅安装板允许负数量'):
                v2.confirmation_payload({'items':[self.item]},validate=True)

    def test_old_price_direction_entry_and_global_sign_state_are_deleted(self):
        client=(ROOT/'desktop_client'/'attachment_v2_client.py').read_text(encoding='utf-8')
        layout=(ROOT/'desktop_client'/'layout_refresh.py').read_text(encoding='utf-8')
        for text in ('安装板加减','加价/扣减','选择金额方向','QInputDialog'):
            self.assertTrue(text not in client, f'旧入口代码仍存在：{text}')
        for text in ('installation_board_sign','installation_board_price_sign','attachmentPriceSign'):
            self.assertTrue(text not in layout, f'旧全局状态代码仍存在：{text}')

if __name__=='__main__':unittest.main()
