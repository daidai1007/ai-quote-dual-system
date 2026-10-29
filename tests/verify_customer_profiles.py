"""Customer/buyer maintenance and automatic contract fields, offline real Qt."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from unittest.mock import patch
import json
import unittest

import verify_contract_customer_flow as fixture
import contract_management as contracts
from PySide6.QtTest import QTest

FIELDS=dict(buyer_address='本机测试地址',buyer_phone='057100000001',buyer_fax='057100000002',buyer_contact='',
 buyer_representative='本机需方代表',buyer_agent='本机代理人',buyer_bank_name='本机测试银行',buyer_bank_account='9000000000000000001',buyer_tax_no='T00000000000000001')

class CustomerProfiles(unittest.TestCase):
    def setUp(self):
        self.h=fixture.ContractCustomerFlow();self.h.setUp();self.p=self.h.p;self.w=self.h.w
        self.addCleanup(self.cleanup)
        self.profile=dict(customer_name=fixture.BUYER,customer_code=fixture.KEY,version=2,can_save=True,fields=deepcopy(FIELDS))
        self.calls=[];self.save_error=None
        original=contracts.ContractWorker.run
        def run(worker):
            path=urlparse(worker.url).path;self.calls.append((path,deepcopy(worker.payload)))
            if path.endswith('/customer-profile'):worker.result=deepcopy(self.profile)
            elif path.endswith('/customer-profile-save'):
                if self.save_error:worker.error=self.save_error
                else:
                    self.assertEqual(worker.payload['expected_version'],self.profile['version'])
                    self.profile.update(fields=deepcopy(worker.payload['fields']),version=self.profile['version']+1)
                    worker.result=deepcopy(self.profile)
            elif path.endswith('/templates/77'):
                worker.result={'template':dict(template_version_id=77,template_name='本机模板',file_format='docx',version_no=1,field_mapping={'fields':[]})}
            else:
                original(worker)
                if path.endswith('/quote') and worker.result:worker.result['customer_profile']=deepcopy(self.profile)
            worker.completed=True
        p=patch.object(contracts.ContractWorker,'run',run);p.start();self.addCleanup(p.stop)
        self.h.open_selected()

    def cleanup(self):
        self.p.profile_dirty=False;self.h.tearDown();self.h.doCleanups()

    def test_selected_quote_auto_fills_buyer_fields_and_supplier_remains_separate(self):
        for key,value in FIELDS.items():self.assertEqual(self.p.inputs[key].text(),value)
        self.assertEqual(self.p.inputs['seller_name'].text(),contracts.DEFAULT_SELLER_NAME)
        self.assertEqual(self.p.customer.currentText(),fixture.BUYER)
        self.assertEqual(self.p.profile_name.text(),fixture.BUYER)
        self.assertFalse(self.p.unsaved)
        self.p.tabs.setCurrentIndex(self.p.profile_tab);self.h.settle()
        self.w.resize(1440,1080);fixture.fixture.APP.processEvents()
        path=Path(__file__).resolve().parents[1]/'.codex-tmp'/'customer-profile-form.png'
        self.assertTrue(self.w.grab().save(str(path)))
        self.w.resize(1024,768);fixture.fixture.APP.processEvents();QTest.qWait(60)
        self.assertEqual(self.p.tabs.widget(self.p.profile_tab).horizontalScrollBar().maximum(),0)

    def test_manual_contract_override_survives_method_or_quote_reload(self):
        control=self.p.inputs['buyer_phone'];control.setFocus();control.selectAll();QTest.keyClicks(control,'MANUAL-001')
        self.assertIn('buyer_phone',self.p.profile_manual_fields)
        self.profile['fields']['buyer_phone']='057199999999'
        self.p.selection_changed();self.h.settle()
        self.assertEqual(control.text(),'MANUAL-001')
        self.p.unsaved=False;self.p.new_contract();self.h.settle()
        self.assertEqual(control.text(),'057199999999')

    def test_profile_import_and_save_preserve_long_identifiers_and_exact_version(self):
        self.p.tabs.setCurrentIndex(self.p.profile_tab);self.h.settle()
        with TemporaryDirectory(prefix='profile-import-') as directory:
            path=Path(directory)/'synthetic.json'
            fields={**FIELDS,'buyer_agent':'本机更新代理人'}
            path.write_text(json.dumps({'customer_name':fixture.BUYER,'fields':fields},ensure_ascii=False),encoding='utf-8')
            with patch.object(contracts.QFileDialog,'getOpenFileName',return_value=(str(path),'')):self.p.import_customer_profile()
            self.assertTrue(self.p.profile_dirty)
            self.p.profile_save_button.click();self.h.settle()
        self.assertFalse(self.p.profile_dirty);self.assertEqual(self.profile['version'],3)
        self.assertEqual(self.p.inputs['buyer_agent'].text(),'本机更新代理人')
        self.assertEqual(self.p.inputs['buyer_bank_account'].text(),FIELDS['buyer_bank_account'])

    def test_failed_profile_save_preserves_edits_and_explicit_use_only_changes_current_contract(self):
        self.p.profile_inputs['buyer_agent'].setText('本次代理人');self.p.profile_inputs['buyer_agent'].textEdited.emit('本次代理人')
        self.save_error='客户资料暂时无法保存'
        self.p.save_customer_profile();self.h.settle()
        self.assertTrue(self.p.profile_dirty);self.assertEqual(self.p.profile_inputs['buyer_agent'].text(),'本次代理人')
        self.p.use_customer_profile()
        self.assertEqual(self.p.inputs['buyer_agent'].text(),'本次代理人')
        self.assertEqual(self.profile['fields']['buyer_agent'],FIELDS['buyer_agent'])
        self.assertTrue(self.p.unsaved)

    def test_import_rejects_other_customer_and_numeric_account_without_overwriting_form(self):
        before={k:w.text() for k,w in self.p.profile_inputs.items()}
        with TemporaryDirectory(prefix='profile-invalid-') as directory:
            path=Path(directory)/'invalid.json'
            for payload in [{'customer_name':'另一个本机客户','fields':FIELDS},
                            {'customer_name':fixture.BUYER,'fields':{**FIELDS,'buyer_bank_account':9000000000000000001}}]:
                path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                with patch.object(contracts.QFileDialog,'getOpenFileName',return_value=(str(path),'')):self.p.import_customer_profile()
                self.assertEqual({k:w.text() for k,w in self.p.profile_inputs.items()},before)
            path.write_text(json.dumps({'customer_name':fixture.BUYER,'fields':{'buyer_agent':'局部更新代理人'}},ensure_ascii=False),encoding='utf-8')
            with patch.object(contracts.QFileDialog,'getOpenFileName',return_value=(str(path),'')):self.p.import_customer_profile()
            self.assertEqual(self.p.profile_inputs['buyer_bank_account'].text(),before['buyer_bank_account'])

    def test_saved_draft_buyer_fields_win_over_current_master_information(self):
        data=dict(scheme_no=fixture.NO,version_no=2,template_version_id=77,method='QUICK',fields={**FIELDS,'buyer_agent':'草稿代理人'})
        self.p.data['drafts']=[dict(draft_id='LOCAL-DRAFT',input_payload=data,lock_version=1)]
        with contracts.QSignalBlocker(self.p.drafts):self.p.drafts.clear();self.p.drafts.addItem('草稿','LOCAL-DRAFT')
        self.p.open_draft(0);self.h.settle()
        self.assertEqual(self.p.inputs['buyer_agent'].text(),'草稿代理人')
        self.assertEqual(data['fields']['buyer_agent'],'草稿代理人')

    def test_customer_profile_action_does_not_unlock_or_rewrite_historical_contract(self):
        record={'record_no':'LOCAL-HISTORY','generation_snapshot':{'scheme_no':fixture.NO,'source_version':1,'method':'QUICK',
            'template_name':'历史模板','template_version':1,'mapping':{'fields':[]},'fields':{'buyer_name':fixture.BUYER,'buyer_agent':'历史代理人'},
            'quote':{'total':10,'total_upper':'壹拾元整','items':[]}}}
        before=deepcopy(record);self.p.show_history(record)
        self.p.use_customer_profile()
        self.assertTrue(self.p.historical);self.assertEqual(self.p.inputs['buyer_agent'].text(),'历史代理人')
        self.assertEqual(record,before);self.assertFalse(self.p.profile_apply_button.isEnabled())


if __name__=='__main__':unittest.main(verbosity=2)
