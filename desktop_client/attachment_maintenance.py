"""API-backed fixed attachment catalog maintenance. Never edits quote snapshots."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QTextEdit, QComboBox, QStackedWidget, QTableWidgetItem,
    QHeaderView, QScrollArea, QMessageBox, QTableWidget, QAbstractItemView, QDialog)
from quote_scheme_widgets import SchemePage, SchemeComboBox, ServerNotice, METRICS, COLORS, apply_light_action, page_style_sheet
from ui_typography import PAGE_TITLE_PX
from quote_scheme_center import QuoteSchemeWorker, _headers
from dialog_style import style_dialog
import name_login

MAINTAINERS = ('戴晨丽', '姜艳娟', '翟晓峰', '吕芝森')
UI = dict(editor_height=96, action_width=190, table_min_height=150, editor_min_width=180)
FIELDS = (('item_name','附件名称 *'),('model_code','型号 / 规格'),('unit','单位 *'),
          ('category_level1','一级分类 *'),('category_level2','二级分类'),('category_level3','三级分类'),
          ('width_mm','宽度（mm，可选）'),('depth_mm','深度（mm，可选）'),('height_mm','高度（mm，可选）'),
          ('variant','规格补充'),('color','颜色'))
LABELS = dict(FIELDS, quick_face_price='快速报价面价', notes='备注')

def authorized():
    return (name_login.session() or {}).get('person', {}).get('display_name') in MAINTAINERS

def number(value):
    if value is None: return '—'
    return format(Decimal(str(value)), 'f')

def scope(rule):
    return ' / '.join(product_label(code) for code in (rule.get('products') or ['通用'])) + ' · ' + ' / '.join(rule.get('materials') or ['全部材质'])

def product_label(code):
    return str(code).replace('_WIDE_EXP','超宽').replace('_SINGLE','（单门）').replace('_DOUBLE','（双门）')

def fill(table, rows):
    table.setRowCount(len(rows))
    for i, values in enumerate(rows):
        for j, value in enumerate(values):
            cell=QTableWidgetItem(str(value if value is not None else '—'))
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cell.setToolTip(cell.text());table.setItem(i,j,cell)
    table.resizeRowsToContents()

def grid(headers):
    result=QTableWidget(0,len(headers));result.setObjectName('quoteSchemeTable');result.setHorizontalHeaderLabels(headers)
    result.verticalHeader().hide();result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    result.horizontalHeader().setStretchLastSection(True)
    return result

def button(text, callback, primary=False):
    result=QPushButton(text);result.setObjectName('scheme2PrimaryAction' if primary else 'scheme2SecondaryAction')
    if not primary: apply_light_action(result)
    result.clicked.connect(callback);return result

class AttachmentMaintenance(SchemePage):
    def __init__(self, window):
        super().__init__();self.setObjectName('quoteSchemeCenterPage');self.setStyleSheet(page_style_sheet()+f'QWidget#quoteSchemeCenterPage QLabel#attachmentMaintenanceTitle {{font-size:{PAGE_TITLE_PX}px;}} QWidget#attachmentMaintenanceEditor {{background:{COLORS["background"]};}} QScrollArea#attachmentMaintenanceScroll {{border:0;}}');self.window=window;self.worker=None;self.rows=[];self.products=[]
        self.current=None;self.pending=None;self.unsaved=False;self.pending_reload=False;self.ready=False
        self._queued_new=False;self._picker=None;self._saving=False
        outer=QVBoxLayout(self);outer.setContentsMargins(*([METRICS['page_margin']]*4));outer.setSpacing(METRICS['section_gap'])
        self.notice=ServerNotice();self.notice.setWordWrap(True)
        self.pages=QStackedWidget();outer.addWidget(self.pages,1);outer.addWidget(self.notice)
        self._build_list();self._build_editor();self._build_confirm();self._build_formula()

    def _page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(METRICS['section_gap']);self.pages.addWidget(page)
        return layout

    def _build_list(self):
        box=self._page();head=QHBoxLayout();title=QLabel('附件管理');title.setObjectName('attachmentMaintenanceTitle')
        head.addWidget(title);head.addStretch();self.refresh_button=button('刷新',self.reload)
        self.add_button=button('＋ 新增附件',lambda:self.edit(None),True);head.addWidget(self.refresh_button);head.addWidget(self.add_button);box.addLayout(head)
        tabs=QHBoxLayout();self.catalog_tab=button('附件库',lambda:self.set_tab(False));self.audit_tab=button('变更记录',lambda:self.set_tab(True))
        tabs.addWidget(self.catalog_tab);tabs.addWidget(self.audit_tab);tabs.addStretch();box.addLayout(tabs)
        self.list_pages=QStackedWidget();box.addWidget(self.list_pages,1)
        catalog=QWidget();layout=QVBoxLayout(catalog);layout.setContentsMargins(0,0,0,0)
        filters=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('附件名称 / 型号 / 分类');self.search.textChanged.connect(self.render)
        self.kind=SchemeComboBox();self.kind.addItem('全部成本类型','ALL');self.kind.addItem('固定成本','FIXED');self.kind.addItem('公式成本 / 其他','OTHER');self.kind.currentIndexChanged.connect(self.render)
        self.status=SchemeComboBox();self.status.addItem('全部状态',None);self.status.addItem('已启用',True);self.status.addItem('已停用',False);self.status.currentIndexChanged.connect(self.render)
        filters.addWidget(self.search,2);filters.addWidget(self.kind,1);filters.addWidget(self.status,1);layout.addLayout(filters)
        self.table=grid(('附件 / 规格','适用产品 / 材质','快速报价面价','成本类型','固定成本','状态','操作'))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6,QHeaderView.ResizeMode.Fixed)
        layout.addWidget(self.table,1);self.count=QLabel();layout.addWidget(self.count)
        foot=QLabel('附件库调整用于后续报价。历史正式报价保留原价格和成本；草稿需明确选择后重新计算。');foot.setWordWrap(True);layout.addWidget(foot)
        self.list_pages.addWidget(catalog)
        self.history_table=grid(('时间 / 操作人','附件','操作','变化明细','修改原因'));self.list_pages.addWidget(self.history_table)

    def _build_editor(self):
        box=self._page();top=QHBoxLayout();top.addWidget(button('‹ 返回附件库',self.cancel_edit));self.editor_title=QLabel();top.addWidget(self.editor_title);top.addStretch();box.addLayout(top)
        area=QScrollArea();area.setObjectName('attachmentMaintenanceScroll');area.setWidgetResizable(True);content=QWidget();content.setObjectName('attachmentMaintenanceEditor');layout=QVBoxLayout(content);self.form_grid=QGridLayout();self.fields={}
        self.advanced=QWidget();advanced_grid=QGridLayout(self.advanced);advanced_grid.setContentsMargins(0,0,0,0)
        for index,(key,title) in enumerate(FIELDS):
            field=QLineEdit();field.setAccessibleName(title);field.setMaxLength(dict(item_name=160,model_code=100,unit=20,category_level1=40,category_level2=160,category_level3=200,variant=80,color=80).get(key,6));self.fields[key]=field
            target=self.form_grid if index<6 else advanced_grid;position=index if index<6 else index-6
            target.addWidget(QLabel(title),position//3*2,position%3);target.addWidget(field,position//3*2+1,position%3)
            field.textEdited.connect(self.mark_dirty)
        layout.addLayout(self.form_grid)
        more=button('更多规格（尺寸 / 颜色）',lambda:self.advanced.setVisible(not self.advanced.isVisible()));layout.addWidget(more,0,Qt.AlignmentFlag.AlignLeft);layout.addWidget(self.advanced);self.advanced.hide()
        self.product=SchemeComboBox();self.product.setAccessibleName('新增附件适用产品');self.product.currentIndexChanged.connect(self.mark_dirty)
        self.product_label=QLabel('适用产品（已有附件保留原适用规则）');layout.addWidget(self.product_label);layout.addWidget(self.product)
        self.price=QLineEdit();self.price.setAccessibleName('快速报价面价');self.price.textEdited.connect(self.mark_dirty)
        prices=QHBoxLayout();quick=QVBoxLayout();quick.addWidget(QLabel('快速报价面价 *（元 / 附件单位）'));quick.addWidget(self.price);self.old_price=QLabel();quick.addWidget(self.old_price);quick.addStretch()
        costs=QVBoxLayout();costs.addWidget(QLabel('固定成本 *（计入成本计算的附件成本）'))
        self.costs=grid(('适用产品 / 材质（保留原规则）','固定成本（元 / 附件单位）'));self.costs.setMinimumHeight(UI['table_min_height']);costs.addWidget(self.costs)
        prices.addLayout(quick,1);prices.addLayout(costs,1);layout.addLayout(prices)
        self.notes=QTextEdit();self.notes.setAccessibleName('备注');self.notes.setFixedHeight(UI['editor_height']);self.notes.textChanged.connect(self.mark_dirty);layout.addWidget(QLabel('备注'));layout.addWidget(self.notes)
        self.reason=QLineEdit();self.reason.setMaxLength(500);self.reason.setAccessibleName('修改原因');self.reason.textEdited.connect(self.mark_dirty);layout.addWidget(QLabel('本次修改原因 *'));layout.addWidget(self.reason)
        hint=QLabel('仅固定成本附件可在本期新增和维护；公式成本规则保持原样。面价和成本均不可留空，0表示已确认的零金额。');hint.setWordWrap(True);layout.addWidget(hint);layout.addStretch();area.setWidget(content);box.addWidget(area,1)
        actions=QHBoxLayout();actions.addStretch();actions.addWidget(button('取消',self.cancel_edit));actions.addWidget(button('核对并保存',self.prepare_save,True));box.addLayout(actions)

    def _build_confirm(self):
        box=self._page();self.confirm_title=QLabel('确认附件修改');box.addWidget(self.confirm_title)
        self.diffs=grid(('修改项','原值','新值'));box.addWidget(self.diffs,1)
        self.confirm_reason=QLabel();self.confirm_reason.setWordWrap(True);box.addWidget(self.confirm_reason)
        hint=QLabel('确认后生成新的附件修订记录。历史报价、原附件记录和原成本规则不改写。');hint.setWordWrap(True);box.addWidget(hint)
        actions=QHBoxLayout();actions.addStretch();actions.addWidget(button('继续修改',lambda:self.pages.setCurrentIndex(1)));self.save_button=button('确认保存',self.save,True);actions.addWidget(self.save_button);box.addLayout(actions)

    def _build_formula(self):
        box=self._page();box.addWidget(button('‹ 返回附件库',lambda:self.pages.setCurrentIndex(0)))
        self.formula_title=QLabel();box.addWidget(self.formula_title);self.formula_table=grid(('适用范围','类型','材料 / 重量规则','喷塑规则','辅材 / 人工规则'))
        box.addWidget(self.formula_table,1);hint=QLabel('第一期仅查看公式成本规则；试算沿用成本计算页的附件弹窗，不在资料维护页重复计算。');hint.setWordWrap(True);box.addWidget(hint)

    def mark_dirty(self,*_):
        if self.pages.currentIndex()==1:self.unsaved=True

    def has_unsaved(self):return self.unsaved

    def request(self,path,callback,payload=None):
        if self.worker is not None:return False
        try:headers=_headers(self.window)
        except Exception as error:self.notice.setText(str(error));return False
        epoch=name_login.identity_epoch();self.pages.setEnabled(False)
        worker=QuoteSchemeWorker('GET' if payload is None else 'POST',self.window.base_url().rstrip('/')+path,headers,payload,self.window);self.worker=worker
        def loaded(body):
            if name_login.window_is_current(self.window,epoch):callback(body)
        def failed(message):
            if name_login.window_is_current(self.window,epoch):self.notice.setText(message)
        def done():
            self.worker=None;self.pages.setEnabled(True);worker.deleteLater()
            if self.pending_reload:self.pending_reload=False;self.reload()
        worker.succeeded.connect(loaded);worker.failed.connect(failed);worker.finished.connect(done);worker.start();return True

    def reload(self):
        if self.unsaved:self.notice.setText('请先保存或取消当前附件修改。');return
        if not authorized():self.ready=False;self.rows=[];self.render();self.notice.setText('当前姓名没有公共附件库维护权限。');return
        self.notice.setText('正在读取附件库…')
        def loaded(body):
            self.rows=body.get('items',[]);self.products=body.get('products',[]);self.ready=True;self.render();self.notice.setText('已读取公共附件库。价格单位为元 / 附件单位。')
            if self._queued_new:self._queued_new=False;QTimer.singleShot(0,lambda:self.edit(None))
        self.request('/api/attachments/maintenance',loaded)

    def set_tab(self,history):
        self.list_pages.setCurrentIndex(1 if history else 0)
        if history:
            def loaded(body):
                data=[]
                for event in body.get('items',[]):
                    before=event.get('before_state') or {};after=event['after_state'];old=before.get('item') or {};new=after.get('item') or {}
                    changes=[]
                    for key,title in LABELS.items():
                        if str(old.get(key) or '')!=str(new.get(key) or ''):changes.append(f'{title}：{old.get(key) if old.get(key) is not None else "—"} → {new.get(key) if new.get(key) is not None else "—"}')
                    old_rules=before.get('rules') or [];new_rules=after.get('rules') or []
                    for index,rule in enumerate(new_rules):
                        previous=old_rules[index].get('fixed_cost') if index<len(old_rules) else None
                        if previous!=rule.get('fixed_cost'):changes.append(f'固定成本：{number(previous)} → {number(rule.get("fixed_cost"))}')
                    if old.get('is_active')!=new.get('is_active'):changes.append('状态：'+('已启用' if new.get('is_active') else '已停用'))
                    data.append((str(event['created_at'])+'\n'+event['actor_name'],new.get('item_name'),dict(CREATE='新增',EDIT='编辑',ENABLE='启用',DISABLE='停用').get(event['action']), '\n'.join(changes),event['reason']))
                fill(self.history_table,data);self.notice.setText('显示最近200条变更记录。')
            self.request('/api/attachments/maintenance/history',loaded)

    def render(self,*_):
        if not hasattr(self,'table'):return
        term=self.search.text().strip().lower();kind=self.kind.currentData();status=self.status.currentData()
        data=[r for r in self.rows if term in ' '.join(str(r.get(k) or '') for k in ('item_name','model_code','category_level1','category_level2','category_level3')).lower()
              and (kind=='ALL' or bool(r.get('editable'))==(kind=='FIXED')) and (status is None or r['is_active']==status)]
        fill(self.table,[(r['item_name']+'\n'+str(r.get('model_code') or ''),'\n'.join(scope(x) for x in r['rules']) or '—',number(r['quick_face_price']),
            '固定成本' if r['editable'] else '公式成本 / 其他',' / '.join(number(x['fixed_cost']) for x in r['rules']) if r['editable'] else '—','已启用' if r['is_active'] else '已停用','') for r in data])
        for index,row in enumerate(data):
            actions=QWidget();layout=QHBoxLayout(actions);layout.setContentsMargins(0,0,0,0)
            layout.addWidget(button('编辑' if row['editable'] else '查看',lambda _=False,r=row:self.edit(r) if r['editable'] else self.inspect(r)))
            toggle=button('停用' if row['is_active'] else '启用',lambda _=False,r=row:self.toggle(r));toggle.setEnabled(row['editable']);layout.addWidget(toggle)
            layout.addStretch()
            self.table.setCellWidget(index,6,actions)
        self.table.setColumnWidth(6,UI['action_width']);self.table.resizeRowsToContents();self.count.setText(f'显示 {len(data)} 项 / 共 {len(self.rows)} 项附件')
        self.add_button.setEnabled(self.ready and authorized())

    def edit(self,row):
        if not authorized() or not self.ready:self.notice.setText('请先刷新附件库并核对维护权限。');return
        if row is not None and not row.get('editable'):return
        self.current=deepcopy(row);self.pending=None
        for key,field in self.fields.items():field.setText(str((row or {}).get(key) or ('件' if key=='unit' else '其他附件' if key=='category_level1' else '')))
        self.price.setText(str(row['quick_face_price']) if row else '');self.notes.setPlainText(str((row or {}).get('notes') or ''));self.reason.clear()
        self.old_price.setText('当前面价：'+str(row['quick_face_price'])+' 元' if row else '与成本分开维护，按附件单位计价。')
        self.advanced.setVisible(bool(row and any(row.get(key) for key in ('width_mm','height_mm','depth_mm','variant','color'))))
        self.product.clear();self.product.addItem('通用（全部产品）',[])
        for code in self.products:self.product.addItem(product_label(code),[code])
        self.product.setVisible(row is None);self.product_label.setVisible(row is None)
        rules=(row or {}).get('rules') or [dict(fixed_cost=None,products=[],materials=[])]
        fill(self.costs,[(scope(r), '') for r in rules]);self.cost_fields=[]
        for index,rule in enumerate(rules):
            edit=QLineEdit('' if rule['fixed_cost'] is None else str(rule['fixed_cost']));edit.setAccessibleName('固定成本 '+scope(rule));edit.textEdited.connect(self.mark_dirty);self.costs.setCellWidget(index,1,edit);self.cost_fields.append(edit)
        self.editor_title.setText('编辑附件 · '+row['item_name'] if row else '新增固定成本附件');self.pages.setCurrentIndex(1);self.unsaved=False;self.notice.setText('面价用于快速报价，固定成本计入附件成本。')

    def cancel_edit(self):
        if self.worker is not None:return
        if self.unsaved and QMessageBox.question(self,'放弃附件修改','放弃本次未保存的附件修改？',QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Discard:return
        self.unsaved=False;self.pending=None;self.pages.setCurrentIndex(0);self.notice.clear()

    def prepare_save(self):
        try:
            item={k:f.text().strip() or None for k,f in self.fields.items()};item.update(quick_face_price=self.price.text().strip(),notes=self.notes.toPlainText().strip())
            if not all(item.get(k) for k in ('item_name','unit','category_level1')):raise ValueError('请填写附件名称、单位和一级分类。')
            for key in ('width_mm','height_mm','depth_mm'):
                if item[key] is not None:
                    d=Decimal(item[key]);
                    if d!=d.to_integral_value() or not 0<d<=100000:raise ValueError('尺寸须为1至100000的整数毫米。')
                    item[key]=int(d)
            rules=[]
            for index,field in enumerate(self.cost_fields):
                value=field.text().strip();d=Decimal(value)
                if not d.is_finite() or not 0<=d<=100000000:raise ValueError('固定成本须为有效非负数。')
                rules.append(dict(fixed_cost=value,**({'rule_id':self.current['rules'][index]['rule_id']} if self.current else {})))
            face=Decimal(item['quick_face_price'])
            if not face.is_finite() or not 0<=face<=100000000:raise ValueError('快速报价面价须为有效非负数。')
            reason=self.reason.text().strip()
            if not reason:raise ValueError('请填写本次修改原因。')
            self.pending=dict(action='EDIT' if self.current else 'CREATE',request_id=str(uuid4()),item=item,cost_rules=rules,reason=reason)
            if self.current:self.pending['attachment_price_id']=self.current['attachment_price_id']
            else:self.pending['products']=self.product.currentData() or []
            diff=[]
            for key,title in LABELS.items():
                old=(self.current or {}).get(key);new=item.get(key)
                if str(old or '')!=str(new or ''):diff.append((title,old if old is not None else '—',new if new is not None else '—'))
            for i,rule in enumerate(rules):
                old=self.current['rules'][i]['fixed_cost'] if self.current else None
                if old is None or Decimal(str(old))!=Decimal(rule['fixed_cost']):diff.append(('固定成本 · '+scope((self.current or {}).get('rules',[{}])[i]),number(old),rule['fixed_cost']))
            if not diff:raise ValueError('尚未修改附件内容。')
            fill(self.diffs,diff);self.confirm_title.setText('确认附件修改 · '+item['item_name']);self.confirm_reason.setText('原因：'+reason);self.pages.setCurrentIndex(2);self.unsaved=True
        except (ValueError,InvalidOperation) as error:self.notice.setText(str(error) if isinstance(error,ValueError) else '请填写有效金额和尺寸，必填金额不能留空。')

    def save(self):
        if not self.pending:return
        def saved(body):
            if not body.get('saved'):self.notice.setText('服务端未确认保存，请保留当前内容并重试。');return
            self.unsaved=False;self.pending=None;self.pages.setCurrentIndex(0)
            if hasattr(self.window,'_attachment_catalog_cache'):del self.window._attachment_catalog_cache
            if self._picker is not None:
                from shiboken6 import isValid
                if isValid(self._picker):self._picker.catalog_hint.setText('附件已保存，请点击重新读取价格库获取新附件；当前所选条目未改动。')
                self._picker=None
            self.notice.setText('附件已保存；历史报价保持原快照。');self.pending_reload=True
        self.notice.setText('正在保存，请稍候…');self.request('/api/attachments/maintenance',saved,self.pending)

    def toggle(self,row):
        from PySide6.QtWidgets import QInputDialog
        action='DISABLE' if row['is_active'] else 'ENABLE';title='停用附件' if row['is_active'] else '启用附件'
        reason,ok=QInputDialog.getText(self,title,row['item_name']+'\n请填写操作原因；历史报价保持原样。')
        if not ok:return
        if not reason.strip():self.notice.setText('请填写操作原因。');return
        self.pending=dict(action=action,request_id=str(uuid4()),attachment_price_id=row['attachment_price_id'],reason=reason.strip());self.save()

    def inspect(self,row):
        self.formula_title.setText(row['item_name']+' · 成本规则（只读）')
        values=[]
        for r in row['rules']:
            f=r.get('formulas') or {};values.append((scope(r),r['method'],str(f.get('weight_kg') or '')+'\n'+str(f.get('material_cost') or ''),str(f.get('spray_area_m2') or '')+'\n'+str(f.get('spray_cost') or ''),str(f.get('auxiliary_cost') or '')+'\n'+str(f.get('labor_cost') or '')))
        fill(self.formula_table,values);self.pages.setCurrentIndex(3)

def install_attachment_maintenance(namespace):
    cls=namespace['MainWindow']
    if getattr(cls,'_attachment_maintenance_installed',False):return
    cls._attachment_maintenance_installed=True
    previous_init,previous_section,previous_close=cls.__init__,cls.show_section,cls.closeEvent
    def init(window,*args,**kwargs):
        previous_init(window,*args,**kwargs);page=AttachmentMaintenance(window);window.attachment_maintenance=page
        route=window.stack.addWidget(page);window.attachment_maintenance_route=route
        nav=QPushButton('基础资料');nav.setObjectName('navButton');nav.setCheckable(True);nav.setFixedHeight(window.nav_buttons[0].height());nav.setVisible(authorized())
        nav.clicked.connect(lambda:window.show_section(route));window.attachment_maintenance_nav=nav
        layout=window.scheme2_nav.layout();last=window.quote_analysis_nav_button;layout.insertWidget(layout.indexOf(last)+1,nav)
        window.nav_buttons.append(nav);window.nav_routes=(*window.nav_routes,(route,'基础资料','',None))
    def section(window,index):
        page=getattr(window,'attachment_maintenance',None)
        if page and window.stack.currentIndex()==window.attachment_maintenance_route and index!=window.attachment_maintenance_route and (page.unsaved or page.worker is not None):
            page.notice.setText('请先保存或取消附件修改，再切换页面。');return
        if page and index==window.attachment_maintenance_route:
            if not authorized():page.notice.setText('当前姓名没有公共附件库维护权限。');return
            window.stack.setCurrentIndex(index)
            for nav in window.nav_buttons:nav.setChecked(nav is window.attachment_maintenance_nav)
            from scheme2_ui import _apply_responsive
            _apply_responsive(window)
            QTimer.singleShot(0,lambda:_apply_responsive(window))
            if not page.unsaved:page.pages.setCurrentIndex(0);page.reload()
            return
        result=previous_section(window,index)
        if hasattr(window,'attachment_maintenance_nav'):window.attachment_maintenance_nav.setChecked(False)
        return result
    def close(window,event):
        page=getattr(window,'attachment_maintenance',None)
        if page and (page.worker is not None or page.unsaved):
            page.notice.setText('请先等待附件保存完成，或取消未保存的附件修改，再关闭程序。');event.ignore();return
        return previous_close(window,event)
    cls.__init__,cls.show_section,cls.closeEvent=init,section,close
    if not getattr(name_login,'_attachment_maintenance_guard',False):
        prior=name_login.critical_tasks
        name_login.critical_tasks=lambda window:prior(window) or bool(getattr(getattr(window,'attachment_maintenance',None),'unsaved',False))
        name_login._attachment_maintenance_guard=True
    # Reuse the existing picker entry, so users cannot accidentally add a
    # quick-only catalog row instead of the approved fixed-cost workflow.
    import layout_refresh
    def picker_add(owner,_namespace):
        window=owner
        while window is not None and not hasattr(window,'attachment_maintenance'):window=window.parentWidget()
        if window is None:return
        if not authorized():QMessageBox.warning(owner,'无维护权限','当前姓名没有公共附件库维护权限。');return
        # Keep the original modal picker and its uncommitted selections alive.
        # Reuse exactly the same editor; an explicit picker refresh loads the
        # new catalog after maintenance, never rewrites current selections.
        class EditorDialog(QDialog):
            def reject(self):
                if self.page.worker is not None:self.page.notice.setText('请等待附件请求完成。');return
                if self.page.unsaved:
                    self.page.cancel_edit()
                    if self.page.unsaved:return
                super().reject()
        dialog=EditorDialog(owner);dialog.setWindowTitle('新增固定成本附件');dialog.resize(owner.width(),owner.height())
        layout=QVBoxLayout(dialog);page=AttachmentMaintenance(window);dialog.page=page;layout.addWidget(page)
        page._picker=owner;page._queued_new=True;layout.addWidget(button('关闭',dialog.reject));style_dialog(dialog)
        owner._attachment_maintenance_dialog=dialog;page.reload();dialog.exec()
    layout_refresh._show_add_attachment_dialog=picker_add
