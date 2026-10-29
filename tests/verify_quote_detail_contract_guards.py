"""Offline actual-window layout/identity guards, without business network."""
from copy import deepcopy
from pathlib import Path
import os,unittest
from unittest.mock import patch
import verify_name_login as fixture
import name_login
from PySide6.QtGui import QCloseEvent

class DetailContractGuards(unittest.TestCase):
    window=fixture.LoginTests.window
    def setUp(self):
        fixture.LoginTests.setUp(self);name_login.set_session(fixture.person('本机合同操作员'))
        self.w=self.window();self.m=self.w.quote_management;self.p=self.w.contract_management;self.c=self.m.detail_contract_controller
        self.w._quote_scheme_loading=True
        self.w.draft_items=[dict(name='合成柜',product_code='JE_SINGLE',quantity=1,specification='600*300*800',quick_discount=1,
          quick={'base_price':200,'attachment_fee':0,'total_cost':200},formula={'material_cost':20,'auxiliary_cost':5,'labor_cost':10,'spray_cost':5,'management_fee':2,'attachment_fee':0,'total_cost':42},attachments=[])]
        self.w.scheme2_company.setCurrentText('本机合成客户');self.w._quote_order_nature='EXTERNAL';self.w._quote_scheme_status='DRAFT'
        self.w.refresh_summary();self.w._quote_scheme_loading=False;self.w._quote_scheme_save_timer.stop();self.w._quote_scheme_saved_seq=self.w._quote_scheme_dirty_seq
        self.w.stack.setCurrentIndex(2);self.m.root.setCurrentWidget(self.m.detail_page);self.m.show_detail()
    def tearDown(self):
        if self.c.active:self.c.finish()
        self.p.unsaved=False;self.p.profile_dirty=False;fixture.LoginTests.tearDown(self)

    def test_header_action_order_and_fit_at_desktop_and_narrow_widths(self):
        folder=Path(os.environ.get('AI_QUOTE_CONTRACT_SCREENSHOT_DIR',fixture.OUT));folder.mkdir(parents=True,exist_ok=True)
        for width,height in ((1519,986),(1366,900),(1024,768),(910,640)):
            self.w.setMinimumSize(0,0);self.w.resize(width,height);fixture.APP.processEvents()
            controls=[self.w.scheme2_quote_print,self.w.scheme2_quote_export,self.m.detail_contract_button,self.m.adjust_button]
            xs=[]
            for control in controls:
                origin=control.mapTo(self.w,control.rect().topLeft());end=control.mapTo(self.w,control.rect().bottomRight())
                self.assertTrue(self.w.rect().contains(end),(width,control.text(),end));xs.append(origin.x())
            self.assertEqual(xs,sorted(xs));self.assertTrue(self.m.detail_contract_button.isEnabled())
            self.w.grab().save(str(folder/f'详情合同入口_缩放{os.environ.get("QT_SCALE_FACTOR","1")}_{width}.png'))

    def test_busy_blocks_close_and_identity_change_cancels_old_context(self):
        with patch.object(self.p,'request',return_value=True):
            before=deepcopy(self.w.draft_items);self.c.start();self.assertTrue(self.c.active)
            event=QCloseEvent();self.w.closeEvent(event);self.assertFalse(event.isAccepted())
            name_login.set_session(fixture.person('本机另一位人员'));self.c.continue_start()
            self.assertFalse(self.c.active);self.assertFalse(self.w._detail_contract_busy);self.assertEqual(self.w.draft_items,before)

    def test_existing_unsaved_contract_is_preserved(self):
        self.p.unsaved=True;self.p.inputs['contract_no'].setText('SYNTHETIC-KEEP');self.c.start()
        self.assertFalse(self.c.active);self.assertEqual(self.p.inputs['contract_no'].text(),'SYNTHETIC-KEEP')
        self.assertIn('当前合同管理',self.m.feedback.text())

if __name__=='__main__':unittest.main(verbosity=2)
