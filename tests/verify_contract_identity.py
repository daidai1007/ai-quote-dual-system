"""Contract page follows task A's current-window guard without losing renewal input."""
import unittest
from unittest.mock import patch
import verify_name_login as fixture
import contract_management as ui
import name_login
from contract_management import contract_headers

class ContractIdentity(unittest.TestCase):
    setUp=fixture.LoginTests.setUp
    tearDown=fixture.LoginTests.tearDown
    window=fixture.LoginTests.window

    def test_same_name_renewal_preserves_input_and_switch_clears_old_files(self):
        a=fixture.person('合同本机人员甲');name_login.set_session(a);w=self.window();p=w.contract_management
        p.inputs['contract_no'].setText('LOCAL-UNSAVED');p.field_edited()
        p.output={'bytes':b'local-contract','name':'local.docx'}
        renewed=fixture.person('合同本机人员甲');renewed['token']='R'*43
        name_login.set_session(renewed);w._name_identity_epoch=name_login.identity_epoch();p.check_identity()
        self.assertEqual(p.inputs['contract_no'].text(),'LOCAL-UNSAVED');self.assertIsNotNone(p.output)
        self.assertTrue(p.unsaved);self.assertTrue(name_login.critical_tasks(w))
        name_login.set_session(fixture.person('合同本机人员乙'))
        self.assertIsNone(contract_headers(w));p.check_identity()
        self.assertIsNone(p.output);self.assertEqual(p.inputs['contract_no'].text(),'')
        self.assertFalse(p.unsaved);self.assertFalse(p.request('/bootstrap',None,lambda value:self.fail('Old callback must not run')))
        p.check_identity();p.check_identity()

    def test_contract_operation_blocks_navigation_and_return_does_not_add_products(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        name_login.set_session(fixture.person('合同本机人员甲'));w=self.window();p=w.contract_management;p.loaded=True
        before=list(w.draft_items);p.inputs['contract_no'].setFocus();QTest.keyClick(p.inputs['contract_no'],Qt.Key.Key_Return);fixture.APP.processEvents();self.assertEqual(w.draft_items,before)
        w.show_section(w.contract_management_route);p.busy=True;w.show_section(1);self.assertEqual(w.stack.currentIndex(),w.contract_management_route);p.busy=False;p.unsaved=False
        record={'record_no':'LOCAL-HISTORY','generation_snapshot':{'scheme_no':'BJ-20261022-000099','source_version':2,'method':'QUICK','template_name':'历史模板','template_version':1,'mapping':{'fields':[]},'fields':{'buyer_name':'历史客户','seller_name':'历史供方','contract_no':'OLD'},'quote':{'total':10,'total_upper':'壹拾元整','items':[{'name':'历史产品','specification':'100x100','quantity':1,'unit':'台','unit_price':10,'total':10}]}}}
        p.show_history(record);self.assertTrue(p.choices_card.isHidden());self.assertIn('历史模板',p.history_banner.text())
        def inspect(dialog):
            self.assertTrue(any('BJ-20261022-000099' in text.text() and 'V2' in text.text() for text in dialog.findChildren(ui.QLabel)));return ui.QDialog.DialogCode.Accepted
        with patch.object(ui.QDialog,'exec',inspect):p.open_source()
        p.new_contract();self.assertEqual(p.inputs['seller_name'].text(),ui.DEFAULT_SELLER_NAME);self.assertEqual(p.inputs['contract_no'].text(),'')


if __name__=='__main__':unittest.main(verbosity=2)
