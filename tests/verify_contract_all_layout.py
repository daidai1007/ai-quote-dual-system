"""All contract surfaces: native Qt, synthetic long text, no business network."""
import os,sys,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
import verify_contract_ledger_layout as fixture
from PySide6.QtCore import Qt,QPoint,QRect,QSignalBlocker
from PySide6.QtWidgets import QLabel,QLineEdit,QComboBox,QPushButton,QPlainTextEdit,QWidget,QTableWidget,QScrollArea
from PySide6.QtGui import QPixmap,QColor
from unittest.mock import patch
import contract_management as ui

OUT=ROOT/'test-output/contract-all-layout';OUT.mkdir(parents=True,exist_ok=True)
def relative(w,parent):return QRect(w.mapTo(parent,QPoint(0,0)),w.size())
def issues(root):
    found=[];groups={}
    for w in root.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w,(QLabel,QLineEdit,QComboBox,QPushButton,QPlainTextEdit)):continue
        if isinstance(w,QLabel) and (not w.text() or w.pixmap() and not w.pixmap().isNull()):continue
        parent=w.parentWidget()
        if parent is None or parent.objectName()=='qt_scrollarea_viewport' or isinstance(parent,QComboBox):continue
        if w.height()+1<w.minimumSizeHint().height() and w.maximumHeight()>=w.minimumSizeHint().height():found.append('height '+type(w).__name__+' '+str(getattr(w,'text',lambda:'' )())[:35]+f' {w.height()} < {w.minimumSizeHint().height()}')
        if not parent.rect().contains(w.geometry()):found.append('outside '+type(w).__name__+' '+str(getattr(w,'text',lambda:'' )())[:35])
        groups.setdefault(parent,[]).append(w)
    for parent,widgets in groups.items():
        for i,w in enumerate(widgets):
            for other in widgets[i+1:]:
                if w.geometry().intersects(other.geometry()):found.append('overlap '+str(getattr(w,'text',lambda:'' )())[:25]+' / '+str(getattr(other,'text',lambda:'' )())[:25])
    return found

