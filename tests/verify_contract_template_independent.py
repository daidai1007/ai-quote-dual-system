"""Actual Qt -> real isolated HTTP API: template maintenance without a quote."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import unittest
from unittest.mock import patch
import verify_contract_management as fixture
from verify_contract_management import ui,APP,QDialog


class IndependentContractTemplates(unittest.TestCase):
    setUpClass=classmethod(fixture.ContractTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ContractTests.tearDownClass.__func__)
    setUp=fixture.ContractTests.setUp
    api=fixture.ContractTests.api
    close_window=fixture.ContractTests.close_window
    settled=fixture.ContractTests.settled

    def upload(self,format='docx',new_version=False):
        self.company='本机无报价模板客户'
        name='独立上传-'+self._testMethodName
        def details(dialog):
            self.assertEqual(dialog.customer.isEnabled(),not new_version)
            if not new_version:dialog.customer.setEditText(self.company);dialog.name.setText(name)
            else:self.assertEqual(dialog.customer.currentText(),self.company)
            dialog.accept();return QDialog.DialogCode.Accepted
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=(str(self.folder/('local-template.'+format)),'')),patch.object(ui.TemplateUploadDialog,'exec',details):
            self.p.upload(new_version);self.settled()
        row=next(row for row in self.p.data['templates'] if row['template_name']==name)
        self.p.library.selectRow(self.p.data['templates'].index(row));return row

    def empty_sources(self):
        self.p.received({**deepcopy(self.p.data),'sources':[]});self.p.tabs.setCurrentIndex(1);self.settled()
        self.assertIsNone(self.p.source.currentData())
        self.assertTrue(self.p.library_upload_button.isEnabled())

    def test_upload_and_configuration_without_formal_quote(self):
        self.empty_sources();row=self.upload()
        self.assertEqual(row['customer_name'],self.company)
        self.assertEqual(row['customer_code'],'contract-name:'+sha256(self.company.encode('utf8')).hexdigest())
        self.assertFalse(any(source['customer_name']==self.company for source in self.p.data['sources']))
        def configure(dialog):dialog.accept();return QDialog.DialogCode.Accepted
        with patch.object(ui.MappingDialog,'exec',configure):self.p.configure_library();self.settled()
        updated=next(r for r in self.p.data['templates'] if r['group_id']==row['group_id'])
        self.assertTrue(updated['configured']);self.assertEqual(updated['version_no'],2)
        self.p.reload();self.settled()
        self.assertTrue(any(r['group_id']==row['group_id'] and r['configured'] for r in self.p.data['templates']))
        self.assertFalse(self.p.generate_button.isEnabled())

    def test_new_version_uses_selected_template_customer_without_selecting_its_quote(self):
        self.empty_sources();first=self.upload('xlsx')
        self.p.customer.setCurrentIndex(0);self.p.tabs.setCurrentIndex(1)
        second=self.upload('xlsx',True)
        self.assertEqual(second['version_no'],2);self.assertEqual(second['group_id'],first['group_id'])
        self.assertEqual(len(self.api('/templates/'+str(second['template_version_id'])+'/versions')['items']),2)

    def test_dialog_empty_validation_cancellation_and_actual_layout(self):
        self.empty_sources()
        d=ui.TemplateUploadDialog(self.p,['本机已有客户'],'','测试模板','template.docx')
        self.addCleanup(d.close);d.accept();self.assertEqual(d.result(),QDialog.DialogCode.Rejected)
        self.assertIn('客户',d.notice.text())
        d.customer.setEditText('杭州浙达精益机电技术股份有限公司');d.show();APP.processEvents()
        self.assertTrue(d.customer.isEnabled());self.assertGreater(d.width(),500)
        out=fixture.ROOT/'.codex-tmp/independent-templates';out.mkdir(parents=True,exist_ok=True)
        self.assertTrue(d.grab().save(str(out/'upload-details.png')));d.reject()
        self.w.show_section(self.w.contract_management_route);self.p.tabs.setCurrentIndex(1)
        for width in (1024,1560):
            self.w.resize(width,960);APP.processEvents()
            self.assertTrue(self.p.library_upload_button.isVisible())
            self.assertTrue(self.w.grab().save(str(out/f'library-{width}.png')))
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=('','')),patch.object(self.p,'request') as request:
            self.p.upload();request.assert_not_called()

    def test_name_key_template_matches_later_catalogue_customer(self):
        name='本机以后建立档案的客户';code='contract-name:'+sha256(name.encode('utf8')).hexdigest()
        row=dict(customer_code=code,customer_name=name,enabled=True,configured=True,can_use=True)
        self.assertTrue(ui.template_matches_customer(row,'LATER-CATALOG',name))
        self.assertFalse(ui.template_matches_customer(row,'LATER-CATALOG','其他客户'))
        self.assertEqual(ui.contract_template_choices([row],'LATER-CATALOG',name),[row])


if __name__=='__main__':unittest.main(verbosity=2)
