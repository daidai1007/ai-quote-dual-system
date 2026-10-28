"""Real quote-list to contract selection with offline, synthetic sources only."""
from copy import deepcopy
from urllib.parse import urlparse
from unittest.mock import patch
import unittest

import verify_name_login as fixture
import contract_management as contracts
import name_login

NO = 'BJ-20261028-000777'
BUYER = '本机正式报价测试客户甲'
KEY = 'contract-name:synthetic-a'

def source(version=2, customer=BUYER, key=KEY):
    return dict(scheme_no=NO,version_no=version,order_nature='EXTERNAL',customer_name=customer,customer_code=key)

def bootstrap(sources):
    return dict(ready=True,sources=sources,templates=[],records=[],drafts=[])


class ContractCustomerFlow(unittest.TestCase):
    setUpBase = fixture.LoginTests.setUp
    window = fixture.LoginTests.window

    def setUp(self):
        self.setUpBase()
        name_login.set_session(fixture.person('本机合同测试人员'))
        self.calls=[]
        self.reply=bootstrap([source(1,'本机旧客户','OLD'),source()])
        self.error=None
        def run(worker):
            path=urlparse(worker.url).path
            self.calls.append((path,deepcopy(worker.payload)))
            if self.error:worker.error=self.error
            elif path.endswith('/bootstrap'):worker.result=deepcopy(self.reply)
            elif path.endswith('/quote'):
                r=next(r for r in self.reply['sources'] if r['scheme_no']==worker.payload['scheme_no'] and r['version_no']==worker.payload['version_no'])
                worker.result={**r,'quote':dict(items=[],total=650.3,total_upper='陆佰伍拾元叁角')}
            else:worker.error='Unexpected offline contract request: '+path
            worker.completed=True
        p=patch.object(contracts.ContractWorker,'run',run);p.start();self.addCleanup(p.stop)
        self.w=self.window();self.m=self.w.quote_management;self.p=self.w.contract_management
        self.addCleanup(lambda:setattr(self.p,'unsaved',False))
        self.p.loaded=True
        self.p.method.setCurrentIndex(self.p.method.findData('QUICK'))
        self.p.data=bootstrap([source(1,'无','EMPTY'),dict(source(1,'本机旧模板客户','OTHER'),scheme_no='BJ-20261020-000001')])
        self.p.render_data()
        self.m.rows=[dict(scheme_no=NO,version_no=2,quote_version=8,company_name=BUYER,
            order_nature='EXTERNAL',status='QUOTED',can_write=True)]
        self.m.list_table.setRowCount(1);self.m.list_table.selectRow(0);self.m.selection_changed()

    def settle(self):
        fixture.wait(lambda:not self.p.busy and not self.p.workers and not self.p.queue)

    def tearDown(self):
        self.p.unsaved=False
        fixture.LoginTests.tearDown(self)

    def open_selected(self):
        self.m.contract_button.click();self.settle()

    def test_selected_quote_reloads_cached_customer_list_and_selects_exact_formal_version(self):
        self.open_selected()
        self.assertEqual(self.w.stack.currentIndex(),self.w.contract_management_route)
        self.assertEqual(self.p.customer.currentText(),BUYER)
        self.assertEqual(self.p.source.currentData(),(NO,2))
        self.assertIn(BUYER,self.p.source_info.text())
        self.assertIn('/ 正式 V2',self.p.source_info.text())
        self.assertEqual([path for path,_ in self.calls].count('/api/contracts/bootstrap'),1)
        self.assertNotEqual(self.p.customer.currentData(),'EMPTY')
        self.assertEqual(self.p.amount.text(),'¥ 650.30')
        self.assertTrue(self.w.grab().save(str(fixture.ROOT/'.codex-tmp'/'contract-customer-correct.png')))

    def test_revision_uses_latest_available_formal_version_not_unconfirmed_workspace(self):
        self.m.rows[0].update(status='REVISING',version_no=3)
        self.reply['sources'].reverse()
        self.open_selected()
        self.assertEqual(self.p.source.currentData(),(NO,2))
        self.assertEqual(self.p.customer.currentText(),BUYER)

    def test_selected_formal_buyer_label_wins_over_older_alias_with_same_code(self):
        self.reply=bootstrap([source(),source(1,'本机较早客户名称',KEY)])
        self.open_selected()
        self.assertEqual(self.p.customer.currentData(),KEY)
        self.assertEqual(self.p.customer.currentText(),BUYER)
        self.assertIn(BUYER,self.p.source_info.text())

    def test_missing_requested_version_does_not_fall_back_to_another_customer_or_v1(self):
        self.reply=bootstrap([source(1,'本机旧客户','OLD')])
        self.open_selected()
        self.assertIsNone(self.p.source.currentData())
        self.assertIsNone(self.p.current_quote)
        self.assertFalse(self.p.generate_button.isEnabled())
        self.assertIn('不会改用其他报价',self.p.notice.text())

    def test_failed_reload_keeps_old_quote_unselected_and_allows_retry(self):
        self.p.customer.setCurrentIndex(1);self.settle()
        self.error='合成网络错误'
        self.open_selected()
        self.assertIsNone(self.p.current_quote)
        self.assertIsNone(self.p.source.currentData())
        self.assertFalse(self.p.generate_button.isEnabled())
        self.assertEqual(self.p.pending_scheme,NO)
        self.error=None;self.p.reload();self.settle()
        self.assertEqual(self.p.customer.currentText(),BUYER)
        self.assertEqual(self.p.source.currentData(),(NO,2))

    def test_second_entry_refreshes_for_new_formal_quote(self):
        self.open_selected()
        self.m.rows[0]['version_no']=3
        self.reply['sources'].append(source(3,'本机下一正式客户','NEXT'))
        self.open_selected()
        self.assertEqual(self.p.source.currentData(),(NO,3))
        self.assertEqual(self.p.customer.currentText(),'本机下一正式客户')
        self.assertEqual([path for path,_ in self.calls].count('/api/contracts/bootstrap'),2)

    def test_unsaved_contract_is_not_replaced_by_selected_quote(self):
        self.p.inputs['contract_no'].setText('LOCAL-UNSAVED');self.p.unsaved=True
        self.m.contract_button.click()
        self.assertFalse(self.calls)
        self.assertEqual(self.p.inputs['contract_no'].text(),'LOCAL-UNSAVED')
        self.assertIn('保存生成草稿',self.p.notice.text())

    def test_internal_or_foreign_quote_cannot_start_contract_flow(self):
        for changes in (dict(order_nature='INTERNAL'),dict(can_write=False)):
            with self.subTest(changes=changes):
                old=deepcopy(self.m.rows[0]);self.m.rows[0].update(changes)
                self.m.contract()
                self.assertFalse(self.calls)
                self.m.rows[0]=old


if __name__=='__main__':unittest.main(verbosity=2)
