"""Offline Qt state, source identity and layout using artificial ledgers."""
from copy import deepcopy
from hashlib import sha256
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
from PySide6.QtTest import QTest

class LedgerStateTests(unittest.TestCase):
    window=fixture.LoginTests.window
    def setUp(self):
        fixture.LoginTests.setUp(self);name_login.set_session(fixture.person('本机台账操作员'))
        self.temp=tempfile.TemporaryDirectory(prefix='ledger-state-');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.w=self.window();self.p=self.w.contract_management;self.l=self.p.ledger
        self.transport2=patch.object(self.p,'request',return_value=True);self.transport2.start()
        self.p.source_mode.setCurrentIndex(1);self.p.source_stack.setCurrentIndex(1)
        self.w.show_section(self.w.contract_management_route)
        self.l.received(dict(ready=True,drafts=[],templates=[dict(customer_name=c['name'],template_name='合成模板',enabled=True,configured=True,template_version_id=i+1,version_no=1) for i,c in enumerate(CUSTOMERS.values())]))
    def tearDown(self):
        self.transport2.stop();self.l.unsaved=False;self.p.unsaved=False;self.p.busy=False;self.p.queue.clear();self.p.shutdown();fixture.LoginTests.tearDown(self)

    def load(self,customer):
        self.l.customer.setCurrentIndex(self.l.customer.findData(customer));self.l.template.setCurrentIndex(1)
        data=read_ledger(write_ledger(self.folder/'synthetic.xls',customer),customer);self.l.load_import(data);return data

    def test_local_picker_reads_ledger_before_service_and_template_are_ready(self):
        self.l.received(dict(ready=False,templates=[],drafts=[],message='合成服务未启用'))
        path=write_ledger(self.folder/'synthetic-offline.xls')
        before=(sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns)
        self.assertTrue(self.l.read_button.isEnabled())
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=(str(path),'')) as picker,patch.object(self.p,'request') as remote:
            QTest.mouseClick(self.l.read_button,Qt.MouseButton.LeftButton)
            fixture.wait(lambda:self.l.imported is not None and not self.p.busy and not self.p.workers)
            picker.assert_called_once();remote.assert_not_called()
            self.l.select_all();self.l.go(1)
            self.assertEqual(self.l.items.rowCount(),3)
            self.assertFalse(self.l.save_button.isEnabled());self.assertFalse(self.l.generate_button.isEnabled())
        self.assertEqual(before,(sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns))
        self.l.go(0)
        self.assertIn('核对',self.l.read_button.toolTip())
        self.assertIn('服务',self.p.notice.text())
        screenshot=Path(os.environ.get('AI_QUOTE_CONTRACT_SCREENSHOT_DIR',str(self.folder)));screenshot.mkdir(parents=True,exist_ok=True)
        self.w.resize(1519,986);fixture.APP.processEvents();QTest.qWait(100)
        self.w.grab().save(str(screenshot/'台账服务未就绪_本机Excel仍可读取.png'))

    def test_local_picker_is_available_before_any_bootstrap_result(self):
        self.l.info={};self.l.sync_actions()
        self.assertTrue(self.l.read_button.isEnabled())
        self.assertFalse(self.l.save_button.isEnabled());self.assertFalse(self.l.generate_button.isEnabled())

    def test_missing_ledger_customer_template_borrows_and_keeps_current_customer(self):
        other=dict(customer_name='本机第三方模板客户',customer_code='THIRD',template_name='可借用模板',enabled=True,configured=True,buyer_configured=True,ledger_compatible=True,can_use=True,template_version_id=88,version_no=1)
        self.l.received(dict(ready=True,templates=[other],drafts=[]))
        self.assertEqual(self.l.template.currentData(),88);self.assertIn('借用',self.l.template.currentText())
        self.assertEqual(self.l.customer.currentData(),'NUOYUE')
        self.p.data['templates']=[other];self.p.library.setRowCount(1);self.p.library.selectRow(0)
        self.p.use_template();self.assertEqual(self.l.customer.currentData(),'NUOYUE')
        self.assertEqual(self.l.template.currentData(),88)
        self.load('NUOYUE');self.l.select_all();self.l.go(1)
        self.assertEqual(self.l.input_data()['customer_key'],'NUOYUE')
        self.assertEqual(self.l.input_data()['template_version_id'],88)
        self.l.go(0);self.w.resize(1519,986);fixture.APP.processEvents();QTest.qWait(100)
        self.assertTrue(self.w.grab().save(str(fixture.ROOT/'.codex-tmp'/'template-fallback-ledger.png')))
        self.l.received(dict(self.l.info,templates=[other,dict(other,customer_name=CUSTOMERS['NUOYUE']['name'],template_version_id=89)]))
        self.assertLess(self.l.template.findData(88),0)
        self.assertGreater(self.l.template.findData(89),0)

    def test_unready_service_blocks_remote_writes_even_with_previous_template_and_rows(self):
        self.load('NUOYUE');self.l.select_all();self.l.go(1)
        self.l.info['ready']=False;self.l.sync_actions()
        self.assertFalse(self.l.save_button.isEnabled());self.assertFalse(self.l.generate_button.isEnabled())
        with patch.object(self.p,'request') as remote:
            self.l.save_draft();self.l.generate();remote.assert_not_called()
        self.assertIn('服务',self.p.notice.text())
        self.l.received(dict(self.l.info,ready=True))
        self.assertTrue(self.l.save_button.isEnabled());self.assertTrue(self.l.generate_button.isEnabled())
        self.assertEqual(self.l.read_button.toolTip(),'')

    def test_failed_bootstrap_keeps_local_reading_and_rows_available(self):
        self.load('NUOYUE');self.l.select_all();keys=set(self.l.selected_keys)
        with patch.object(self.p,'request') as remote:
            self.l.reload()
            remote.call_args.kwargs['on_error']('合成网络不可用')
        self.assertFalse(self.l.info['ready']);self.assertTrue(self.l.read_button.isEnabled())
        self.assertEqual(self.l.selected_keys,keys);self.assertIsNotNone(self.l.imported)
        self.assertFalse(self.l.generate_button.isEnabled())

    def test_busy_picker_and_discard_cancellation_still_protect_local_work(self):
        self.load('NUOYUE');original=self.l.imported
        self.p.busy=True;self.l.sync_actions()
        with patch.object(ui.QFileDialog,'getOpenFileName') as picker:
            QTest.mouseClick(self.l.read_button,Qt.MouseButton.LeftButton);picker.assert_not_called()
        self.p.busy=False;self.l.sync_actions()
        with patch.object(ui.QMessageBox,'question',return_value=ui.QMessageBox.StandardButton.Cancel):
            self.l.read_file(self.folder/'must-not-read.xls')
        self.assertIs(self.l.imported,original)

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
