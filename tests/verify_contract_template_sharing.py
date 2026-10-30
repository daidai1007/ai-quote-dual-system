"""Real Qt shared-template controls with synthetic data and offline transport."""
from copy import deepcopy
from urllib.parse import urlparse
from unittest.mock import patch,Mock
import unittest
import verify_name_login as fixture
import name_login
import contract_management as ui

NO_A='BJ-20261028-000201'
NO_B='BJ-20261028-000202'

class ContractTemplateSharing(unittest.TestCase):
    window=fixture.LoginTests.window

    def setUp(self):
        fixture.LoginTests.setUp(self)
        name_login.set_session(fixture.person('本机使用同事'))
        self.calls=[]
        owner=fixture.person('本机上传同事')['person']['user_id']
        def template(number,customer='A',**updates):
            row=dict(template_version_id=number,group_id='local-group-'+str(number),version_no=1,
                customer_code=customer,customer_name='本机客户'+customer,template_name='共享模板'+str(number),
                file_format='xlsx',configured=True,enabled=True,is_default=False,can_use=True,can_write=False,
                owner_user_id=owner,owner_name='本机上传同事',lock_version=1)
            row.update(updates);return row
        self.rows=[template(1),template(2,'B'),template(3,enabled=False),template(4,configured=False),
            template(5,can_write=True,owner_user_id=name_login.user_id(),owner_name='本机使用同事'),
            template(6,can_use=False),template(7,'NO-QUOTE')]
        self.boot=dict(ready=True,templates=self.rows,records=[],drafts=[],sources=[
            dict(scheme_no=NO_A,version_no=2,order_nature='EXTERNAL',customer_code='A',customer_name='本机客户A'),
            dict(scheme_no=NO_B,version_no=1,order_nature='EXTERNAL',customer_code='B',customer_name='本机客户B')])
        def run(worker):
            path=urlparse(worker.url).path;self.calls.append((path,deepcopy(worker.payload)))
            if path.endswith('/bootstrap'):worker.result=deepcopy(self.boot)
            elif path.endswith('/quote'):
                source=next(r for r in self.boot['sources'] if r['scheme_no']==worker.payload['scheme_no'])
                worker.result={**source,'quote':dict(items=[],total=650.3,total_upper='陆佰伍拾元叁角')}
            elif '/templates/' in path:
                number=int(path.rsplit('/',1)[-1]);row=next(r for r in self.rows if r['template_version_id']==number)
                worker.result=dict(template={**deepcopy(row),'field_mapping':{'fields':[]} if row['configured'] else None},inspection={})
            else:worker.error='Unexpected offline shared-template request: '+path
            worker.completed=True
        transport=patch.object(ui.ContractWorker,'run',run);transport.start();self.addCleanup(transport.stop)
        self.w=self.window();self.p=self.w.contract_management
        self.p.received(deepcopy(self.boot));self.p.method.setCurrentIndex(self.p.method.findData('QUICK'))
        self.p.customer.setCurrentIndex(self.p.customer.findData('A'))
        self.p.source.setCurrentIndex(ui.index_of(self.p.source,(NO_A,2)));self.settle()

    def settle(self):
        fixture.wait(lambda:not self.p.busy and not self.p.workers and not self.p.queue)

    def test_missing_customer_template_borrows_without_switching_source_or_buyer(self):
        other={**self.rows[1],'buyer_configured':True}
        self.p.data['templates']=[other];self.rows=[other]
        self.p.customer_changed()
        self.p.source.setCurrentIndex(ui.index_of(self.p.source,(NO_A,2)));self.settle()
        self.assertEqual(self.p.template.currentData(),2)
        self.assertIn('借用',self.p.template.currentText())
        self.assertEqual(self.p.customer.currentData(),'A')
        self.assertEqual(self.p.customer_display.text(),'本机客户A')
        self.assertEqual(self.p.source.currentData(),(NO_A,2))
        self.assertEqual(self.p.amount.text(),'¥ 650.30')
        self.p.library.setRowCount(1);self.p.library.selectRow(0)
        self.p.tabs.setCurrentIndex(1);self.p.use_template();self.settle()
        self.assertEqual(self.p.customer.currentData(),'A');self.assertEqual(self.p.source.currentData(),(NO_A,2))
        self.w.show_section(self.w.contract_management_route);self.w.resize(1519,986)
        fixture.APP.processEvents();fixture.QTest.qWait(100)
        self.assertTrue(self.w.grab().save(str(fixture.ROOT/'.codex-tmp'/'template-fallback-quotation.png')))

    def test_usable_matching_template_takes_priority_over_other_customer_templates(self):
        self.p.data['templates']=[dict(r,buyer_configured=True) for r in self.rows]
        self.p.customer_changed();self.settle()
        self.assertLess(self.p.template.findData(2),0)

    def choose(self,number):
        self.p.template.setCurrentIndex(self.p.template.findData(number));self.settle()

    def library(self,number):
        index=next(i for i,r in enumerate(self.p.data['templates']) if r['template_version_id']==number)
        self.p.library.selectRow(index)

    def tearDown(self):
        self.p.unsaved=False
        fixture.LoginTests.tearDown(self)

    def test_library_lists_other_uploaders_and_dropdown_matches_quote_customer(self):
        self.assertEqual(self.p.library.rowCount(),7)
        self.assertIn('本机上传同事',self.p.library.item(0,6).text())
        self.assertEqual({self.p.template.itemData(i) for i in range(self.p.template.count())},{None,1,4,5})
        self.choose(1)
        self.assertTrue(self.p.generate_button.isEnabled())
        self.assertEqual(self.p.source.currentData(),(NO_A,2))

    def test_ordinary_user_can_select_and_generate_with_matching_shared_template(self):
        self.library(1);self.p.use_template();self.settle()
        self.p.inputs['contract_no'].setText('LOCAL-SHARED')
        self.assertEqual(self.p.template.currentData(),1)
        with patch.object(self.p,'request',return_value=True) as request:
            self.p.generate()
        args=request.call_args.args
        self.assertEqual(args[0],'/generate')
        self.assertEqual(args[1]['template_version_id'],1)
        self.assertEqual(args[1]['scheme_no'],NO_A)
        self.assertEqual(args[1]['version_no'],2)
        self.assertEqual(self.p.current_quote['total'],650.3)

    def test_other_uploader_configuration_is_blocked_before_mapping_or_write(self):
        self.choose(1);self.library(1)
        with patch.object(self.p,'request') as request,patch.object(ui,'MappingDialog') as dialog:
            self.p.configure_selected();self.p.configure_library()
            request.assert_not_called();dialog.assert_not_called()
        self.assertIn('只有上传人',self.p.notice.text())

    def test_other_uploader_version_and_settings_are_read_only(self):
        self.library(1)
        with patch.object(self.p,'request') as request,patch.object(ui.QFileDialog,'getOpenFileName') as picker:
            self.p.upload(True);self.p.settings(True);self.p.settings(False)
            request.assert_not_called();picker.assert_not_called()

    def test_uploader_can_open_own_mapping_dialog(self):
        self.choose(5)
        dialog=Mock();dialog.exec.return_value=ui.QDialog.DialogCode.Rejected
        with patch.object(ui,'MappingDialog',return_value=dialog) as constructor:
            self.p.configure_selected();self.settle()
        constructor.assert_called_once();dialog.exec.assert_called_once()

    def test_shared_template_without_accessible_matching_quote_leaves_selection_intact(self):
        self.choose(1);before=(self.p.customer.currentData(),self.p.source.currentData(),self.p.template.currentData())
        self.library(7)
        with patch.object(self.p,'request') as request:self.p.use_template();request.assert_not_called()
        self.assertEqual((self.p.customer.currentData(),self.p.source.currentData(),self.p.template.currentData()),before)
        self.assertIn('没有该客户可用的正式报价',self.p.notice.text())

    def test_unsaved_contract_is_kept_when_selecting_another_customer_template(self):
        self.choose(1);self.p.inputs['contract_no'].setText('LOCAL-KEEP');self.p.unsaved=True
        self.library(2)
        with patch.object(self.p,'request') as request:self.p.use_template();request.assert_not_called()
        self.assertEqual(self.p.customer.currentData(),'A');self.assertEqual(self.p.template.currentData(),1)
        self.assertEqual(self.p.inputs['contract_no'].text(),'LOCAL-KEEP')
        self.assertIn('未保存',self.p.notice.text())

    def test_disabled_template_stays_visible_but_cannot_be_used(self):
        self.library(3)
        with patch.object(self.p,'request') as request:self.p.use_template();request.assert_not_called()
        self.assertLess(self.p.template.findData(3),0)

    def test_unconfigured_shared_template_is_visible_and_requires_uploader_configuration(self):
        self.choose(4)
        self.assertIn('待配置',self.p.template.currentText())
        self.assertFalse(self.p.generate_button.isEnabled())
        self.p.configure_selected();self.assertIn('只有上传人',self.p.notice.text())

    def test_switch_to_another_matching_customer_does_not_reuse_old_quote(self):
        self.choose(1);self.library(2);self.p.use_template();self.settle()
        self.assertEqual(self.p.customer.currentData(),'B');self.assertEqual(self.p.template.currentData(),2)
        self.assertIsNone(self.p.source.currentData());self.assertFalse(self.p.generate_button.isEnabled())
        self.p.source.setCurrentIndex(ui.index_of(self.p.source,(NO_B,1)));self.settle()
        self.assertEqual(self.p.source.currentData(),(NO_B,1));self.assertTrue(self.p.generate_button.isEnabled())

if __name__=='__main__':unittest.main(verbosity=2)
