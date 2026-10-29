"""Supplier defaults and optional buyer contract number in the real Qt flow."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import unittest
from PySide6.QtCore import QSignalBlocker

import verify_contract_customer_flow as fixture
import contract_management as contracts


class ContractDefaults(unittest.TestCase):
    def setUp(self):
        self.h=fixture.ContractCustomerFlow();self.h.setUp()
        self.p=self.h.p;self.w=self.h.w
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.h.tearDown();self.h.doCleanups()

    def test_initial_supplier_is_editable_default_without_marking_unsaved(self):
        self.assertEqual(self.p.inputs['seller_name'].text(),'浙江京能电力设备有限公司')
        self.assertFalse(self.p.inputs['seller_name'].isReadOnly())
        self.assertFalse(self.p.unsaved)
        self.assertEqual(self.p.inputs['sign_date'].text(),contracts.contract_today())
        self.assertIn('留空',self.p.inputs['contract_no'].placeholderText())
        self.h.open_selected()
        image=Path(__file__).resolve().parents[1]/'.codex-tmp'/'contract-defaults.png'
        self.assertTrue(self.w.grab().save(str(image)))

    def test_manual_supplier_survives_source_reload_and_new_contract_restores_default(self):
        self.p.inputs['seller_name'].setText('本机人工供方')
        self.h.open_selected()
        self.assertEqual(self.p.inputs['seller_name'].text(),'本机人工供方')
        self.p.new_contract();self.h.settle()
        self.assertEqual(self.p.inputs['seller_name'].text(),contracts.DEFAULT_SELLER_NAME)
        self.assertEqual(self.p.inputs['contract_no'].text(),'')

    def test_empty_contract_number_reaches_generate_with_supplier_and_original_quote(self):
        self.h.open_selected()
        with QSignalBlocker(self.p.template):
            self.p.template.addItem('本机模板',77);self.p.template.setCurrentIndex(self.p.template.findData(77))
        self.p.mapping={'fields':[]}
        requests=[]
        with patch.object(self.p,'request',side_effect=lambda path,payload,callback:requests.append((path,deepcopy(payload)))):
            self.p.generate()
        self.assertEqual(len(requests),1)
        path,payload=requests[0]
        self.assertEqual(path,'/generate')
        self.assertEqual(payload['fields']['contract_no'],'')
        self.assertEqual(payload['fields']['seller_name'],contracts.DEFAULT_SELLER_NAME)
        self.assertEqual((payload['scheme_no'],payload['version_no']),(fixture.NO,2))

    def test_saved_draft_preserves_manual_supplier_and_missing_field_gets_default(self):
        self.h.open_selected()
        request=self.p.request
        template=dict(template_version_id=77,template_name='本机模板',file_format='docx',version_no=1,field_mapping={'fields':[]})
        def intercept(path,payload,callback,*args):
            if path=='/templates/77':callback({'template':template});return True
            return request(path,payload,callback,*args)
        for fields,expected in [({'seller_name':'本机草稿供方'},'本机草稿供方'),({},contracts.DEFAULT_SELLER_NAME),({'seller_name':''},'')]:
            with self.subTest(fields=fields),patch.object(self.p,'request',intercept):
                data=dict(scheme_no=fixture.NO,version_no=2,template_version_id=77,method='QUICK',fields=fields)
                self.p.data['drafts']=[dict(draft_id='LOCAL-DRAFT',input_payload=data,lock_version=1)]
                with QSignalBlocker(self.p.drafts):
                    self.p.drafts.clear();self.p.drafts.addItem('合成草稿','LOCAL-DRAFT')
                self.p.open_draft(0);self.h.settle()
                self.assertEqual(self.p.inputs['seller_name'].text(),expected)

    def test_historical_supplier_and_record_stay_unchanged(self):
        record={'record_no':'LOCAL-HISTORY','generation_snapshot':{'scheme_no':fixture.NO,'source_version':1,'method':'QUICK',
            'template_name':'历史模板','template_version':1,'mapping':{'fields':[]},
            'fields':{'buyer_name':'历史客户','seller_name':'历史供方','contract_no':'OLD','sign_date':'2020-01-02','buyer_contact':'历史联系人'},
            'quote':{'total':10,'total_upper':'壹拾元整','items':[]}}}
        original=deepcopy(record)
        self.p.show_history(record)
        self.assertEqual(self.p.inputs['seller_name'].text(),'历史供方')
        self.assertEqual(self.p.inputs['sign_date'].text(),'2020-01-02')
        self.assertEqual(self.p.inputs['buyer_contact'].text(),'历史联系人')
        self.assertTrue(self.p.inputs['seller_name'].isReadOnly())
        self.assertEqual(record,original)
        self.p.new_contract()
        self.assertEqual(self.p.inputs['seller_name'].text(),contracts.DEFAULT_SELLER_NAME)
        self.assertEqual(self.p.inputs['sign_date'].text(),contracts.contract_today())

    def test_manual_date_survives_reload_and_new_contract_uses_current_business_day(self):
        self.h.open_selected()
        self.p.inputs['sign_date'].setText('2020-01-02')
        self.p.reload();self.h.settle()
        self.assertEqual(self.p.inputs['sign_date'].text(),'2020-01-02')
        with patch.object(contracts,'contract_today',return_value='2026-10-29'):
            self.p.new_contract();self.h.settle()
            self.assertEqual(self.p.inputs['sign_date'].text(),'2026-10-29')
        self.assertNotIn('delivery_date',self.p.inputs)

    def test_draft_date_is_preserved_and_only_missing_date_defaults_to_today(self):
        self.h.open_selected()
        request=self.p.request
        template=dict(template_version_id=77,template_name='本机模板',file_format='docx',version_no=1,field_mapping={'fields':[]})
        def intercept(path,payload,callback,*args):
            if path=='/templates/77':callback({'template':template});return True
            return request(path,payload,callback,*args)
        for fields,expected in [({'sign_date':'2020-01-02'},'2020-01-02'),({},'2026-10-29'),({'sign_date':''},'')]:
            with self.subTest(fields=fields),patch.object(self.p,'request',intercept),patch.object(contracts,'contract_today',return_value='2026-10-29'):
                data=dict(scheme_no=fixture.NO,version_no=2,template_version_id=77,method='QUICK',fields=fields)
                self.p.data['drafts']=[dict(draft_id='LOCAL-DATE-DRAFT',input_payload=data,lock_version=1)]
                with QSignalBlocker(self.p.drafts):
                    self.p.drafts.clear();self.p.drafts.addItem('合成草稿','LOCAL-DATE-DRAFT')
                self.p.open_draft(0);self.h.settle()
                self.assertEqual(self.p.inputs['sign_date'].text(),expected)

    def test_business_day_is_shanghai_day_at_utc_midnight_boundary(self):
        from PySide6.QtCore import QDateTime, Qt
        for utc,expected in [('2026-10-28T15:59:59Z','2026-10-28'),('2026-10-28T16:00:00Z','2026-10-29')]:
            instant=QDateTime.fromString(utc,Qt.DateFormat.ISODate)
            with patch.object(contracts,'QDateTime') as clock:
                clock.currentDateTimeUtc.return_value=instant
                self.assertEqual(contracts.contract_today(),expected)

    def test_optional_contact_is_submitted_blank_or_as_manually_entered(self):
        self.h.open_selected()
        self.assertIn('留空',self.p.inputs['buyer_contact'].placeholderText())
        with QSignalBlocker(self.p.template):
            self.p.template.addItem('本机联系人模板',77);self.p.template.setCurrentIndex(self.p.template.findData(77))
        self.p.mapping={'fields':[{'source':'buyer_contact'}]}
        for contact in ('','本机人工联系人'):
            with self.subTest(contact=contact):
                self.p.inputs['buyer_contact'].setText(contact)
                requests=[]
                with patch.object(self.p,'request',side_effect=lambda path,payload,callback:requests.append((path,deepcopy(payload)))):
                    self.p.generate()
                self.assertEqual(len(requests),1)
                self.assertEqual(requests[0][0],'/generate')
                self.assertEqual(requests[0][1]['fields']['buyer_contact'],contact)
                self.assertNotIn('delivery_date',requests[0][1]['fields'])


if __name__=='__main__':unittest.main(verbosity=2)
