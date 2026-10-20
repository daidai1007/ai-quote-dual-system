"""Isolated Qt lifecycle prototype: sample records, no API or database writes.

Uses the current application shell and existing table/dialog components. Nothing
installs this preview in the production launcher; executable builds are untouched.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import QDate, QRect, QRectF, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget
import quote_scheme_center as centre
import quote_scheme_widgets as widgets
import scheme2_ui as ui
from dialog_style import style_dialog
from ui_typography import AUXILIARY_PX, BODY_PX
import v3_launcher


LABELS = dict(DRAFT='草稿', QUOTED='已报价', REVISING='修订中',
              WAIT_CONTRACT='待签合同', COMPLETED='已完成', LOST='未成交', VOID='已作废')
BADGES = {**centre.STATUS_COLORS, 'QUOTED':('#EAF2FF','#185FA5'),
          'WAIT_CONTRACT':('#F1ECFF','#6741A5'), 'COMPLETED':('#EAF3DE','#237804'),
          'LOST':('#F3F4F6','#64748B')}
ARCHIVE_BADGE = ('#F3F5F8','#64748B')
ARCHIVE_ROLE = Qt.ItemDataRole.UserRole+1
ARCHIVE_FILTER = '__ARCHIVED__'
HEADERS = ('方案编号','下单公司','产品','状态','报价金额','版本','创建人','审核人','更新时间','操作')
LAYOUT = dict(full_columns=(166,150,104,148,108,62,78,78,136,206),
              compact_columns=(166,126,96,148,108,62,78,78,136,116),
              full_actions_width=1320, dialog_width=620, dialog_inset=20, dialog_gap=16)
TERMINAL = {'COMPLETED','LOST','VOID'}


def sample_rows():
    states = ('COMPLETED','WAIT_CONTRACT','QUOTED','REVISING','DRAFT','LOST','VOID','COMPLETED','LOST')
    amounts = (7969.62,7399.76,18696.91,7976.44,627.67,1122.34,26535.33,3741.53,5815.65)
    products = ('JP；JA','JP；JA','JQ；JE；JP','JS；JE','JA','JE','JQ；JE；JP','JE','JQ')
    companies = ('华东电气有限公司','苏州精密机械有限公司','上海电子科技有限公司',
                 '宁波成套设备有限公司','无锡电控设备有限公司','杭州自动化设备有限公司',
                 '常州设备制造有限公司','苏州精密机械有限公司','上海电子科技有限公司')
    return [dict(scheme_no=f'BJ-20261020-{9-i:06d}',status=status,archived=i>=7,
                 company_name=companies[i],product_summary=products[i],quoted_amount=amounts[i],
                 version_no=(2,2,1,3,1,2,1,2,1)[i],creator_name='戴晨丽' if i!=3 else '钱玉楠',
                 reviewer_name='',updated_at=f'2026-10-20 {10-i//3:02d}:{36-i*3:02d}',
                 contract_no=f'HT-20261020-{9-i:03d}' if status=='COMPLETED' else '',
                 contract_date='2026-10-20' if status=='COMPLETED' else '')
            for i,status in enumerate(states)]


def fit_preview_columns(table):
    width = table.viewport().width()
    compact = width < LAYOUT['full_actions_width']
    columns = list(LAYOUT['compact_columns'] if compact else LAYOUT['full_columns'])
    columns[0] = max(columns[0],table.fontMetrics().horizontalAdvance('BJ-20261020-000009')+32)
    columns[8] = max(columns[8],table.fontMetrics().horizontalAdvance('2026-10-20 10:36')+32)
    extra = max(0, width-sum(columns))
    columns[1] += extra//2
    columns[2] += extra-extra//2
    for column,value in enumerate(columns):
        if table.columnWidth(column)!=value:
            table.setColumnWidth(column,value)
    table.compact_actions = compact
    for row in range(table.rowCount()):
        actions = table.cellWidget(row,9)
        if isinstance(actions,widgets.RowActions):
            actions.set_compact(compact)
    if table.state_label is not None:
        table.state_label.setGeometry(table.viewport().rect())


class LifecycleStatusDelegate(widgets.StatusBadgeDelegate):
    def paint(self,painter,option,index):
        if not index.data(ARCHIVE_ROLE):
            return super().paint(painter,option,index)
        # One status cell, two truthful tags: archival never erases the result.
        from PySide6.QtWidgets import QStyleOptionViewItem,QStyle
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base,index)
        base.text = ''
        style = base.widget.style() if base.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,base,painter,base.widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(base.font)
        code = index.data(Qt.ItemDataRole.UserRole)
        labels = ((self.labels[code],self.colors[code]),('已归档',ARCHIVE_BADGE))
        gap = widgets.METRICS['field_gap']
        padding = widgets.METRICS['badge_padding']
        widths = [painter.fontMetrics().horizontalAdvance(label)+2*padding for label,_ in labels]
        x = option.rect.center().x()-(sum(widths)+gap)/2
        height = widgets.METRICS['badge_height']
        for (label,(background,foreground)),width in zip(labels,widths):
            rect = QRectF(x,option.rect.center().y()-height/2,width,height)
            painter.setPen(QPen(QColor(background).darker(112)))
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(rect,widgets.METRICS['badge_radius'],widgets.METRICS['badge_radius'])
            painter.setPen(QColor(foreground))
            painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,label)
            x += width+gap
        painter.restore()


class LifecyclePreview:
    def __init__(self):
        self.app = QApplication.instance() or QApplication([])
        self.namespace = v3_launcher.load_v3_namespace()
        self.namespace['install_application_font'](self.app)
        self.patches = ExitStack()
        cls = self.namespace['MainWindow']
        screen = Mock(wraps=self.app.primaryScreen())
        screen.availableGeometry.return_value = QRect(0,0,4096,2160)
        self.patches.enter_context(patch.object(cls,'screen',return_value=screen))
        self.patches.enter_context(patch.object(cls,'load_catalogs',lambda w:None))
        self.patches.enter_context(patch.object(cls,'refresh_formula_inputs',lambda w,*a:None))
        self.patches.enter_context(patch.object(widgets.SchemeTable,'fit_columns',fit_preview_columns))
        self.patches.enter_context(patch.object(centre,'_load_list',lambda w,*a:self.populate()))
        self.patches.enter_context(patch.object(centre,'_open_scheme',lambda w,no,*a:self.notice('打开方案',no)))
        self.patches.enter_context(patch.object(centre,'_new_scheme',lambda w:self.notice('新建方案','本次仅预览界面，不创建线上方案。')))
        self.patches.enter_context(patch.object(centre.QuoteSchemeWorker,'start',self.no_network))
        self.patches.enter_context(patch.object(self.namespace['ApiWorker'],'start',
            lambda worker:QTimer.singleShot(0,lambda:(worker.failed.emit('离线视觉预览'),worker.finished.emit()))))
        self.rows = sample_rows()
        self.window = cls()
        w = self.window
        w.base_url = lambda:'http://127.0.0.1:9'
        w.setWindowTitle('AI 双报价系统 · 报价流程视觉预览')
        w._scheme2_loading_order = True
        w._scheme2_dirty = False
        w.quote_scheme_operator_name.setText('戴晨丽')
        w.quote_scheme_page.findChild(QLabel,'quoteSchemeServerNotice').setText('视觉预览 · 示例数据')
        w.scheme2_service_status.setText('离线预览模式')
        table = w.quote_scheme_table
        table.setColumnCount(len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.setItemDelegateForColumn(3,LifecycleStatusDelegate(LABELS,BADGES,table))
        with QSignalBlocker(w.quote_scheme_status_filter):
            w.quote_scheme_status_filter.clear()
            w.quote_scheme_status_filter.addItem('全部','')
            for code,label in LABELS.items():
                w.quote_scheme_status_filter.addItem(label,code)
            w.quote_scheme_status_filter.insertSeparator(w.quote_scheme_status_filter.count())
            w.quote_scheme_status_filter.addItem('已归档',ARCHIVE_FILTER)
        with QSignalBlocker(w.product_combo):
            w.product_combo.clear()
            for name in ('JA','JC','JE','JK','JM','JP','JP WIDE','JQ','JS','JS WIDE','操作台'):
                w.product_combo.addItem(name,name)
        centre._sync_product_filter(w)
        w.quote_scheme_reset.clicked.disconnect()
        w.quote_scheme_reset.clicked.connect(self.reset_filters)
        w.quote_scheme_status_filter.currentIndexChanged.connect(lambda *_:self.populate())
        self.dialogs = []
        self.window.resize(1553,980)
        self.window.show()
        ui._set_nav_collapsed(w,False,manual=True)
        w.show_section(centre.SCHEME_ROUTE)
        self.populate()
        QTest.qWait(80)

    @staticmethod
    def no_network(*args):
        raise AssertionError('The lifecycle visual preview must not access an API.')

    def reset_filters(self):
        w = self.window
        for editor in w.quote_scheme_filters.values():
            editor.clear() if isinstance(editor,QLineEdit) else editor.setCurrentIndex(0)
        w.quote_scheme_status_filter.setCurrentIndex(0)
        self.populate()

    def populate(self):
        if not hasattr(self,'window'): return
        w = self.window
        table = w.quote_scheme_table
        status = w.quote_scheme_status_filter.currentData()
        filters = centre._filters(w,1)
        rows = [r for r in self.rows if (not status or r['status']==status
                                      or status==ARCHIVE_FILTER and r['archived'])
                and all(not filters.get(key) or str(filters[key]).lower() in str(r.get(field,'')).lower()
                        for key,field in (('scheme_no','scheme_no'),('company','company_name'),
                                          ('product','product_summary'),('creator','creator_name')))
                and (not filters.get('updated_from') or r['updated_at'][:10]>=filters['updated_from'])
                and (not filters.get('updated_to') or r['updated_at'][:10]<=filters['updated_to'])]
        table.setRowCount(len(rows))
        for row,r in enumerate(rows):
            display_status = LABELS[r['status']]+(' · 已归档' if r['archived'] else '')
            values = (r['scheme_no'],r['company_name'],r['product_summary'],display_status,
                      f"¥ {r['quoted_amount']:,.2f}",
                      f"V{r['version_no']}",r['creator_name'],r['reviewer_name'] or '—',r['updated_at'])
            for column,value in enumerate(values):
                alignment = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if column==4 else
                            Qt.AlignmentFlag.AlignHCenter if column==5 else Qt.AlignmentFlag.AlignLeft)
                table.setItem(row,column,centre._item(value,alignment))
            table.item(row,0).setData(Qt.ItemDataRole.UserRole,deepcopy(r))
            table.item(row,3).setData(Qt.ItemDataRole.UserRole,r['status'])
            table.item(row,3).setData(ARCHIVE_ROLE,r['archived'])
            table.item(row,3).setToolTip(display_status)
            table.item(row,5).setToolTip(f"当前报价版本：V{r['version_no']}")
            table.setCellWidget(row,9,self.actions(r))
        w.quote_scheme_count.setText(f'共 {len(rows)} 条记录')
        w.quote_scheme_page_status.setText('没有符合条件的方案' if not rows else '')
        w.quote_scheme_page_status.setVisible(not rows)
        table.fit_columns()

    def actions(self,row):
        status = row['status']
        direct = ['打开']
        labels = ['打开']
        if status=='COMPLETED': labels+=['打印','导出','合同']; direct+=['合同']
        elif status=='WAIT_CONTRACT': labels+=['确认合同','修订','标记未成交','作废']; direct+=['确认合同']
        elif status=='QUOTED': labels+=['客户确认','打印','导出','修订','标记未成交','作废']; direct+=['客户确认']
        elif status=='REVISING': labels+=['继续修订','作废']; direct+=['继续修订']
        elif status=='DRAFT': labels+=['复制','作废']; direct+=['复制']
        elif status=='LOST' and not row['archived']: labels+=['重新跟进']
        if '复制' not in labels: labels+=['复制']
        if status in TERMINAL: labels+=['取消归档' if row['archived'] else '归档']
        callbacks = [(label,lambda _checked=False,r=row,a=label:self.act(r,a)) for label in labels]
        return widgets.RowActions(callbacks,direct)

    def act(self,row,action):
        if action in ('确认合同','合同'):
            dialog = self.contract_dialog(row,readonly=action=='合同')
            dialog.show()
            return
        targets = {'客户确认':'WAIT_CONTRACT','修订':'REVISING','作废':'VOID','标记未成交':'LOST','重新跟进':'QUOTED'}
        if action in targets or action in ('归档','取消归档'):
            dialog = ui._SchemeConfirmDialog(self.window,action,
                f"{row['scheme_no']} · V{row['version_no']}\n"+
                ('只改变归档标记，不改变业务状态。' if action in ('归档','取消归档') else f'确认{action}此报价方案？'),
                '确认'+action,'取消')
            def confirmed():
                if action in targets:
                    row['status'] = targets[action]
                    if action=='修订': row['version_no']+=1
                else: row['archived']=action=='归档'
                self.populate()
            dialog.accepted.connect(confirmed)
            self.keep_dialog(dialog)
            dialog.show()
        else:
            self.notice(action,f"{row['scheme_no']} · V{row['version_no']}\n视觉预览，不执行文件导出或线上操作。")

    def keep_dialog(self,dialog):
        style_dialog(dialog)
        self.dialogs.append(dialog)
        return dialog

    def notice(self,title,text):
        dialog = ui._SchemeConfirmDialog(self.window,title,text,'知道了','关闭')
        self.keep_dialog(dialog)
        dialog.show()

    def contract_dialog(self,row,readonly=False):
        dialog = ui._SchemeConfirmDialog(self.window,'合同信息' if readonly else '确认合同完成','',
                                        '关闭' if readonly else '确认完成','取消')
        dialog.shell.setFixedWidth(LAYOUT['dialog_width'])
        shell_layout = dialog.shell.layout()
        old = shell_layout.itemAt(1).widget()
        shell_layout.removeWidget(old)
        old.hide()
        old.deleteLater()
        body = QWidget()
        body.setObjectName('quoteContractBody')
        c = widgets.COLORS
        body.setStyleSheet(f"QWidget#quoteContractBody QLabel {{color:{c['text']};font-size:{BODY_PX}px;}} "
                          f"QWidget#quoteContractBody QLineEdit {{background:{c['background']};color:{c['text']};"
                          f"border:1px solid {c['border']};border-radius:4px;padding:0 10px;min-height:38px;font-size:{BODY_PX}px;}}")
        grid = QGridLayout(body)
        inset = LAYOUT['dialog_inset']
        grid.setContentsMargins(inset,inset,inset,inset)
        grid.setHorizontalSpacing(LAYOUT['dialog_gap'])
        grid.setVerticalSpacing(LAYOUT['dialog_gap'])
        grid.setColumnStretch(0,1); grid.setColumnStretch(1,1)
        grid.addWidget(QLabel(row['scheme_no']),0,0)
        amount = QLabel(f"最终报价：¥ {row['quoted_amount']:,.2f}")
        amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(amount,0,1)
        company = QLabel('下单公司：'+row['company_name'])
        grid.addWidget(company,1,0,1,2)
        contract = QLineEdit(row['contract_no'])
        contract.setPlaceholderText('请输入合同编号')
        contract.setReadOnly(readonly)
        date = widgets.DateFilter('contractConfirmDate','合同确认日期')
        date.setText(row['contract_date'] or '2026-10-20')
        date.setEnabled(not readonly)
        version = QLineEdit(f"V{row['version_no']}（当前正式报价版本）")
        version.setReadOnly(True)
        operator = QLineEdit('戴晨丽')
        operator.setReadOnly(True)
        for caption,editor,r,col in (('合同编号 *',contract,2,0),('合同确认日期 *',date,2,1),
                                    ('最终报价版本',version,3,0),('登记人',operator,3,1)):
            grid.addWidget(widgets.filter_field(caption,editor,'contractField'+str(r)+str(col)),r,col)
        attachment = QLabel('合同附件（可选）　未添加')
        grid.addWidget(attachment,4,0)
        choose = QPushButton('选择附件')
        choose.setObjectName('scheme2ConfirmReject')
        choose.clicked.connect(lambda:attachment.setText('合同附件（可选）　合同扫描件.pdf（示例）'))
        grid.addWidget(choose,4,1,Qt.AlignmentFlag.AlignRight)
        if readonly: choose.hide()
        message = QLabel('合同已确认，报价流程已结束。' if readonly else
                         '确认后状态变为“已完成”，并锁定此报价版本。后续仍可查看、打印和导出。')
        message.setWordWrap(True)
        message.setStyleSheet(f"font-size:{AUXILIARY_PX}px;color:{c['muted']};")
        grid.addWidget(message,5,0,1,2)
        error = QLabel('')
        error.setStyleSheet('color:'+centre.STATUS_COLORS['VOID'][1])
        error.hide()
        grid.addWidget(error,6,0,1,2)
        shell_layout.insertWidget(1,body)
        dialog.accept_button.clicked.disconnect()
        def confirm():
            if readonly: dialog.accept(); return
            if not contract.text().strip():
                error.setText('请填写合同编号后再确认完成。'); error.show(); contract.setFocus(); return
            if not QDate.fromString(date.text().strip(),'yyyy-MM-dd').isValid():
                error.setText('请填写有效的合同确认日期（YYYY-MM-DD）。'); error.show(); return
            row.update(status='COMPLETED',contract_no=contract.text().strip(),contract_date=date.text())
            self.populate()
            dialog.accept()
        dialog.accept_button.clicked.connect(confirm)
        dialog.reject_button.setDefault(True)
        if readonly: dialog.reject_button.hide()
        dialog.contract_number,dialog.contract_date,dialog.final_version = contract,date,version
        return self.keep_dialog(dialog)

    def capture(self,output):
        output = Path(output)
        output.mkdir(parents=True,exist_ok=True)
        QTest.qWait(100)
        self.window.quote_scheme_table.selectRow(1)
        self.app.processEvents()
        assert self.window.grab().save(str(output/'scheme-lifecycle-overview.png'))
        dialog = self.contract_dialog(self.rows[1])
        dialog.contract_number.setText('HT-20261020-008')
        dialog.show()
        QTest.qWait(100)
        assert dialog.shell.grab().save(str(output/'confirm-contract-dialog.png'))
        dialog.reject()

    def close(self):
        for dialog in self.dialogs: dialog.close()
        self.window._quote_scheme_save_timer.stop()
        self.window._quote_scheme_id = ''
        self.window._scheme2_dirty = False
        self.window.close()
        self.app.processEvents()
        self.patches.close()


if __name__=='__main__':
    preview = LifecyclePreview()
    if '--capture' in sys.argv:
        target = sys.argv[sys.argv.index('--capture')+1]
        preview.capture(target)
        preview.close()
        print('PREVIEW_CAPTURE=PASS '+str(Path(target).resolve()))
    else:
        result = preview.app.exec()
        preview.close()
        sys.exit(result)
