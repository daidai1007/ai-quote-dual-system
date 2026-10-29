"""Offline Qt state, source identity and layout using artificial ledgers."""
from copy import deepcopy
from pathlib import Path
import os,tempfile,unittest
from unittest.mock import patch
import verify_name_login as fixture
import name_login
import contract_management as ui
import contract_ledger_ui as ledgerui
from contract_ledger import CUSTOMERS,read_ledger,reopen_import,record_key
from contract_ledger_test_data import write_ledger
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent

class LedgerStateTests(unittest.TestCase):
    window=fixture.LoginTests.window
    def setUp(self):
        fixture.LoginTests.setUp(self);name_login.set_session(fixture.person('本机台账操作员'))
        self.temp=tempfile.TemporaryDirectory(prefix='ledger-state-');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.w=self.window();self.p=self.w.contract_management;self.l=self.p.ledger
        self.transport2=patch.object(self.p,'request',return_value=True);self.transport2.start()
        self.p.source_mode.setCurrentIndex(1);self.p.source_stack.setCurrentIndex(1)
        self.w.stack.setCurrentIndex(self.w.contract_management_route)
        self.l.received(dict(ready=True,drafts=[],templates=[dict(customer_name=c['name'],template_name='合成模板',enabled=True,configured=True,template_version_id=i+1,version_no=1) for i,c in enumerate(CUSTOMERS.values())]))
    def tearDown(self):
        self.transport2.stop();self.l.unsaved=False;self.p.unsaved=False;self.p.busy=False;self.p.queue.clear();self.p.shutdown();fixture.LoginTests.tearDown(self)

    def load(self,customer):
        self.l.customer.setCurrentIndex(self.l.customer.findData(customer));self.l.template.setCurrentIndex(1)
        data=read_ledger(write_ledger(self.folder/'synthetic.xls',customer),customer);self.l.load_import(data);return data

    def test_sheet_selections_and_reopen_preserve_all_rows_and_remarks(self):
        data=self.load('FANGYUAN');row=deepcopy(data['records'][0]);row.update(sheet='方圆接手2026',source_row=2)
        row['record_id']=record_key(data['source']['sha256'],row['sheet'],row['source_row']);data['records'].append(row)
        data['sheets'].append(dict(name=row['sheet'],header_row=1,record_count=1,columns={},warnings=[]))
        self.l.load_import(data);self.l.selection.item(0,0).setCheckState(Qt.CheckState.Checked)
        self.l.sheet.setCurrentIndex(1);self.l.selection.item(0,0).setCheckState(Qt.CheckState.Checked);self.l.go(1)
        self.assertEqual(self.l.items.rowCount(),2);self.l.items.item(0,7).setText('独立备注')
        self.l.go(0);self.l.go(1);self.assertEqual(self.l.items.item(0,7).text(),'独立备注')
        self.l.documents.item(0,0).setText('SYNTHETIC-REOPEN');payload=self.l.input_data()
        self.l.load_import(reopen_import(payload),payload);self.assertEqual(self.l.items.rowCount(),2)
        self.assertEqual(len(self.l.selected_keys),2);self.assertEqual(self.l.items.item(0,7).text(),'独立备注')
        self.assertEqual(self.l.input_data()['fields']['contract_no'],'SYNTHETIC-REOPEN')

    def test_unsaved_ledger_and_quote_guards_and_explicit_discard(self):
        self.load('NUOYUE');self.l.select_all();self.l.go(1)
        self.assertTrue(name_login.critical_tasks(self.w));self.p.unsaved=True
        self.l.unsaved=False;self.assertTrue(self.p.has_unsaved());self.l.unsaved=True
        self.p.unsaved=False
        with patch.object(ui.QMessageBox,'question',return_value=ui.QMessageBox.StandardButton.Save),patch.object(self.l,'save_draft') as save:
            event=QCloseEvent();self.w.closeEvent(event);self.assertFalse(event.isAccepted());save.assert_called_once()
        with patch.object(ui.QMessageBox,'question',return_value=ui.QMessageBox.StandardButton.Cancel):
            self.l.customer.setCurrentIndex(1);self.assertEqual(self.l.customer.currentData(),'NUOYUE')

    def test_export_cannot_overwrite_original_ledger_or_uploaded_template(self):
        data=self.load('NUOYUE');source=self.folder/'synthetic.xls'
        self.l.payload={'source':data['source']}
        self.assertFalse(self.l.validate_export_target(source))
        template=self.folder/'synthetic-template.xlsx';template.write_bytes(b'artificial-template')
        self.l.protected_paths.add(template.resolve());self.assertFalse(self.l.validate_export_target(template))
        self.assertTrue(self.l.validate_export_target(self.folder/'new-contract.xlsx'))

    def test_shared_library_template_can_be_selected_without_a_formal_quote(self):
        self.load('NUOYUE')
        template=dict(customer_code='SYNTHETIC',customer_name=CUSTOMERS['NUOYUE']['name'],template_name='合成共享模板',template_version_id=5,version_no=1,enabled=True,configured=True,can_use=True)
        self.p.data['sources']=[];self.p.data['templates']=[template]
        self.p.library.setRowCount(1);self.p.library.selectRow(0);self.p.tabs.setCurrentIndex(1)
        self.p.use_template();self.assertEqual(self.p.tabs.currentIndex(),0);self.assertEqual(self.l.template.currentData(),5)
        self.assertTrue(self.l.unsaved);self.assertIsNotNone(self.l.imported)

    def test_late_reader_after_identity_switch_cannot_restore_old_rows(self):
        held=[];path=write_ledger(self.folder/'synthetic.xls');old=read_ledger(path,'NUOYUE')
        with patch.object(ledgerui.ReadWorker,'start',lambda worker:held.append(worker)):
            self.l.read_file(path)
        worker=held[0];self.assertTrue(self.p.busy);self.assertFalse(self.p.source_mode.isEnabled())
        name_login.set_session(fixture.person('本机另一人员'));self.p.check_identity();worker._callbacks[0](old)
        self.assertIsNone(self.l.imported);self.assertIsNone(self.l.output)
        self.p.workers.remove(worker);worker.deleteLater();self.p.busy=False

    def test_selection_and_review_layout_at_desktop_and_laptop_width(self):
        self.load('NUOYUE');self.l.select_all()
        target=Path(os.environ.get('AI_QUOTE_CONTRACT_SCREENSHOT_DIR',str(self.folder)));target.mkdir(parents=True,exist_ok=True)
        scale=os.environ.get('QT_SCALE_FACTOR','1')
        for width,height in ((1519,986),(1024,768)):
            self.w.resize(width,height);fixture.APP.processEvents()
            for step in (0,1):
                self.l.go(step);fixture.APP.processEvents()
                self.assertGreater(self.l.stack.height(),200)
                for control in (self.l.save_button,self.l.generate_button):
                    self.assertTrue(self.l.rect().contains(control.mapTo(self.l,control.rect().bottomRight())),(scale,width,step,control.text()))
                self.assertGreater(self.l.selection.viewport().width(),200)
                self.w.grab().save(str(target/f'布局核对_缩放{scale}_{width}_步骤{step+1}.png'))

if __name__=='__main__':unittest.main(verbosity=2)
