"""Offline Qt/API-boundary regression for installation-board deductions."""
import copy
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtWidgets import QApplication,QPushButton,QTableWidget,QWidget
import attachment_v2_client as v2
from quote_document_progress import QuoteDocumentProgress
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
        self.assertEqual(float(editor.table.item(0, editor.COL_AMOUNT).text().replace(",", "")),-20)
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

    def set_priced_boards(self, *boards):
        attachment_cost = sum(row['formula_amount'] for row in boards)
        face = sum(row['quick_amount'] for row in boards)
        self.item.update(name='回归柜体', quick_discount=.5, material_code='SECC',
                         freight_mode='MANUAL', freight_fee=0,
                         formula=dict(material_cost=100, auxiliary_cost=10, labor_cost=20, spray_cost=5,
                                      attachment_fee=attachment_cost, total_cost=135 + attachment_cost),
                         quick=dict(base_price=500, attachment_fee=face, total_cost=500 + face),
                         attachments=list(boards), attachment_confirmation_inputs=v2.confirmation_inputs(boards))

    def test_zero_quantity_removes_only_the_selected_child_board_and_keeps_costs(self):
        first = {**self.row, 'material_cost':2, 'spray_cost':1, 'auxiliary_cost':0, 'labor_cost':1,
                 'ganged_cabinet_index':0}
        second = {**first, 'attachment_price_id':2, 'ganged_cabinet_index':1}
        self.set_priced_boards(first, second)
        self.item['ganged_cabinet_count'] = 2
        self.window.draft_items = [self.item]
        self.window.summary_table = QTableWidget(0, len(ui.HEADERS), self.window)
        self.window.scheme2_cost_generate = QPushButton(self.window)
        self.window.refresh_summary = lambda: ui._refresh_cost_table(self.window)
        self.window.refresh_summary()
        self.assertEqual(self.item['formula']['cost_allocation']['totals']['material_cost'],104)

        editor = self.editor()
        editor.table.cellWidget(0, editor.COL_QUANTITY).setValue(0)
        for column in (editor.COL_FORMULA_AMOUNT, editor.COL_AMOUNT, editor.COL_DISCOUNTED_AMOUNT):
            self.assertEqual(editor.table.item(0, column).text(), '0.00')
        editor.accept()

        self.assertEqual([row['ganged_cabinet_index'] for row in self.item['attachments']], [1])
        formula = self.item['formula']
        self.assertTrue(formula['cost_allocation']['complete'])
        self.assertEqual(formula['cost_allocation']['totals']['material_cost'],102)
        self.assertEqual(formula['attachment_fee'],4)
        self.assertEqual(formula['tax_cost'],20.55)
        self.assertEqual(self.item['quick']['attachment_fee'],10)
        self.assertTrue(self.item['attachment_snapshot_dirty'])
        grid = self.window.summary_table
        self.assertEqual(grid.item(0, ui.HEADERS.index('材料成本')).text(), '102.00')
        self.assertEqual(grid.item(0, ui.TAX_COST_COLUMN).text(), '20.55')
        self.assertNotIn(grid.item(0, ui.HEADERS.index('成本单价')).text(), ('待核对', '待重算'))
        self.assertTrue(self.window.scheme2_cost_generate.isEnabled())
        exported = ui._quote_export_items_snapshot(self.window, [self.item])[0]
        payload = v2.confirmation_payload({'items': [exported]}, validate=True)['items'][0]
        self.assertEqual([row['attachment_price_id'] for row in payload['attachments']], [2])
        self.assertEqual(payload['quote_display']['attachments'], payload['attachments'])

    def test_old_zero_board_with_pending_dimensions_does_not_block_preview(self):
        self.set_priced_boards({**self.row, 'quantity':0, 'status':'PENDING_MANUAL',
                                'pending_manual_dimensions':['安装板高度']})
        original = copy.deepcopy(self.item)
        progress = SimpleNamespace(ui=ui, window=self.window, kind='generate', trace='test', set_stage=lambda *_: None)
        exported = QuoteDocumentProgress.validate(progress, [self.item])[0]
        self.assertEqual(exported['attachments'], [])
        self.assertEqual(exported['formula']['tax_cost'],20.25)
        self.assertEqual(self.item, original)

        self.item['formula'].update(cost_allocation={'complete':False, 'errors':['旧安装板分项不全']},
                                    tax_cost_error='旧安装板分项不全', tax_cost_error_code='MISSING_COSTS')
        ui._refresh_item_cost(self.item, None, read_only=False)
        self.assertEqual(self.item['attachments'], [])
        self.assertNotIn('cost_allocation', self.item['formula'])
        self.assertNotIn('tax_cost_error', self.item['formula'])
        self.assertEqual(self.item['formula']['tax_cost'],20.25)
        self.assertEqual(self.item['quick']['total_cost'],500)

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