class AllContractLayout(unittest.TestCase):
    setUp=fixture.LedgerLayout.setUp
    cleanup=fixture.LedgerLayout.cleanup
    settle=fixture.LedgerLayout.settle
    def prepare(self):
        self.guard=patch.object(ui.ContractManagement,'request',return_value=False);self.guard.start();self.addCleanup(self.guard.stop)
        self.p.record_search_timer.stop();self.p.identity_timer.stop()
        self.p.notice.setText('合成提示：请核对合同信息。'*5)
        self.long='合成客户名称与专属合同模板名称需要完整核对'
        with QSignalBlocker(self.p.template),QSignalBlocker(self.p.source),QSignalBlocker(self.p.method):
            self.p.template.addItem(self.long*4,88);self.p.source.addItem('BJ-SYNTHETIC-000001 / V12 / '+self.long,('LOCAL',12));self.p.method.setCurrentIndex(1)
        self.p.customer_display.setText(self.long*3)
        ui.fill(self.p.items,[(self.long,'800×600×1800',2,'台','175.00','350.00')])
        self.p.source_info.setText('正式报价 V12 · '+self.long*2)
        for key,field in self.p.inputs.items():field.setText('本机合成测试文字'+('很长的地址' * 15 if 'address' in key else ''))
        ui.fill(self.p.library,[(self.long,self.long*3,'DOCX','V12','已配置','启用','本机测试人员')])
        ui.fill(self.p.records,[('HT-SYNTHETIC-20261103-000001','客户合同编号-000001',self.long,'BJ-SYNTHETIC-000001 / V12','快速报价','¥ 123,456.78',self.long*3+' / V12','DOCX','本机测试人员')])
        with QSignalBlocker(self.p.profile_customer):self.p.profile_customer.addItem(self.long*4,'LOCAL');self.p.profile_customer.setCurrentIndex(1)
        self.p.profile_name.setText(self.long*3)
        for key,field in self.p.profile_inputs.items():field.setText('合成数据'+('长地址'*30 if 'address' in key else '900000000000000000000'))
        ui.fill(self.l.documents,[('HT-SYNTHETIC-000001','2026-11-03',3,'750.29')])
        ui.fill(self.l.items,[('001 / 合成工作表:2',self.long,'800×600×1800',2,'台','175.00','350.00','人工备注：'+self.long*12)])
        with QSignalBlocker(self.l.output_choice):self.l.output_choice.addItem(self.long*6,1);self.l.output_choice.setCurrentIndex(1)
    def audit(self,name,width=1024,height=700):
        self.w.resize(width,height);self.settle();errors=issues(self.p)
        (OUT/f'{name}-{width}-scale-{fixture.SCALE}.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
        self.w.grab().save(str(OUT/f'{name}-{width}-scale-{fixture.SCALE}.png'))
        self.assertEqual(errors,[],name+'\n'+'\n'.join(errors))
    def test_quote_generation_and_profile(self):
        self.prepare();self.p.source_mode.setCurrentIndex(0);self.p.tabs.setCurrentIndex(0)
        self.audit('quote',1024,700);self.audit('quote',1536,800)
        self.p.tabs.setCurrentIndex(3);self.audit('profile',1024,700);self.audit('profile',1536,800)
    def test_template_library_and_records(self):
        self.prepare()
        for index,name in [(1,'templates'),(2,'records')]:self.p.tabs.setCurrentIndex(index);self.audit(name)
    def test_ledger_review_and_preview(self):
        self.prepare();self.p.tabs.setCurrentIndex(0);self.p.source_mode.setCurrentIndex(1)
        for index,name in [(1,'ledger-review'),(2,'ledger-preview')]:self.l.stack.setCurrentIndex(index);self.l.sync_actions();self.audit(name)
    def test_table_headers_are_readable(self):
        self.prepare()
        for tab,table in [(1,self.p.library),(2,self.p.records)]:
            self.p.tabs.setCurrentIndex(tab);self.w.resize(1024,700);self.settle()
            for col in range(table.columnCount()):
                required=table.horizontalHeader().fontMetrics().horizontalAdvance(table.horizontalHeaderItem(col).text())+16
                self.assertGreaterEqual(table.columnWidth(col),required,table.horizontalHeaderItem(col).text())
    def test_long_cells_wrap_and_fields_do_not_widen_customer_page(self):
        self.prepare();self.p.tabs.setCurrentIndex(3);self.w.resize(1024,700);self.settle()
        scroll=self.p.tabs.widget(3);self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
        self.assertEqual(self.p.profile_name.toolTip(),self.p.profile_name.text());self.assertEqual(self.p.profile_name.cursorPosition(),0)
        self.p.tabs.setCurrentIndex(0);self.p.source_mode.setCurrentIndex(1);self.l.stack.setCurrentIndex(1);self.settle()
        self.assertGreater(self.l.items.rowHeight(0),64);self.assertEqual(self.l.items.item(0,7).toolTip(),self.l.items.item(0,7).text())
    def test_mapping_dialog_docx_and_xlsx(self):
        self.prepare()
        for format in ('docx','xlsx'):
            result={'inspection':{'format':format,'rows':[{'label':'合成产品样板行','cells':[self.long]*6,'id':'LOCAL-ROW'}],
              'fields':{'buyer_name':'客户名称','total_amount':'合计金额'},'locations':[{'label':'合成段落','text':self.long*5,'id':'LOCAL-TARGET'}],
              'suggested':{'fields':[{'source':'buyer_name','target':'LOCAL-TARGET'}],'items':{'target':'LOCAL-ROW','columns':{}}}},'template':{}}
            dialog=ui.MappingDialog(result,self.p);dialog.resize(900,600);dialog.show();self.settle()
            self.assertEqual(issues(dialog),[]);self.assertGreater(dialog.row.width(),100)
            dialog.grab().save(str(OUT/f'mapping-{format}-scale-{fixture.SCALE}.png'));dialog.close();dialog.deleteLater();self.settle()
    def test_loaded_ledger_review_keeps_long_current_remark_and_money(self):
        from contract_ledger_test_data import write_ledger
        from contract_ledger import read_ledger,CUSTOMERS
        self.prepare();self.l.received({'ready':True,'drafts':[],'templates':[{'template_name':'合成模板','customer_name':CUSTOMERS['NUOYUE']['name'],'enabled':True,'configured':True,'template_version_id':1,'version_no':1}]})
        self.l.template.setCurrentIndex(1)
        source=write_ledger(OUT/f'synthetic-{fixture.SCALE}.xls');self.l.load_import(read_ledger(source,'NUOYUE'));self.l.select_all();self.l.go(1);self.w.resize(1024,700)
        self.l.items.item(0,7).setText('人工备注：'+self.long*12);self.settle()
        self.assertEqual(self.l.items.item(0,5).text(),'175.00');self.assertGreater(self.l.items.rowHeight(0),64)
        for table in (self.l.documents,self.l.items):
            for col in range(table.columnCount()):self.assertGreaterEqual(table.columnWidth(col),table.horizontalHeader().fontMetrics().horizontalAdvance(table.horizontalHeaderItem(col).text())+16)
    def test_customer_template_upload_dialog_long_names(self):
        self.prepare()
        for locked in (False,True):
            dialog=ui.TemplateUploadDialog(self.p,[self.long*8],self.long*8,'合成模板名称'*12,'合成合同文件名.xlsx',locked)
            dialog.resize(660,440);dialog.show();self.settle()
            self.assertEqual(issues(dialog),[]);self.assertLessEqual(dialog.width(),700)
            self.assertEqual(dialog.customer.currentText(),self.long*8)
            dialog.grab().save(str(OUT/f'template-upload-{locked}-scale-{fixture.SCALE}.png'));dialog.close();dialog.deleteLater();self.settle()

if __name__=='__main__':unittest.main()
