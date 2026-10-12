"""Focused offline Qt tests for customer-facing names in the cost table."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLineEdit
import attachment_v2_client as v2
import scheme2_ui as ui
import v3_launcher

app=QApplication.instance() or QApplication([])
ns=v3_launcher.load_v3_namespace()
Window=ns['MainWindow']

class CostNameEdit(unittest.TestCase):
    def setUp(self):
        self.saves=[]
        for p in (patch.object(Window,'load_catalogs',lambda self:None),
                  patch.object(Window,'refresh_formula_inputs',lambda self,*args:None),
                  patch.object(ui,'_schedule_order_workspace_save',lambda window:self.saves.append(True))):
            p.start();self.addCleanup(p.stop)
        self.window=Window()
        self.addCleanup(self.window.close)
        self.item=dict(name='未命名',product_code='JP_SINGLE',material_code='SECC',
            specification='800*600*1800',quantity=1,quick_discount=.5,attachments=[],
            attachment_contract=2,quote_line_id='11111111-1111-4111-8111-111111111111',
            attachment_confirmation_inputs=[],formula={'total_cost':100},quick={'total_cost':200})
        self.other={**copy.deepcopy(self.item),'name':'另一个柜'}
        self.window.draft_items=[self.item,self.other]
        self.window.refresh_summary()
        self.saves.clear()

    def test_name_edit_updates_preview_print_and_confirmation_without_repricing(self):
        before=copy.deepcopy(self.item)
        self.window.summary_table.item(0,1).setText('  主控制柜  ')
        self.assertEqual(self.item['name'],'主控制柜')
        self.assertEqual(self.window.summary_table.item(0,1).text(),'主控制柜')
        self.assertEqual(self.window.scheme2_quote_preview.item(10,1).text(),'主控制柜')
        self.assertIn('主控制柜',ui._printable_quote_html(self.window))
        self.assertEqual(v2.confirmation_payload({'items':[self.item]},validate=True)['items'][0]['name'],'主控制柜')
        self.assertEqual({k:v for k,v in self.item.items() if k!='name'},
                         {k:v for k,v in before.items() if k!='name'})
        self.assertFalse(v2.attachment_snapshot_needs_refresh(self.item))
        self.assertEqual(self.other['name'],'另一个柜')
        self.assertTrue(self.saves)

    def test_double_click_name_creates_text_editor_and_focus_out_commits(self):
        self.window.show_section(ui.COST_ROUTE)
        self.window.show();app.processEvents()
        table=self.window.summary_table
        table.setCurrentCell(0,1)
        position=table.visualItemRect(table.item(0,1)).center()
        QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,pos=position)
        QTest.mouseDClick(table.viewport(),Qt.MouseButton.LeftButton,pos=position)
        app.processEvents()
        editor=next((candidate for candidate in table.findChildren(QLineEdit) if candidate.isVisible()),None)
        self.assertIsNotNone(editor)
        editor.setFocus()
        QTest.keyClick(editor,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor,'CabinetA-01')
        QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,
                        pos=table.visualItemRect(table.item(0,0)).center())
        QTest.qWait(20);app.processEvents()
        self.assertEqual(self.item['name'],'CabinetA-01')
        self.window._scheme2_dirty=False

    def test_blank_name_restores_existing_name_and_total_row_stays_read_only(self):
        self.window.summary_table.item(0,1).setText('  ')
        self.assertEqual(self.item['name'],'未命名')
        self.assertEqual(self.window.summary_table.item(0,1).text(),'未命名')
        self.assertFalse(self.window.summary_table.item(2,1).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(self.window.summary_table.item(0,2).flags() & Qt.ItemFlag.ItemIsEditable)

    def test_copied_names_can_be_edited_independently_and_quote_name_edit_still_works(self):
        self.window.summary_table.selectRow(0)
        self.window.scheme2_cost_action_buttons[3].click()
        self.window.summary_table.item(1,1).setText('副本柜')
        self.assertEqual(self.item['name'],'未命名')
        self.assertEqual(self.window.draft_items[1]['name'],'副本柜')
        self.window.scheme2_quote_preview.item(11,1).setText('报价单修改名')
        self.assertEqual(self.window.summary_table.item(1,1).text(),'报价单修改名')
        self.assertEqual(self.item['name'],'未命名')

if __name__=='__main__':unittest.main()
