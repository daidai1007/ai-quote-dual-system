"""Customer Office contracts over immutable formal quotation snapshots.

This page owns its requests, temporary preview and original output bytes. It
never edits quote prices, updates source customer data or marks a quote won.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.error
import urllib.request
from uuid import uuid4

from PySide6.QtCore import Qt, QEvent, QThread, Signal, QSignalBlocker, QTimer, QUrl, QSaveFile, QIODevice
from PySide6.QtGui import QPixmap, QDesktopServices, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QFrame, QLabel, QPushButton, QTabWidget, QComboBox, QLineEdit,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox, QDialog, QDialogButtonBox,
    QInputDialog, QSizePolicy, QPlainTextEdit)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

import quote_scheme_center as schemes
from quote_analysis import COLORS, label, table, fill
from quote_management import PAGE_STYLE, button
from quote_scheme_widgets import SchemeComboBox, QueryLineEdit, apply_light_action, light_purpose_style_sheet
from scheme2_ui import QUOTE_ROUTE

METRICS = dict(margin=20, gap=12, left_min=340, left_max=640, preview_width=760,
               preview_dpi=100, max_pages=100, upload_bytes=8*1024*1024)
MANUAL_FIELDS = dict(contract_no='客户合同编号', seller_name='供方名称', sign_date='签约日期',
    delivery_date='约定交货日期', buyer_contact='客户联系人', buyer_address='客户地址', seller_address='供方地址')
ITEM_FIELDS = dict(number='序号', name='产品名称', specification='规格', quantity='数量',
    unit='单位', unit_price='单价', total='金额', remark='备注')
STYLE = PAGE_STYLE + """
QWidget#contractManagement { background:#f3f6fa; }
QFrame#contractCard { background:white; border:1px solid #dce4ee; border-radius:6px; }
QLabel#contractHeading { font-size:17px; font-weight:600; }
QLabel#contractNote { color:#63748a; font-size:12px; }
QLabel#contractAmount { font-size:25px; font-weight:600; color:#173e76; }
QLabel#contractNotice { background:#eaf2ff; color:#173e76; padding:10px; border-radius:5px; }
QScrollArea { border:0; background:transparent; }
QWidget#contractPaperTray { background:#e8edf3; }
QLabel#contractPaper { background:white; }
QSplitter::handle { background:transparent; width:12px; }
"""


def contract_headers(window):
    try:return dict(schemes._headers(window))
    except RuntimeError:return None  # A deliberately rejects a closed/old name context.


def person_key(window):
    try:
        import name_login
        return name_login.user_id() or tuple(sorted((contract_headers(window) or {}).items()))
    except ImportError:return tuple(sorted((contract_headers(window) or {}).items()))


def freeze_contract_quote(window,snapshot):
    """Add an immutable document face; never rewrite the editable workspace.

    Formula face uses the formal workbook's existing per-unit ordering. Its
    costs have already been normalized by the current document snapshot path.
    """
    import scheme2_ui
    from quick_discount_rules import (money_sum,money_product,
        formula_attachment_line_amount,formula_attachment_excluded,attachment_excluded_from_discount)
    items=scheme2_ui._quote_export_items_snapshot(window)
    for item in items:
        rows=item.get('attachments') or [];cost=item['formula']
        eligible=[r for r in rows if not formula_attachment_excluded(r)]
        base=money_sum([cost[k] for k in ('material_cost','auxiliary_cost','labor_cost','spray_cost','management_fee')]+[formula_attachment_line_amount(r) for r in eligible if not attachment_excluded_from_discount(r)])
        unit=money_sum([money_product(base,float(item.get('formula_discount') or 1)),*[formula_attachment_line_amount(r) for r in eligible if attachment_excluded_from_discount(r)],max(0,float(item.get('freight_fee',item.get('freight',0)) or 0))])
        item['quote_display'].update(formula_unit_price=unit,formula_total=money_product(unit,item['quote_display']['quantity']))
        # Freeze the existing cost-page values now; recipient viewing must not
        # run the latest cost formulas or catalogue against an older document.
        values=scheme2_ui._row_values(item)
        item['quote_cost_display']={'schema':1,'values':{
            heading:(scheme2_ui._money(values[scheme2_ui.COST_DISPLAY_ORDER[column]])
                     if column in scheme2_ui.MONEY_COLUMNS else str(values[scheme2_ui.COST_DISPLAY_ORDER[column]]))
            for column,heading in enumerate(scheme2_ui.HEADERS)}}
    snapshot['contract_quote_snapshot']={'schema':1,'items':items}
    return snapshot


def install_contract_snapshot():
    if getattr(schemes,'_contract_snapshot_installed',False):return
    schemes._contract_snapshot_installed=True
    prior_snapshot,prior_prepare,prior_record=schemes._snapshot,schemes._prepare_export,schemes._record_export
    def snapshot(window):
        payload=prior_snapshot(window)
        return freeze_contract_quote(window,payload) if getattr(window,'_contract_freeze_requested',False) else payload
    def prepare(window, kind='XLSX'):
        window._contract_freeze_requested=True
        try:return prior_prepare(window, kind)
        except (ValueError,KeyError,TypeError) as error:
            schemes._release_export(window)
            if getattr(window,'_quote_scheme_dirty_seq',0)>getattr(window,'_quote_scheme_saved_seq',0):window._quote_scheme_save_timer.start(500)
            show_message(window,'正式报价快照待核对',str(error));return False
        finally:window._contract_freeze_requested=False
    def record(window,succeeded,kind='XLSX'):
        window._contract_freeze_requested=bool(succeeded and kind in ('PRINT','XLSX'))
        try:return prior_record(window,succeeded,kind)
        except (ValueError,KeyError,TypeError) as error:
            schemes._set_state(window,'文件已打印，正式报价快照登记未完成，请核对后重新登记：'+str(error),'error');return False
        finally:window._contract_freeze_requested=False
    schemes._snapshot,schemes._prepare_export,schemes._record_export=snapshot,prepare,record


def index_of(combo,value):
    # QVariant stores Python tuples by identity; compare values for reloaded keys.
    return next((i for i in range(combo.count()) if combo.itemData(i)==value),-1)


def card(title, note=''):
    frame = QFrame(); frame.setObjectName('contractCard')
    box = QVBoxLayout(frame); box.setContentsMargins(16,14,16,14); box.setSpacing(10)
    box.addWidget(label(title, 'contractHeading'))
    if note: box.addWidget(label(note, 'contractNote'))
    return frame, box


def show_message(parent,title,text):
    message=QMessageBox(parent);message.setWindowTitle(title);message.setIcon(QMessageBox.Icon.Information);message.setTextFormat(Qt.TextFormat.PlainText);message.setText(text);return message.exec()


def scrollable(widget):
    result=QScrollArea();result.setWidgetResizable(True);result.setWidget(widget);return result


class OptionalFeedback(QLabel):
    """Collapse empty feedback without suppressing validation or operation results."""
    def __init__(self, name):
        super().__init__(); self.setObjectName(name); self.setTextFormat(Qt.TextFormat.PlainText); self.setWordWrap(True); self.hide()

    def setText(self, text):
        super().setText(text); self.setVisible(bool(text.strip()))

    def clear(self):
        self.setText('')


class ContractTextEdit(QPlainTextEdit):
    textEdited=Signal(str)
    def __init__(self):
        super().__init__();self.setFixedHeight(84);self.textChanged.connect(lambda:self.textEdited.emit(self.toPlainText()))
    def text(self):return self.toPlainText()
    def setText(self,value):
        with QSignalBlocker(self):self.setPlainText(value)


class ContractWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, window, path, payload=None, binary=False):
        super().__init__(window)
        self.url = schemes._base_url(window)+path
        self.headers = (contract_headers(window) or {}); self.payload = deepcopy(payload)
        self.binary = binary;self.result=None;self.error=None;self.completed=False

    def run(self):
        try:
            data = None if self.payload is None else json.dumps(self.payload,ensure_ascii=False).encode('utf-8')
            headers = {**self.headers, 'Accept':'application/octet-stream' if self.binary else 'application/json'}
            if data is not None: headers['Content-Type']='application/json; charset=utf-8'
            request=urllib.request.Request(self.url,data=data,headers=headers,method='GET' if data is None else 'POST')
            with urllib.request.urlopen(request,timeout=60) as response:
                raw=response.read(17*1024*1024+1)
                if len(raw)>17*1024*1024: raise ValueError('合同响应超过限制')
                if self.binary:
                    digest=response.headers.get('X-Content-SHA256','')
                    if not digest or sha256(raw).hexdigest()!=digest: raise ValueError('合同文件校验失败，请重新下载')
                    result=dict(bytes=raw,sha256=digest)
                else: result=json.loads(raw.decode('utf-8'))
            if not self.isInterruptionRequested(): self.result=result
        except urllib.error.HTTPError as error:
            try: message=json.loads(error.read().decode('utf-8')).get('message') or '合同请求失败'
            except Exception: message='合同服务尚未部署或请求失败，请联系管理员核对。'
            if not self.isInterruptionRequested(): self.error=message
        except Exception as error:
            message=str(error) if isinstance(error,ValueError) else '连接失败，请检查网络后重试；填写内容已保留。'
            if not self.isInterruptionRequested(): self.error=message

        finally:self.completed=True

def preview_office(source: Path, output: Path, pdftoppm: str):
    """Render the very same Office file that will be exported, in a private profile."""
    office=shutil.which('soffice') or next((str(p) for p in (
        Path(os.environ.get('ProgramFiles','C:/Program Files'))/'LibreOffice/program/soffice.exe',
        Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'LibreOffice/program/soffice.exe') if p.is_file()),None)
    if not office: raise ValueError('此电脑未安装 LibreOffice，无法生成文件预览。可打开原文件核对后输出。')
    if not pdftoppm or not Path(pdftoppm).is_file(): raise ValueError('缺少现有 PDF 预览组件，可打开原文件核对后输出。')
    source=source.resolve();output=output.resolve()
    if output==source.parent or not output.is_relative_to(source.parent):raise ValueError('预览目录必须是本次文件的独立临时子目录')
    output.mkdir(parents=True,exist_ok=True)
    for old in output.glob('page-*.png'):old.unlink()
    pdf=output/(source.stem+'.pdf')
    if pdf.exists():pdf.unlink()
    profile=output/'office-profile'
    options=dict(stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,
                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    done=subprocess.run([office,'-env:UserInstallation='+profile.resolve().as_uri(),'--headless',
        '--convert-to','pdf','--outdir',str(output),str(source)],**options)
    pdf=output/(source.stem+'.pdf')
    if done.returncode or not pdf.is_file(): raise ValueError('合同转换失败，请打开生成的原文件核对版式。')
    from pypdf import PdfReader
    count=len(PdfReader(str(pdf)).pages)
    if not 1<=count<=METRICS['max_pages']: raise ValueError('合同页数超出预览限制，请打开原文件核对。')
    done=subprocess.run([str(pdftoppm),'-png','-r',str(METRICS['preview_dpi']),str(pdf),str(output/'page')],**options)
    pages=sorted(output.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
    if done.returncode or len(pages)!=count: raise ValueError('合同页面渲染失败，请重试或打开原文件核对。')
    return dict(pdf=str(pdf),pages=[str(p) for p in pages])


class PreviewWorker(QThread):
    succeeded=Signal(object); failed=Signal(str)
    def __init__(self,source,output,pdftoppm,parent):
        super().__init__(parent); self.args=(source,output,pdftoppm);self.result=None;self.error=None;self.completed=False
    def run(self):
        try:
            result=preview_office(*self.args)
            if not self.isInterruptionRequested(): self.result=result
        except Exception as error:
            if not self.isInterruptionRequested(): self.error=str(error)
        finally:self.completed=True


class MappingDialog(QDialog):
    """Explicit, repeatable targets; does not guess replacement of plain text."""
    def __init__(self,result,parent=None):
        super().__init__(parent); self.setWindowTitle('配置合同填入位置'); self.resize(1040,700)
        self.setStyleSheet(STYLE); self.result_data=result; self.mapping=None
        inspection=result['inspection']; self.format=inspection['format']
        layout=QVBoxLayout(self); layout.addWidget(label('逐项确认位置。替换文字必须在所选位置唯一；空白位置可留空。已有条款保持原样。','contractNotice'))
        self.fields=QTableWidget(0,3); self.fields.setHorizontalHeaderLabels(('字段来源 / 自定义字段','填入位置','要替换的原文字（空白位置留空）'))
        self.fields.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.fields,1)
        actions=QHBoxLayout(); actions.addWidget(button('新增字段',lambda:self.add_field())); actions.addWidget(button('删除所选字段',self.remove_field)); actions.addStretch(); layout.addLayout(actions)
        rowline=QHBoxLayout(); rowline.addWidget(label('产品样板行')); self.row=SchemeComboBox()
        for row in inspection['rows']: self.row.addItem(row['label']+' · '+' | '.join(row['cells'])[:160],row['id'])
        rowline.addWidget(self.row,1); layout.addLayout(rowline)
        layout.addWidget(label('明细列：Word 使用从 1 开始的列号；Excel 使用 A、B 等列字母。名称、数量、单价、金额为必填。','contractNote'))
        grid=QGridLayout(); self.columns={}
        suggested=(result['template'].get('field_mapping') or inspection['suggested'])
        for i,(key,title) in enumerate(ITEM_FIELDS.items()):
            control=QLineEdit(); self.columns[key]=control
            value=(suggested.get('items') or {}).get('columns',{}).get(key,'')
            control.setText(str(int(value)+1) if value!='' and self.format=='docx' else str(value))
            grid.addWidget(label(title),i//4*2,i%4); grid.addWidget(control,i//4*2+1,i%4)
        layout.addLayout(grid)
        target=(suggested.get('items') or {}).get('target'); self.row.setCurrentIndex(max(0,self.row.findData(target)))
        for field in suggested.get('fields',[]): self.add_field(field)
        self.error=label(); layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def add_field(self,field=None):
        field=field or {}; row=self.fields.rowCount(); self.fields.insertRow(row)
        source=SchemeComboBox(); source.setEditable(True)
        for key,name in self.result_data['inspection']['fields'].items(): source.addItem(name,key)
        key=field.get('source','buyer_name'); index=source.findData(key)
        if index>=0: source.setCurrentIndex(index)
        else: source.setEditText(key)
        source.setToolTip('自定义字段请填 custom:字段名称')
        location=SchemeComboBox();location.setEditable(self.format=='xlsx');location.setToolTip('Excel 空白位置可直接输入 工作表名!B5；合并单元格选择左上角')
        for loc in self.result_data['inspection']['locations']: location.addItem(loc['label']+' · '+loc['text'][:100],loc['id'])
        location.setCurrentIndex(max(0,location.findData(field.get('target'))))
        find=QLineEdit(field.get('find',''))
        self.fields.setCellWidget(row,0,source); self.fields.setCellWidget(row,1,location); self.fields.setCellWidget(row,2,find)
        self.fields.setRowHeight(row,42)

    def field_target(self,control):
        if self.format!='xlsx' or (control.currentIndex()>=0 and control.currentText()==control.itemText(control.currentIndex())):return control.currentData()
        import re
        text=control.currentText().strip();match=re.fullmatch(r'(.+)!([A-Za-z]{1,3}[1-9][0-9]*)',text)
        if not match:raise ValueError('请填写 工作表名!单元格，例如 合同!B5')
        sheet=next((s for s in self.result_data['inspection'].get('sheets',[]) if s['name']==match[1]),None)
        if not sheet:raise ValueError('工作表名称不存在')
        return sheet['part']+'#'+match[2].upper()

    def remove_field(self):
        if self.fields.currentRow()>=0: self.fields.removeRow(self.fields.currentRow())

    def accept(self):
        try:
            fields=[]
            for r in range(self.fields.rowCount()):
                source=self.fields.cellWidget(r,0); key=source.currentData() if source.currentIndex()>=0 and source.currentText()==source.itemText(source.currentIndex()) else source.currentText().strip()
                if key not in self.result_data['inspection']['fields'] and not key.startswith('custom:'): raise ValueError('自定义字段请使用 custom:字段名称')
                fields.append(dict(source=key,target=self.field_target(self.fields.cellWidget(r,1)),find=self.fields.cellWidget(r,2).text()))
            columns={k:(int(w.text())-1 if self.format=='docx' else w.text().strip().upper()) for k,w in self.columns.items() if w.text().strip()}
            if any(k not in columns for k in ('name','quantity','unit_price','total')): raise ValueError('请填写产品名称、数量、单价、金额列')
            self.mapping=dict(fields=fields,items=dict(target=self.row.currentData(),columns=columns))
        except (ValueError,TypeError) as error: self.error.setText(str(error)); return
        super().accept()


class ContractManagement(QWidget):
    def __init__(self,window):
        super().__init__(); self.window=window; self.setObjectName('contractManagement'); self.setStyleSheet(STYLE)
        self.data=dict(sources=[],templates=[],records=[],drafts=[]);self.record_page=1;self.record_total=0; self.workers=[]; self.busy=False; self.queue=[]
        self.pending_scheme=None; self.selected_customer=None; self.loaded=False; self.identity=(contract_headers(window) or {});self.person=person_key(window);self.unsaved=False
        self.request_id=str(uuid4()); self.draft=None; self.record=None; self.output=None; self.preview_pages=[]
        self.temp_dirs=[]; self.current_quote=None; self.mapping=None; self.populating=False; self.historical=False
        root=QVBoxLayout(self); root.setContentsMargins(*[METRICS['margin']]*4); root.setSpacing(METRICS['gap'])
        top=QHBoxLayout(); top.addWidget(label('合同管理','scheme2PageTitle'),1)
        self.reload_button=apply_light_action(button('重新加载',self.reload))
        self.upload_button=apply_light_action(button('上传客户模板',self.upload,True))
        top.addWidget(self.reload_button); top.addWidget(self.upload_button); root.addLayout(top)
        self.purpose=label('使用客户合同模板，填入已确定报价并按原格式输出','contractPurpose')
        self.purpose.setWordWrap(False)
        self.purpose.setStyleSheet(light_purpose_style_sheet()); root.addWidget(self.purpose,0,Qt.AlignmentFlag.AlignLeft)
        self.notice=OptionalFeedback('contractNote'); root.addWidget(self.notice)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        self.generate_page=QWidget(); self.tabs.addTab(self.generate_page,'生成合同')
        self.build_generate(); self.build_library(); self.build_records()
        self.poll_timer=QTimer(self);self.poll_timer.setInterval(25);self.poll_timer.timeout.connect(self.deliver_results)
        self.identity_timer=QTimer(self); self.identity_timer.setInterval(300); self.identity_timer.timeout.connect(self.check_identity); self.identity_timer.start()

    def build_generate(self):
        body=QVBoxLayout(self.generate_page); body.setContentsMargins(0,12,0,0)
        middle=QWidget();content=QVBoxLayout(middle);content.setContentsMargins(0,0,0,0);content.setSpacing(12);self.middle_scroll=scrollable(middle);body.addWidget(self.middle_scroll,1)
        choose,box=card('选择客户模板与报价')
        choices=QGridLayout(); self.customer=SchemeComboBox(); self.source=SchemeComboBox(); self.template=SchemeComboBox(); self.method=SchemeComboBox()
        for caption,code in (('请选择采用报价',''),('快速报价','QUICK'),('公式报价','FORMULA')): self.method.addItem(caption,code)
        for i,(title,control) in enumerate((('客户',self.customer),('客户合同模板',self.template),('正式报价 / 版本',self.source),('采用报价',self.method))):
            control.setMinimumWidth(0);control.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);choices.addWidget(label(title),0,i); choices.addWidget(control,1,i); choices.setColumnStretch(i,1)
        box.addLayout(choices);self.choices_card=choose;content.addWidget(choose);self.history_banner=label('', 'contractNotice');self.history_banner.hide();content.addWidget(self.history_banner)
        self.customer.currentIndexChanged.connect(self.customer_changed); self.source.currentIndexChanged.connect(self.selection_changed)
        self.template.currentIndexChanged.connect(self.template_changed); self.method.currentIndexChanged.connect(self.selection_changed)
        self.splitter=QSplitter(); content.addWidget(self.splitter,1)
        self.left=QScrollArea(); self.left.setWidgetResizable(True); left=QWidget(); leftbox=QVBoxLayout(left); leftbox.setContentsMargins(0,0,0,0); leftbox.setSpacing(12); self.left.setWidget(left); self.splitter.addWidget(self.left)
        source,sourcebox=card('已确定报价信息')
        self.source_info=OptionalFeedback('contractNote'); sourcebox.addWidget(self.source_info)
        self.items=table(('产品','规格','数量','单位','合同单价','金额'),'contractItems'); self.items.setMinimumHeight(130);self.items.horizontalHeader().setMinimumSectionSize(36)
        for col,width in enumerate((110,130,48,44,96,96)):
            self.items.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Interactive);self.items.setColumnWidth(col,width)
        self.items.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);sourcebox.addWidget(self.items)
        self.amount=label('¥ —','contractAmount'); self.upper=label('人民币大写：—','contractNote'); sourcebox.addWidget(self.amount); sourcebox.addWidget(self.upper); leftbox.addWidget(source)
        form,formbox=card('补充合同信息')
        self.form=QFormLayout(); self.inputs={}
        for key,title in MANUAL_FIELDS.items():
            control=QueryLineEdit(); control.setPlaceholderText('按双方确认内容填写' if key not in ('sign_date','delivery_date') else 'YYYY-MM-DD')
            control.textEdited.connect(self.field_edited); self.inputs[key]=control; self.form.addRow(title,control)
        formbox.addLayout(self.form); actions=QHBoxLayout(); actions.addWidget(button('配置填入位置',self.configure_selected)); actions.addWidget(button('查看来源报价',self.open_source)); actions.addStretch(); formbox.addLayout(actions); leftbox.addWidget(form); leftbox.addStretch()
        right,rightbox=card('合同预览'); self.preview_info=OptionalFeedback('contractNote'); rightbox.addWidget(self.preview_info)
        self.preview_scroll=QScrollArea(); self.preview_scroll.setWidgetResizable(True);self.preview_scroll.viewport().installEventFilter(self); self.tray=QWidget(); self.tray.setObjectName('contractPaperTray'); self.pagebox=QVBoxLayout(self.tray); self.pagebox.setAlignment(Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop); self.preview_scroll.setWidget(self.tray); self.placeholder=label('生成合同后，在这里核对实际文件\n原有条款、签章区域和分页均需确认。','contractNote'); self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter); self.pagebox.addWidget(self.placeholder); rightbox.addWidget(self.preview_scroll,1)
        tools=QHBoxLayout(); self.original_button=button('打开原文件',self.open_original); self.print_button=button('打印预览文件',self.print_file); tools.addWidget(self.original_button); tools.addWidget(self.print_button); tools.addWidget(button('新建合同',self.new_contract)); tools.addStretch(); rightbox.addLayout(tools); self.splitter.addWidget(right); self.splitter.setSizes([520,700]); self.splitter.setChildrenCollapsible(False)
        footer=QHBoxLayout(); footer.addStretch(1)
        self.drafts=apply_light_action(SchemeComboBox());self.drafts.setMaximumWidth(180); self.drafts.addItem('打开生成草稿',None); self.drafts.activated.connect(self.open_draft); footer.addWidget(self.drafts)
        self.save_button=button('保存生成草稿',self.save_draft); self.generate_button=button('生成合同',self.generate,True); self.export_button=button('输出原文件',self.export_file,True)
        for control in (self.save_button,self.generate_button,self.export_button): footer.addWidget(apply_light_action(control))
        body.addLayout(footer); self.sync_actions()

    def build_library(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(0,14,0,0)
        frame,box=card('客户合同模板','上传新文件或保存字段配置均产生新版本；历史合同始终关联原版本。')
        self.library=table(('客户','模板名称','格式','版本','字段配置','状态','维护人'),'contractTemplates'); box.addWidget(self.library,1)
        actions=QHBoxLayout()
        for title,callback in (('使用所选模板',self.use_template),('配置字段',self.configure_library),('上传新版本',lambda:self.upload(True)),('设为默认',lambda:self.settings(True)),('启用 / 停用',lambda:self.settings(False)),('版本记录',self.template_versions)):
            actions.addWidget(button(title,callback))
        actions.addStretch(); box.addLayout(actions); layout.addWidget(frame,1)
        helpframe,helpbox=card('模板填入说明'); helpbox.addWidget(label('Word：指定段落字段和产品样板行，复制行样式并保留页眉、页脚及条款。\nExcel：指定单元格和产品行，保留样式与打印设置，并重算支持的公式。\n支持 DOCX / XLSX（每份不超过 8MB）；旧 DOC / XLS 请先转换并核对。','contractNote')); layout.addWidget(helpframe); self.tabs.addTab(scrollable(page),'客户模板')

    def build_records(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(0,14,0,0)
        frame,box=card('合同生成记录','打开或下载该次保存的原始文件，不按当前价格或模板重新生成。')
        self.records=table(('内部记录号','客户合同号','客户','来源报价 / 版本','采用报价','合同金额','模板 / 版本','格式','生成人'),'contractRecords'); box.addWidget(self.records,1)
        actions=QHBoxLayout(); self.record_search=QueryLineEdit(); self.record_search.setPlaceholderText('客户 / 合同号 / 报价号 / 模板名称');self.record_search_timer=QTimer(self);self.record_search_timer.setSingleShot(True);self.record_search_timer.setInterval(250);self.record_search_timer.timeout.connect(lambda:self.load_records(True));self.record_search.textChanged.connect(lambda:self.record_search_timer.start());self.record_search.returnPressed.connect(lambda:self.load_records(True)); actions.addWidget(self.record_search,1); actions.addWidget(button('预览所选记录',self.open_record)); actions.addWidget(button('下载原文件',lambda:self.open_record(export=True))); actions.addWidget(button('刷新',lambda:self.load_records(True))); box.addLayout(actions)
        pages=QHBoxLayout();self.record_page_info=label('第 1 页','contractNote');pages.addWidget(self.record_page_info);pages.addStretch();self.record_prev=button('上一页',lambda:self.change_record_page(-1));self.record_next=button('下一页',lambda:self.change_record_page(1));pages.addWidget(self.record_prev);pages.addWidget(self.record_next);box.addLayout(pages);layout.addWidget(frame,1);self.tabs.addTab(scrollable(page),'生成记录');self.tabs.currentChanged.connect(lambda index:self.load_records(True) if index==2 and self.loaded else None)

    def check_identity(self):
        current=(contract_headers(self.window) or {})
        if current==self.identity: return
        same_person=person_key(self.window)==self.person;self.person=person_key(self.window)
        self.identity=current; self.queue.clear(); self.busy=False
        for worker in self.workers:worker.requestInterruption()
        if same_person:
            self.notice.setText('姓名会话已续期，填写内容已保留，可重试原操作。');self.sync_actions();return
        self.loaded=False;self.unsaved=False;self.selected_customer=None
        self.record_search_timer.stop()
        with QSignalBlocker(self.record_search):self.record_search.clear()
        for worker in self.workers: worker.requestInterruption()
        self.data=dict(sources=[],templates=[],records=[],drafts=[]); self.record=None; self.draft=None
        for control in self.inputs.values(): control.clear()
        self.render_data(); self.invalidate(); self.notice.setText('登录身份已变化，请重新加载本人合同数据。')

    def request(self,path,payload,callback,binary=False):
        self.check_identity()
        if contract_headers(self.window) is None:self.notice.setText('姓名会话已变化，请在当前姓名窗口重新操作。');return False
        if self.busy:
            self.queue.append((path,deepcopy(payload),callback,binary,dict(self.identity))); return True
        self.busy=True; self.sync_actions(); self.notice.setText('正在处理，请稍候…')
        worker=ContractWorker(self.window,'/api/contracts'+path,payload,binary); identity=dict(self.identity);worker._contract_identity=identity; self.workers.append(worker)
        def success(value):
            if identity!=(contract_headers(self.window) or {}): return
            self.busy=False; self.sync_actions(); callback(value)
        def failed(message):
            if identity!=(contract_headers(self.window) or {}): return
            self.busy=False; self.sync_actions(); self.notice.setText(message)
        def finished():
            if worker in self.workers:self.workers.remove(worker)
            worker.deleteLater()
            if identity!=self.identity and not any(getattr(w,'_contract_identity',None)==self.identity for w in self.workers):self.busy=False; self.sync_actions()
            self.drain_queue()
        worker._callbacks=(success,failed,finished);self.poll_timer.start();worker.start();return True

    def deliver_results(self):
        # Read completed immutable results on the GUI thread. Chained workers
        # cannot inherit a receiver context belonging to a finished thread.
        for worker in list(self.workers):
            if not worker.completed or worker.isRunning():continue
            self.workers.remove(worker);success,failure,finished=worker._callbacks
            try:
                if worker.error is not None:failure(worker.error)
                elif worker.result is not None:success(worker.result)
            finally:finished()
        if not self.workers:self.poll_timer.stop()

    def drain_queue(self):
        if self.busy:return
        while self.queue:
            path,payload,callback,binary,identity=self.queue.pop(0)
            if identity==self.identity:
                self.request(path,payload,callback,binary);break

    def reload(self):
        if self.busy:self.notice.setText('当前合同操作正在处理，完成后可重新加载。');return
        self.request('/bootstrap',None,self.received)

    def enter(self):
        self.check_identity()
        if not self.loaded: self.reload()
        elif self.pending_scheme: self.apply_pending()

    def received(self,result):
        result={**result,'sources':[row for row in result.get('sources',[]) if row.get('order_nature')=='EXTERNAL']}
        self.data=result; self.loaded=bool(result.get('ready')); self.render_data(); self.apply_pending()
        self.notice.setText('已加载合同模板与记录。' if self.loaded else result.get('message','合同服务尚未启用。'))

    def render_data(self):
        selected=self.customer.currentData(); source=self.source.currentData(); template=self.template.currentData()
        self.populating=True; self.customer.clear(); self.customer.addItem('请选择客户',None)
        customers={r['customer_code']:r['customer_name'] for r in self.data.get('sources',[]) if r.get('customer_code')}
        for code,name in customers.items(): self.customer.addItem(name,code)
        self.customer.setCurrentIndex(max(0,self.customer.findData(selected))); self.populating=False; self.customer_changed()
        if source:self.source.setCurrentIndex(max(0,index_of(self.source,source)))
        if template:self.template.setCurrentIndex(max(0,self.template.findData(template)))
        if self.template.currentData():self.template_changed()
        rows=self.data.get('templates',[])
        fill(self.library,[(r['customer_name'],r['template_name'],r['file_format'].upper(),'V'+str(r['version_no']),'已配置' if r['configured'] else '待配置',('默认 · ' if r['is_default'] else '')+('可用' if r['enabled'] else '停用'),r['owner_name']) for r in rows]); self.library.setMaximumHeight(16777215)
        self.record_page=1;self.record_total=self.data.get('records_total',len(self.data.get('records',[])));self.render_records(); self.drafts.clear(); self.drafts.addItem('打开生成草稿',None)
        for d in self.data.get('drafts',[]): self.drafts.addItem(d['input_payload']['fields'].get('contract_no') or d['draft_id'],d['draft_id'])
        self.sync_actions()

    def apply_pending(self):
        no=self.pending_scheme
        if not no:return
        self.pending_scheme=None; source=next((r for r in self.data.get('sources',[]) if r['scheme_no']==no),None)
        if source:
            self.customer.setCurrentIndex(self.customer.findData(source['customer_code'])); self.source.setCurrentIndex(index_of(self.source,(no,source['version_no']))); self.tabs.setCurrentIndex(0)
        else: self.notice.setText('所选报价尚无可用于合同的正式版本。请先按现有流程确认并成功导出报价。')

    def customer_changed(self,*_):
        if self.populating:return
        code=self.customer.currentData()
        if self.selected_customer and code!=self.selected_customer:
            if self.unsaved:
                with QSignalBlocker(self.customer):self.customer.setCurrentIndex(self.customer.findData(self.selected_customer))
                self.notice.setText('当前合同信息未保存，请先保存生成草稿，或点击“新建合同”舍弃后再切换客户。');return
            for key,control in self.inputs.items():
                if key not in ('seller_name','seller_address'):control.setText('')
            self.draft=None
        self.selected_customer=code
        self.populating=True; self.source.clear(); self.source.addItem('请选择正式报价',None); self.template.clear(); self.template.addItem('请选择客户模板',None)
        for r in self.data.get('sources',[]):
            if r.get('customer_code')==code:self.source.addItem(r['scheme_no']+' / 正式 V'+str(r['version_no']),(r['scheme_no'],r['version_no']))
        for r in self.data.get('templates',[]):
            if r['customer_code']==code and r.get('can_use',r.get('can_write')) and r['enabled']:
                self.template.addItem(r['template_name']+' · '+r['file_format'].upper()+' · V'+str(r['version_no'])+(' · 待配置' if not r['configured'] else ''),r['template_version_id'])
        default=next((r for r in self.data.get('templates',[]) if r['customer_code']==code and r.get('can_use',r.get('can_write')) and r['enabled'] and r['configured'] and r['is_default']),None)
        if default:self.template.setCurrentIndex(self.template.findData(default['template_version_id']))
        self.populating=False; self.selection_changed()
        if default:self.template_changed()

    def field_edited(self,*_):
        self.unsaved=True;self.invalidate()

    def invalidate(self,*_):
        if hasattr(self,'choices_card'):self.choices_card.show();self.history_banner.hide()
        self.record=None; self.output=None; self.historical=False; self.request_id=str(uuid4()); self.preview_pages=[]; self.preview_info.clear()
        while self.pagebox.count():
            item=self.pagebox.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.pagebox.addWidget(label('生成合同后显示实际文件预览。','contractNote')); self.sync_actions()

    def selection_changed(self,*_):
        if self.populating:return
        self.invalidate(); self.current_quote=None; fill(self.items,[]); self.amount.setText('¥ —'); self.upper.setText('人民币大写：—'); self.source_info.clear()
        selected=self.source.currentData(); method=self.method.currentData()
        if selected and method:
            selection=(selected,method)
            def received(result):
                if selection!=(self.source.currentData(),self.method.currentData()):return
                self.current_quote=result['quote']; q=self.current_quote; self.source_info.setText(f"客户：{result['customer_name']}\n来源：{selected[0]} / 正式 V{selected[1]} · {self.method.currentText()}")
                fill(self.items,[(r['name'],r['specification'],r['quantity'],r['unit'],f"{r['unit_price']:,.2f}",f"{r['total']:,.2f}") for r in q['items']]); self.amount.setText(f"¥ {q['total']:,.2f}"); self.upper.setText('人民币大写：'+q['total_upper']); self.notice.setText('已读取正式报价冻结金额。'); self.sync_actions()
            self.request('/quote',dict(scheme_no=selected[0],version_no=selected[1],method=method),received)

    def template_changed(self,*_):
        if self.populating:return
        self.invalidate(); self.mapping=None
        selected=self.template.currentData()
        if selected:
            def received(result):
                if selected!=self.template.currentData():return
                self.mapping=result['template'].get('field_mapping'); self.update_custom_fields(); self.notice.setText('模板已配置。' if self.mapping else '模板尚未配置，请先配置填入位置。'); self.sync_actions()
            self.request('/templates/'+str(selected),None,received)

    def update_custom_fields(self):
        wanted={f['source'] for f in (self.mapping or {}).get('fields',[]) if f['source'].startswith('custom:')}
        for key in list(self.inputs):
            if key.startswith('custom:') and key not in wanted:
                control=self.inputs.pop(key); self.form.removeRow(control)
        for key in sorted(wanted):
            if key not in self.inputs:
                control=ContractTextEdit(); control.textEdited.connect(self.field_edited); self.inputs[key]=control; self.form.addRow(label(key[7:]),control)

    def sync_actions(self):
        if not hasattr(self,'generate_button'):return
        valid=bool(self.loaded and self.current_quote and self.template.currentData() and self.mapping)
        self.generate_button.setEnabled(valid and not self.busy and not self.historical); self.save_button.setEnabled(valid and not self.busy and not self.historical)
        self.export_button.setEnabled(bool(self.output) and not self.busy); self.original_button.setEnabled(bool(self.output) and not self.busy); self.print_button.setEnabled(bool(self.preview_pages) and not self.busy)
        for control in (self.customer,self.source,self.template,self.method,self.drafts,self.tabs.tabBar()):control.setEnabled(not self.busy)
        for control in self.inputs.values():control.setReadOnly(self.busy or self.historical)
        if hasattr(self,'record_prev'):
            self.record_prev.setEnabled(not self.busy and self.record_page>1);self.record_next.setEnabled(not self.busy and self.record_page*100<self.record_total)

    def input_data(self):
        selected=self.source.currentData()
        if not selected or not self.template.currentData() or not self.method.currentData():raise ValueError('请选择客户模板、正式报价和采用报价方式。')
        return dict(scheme_no=selected[0],version_no=selected[1],template_version_id=self.template.currentData(),method=self.method.currentData(),fields={k:w.text().strip() for k,w in self.inputs.items()})

    def save_draft(self):
        try:payload=self.input_data()
        except ValueError as e:self.notice.setText(str(e));return
        if self.draft:payload.update(draft_id=self.draft['draft_id'],expected_version=self.draft['lock_version'])
        def saved(result):self.draft=result;self.unsaved=False;self.notice.setText('生成草稿已保存。')
        self.request('/drafts',payload,saved)

    def open_draft(self,index):
        selected=self.drafts.itemData(index); d=next((r for r in self.data.get('drafts',[]) if r['draft_id']==selected),None)
        if not d:return
        data=d['input_payload']; source=next((r for r in self.data['sources'] if (r['scheme_no'],r['version_no'])==(data['scheme_no'],data['version_no'])),None)
        if not source:self.notice.setText('草稿所用正式报价当前不可用。');return
        # Load immutable template version even after a newer version was uploaded.
        self.customer.setCurrentIndex(self.customer.findData(source['customer_code'])); self.populating=True
        self.source.setCurrentIndex(index_of(self.source,(data['scheme_no'],data['version_no']))); self.method.setCurrentIndex(self.method.findData(data['method']))
        self.populating=False; self.selection_changed()
        def loaded(result):
            t=result['template']; self.populating=True; index=self.template.findData(t['template_version_id'])
            if index<0:self.template.addItem(t['template_name']+' · 草稿 V'+str(t['version_no']),t['template_version_id']);index=self.template.count()-1
            self.template.setCurrentIndex(index); self.populating=False; self.mapping=t.get('field_mapping'); self.update_custom_fields()
            for key,control in self.inputs.items():control.setText(data['fields'].get(key,''))
            self.draft=deepcopy(d); self.sync_actions(); self.notice.setText('草稿已恢复；生成前重新核对报价和合同字段。')
        self.request('/templates/'+str(data['template_version_id']),None,loaded)

    def generate(self):
        try:
            payload=self.input_data()
            if not payload['fields']['contract_no']:raise ValueError('请填写客户合同编号。')
        except ValueError as e:self.notice.setText(str(e));return
        payload['request_id']=self.request_id
        self.request('/generate',payload,self.generated)

    def generated(self,result):
        self.record=result; self.unsaved=False; self.download(result)

    def download(self,record,export=False):
        def received(result):
            if result['sha256']!=record['file_sha256']:self.notice.setText('合同校验值与生成记录不一致，请重试。');return
            try:
                directory=Path(tempfile.mkdtemp(prefix='aiquote-contract-')); self.temp_dirs.append(directory)
                path=directory/('contract.'+record['file_format']); path.write_bytes(result['bytes'])
            except OSError:
                self.output=None;self.notice.setText('临时文件无法写入；生成记录已保存，可释放磁盘空间后重新打开。');self.sync_actions();return
            self.output=dict(path=path,bytes=result['bytes'],name=record['record_no']+'.'+record['file_format'])
            self.preview_info.setText(record['record_no']+' · '+record['file_format'].upper()+' · 实际生成文件'); self.notice.setText('合同已生成并留存记录，正在转换预览…'); self.sync_actions()
            if export:self.export_file()
            self.render_preview(path,directory/'preview')
        self.request('/records/'+record['record_id']+'/file',None,received,True)

    def render_preview(self,path,directory):
        pdftoppm=getattr(getattr(self.window,'drawing_preview',None),'_pdftoppm_path',None)
        if callable(pdftoppm):
            try:pdftoppm=pdftoppm()
            except OSError:pdftoppm=None
        self.busy=True; self.sync_actions(); identity=dict(self.identity); output=self.output
        worker=PreviewWorker(path,directory,pdftoppm,self);worker._contract_identity=identity;self.workers.append(worker)
        def received(result):
            if identity!=self.identity or output is not self.output:return
            self.busy=False;self.preview_pages=result['pages']
            while self.pagebox.count():
                item=self.pagebox.takeAt(0)
                if item.widget():item.widget().deleteLater()
            for i,page in enumerate(self.preview_pages):
                caption=label(f'第 {i+1} / {len(self.preview_pages)} 页','contractNote');self.pagebox.addWidget(caption)
                picture=QLabel();picture.setObjectName('contractPaper'); pix=QPixmap(page);picture.source_pixmap=pix;picture.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);picture.setMinimumWidth(0);self.pagebox.addWidget(picture)
            self.fit_previews()
            self.notice.setText('实际文件预览已就绪，请核对客户、金额、条款及分页后输出。');self.sync_actions()
        def failed(message):
            if identity!=self.identity:return
            self.busy=False;self.notice.setText(message);self.sync_actions()
        worker._callbacks=(received,failed,lambda:self.worker_finished(worker));self.poll_timer.start();worker.start()

    def worker_finished(self,worker):
        if worker in self.workers:self.workers.remove(worker)
        worker.deleteLater();self.drain_queue()

    def export_file(self):
        if not self.output:return
        output=self.output; path,_=QFileDialog.getSaveFileName(self,'输出已生成合同',output['name'],'Office 合同 (*.'+output['path'].suffix[1:]+')')
        if not path:return
        if not Path(path).suffix:path+=output['path'].suffix
        if Path(path).suffix.lower()!=output['path'].suffix.lower():self.notice.setText('请按原格式输出，文件后缀应为 '+output['path'].suffix+'。');return
        target=QSaveFile(path)
        if not target.open(QIODevice.OpenModeFlag.WriteOnly) or target.write(output['bytes'])!=len(output['bytes']) or not target.commit():
            target.cancelWriting();self.notice.setText('输出失败，原生成记录仍保留，可重新选择位置。');return
        self.notice.setText('合同原文件已输出；内容与该次生成记录一致。')

    def open_original(self):
        if self.output:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output['path'])))

    def print_file(self):
        if not self.preview_pages:return
        printer=QPrinter(QPrinter.PrinterMode.HighResolution); dialog=QPrintDialog(printer,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        painter=QPainter()
        if not painter.begin(printer):self.notice.setText('打印机未就绪，请重试。');return
        try:
            for i,page in enumerate(self.preview_pages):
                if i:printer.newPage()
                pix=QPixmap(page); area=printer.pageRect(QPrinter.Unit.DevicePixel).toRect();scaled=pix.scaled(area.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation); painter.drawPixmap(area.x()+(area.width()-scaled.width())//2,area.y(),scaled)
        finally:painter.end()
        self.notice.setText('打印任务已发送，请核对打印机实际结果。')

    def selected_template(self,library=False):
        if library:
            row=self.library.currentRow(); rows=self.data.get('templates',[]);return rows[row] if 0<=row<len(rows) else None
        return next((r for r in self.data.get('templates',[]) if r['template_version_id']==self.template.currentData()),None)

    def configure_selected(self):self.configure(self.template.currentData())
    def configure_library(self):
        t=self.selected_template(True)
        if t:self.configure(t['template_version_id'])

    def configure(self,template_id):
        if not template_id:self.notice.setText('请先选择或上传客户模板。');return
        def loaded(result):
            if result['template']['owner_user_id']!=next((r['owner_user_id'] for r in self.data.get('templates',[]) if r['template_version_id']==template_id and r.get('can_write')),None):self.notice.setText('该模板为只读，不能修改字段配置。');return
            dialog=MappingDialog(result,self)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            self.request('/templates/'+str(template_id)+'/configure',dict(mapping=dialog.mapping,expected_version=result['template']['lock_version']),lambda _:self.reload())
        self.request('/templates/'+str(template_id),None,loaded)

    def upload(self,new_version=False):
        if self.busy:return
        t=self.selected_template(True) if new_version else None
        if new_version and (not t or not t.get('can_write')):self.notice.setText('请选择本人维护的客户模板。');return
        source=self.source.currentData(); customer=self.customer.currentData()
        if not source or not customer:self.notice.setText('请先在生成合同页选择所属客户及一份正式报价。');self.tabs.setCurrentIndex(0);return
        if t and t['customer_code']!=customer:self.notice.setText('新版本模板必须与当前所选客户一致。');return
        path,_=QFileDialog.getOpenFileName(self,'选择客户提供的合同模板','','Office 客户模板 (*.docx *.xlsx)')
        if not path:return
        file=Path(path)
        if file.suffix.lower() not in ('.docx','.xlsx') or file.stat().st_size>METRICS['upload_bytes']:self.notice.setText('请选择不超过 8MB 的 DOCX / XLSX 模板。');return
        name,ok=(t['template_name'],True) if t else QInputDialog.getText(self,'客户模板名称','模板名称',text=file.stem)
        if not ok or not name.strip():return
        payload=dict(scheme_no=source[0],version_no=source[1],customer_code=customer,template_name=name.strip(),filename=file.name,format=file.suffix[1:].lower(),content=base64.b64encode(file.read_bytes()).decode('ascii'))
        if t:payload.update(group_id=t['group_id'],expected_version=t['lock_version'])
        def uploaded(result):
            self.notice.setText('模板已上传，请在客户模板页配置字段后使用。');self.tabs.setCurrentIndex(1);self.reload()
        self.request('/templates',payload,uploaded)

    def settings(self,make_default):
        t=self.selected_template(True)
        if not t or not t.get('can_write'):self.notice.setText('仅可修改本人维护的模板。');return
        payload=dict(enabled=t['enabled'] if make_default else not t['enabled'],is_default=True if make_default else (t['is_default'] if not t['enabled'] else False),expected_version=t['lock_version'])
        self.request('/templates/'+str(t['template_version_id'])+'/settings',payload,lambda _:self.reload())

    def use_template(self):
        t=self.selected_template(True)
        if not t or not t.get('can_use',t.get('can_write')) or not t['enabled']:self.notice.setText('请选择有权使用的可用模板。');return
        self.customer.setCurrentIndex(self.customer.findData(t['customer_code']));self.template.setCurrentIndex(self.template.findData(t['template_version_id']));self.tabs.setCurrentIndex(0)

    def template_versions(self):
        t=self.selected_template(True)
        if not t:return
        self.request('/templates/'+str(t['template_version_id'])+'/versions',None,lambda result:show_message(self,'模板版本记录','\n'.join(f"V{r['version_no']} · {r['original_filename']} · {'已配置' if r['configured'] else '待配置'} · {r['created_at']}" for r in result['items'])))

    def change_record_page(self,delta):
        page=max(1,self.record_page+delta)
        if page!=self.record_page:self.record_page=page;self.load_records()

    def load_records(self,reset=False):
        if not self.loaded:return
        self.record_search_timer.stop()
        if reset:self.record_page=1
        search=self.record_search.text().strip();page=self.record_page
        def received(result):
            if search!=self.record_search.text().strip() or page!=self.record_page:return
            self.data['records']=result['items'];self.record_total=result['total'];self.render_records();self.notice.setText('合同生成记录已加载。')
        self.request('/records?'+urllib.parse.urlencode({'page':page,'search':search}),None,received)

    def render_records(self):
        search=self.record_search.text().strip().casefold();self.visible_records=[r for r in self.data.get('records',[]) if search in json.dumps(r,ensure_ascii=False).casefold()]
        fill(self.records,[(r['record_no'],r['customer_contract_no'],r['customer_name'],r['scheme_no']+' / V'+str(r['source_version_no']),'快速报价' if r['quote_method']=='QUICK' else '公式报价',f"¥ {float(r['amount']):,.2f}",r['template_name']+' / V'+str(r['template_version']),r['file_format'].upper(),r['owner_name']) for r in self.visible_records]);self.records.setMaximumHeight(16777215)
        self.record_page_info.setText(f'第 {self.record_page} 页 · 共 {self.record_total} 条，每页 100 条');self.sync_actions()

    def new_contract(self):
        if self.busy:return
        if self.unsaved and QMessageBox.question(self,'新建合同','舍弃当前未保存的合同信息并重新开始？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.unsaved=False;self.draft=None
        for control in self.inputs.values():control.setText('')
        self.invalidate();self.selection_changed();self.template_changed();self.notice.setText('请核对本次合同字段后生成。')

    def show_history(self,result):
        self.record=result;self.historical=True;s=result['generation_snapshot'];q=s['quote']
        self.choices_card.hide();self.history_banner.setText(f"历史记录只读：{result['record_no']} · 客户：{s['fields']['buyer_name']}\n来源：{s['scheme_no']} / 正式 V{s['source_version']} · 模板：{s['template_name']} / V{s['template_version']} · {'快速报价' if s['method']=='QUICK' else '公式报价'}");self.history_banner.show()
        self.source_info.setText(f"历史生成记录：{result['record_no']}\n客户：{s['fields']['buyer_name']}\n来源：{s['scheme_no']} / 正式 V{s['source_version']} · {'快速报价' if s['method']=='QUICK' else '公式报价'}")
        fill(self.items,[(r['name'],r['specification'],r['quantity'],r['unit'],f"{r['unit_price']:,.2f}",f"{r['total']:,.2f}") for r in q['items']]);self.amount.setText(f"¥ {q['total']:,.2f}");self.upper.setText('人民币大写：'+q['total_upper'])
        self.mapping=s['mapping'];self.update_custom_fields()
        for key,control in self.inputs.items():control.setText(s['fields'].get(key,''))
        self.sync_actions()

    def open_record(self,export=False):
        row=self.records.currentRow()
        if not 0<=row<len(self.visible_records):self.notice.setText('请选择一条生成记录。');return
        selected=self.visible_records[row];self.invalidate()
        def received(result):
            self.show_history(result);self.tabs.setCurrentIndex(0)
            if selected.get('can_write'):self.download(result,export)
            else:self.notice.setText('可查看该历史合同信息；原文件打开、打印与输出仅限生成人。')
        self.request('/records/'+selected['record_id'],None,received)

    def open_source(self):
        if self.historical and self.record:
            snapshot=self.record['generation_snapshot'];source=(snapshot['scheme_no'],snapshot['source_version']);quote=snapshot['quote'];method='快速报价' if snapshot['method']=='QUICK' else '公式报价'
        else:source=self.source.currentData();quote=self.current_quote;method=self.method.currentText()
        if not source or not quote:return
        dialog=QDialog(self);dialog.setWindowTitle('来源正式报价快照');dialog.resize(850,520);dialog.setStyleSheet(STYLE);box=QVBoxLayout(dialog)
        box.addWidget(label(f'{source[0]} / 正式 V{source[1]} · {method}'));grid=table(('产品','规格','数量','单价','金额'),'contractSource');fill(grid,[(r['name'],r['specification'],r['quantity'],f"{r['unit_price']:,.2f}",f"{r['total']:,.2f}") for r in quote['items']]);box.addWidget(grid,1);box.addWidget(label(f"合计：¥ {quote['total']:,.2f}"));box.addWidget(button('关闭',dialog.accept));dialog.exec()

    def fit_previews(self):
        width=max(160,min(METRICS['preview_width'],self.preview_scroll.viewport().width()-24))
        for index in range(self.pagebox.count()):
            picture=self.pagebox.itemAt(index).widget();pix=getattr(picture,'source_pixmap',None)
            if pix is not None and not pix.isNull():
                picture.setPixmap(pix.scaledToWidth(width,Qt.TransformationMode.SmoothTransformation));picture.setFixedHeight(round(pix.height()*width/pix.width()));picture.setFixedWidth(width)

    def eventFilter(self,watched,event):
        if hasattr(self,'preview_scroll') and watched is self.preview_scroll.viewport() and event.type()==QEvent.Type.Resize:QTimer.singleShot(0,self.fit_previews)
        return super().eventFilter(watched,event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'splitter'):self.splitter.setOrientation(Qt.Orientation.Vertical if self.width()<820 else Qt.Orientation.Horizontal)

    def shutdown(self):
        for worker in list(self.workers):worker.requestInterruption();worker.wait(65000)
        for directory in self.temp_dirs:
            if directory.parent==Path(tempfile.gettempdir()) and directory.name.startswith('aiquote-contract-'):shutil.rmtree(directory,ignore_errors=True)


def install_contract_management(namespace):
    cls=namespace['MainWindow']
    if getattr(cls,'_contract_management_installed',False):return
    cls._contract_management_installed=True
    install_contract_snapshot()
    try:
        import name_login
        if not getattr(name_login,'_contract_guard_installed',False):
            previous=name_login.critical_tasks
            name_login.critical_tasks=lambda window:previous(window) or any(bool(getattr(getattr(window,'contract_management',None),key,False)) for key in ('unsaved','busy','queue'))
            name_login._contract_guard_installed=True
    except ImportError:pass
    prior_init,prior_section,prior_close=cls.__init__,cls.show_section,cls.closeEvent
    def init(window,*args,**kwargs):
        prior_init(window,*args,**kwargs);manager=window.quote_management;route=manager.contract_route
        # Keep visual order and route metadata aligned without changing stack indices.
        quote_index=next(i for i,entry in enumerate(window.nav_routes) if entry[0]==QUOTE_ROUTE)
        quote_nav=window.nav_buttons[quote_index]
        window.nav_buttons.remove(manager.contract_nav)
        window.nav_buttons.insert(quote_index+1,manager.contract_nav)
        nav_layout=window.scheme2_nav.layout();nav_layout.removeWidget(manager.contract_nav)
        nav_layout.insertWidget(nav_layout.indexOf(quote_nav)+1,manager.contract_nav)
        routes=[entry for entry in window.nav_routes if entry[0]!=route]
        routes.insert(quote_index+1,(route,'合同管理','',None));window.nav_routes=tuple(routes)
        old=manager.contract_page;window.stack.removeWidget(old)
        page=ContractManagement(window);window.contract_management=page;manager.contract_page=page
        window.stack.insertWidget(route,page);window.contract_management_route=route;old.deleteLater()
        def contract():
            row=manager.list_table.currentRow()
            if 0<=row<len(manager.rows):
                selected=manager.rows[row]
                if selected.get('order_nature') != 'EXTERNAL' or selected.get('can_write') is False:
                    page.notice.setText('仅外部正式报价可生成合同。');return
                page.pending_scheme=manager.rows[row]['scheme_no'];page.source_info.setText('待加载来源报价：'+page.pending_scheme);window.show_section(route)
        manager.contract=contract;manager.contract_source=page.source_info
        manager.contract_button.clicked.disconnect();manager.contract_button.clicked.connect(contract)
    def section(window,index):
        page=getattr(window,'contract_management',None)
        if page is not None and page.busy and window.stack.currentIndex()==window.contract_management_route and index!=window.contract_management_route:
            page.notice.setText('合同正在处理，请完成后再切换页面。');return
        result=prior_section(window,index)
        if page is not None and index==window.contract_management_route and window.stack.currentIndex()==index:page.enter()
        return result
    def close(window,event):
        page=getattr(window,'contract_management',None)
        if page is not None and (page.busy or page.queue):
            page.notice.setText('合同正在处理，请完成后再关闭程序。');event.ignore();return
        if page is not None and page.unsaved:
            answer=QMessageBox.question(window,'合同信息尚未保存','保存生成草稿后再关闭？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
            if answer==QMessageBox.StandardButton.Save:
                page.save_draft();event.ignore();return
            if answer==QMessageBox.StandardButton.Cancel:event.ignore();return
            page.unsaved=False
        result=prior_close(window,event)
        if page is not None and event.isAccepted():page.shutdown()
        return result
    cls.__init__,cls.show_section,cls.closeEvent=init,section,close
