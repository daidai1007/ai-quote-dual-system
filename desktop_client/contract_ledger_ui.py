"""Ledger contracts: select source, confirm frozen rows, inspect actual output.

Source workbooks are only read by the local worker. Only selected rows are sent
to the named-user API; reopening uses the saved snapshot, never the live ledger.
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import base64
import json
from uuid import uuid4

from PySide6.QtCore import Qt, QThread, QSignalBlocker, QTimer, QEvent
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedWidget, QLineEdit, QFileDialog, QMessageBox, QLabel, QScrollArea,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QStyledItemDelegate,
    QPlainTextEdit, QDialog)
import contract_management as contracts
from contract_ledger import (CUSTOMERS, LedgerError, read_ledger, contract_groups,
    selected_payload, reopen_import)

METRICS = dict(gap=12, selection_height=200, row_height=64, preview_height=260)
READ_ONLY = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
SERVICE_WAIT_MESSAGE = '台账合同服务暂未就绪，可先选择并核对 Excel 台账；暂不能保存或生成合同。可点击“重新加载”重试。'


class ReadWorker(QThread):
    def __init__(self, path, customer, parent):
        super().__init__(parent)
        self.args=(path,customer);self.result=None;self.error=None;self.completed=False

    def run(self):
        try:
            result=read_ledger(*self.args)
            if not self.isInterruptionRequested():self.result=result
        except Exception as error:
            if not self.isInterruptionRequested():
                self.error=str(error) if isinstance(error,(LedgerError,OSError)) else '台账读取失败，请核对文件格式及表头。'
        finally:self.completed=True


class RemarkDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):return QPlainTextEdit(parent)
    def setEditorData(self,editor,index):editor.setPlainText(str(index.data() or ''))
    def setModelData(self,editor,model,index):model.setData(index,editor.toPlainText())


class LedgerContractPanel(QWidget):
    def __init__(self,manager):
        super().__init__();self.manager=manager;self.window=manager.window;self.notice=manager.notice
        self.imported=None;self.payload=None;self.unsaved=False;self.draft=None;self.record=None
        self.output=None;self.preview_pages=[];self.request_id=str(uuid4());self.populating=False
        self.info={};self.generated_records=[];self.groups=[];self.selected_keys=set();self.historical=False
        self.protected_paths=set()
        root=QVBoxLayout(self);root.setContentsMargins(0,12,0,0);root.setSpacing(METRICS['gap'])
        self.steps=QHBoxLayout();self.step_buttons=[]
        for index,title in enumerate(('1  选择台账记录','2  核对合同信息','3  预览与输出')):
            control=contracts.button(title,lambda checked=False,i=index:self.go(i))
            self.steps.addWidget(control);self.step_buttons.append(control)
        root.addLayout(self.steps);self.stack=QStackedWidget();root.addWidget(self.stack,1)
        self.build_select();self.build_review();self.build_preview()
        footer=QHBoxLayout();self.drafts=contracts.SchemeComboBox();self.drafts.addItem('打开台账合同草稿',None)
        self.drafts.setMinimumWidth(0);self.drafts.activated.connect(self.open_draft);footer.addWidget(self.drafts,1)
        self.save_button=contracts.button('保存生成草稿',self.save_draft)
        self.generate_button=contracts.button('生成合同',self.generate,True)
        footer.addWidget(self.save_button);footer.addWidget(self.generate_button);root.addLayout(footer)
        self.sync_actions()

    @property
    def busy(self):return self.manager.busy
    @busy.setter
    def busy(self,value):self.manager.busy=value
    @property
    def identity(self):return self.manager.identity
    @property
    def workers(self):return self.manager.workers
    @property
    def poll_timer(self):return self.manager.poll_timer
    @property
    def temp_dirs(self):return self.manager.temp_dirs
    def request(self,*args,**kwargs):return self.manager.request(*args,**kwargs)
    def worker_finished(self,worker):self.manager.worker_finished(worker)

    def build_select(self):
        page=QWidget();box=QVBoxLayout(page);box.setContentsMargins(0,0,0,0)
        frame,content=contracts.card('从 Excel 台账生成合同','诺玥按钉钉合同号分组；方圆将选中序号合并为一份合同。')
        grid=QGridLayout();self.customer=contracts.SchemeComboBox()
        for key,entry in CUSTOMERS.items():self.customer.addItem(entry['name'],key)
        self.customer.currentIndexChanged.connect(self.customer_changed)
        self.template=contracts.SchemeComboBox();self.template.setMinimumWidth(0)
        self.template.currentIndexChanged.connect(self.template_changed)
        grid.addWidget(contracts.label('客户'),0,0);grid.addWidget(self.customer,1,0)
        grid.addWidget(contracts.label('客户合同模板'),0,1);grid.addWidget(self.template,1,1)
        grid.addWidget(contracts.button('上传客户模板',self.upload),1,2)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1);content.addLayout(grid)
        row=QHBoxLayout();self.filename=QLineEdit();self.filename.setReadOnly(True);self.filename.setPlaceholderText('选择已有总订单台账（.xls / .xlsx）')
        row.addWidget(self.filename,1);self.read_button=contracts.button('选择 Excel 台账',self.pick_file);row.addWidget(self.read_button);content.addLayout(row)
        row=QHBoxLayout();self.sheet=contracts.SchemeComboBox();self.sheet.currentIndexChanged.connect(self.sheet_changed)
        self.search=QLineEdit();self.search.setPlaceholderText('查找原序号、合同号或产品名称');self.search.textChanged.connect(self.filter_groups)
        row.addWidget(contracts.label('工作表'));row.addWidget(self.sheet);row.addWidget(self.search,1);content.addLayout(row)
        self.source_note=contracts.label('仅读取台账，不修改原文件。','contractNote');self.source_note.setWordWrap(True);content.addWidget(self.source_note)
        box.addWidget(frame)
        self.selection=contracts.table(('选择','钉钉合同号 / 原序号','来源序号','产品 / 明细数','台账合计','核对状态'),'ledgerSelection')
        self.selection.setMinimumHeight(METRICS['selection_height']);self.selection.setMaximumHeight(16777215)
        self.selection.itemChanged.connect(self.selection_edited);self.selection.itemDoubleClicked.connect(self.source_detail)
        box.addWidget(self.selection,1)
        row=QHBoxLayout();self.selection_note=contracts.label('请选择客户及台账。','contractNote');self.selection_note.setWordWrap(True)
        row.addWidget(self.selection_note,1);row.addWidget(contracts.button('全选可用记录',self.select_all));row.addWidget(contracts.button('清除选择',self.clear_selection))
        row.addWidget(contracts.button('下一步：核对信息',lambda:self.go(1),True));box.addLayout(row)
        self.stack.addWidget(page)

    def build_review(self):
        page=QWidget();box=QVBoxLayout(page);box.setContentsMargins(0,0,0,0)
        self.review_note=contracts.label('合同名称、规格、数量和金额读取台账；备注可修改。','contractNote');self.review_note.setWordWrap(True);box.addWidget(self.review_note)
        self.documents=contracts.table(('本次合同编号','签约日期（YYYY-MM-DD）','明细行数','合同合计'),'ledgerDocuments')
        self.documents.setMaximumHeight(150);self.documents.cellChanged.connect(self.document_edited);box.addWidget(self.documents)
        self.items=contracts.table(('原序号 / 工作表行','产品名称','规格型号','数量','单位','含税单价','金额','备注（可人工修改）'),'ledgerItems')
        self.items.setMaximumHeight(16777215);self.items.setWordWrap(True)
        self.items.setItemDelegateForColumn(7,RemarkDelegate(self.items));self.items.cellChanged.connect(self.remark_edited)
        box.addWidget(self.items,1)
        row=QHBoxLayout();self.amount=contracts.label('合计：—','contractHeading');row.addWidget(self.amount,1)
        row.addWidget(contracts.button('恢复选中行的台账备注',self.restore_remark));row.addWidget(contracts.button('返回选择',lambda:self.go(0)));box.addLayout(row)
        self.stack.addWidget(page)

    def build_preview(self):
        page=QWidget();box=QVBoxLayout(page);box.setContentsMargins(0,0,0,0)
        row=QHBoxLayout();self.output_choice=contracts.SchemeComboBox();self.output_choice.setMinimumWidth(0)
        self.output_choice.activated.connect(self.choose_output);row.addWidget(self.output_choice,1)
        self.original_button=contracts.button('打开原文件',self.open_original);self.print_button=contracts.button('打印',self.print_file)
        self.export_button=contracts.button('导出合同',self.export_file,True)
        for button in (self.original_button,self.print_button,self.export_button):row.addWidget(button)
        row.addWidget(contracts.button('新建台账合同',self.new_contract))
        box.addLayout(row);self.preview_info=contracts.label('生成后显示实际合同文件。','contractNote');self.preview_info.setWordWrap(True);box.addWidget(self.preview_info)
        self.preview_scroll=QScrollArea();self.preview_scroll.setWidgetResizable(True);self.preview_scroll.viewport().installEventFilter(self)
        tray=QWidget();tray.setObjectName('contractPaperTray');self.pagebox=QVBoxLayout(tray)
        self.pagebox.setAlignment(Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop)
        self.pagebox.addWidget(contracts.label('此处预览实际生成文件，核对原有条款、签章区域和分页。','contractNote'))
        self.preview_scroll.setWidget(tray);box.addWidget(self.preview_scroll,1);self.stack.addWidget(page)

    def reload(self):
        self.request('/ledger/bootstrap',None,self.received,on_error=self.bootstrap_failed)

    def bootstrap_failed(self,message):
        # Keep locally read rows and remarks when the remote service is down.
        self.info={**self.info,'ready':False}
        self.notice.setText(message);self.sync_actions()

    def received(self,result):
        self.info=result;selected=self.template.currentData();self.sync_templates(selected)
        with QSignalBlocker(self.drafts):
            self.drafts.clear();self.drafts.addItem('打开台账合同草稿',None)
            for d in result.get('drafts',[]):self.drafts.addItem(d['customer_name']+' · '+d['filename']+' · '+str(d['item_count'])+' 行',d['draft_id'])
        if not result.get('ready'):self.notice.setText(SERVICE_WAIT_MESSAGE)
        else:self.notice.setText('台账合同模板与本人草稿已加载。')
        self.sync_actions()

    def sync_templates(self,selected=None):
        name=CUSTOMERS[self.customer.currentData()]['name']
        choices=contracts.contract_template_choices([t for t in self.info.get('templates',[]) if t.get('configured')],name=name,ledger=True)
        with QSignalBlocker(self.template):
            self.template.clear();self.template.addItem('请选择已配置的客户模板',None)
            for t in choices:
                self.template.addItem(t['template_name']+' · V'+str(t['version_no'])+contracts.borrowed_template_label(t,name=name),t['template_version_id'])
            default=next((t for t in choices if not contracts.template_matches_customer(t,name=name)),None) if selected is None else None
            self.template.setCurrentIndex(max(0,self.template.findData(default['template_version_id'] if default else selected)))
        self.template.setToolTip('借用其他客户模板时，需方和金额仍取当前台账，请核对模板固定条款。' if any(not contracts.template_matches_customer(t,name=name) for t in choices) else '')

    def confirm_discard(self):
        return not self.unsaved or QMessageBox.question(self,'合同信息尚未保存','放弃当前未保存的台账合同信息？',QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)==QMessageBox.StandardButton.Discard

    def customer_changed(self):
        if self.populating:return
        old=self.imported['customer_key'] if self.imported else None
        if old and old!=self.customer.currentData() and not self.confirm_discard():
            with QSignalBlocker(self.customer):self.customer.setCurrentIndex(self.customer.findData(old))
            return
        self.clear_work();self.sync_templates()

    def clear_work(self):
        self.imported=None;self.payload=None;self.selected_keys=set();self.groups=[];self.draft=None;self.unsaved=False;self.historical=False
        self.filename.clear();self.sheet.clear();self.selection.setRowCount(0);self.items.setRowCount(0);self.documents.setRowCount(0)
        self.invalidate();self.stack.setCurrentIndex(0);self.sync_actions()

    def reset_identity(self):
        self.clear_work();self.info={};self.sync_templates();self.drafts.clear();self.drafts.addItem('打开台账合同草稿',None)

    def invalidate(self):
        self.request_id=str(uuid4());self.record=None;self.output=None;self.preview_pages=[];self.generated_records=[]
        with QSignalBlocker(self.output_choice):self.output_choice.clear()
        while self.pagebox.count():
            item=self.pagebox.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.preview_info.setText('信息已变化，请重新生成合同后核对实际文件。');self.sync_actions()

    def changed(self):
        if self.populating:return
        self.unsaved=True;self.invalidate()

    def template_changed(self):
        if self.imported:self.changed()

    def pick_file(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'选择客户 Excel 台账','','Excel 台账 (*.xls *.xlsx)')
        if path:self.read_file(path)

    def read_file(self,path):
        if self.busy or not self.confirm_discard():return
        key=self.customer.currentData();identity=dict(self.identity)
        worker=ReadWorker(path,key,self.manager);worker._contract_identity=identity
        self.busy=True;self.manager.sync_actions();self.notice.setText('正在只读解析台账，请稍候…');self.workers.append(worker)
        def success(result):
            if identity!=self.identity:return
            self.protected_paths.add(Path(path).resolve())
            self.busy=False;self.load_import(result)
            self.notice.setText('台账已只读加载，请选择记录。双击记录可核对来源字段。' if self.info.get('ready') else '台账已只读加载；服务暂未就绪，可先核对，暂不能保存或生成合同。')
        def failed(message):
            if identity!=self.identity:return
            self.busy=False;self.notice.setText(message);self.manager.sync_actions()
        worker._callbacks=(success,failed,lambda:self.worker_finished(worker));self.poll_timer.start();worker.start()

    def load_import(self,result,payload=None):
        selected_template=self.template.currentData()
        self.populating=True
        self.imported=result;self.payload=deepcopy(payload);self.draft=None;self.historical=False
        self.selected_keys=set();self.filename.setText(result['source']['filename'])
        self.customer.setCurrentIndex(self.customer.findData(result['customer_key']));self.sync_templates(payload.get('template_version_id') if payload else selected_template)
        with QSignalBlocker(self.sheet):
            self.sheet.clear()
            for sheet in result['sheets']:self.sheet.addItem(sheet['name'],sheet['name'])
        self.populating=False;self.unsaved=payload is None;self.invalidate();self.sheet_changed()
        if payload:
            self.selected_keys={g['key'] for g in contract_groups(result)};self.render_groups();self.render_review();self.stack.setCurrentIndex(1)
        self.sync_actions()

    def sheet_changed(self):
        if self.populating or not self.imported:return
        # Selection is keyed by physical row. A sheet switch preserves selections
        # in other sheets; the summary explicitly includes them.
        self.groups=contract_groups(self.imported,self.sheet.currentData())
        entry=next((s for s in self.imported['sheets'] if s['name']==self.sheet.currentData()),{})
        self.source_note.setText('原文件只读 · '+str(entry.get('record_count',0))+' 条记录 · '+
            ('按钉钉合同号选择会包含该合同号下的全部明细。' if self.customer.currentData()=='NUOYUE' else '勾选的原序号将合并到一份新合同。')+' '+ ' '.join(entry.get('warnings',[])))
        self.render_groups()

    def render_groups(self):
        with QSignalBlocker(self.selection):
            self.selection.setRowCount(len(self.groups))
            for i,g in enumerate(self.groups):
                amount=sum((Decimal(r['total']) for r in g['records'] if r['total']),Decimal(0))
                values=('',g['number'] or '缺少钉钉合同号','、'.join(r['serial'] for r in g['records']),
                    g['records'][0]['name']+(' 等 '+str(len(g['records']))+' 条' if len(g['records'])>1 else ''),f'¥ {amount:,.2f}',
                    '；'.join(dict.fromkeys(g['issues'])) or '可生成')
                for col,value in enumerate(values):
                    cell=QTableWidgetItem(value);cell.setFlags(READ_ONLY);self.selection.setItem(i,col,cell)
                cell=self.selection.item(i,0)
                if not g['issues']:cell.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable)
                cell.setCheckState(Qt.CheckState.Checked if g['key'] in self.selected_keys else Qt.CheckState.Unchecked)
                self.selection.item(i,5).setToolTip(values[5])
        for col,width in ((0,48),(1,170),(2,120),(3,210),(4,120)):
            self.selection.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Interactive);self.selection.setColumnWidth(col,width)
        self.filter_groups();self.update_selection_note()

    def filter_groups(self):
        search=self.search.text().strip().casefold()
        for i,g in enumerate(self.groups):self.selection.setRowHidden(i,bool(search and search not in json.dumps(g,ensure_ascii=False).casefold()))

    def selection_edited(self,item):
        if item.column()!=0:return
        group=self.groups[item.row()]
        if item.checkState()==Qt.CheckState.Checked:self.selected_keys.add(group['key'])
        else:self.selected_keys.discard(group['key'])
        self.changed();self.update_selection_note()

    def select_all(self):
        for i,g in enumerate(self.groups):
            if not g['issues'] and not self.selection.isRowHidden(i):self.selection.item(i,0).setCheckState(Qt.CheckState.Checked)

    def clear_selection(self):
        self.selected_keys.clear();self.changed();self.render_groups()

    def update_selection_note(self):
        groups=[g for g in contract_groups(self.imported) if g['key'] in self.selected_keys] if self.imported else []
        count=sum(len(g['records']) for g in groups);docs=len(groups) if self.customer.currentData()=='NUOYUE' else bool(groups)
        self.selection_note.setText(f'已选 {count} 条产品明细，将生成 {int(docs)} 份合同（含其他工作表已选记录）。')
        self.sync_actions()

    def source_detail(self,item):
        group=self.groups[item.row()];dialog=QDialog(self);dialog.setWindowTitle('台账来源核对');dialog.resize(850,500)
        box=QVBoxLayout(dialog);grid=contracts.table(('工作表 / 原始行','原序号','合同号','名称','备注'),'ledgerOrigins')
        contracts.fill(grid,[(r['sheet']+' / '+str(r['source_row']),r['serial'],r['contract_no'],r['name'],r['remark']) for r in group['records']]);grid.setMaximumHeight(16777215)
        box.addWidget(grid,1);box.addWidget(contracts.label('备注读取产品明细旁的备注列；这里保留台账原文。','contractNote'));box.addWidget(contracts.button('关闭',dialog.accept));dialog.exec()

    def prepare_review(self):
        if not self.imported:raise LedgerError('请先选择 Excel 台账')
        previous=self.payload or {}
        self.payload=selected_payload(self.imported,self.selected_keys,previous.get('remarks'),previous.get('fields'),previous.get('document_fields'))
        group_keys={r['contract_no'] for r in self.payload['records']}
        self.payload['document_fields']=[d for d in self.payload['document_fields'] if d['contract_no'] in group_keys]
        self.payload['template_version_id']=self.template.currentData()
        self.render_review()

    def render_review(self):
        if not self.payload:return
        self.populating=True
        rows=self.payload['records'];ny=self.payload['customer_key']=='NUOYUE'
        grouped={}
        for r in rows:grouped.setdefault(r['contract_no'] if ny else 'MERGED',[]).append(r)
        fields=self.payload.get('fields',{});overrides={d['contract_no']:d for d in self.payload.get('document_fields',[])}
        self.doc_keys=list(grouped)
        with QSignalBlocker(self.documents):
            self.documents.setRowCount(len(grouped))
            for i,(key,records) in enumerate(grouped.items()):
                source_dates=set(r['source_date'] for r in records if r['source_date'])
                source_date=next(iter(source_dates)) if len(source_dates)==1 else ('' if source_dates else contracts.contract_today())
                sign=overrides.get(key,{}).get('sign_date',fields.get('sign_date',source_date if ny else contracts.contract_today()))
                values=(key if ny else fields.get('contract_no',''),sign,str(len(records)),f"¥ {sum(Decimal(r['total']) for r in records):,.2f}")
                for col,value in enumerate(values):
                    cell=QTableWidgetItem(value);cell.setFlags(READ_ONLY | (Qt.ItemFlag.ItemIsEditable if col==1 or (col==0 and not ny) else Qt.ItemFlag.NoItemFlags));self.documents.setItem(i,col,cell)
        with QSignalBlocker(self.items):
            self.items.setRowCount(len(rows))
            for i,r in enumerate(rows):
                values=(r['serial']+' / '+r['sheet']+':'+str(r['source_row']),r['name'],r['specification'],r['quantity'],r['unit'],f"{Decimal(r['unit_price']):,.2f}",f"{Decimal(r['total']):,.2f}",self.payload.get('remarks',{}).get(r['record_id'],r['remark']))
                for col,value in enumerate(values):
                    cell=QTableWidgetItem(value);cell.setFlags(READ_ONLY | (Qt.ItemFlag.ItemIsEditable if col==7 else Qt.ItemFlag.NoItemFlags));self.items.setItem(i,col,cell)
                self.items.item(i,7).setToolTip('台账原备注：\n'+r['remark']);self.items.setRowHeight(i,METRICS['row_height'])
        for col,width in enumerate((145,145,150,58,45,100,110,250)):
            self.items.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Interactive);self.items.setColumnWidth(col,width)
        self.items.horizontalHeader().setSectionResizeMode(7,QHeaderView.ResizeMode.Stretch)
        self.amount.setText(f"{len(grouped)} 份合同 · 合计 ¥ {sum(Decimal(r['total']) for r in rows):,.2f}")
        self.review_note.setText(('诺玥：相同钉钉合同号写入一份合同，产品名称以台账名称为准。' if ny else '方圆：选中序号合并为一份合同，请填写本次新合同编号与签约日期。')+' 双击备注可编辑；修改仅用于当前合同，不回写台账。')
        self.populating=False
        # Persist the displayed default dates as explicit confirmed input.
        self.capture_documents();self.sync_actions()

    def capture_documents(self):
        if not self.payload:return
        if self.payload['customer_key']=='FANGYUAN':
            self.payload['fields']['contract_no']=self.documents.item(0,0).text().strip()
            self.payload['fields']['sign_date']=self.documents.item(0,1).text().strip()
            self.payload['document_fields']=[]
        else:self.payload['document_fields']=[dict(contract_no=key,sign_date=self.documents.item(i,1).text().strip()) for i,key in enumerate(self.doc_keys)]

    def document_edited(self,*_):
        if self.populating or not self.payload:return
        self.capture_documents();self.changed()

    def remark_edited(self,row,col):
        if self.populating or col!=7 or not self.payload:return
        record=self.payload['records'][row];self.payload['remarks'][record['record_id']]=self.items.item(row,7).text();self.changed()

    def restore_remark(self):
        row=self.items.currentRow()
        if self.payload and 0<=row<len(self.payload['records']):self.items.item(row,7).setText(self.payload['records'][row]['remark'])

    def go(self,index):
        if self.busy:return
        try:
            if index==1 and self.stack.currentIndex()==0:self.prepare_review()
            if index==2 and not self.record:raise LedgerError('请先核对并生成合同，再预览实际文件')
            if self.historical and index!=2:raise LedgerError('历史合同为只读文件，请重新选择台账创建新合同')
            self.stack.setCurrentIndex(index);self.sync_actions()
            if index==1 and not self.info.get('ready'):self.notice.setText(SERVICE_WAIT_MESSAGE)
        except LedgerError as error:self.notice.setText(str(error))

    def input_data(self):
        if not self.info.get('ready'):
            raise LedgerError(SERVICE_WAIT_MESSAGE)
        if self.stack.currentIndex()==0:self.prepare_review()
        if not self.payload:raise LedgerError('请先选择台账记录')
        if not self.template.currentData():raise LedgerError('请选择已配置的客户合同模板')
        self.capture_documents();value=deepcopy(self.payload);value['template_version_id']=self.template.currentData();return value

    def save_draft(self):
        try:value=self.input_data()
        except LedgerError as error:self.notice.setText(str(error));return
        if self.draft:value.update(draft_id=self.draft['draft_id'],expected_version=self.draft['lock_version'])
        def saved(result):
            self.draft=result;self.unsaved=False;self.notice.setText('台账合同草稿已保存，重新打开无需原台账。');self.reload()
        self.request('/ledger/drafts',value,saved)

    def open_draft(self,index):
        id=self.drafts.itemData(index)
        if not id or not self.confirm_discard():return
        def loaded(result):
            payload=result['input_payload'];self.load_import(reopen_import(payload),payload);self.draft=result;self.unsaved=False
            self.notice.setText('已打开保存的台账合同草稿，未重新读取原台账。')
        self.request('/ledger/drafts/'+id,None,loaded)

    def generate(self):
        if self.historical or self.busy:return
        try:value=self.input_data()
        except LedgerError as error:self.notice.setText(str(error));return
        value['request_id']=self.request_id
        self.request('/ledger/generate',value,self.generated)

    def generated(self,result):
        contracts.contract_schemes_changed(self.window,[r.get('scheme') for r in result['records']])
        self.generated_records=result['records'];self.unsaved=False
        self.output_choice.clear()
        for r in self.generated_records:self.output_choice.addItem(r['generation_snapshot']['fields']['contract_no']+' · '+r['record_no'],r['record_id'])
        self.stack.setCurrentIndex(2);self.choose_output(0)

    def choose_output(self,index):
        if not 0<=index<len(self.generated_records):return
        self.output=None;self.preview_pages=[];self.record=self.generated_records[index]
        while self.pagebox.count():
            item=self.pagebox.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.download(self.record)

    def show_history(self,result,can_download,export=False):
        self.historical=True;self.unsaved=False;self.generated_records=[result];self.record=result
        self.output=None;self.preview_pages=[];self.output_choice.clear();self.output_choice.addItem(result['record_no'],result['record_id'])
        self.stack.setCurrentIndex(2)
        snapshot=result['generation_snapshot'];self.preview_info.setText('历史台账合同只读 · '+snapshot['customer_name']+' · '+snapshot['fields']['contract_no'])
        if can_download:self.download(result,export)
        else:
            while self.pagebox.count():
                item=self.pagebox.takeAt(0)
                if item.widget():item.widget().deleteLater()
            self.notice.setText('可查看合同记录；原文件、打印与导出仅限生成人。')
        self.sync_actions()

    def new_contract(self):
        if self.busy or not self.confirm_discard():return
        self.clear_work();self.sync_templates();self.notice.setText('请选择台账创建新的合同。')

    def upload(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'上传该客户合同模板','','合同模板 (*.docx *.xlsx)')
        if not path:return
        source=Path(path)
        try:
            if source.stat().st_size>contracts.METRICS['upload_bytes']:raise LedgerError('模板超过 8MB')
            data=source.read_bytes()
        except (OSError,LedgerError) as error:self.notice.setText(str(error));return
        self.protected_paths.add(source.resolve())
        value=dict(customer_key=self.customer.currentData(),filename=source.name,template_name=source.stem,format=source.suffix[1:].lower(),content=base64.b64encode(data).decode('ascii'))
        def uploaded(result):
            if not result.get('auto_configured'):
                self.notice.setText('模板已上传，请在“客户模板”中配置字段位置后使用。');self.manager.reload();return
            id=result['template_version_id']
            def refreshed(info):self.received(info);self.template.setCurrentIndex(self.template.findData(id));self.notice.setText('客户模板已上传并识别填入位置，请核对生成文件。')
            self.request('/ledger/bootstrap',None,refreshed)
        self.request('/ledger/templates',value,uploaded)

    def validate_export_target(self,path):
        try:return self._validate_export_target(path)
        except OSError:
            self.notice.setText('无法核对输出位置，请选择新的合同文件名或其他目录。');return False

    def _validate_export_target(self,path):
        snapshot=(self.record or {}).get('generation_snapshot',{})
        origin=snapshot.get('ledger_source') or (self.payload or {}).get('source') or {}
        protected=path.resolve() in self.protected_paths
        if path.is_file():
            hashes={origin.get('sha256'),snapshot.get('template_sha256')}
            hashes.update(t.get('file_sha256') for t in self.info.get('templates',[]))
            if path.stat().st_size<=64*1024*1024:
                protected=protected or sha256(path.read_bytes()).hexdigest() in hashes
            protected=protected or path.name==origin.get('filename')
        if protected:self.notice.setText('不能覆盖原台账或客户模板，请选择新的合同文件名。')
        return not protected

    def sync_actions(self):
        available=not self.busy
        self.stack.setEnabled(available)
        # Reading a local Excel is independent of API/database readiness and
        # template choice. Only remote persistence/generation needs readiness.
        ready=bool(self.info.get('ready'))
        self.read_button.setEnabled(available)
        self.read_button.setToolTip('' if ready else SERVICE_WAIT_MESSAGE)
        for control in (self.customer,self.sheet,self.search,self.template,self.selection,self.items,self.documents,self.drafts):control.setEnabled(available)
        self.save_button.setEnabled(available and ready and bool(self.selected_keys) and not self.historical)
        self.generate_button.setEnabled(available and ready and bool(self.selected_keys) and not self.historical)
        self.generate_button.setVisible(self.stack.currentIndex()!=0)
        self.original_button.setEnabled(available and self.output is not None)
        self.export_button.setEnabled(available and self.output is not None)
        self.print_button.setEnabled(available and bool(self.preview_pages))
        self.output_choice.setEnabled(available)
        for i,control in enumerate(self.step_buttons):
            control.setEnabled(available and (not self.historical or i==2))
            control.setObjectName('scheme2PrimaryAction' if i==self.stack.currentIndex() else 'scheme2PrimaryGhost')
            control.style().unpolish(control);control.style().polish(control)

    download=contracts.ContractManagement.download
    render_preview=contracts.ContractManagement.render_preview
    export_file=contracts.ContractManagement.export_file
    open_original=contracts.ContractManagement.open_original
    print_file=contracts.ContractManagement.print_file
    fit_previews=contracts.ContractManagement.fit_previews

    def eventFilter(self,watched,event):
        if watched is self.preview_scroll.viewport() and event.type()==QEvent.Type.Resize:QTimer.singleShot(0,self.fit_previews)
        return super().eventFilter(watched,event)
