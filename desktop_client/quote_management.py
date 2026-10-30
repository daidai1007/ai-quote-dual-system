"""Quotation management over the existing V3 document and scheme controllers.

The original quote table, printer and transactional XLSX exporter remain alive.
Versions contain only document data, never copies of drawing files.
"""
from copy import deepcopy
from types import MethodType
import urllib.parse

from PySide6.QtCore import QDate, QDateTime, QTimeZone, QSignalBlocker, Qt, QTimer, QEventLoop
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget, QRadioButton, QButtonGroup, QSizePolicy, QGridLayout, QHeaderView,
    QScrollArea, QStyledItemDelegate, QStyleOptionViewItem, QStyle)

import quote_management_model as model
import quote_order_nature as nature
from quote_scheme_widgets import DateFilter, QueryLineEdit, SchemeComboBox, filter_field, METRICS, apply_light_action
from quick_discount_rules import money, money_sum, quick_discount_category

# Approved quote-management surfaces; scoped to this module, not the cost page.
PAGE_STYLE = """
QWidget { color:#20344e; font-family:'Microsoft YaHei UI'; font-size:14px; }
QWidget#quoteManagementListPage, QWidget#quoteManagementDetail { background:#f3f6fa; }
QWidget#quoteManagementDocument { background:white; }
QWidget#quoteManagementAdjust { background:#f3f6fa; }
QFrame#quoteManagementSheet { background:white; border:1px solid #dce4ee; border-radius:5px; }
QWidget#quoteManagementListPage QLabel, QWidget#quoteManagementDetail QLabel { background:transparent; }
QFrame#quoteManagementCustomer, QFrame#quoteManagementAmount { background:white; border:1px solid #dce4ee; border-radius:5px; }
QLabel#quoteManagementAmountValue { font-size:25px; font-weight:600; color:#20344e; }
QLabel#scheme2PageTitle { font-size:23px; font-weight:600; }
QPushButton { background:white; border:1px solid #dce4ee; border-radius:5px; padding:8px 13px; color:#20344e; }
QPushButton#scheme2PrimaryAction { background:#2463bd; color:white; border-color:#2463bd; }
QPushButton:hover { border-color:#2463bd; }
QPushButton:disabled { color:#8798ad; background:#eef2f7; }
QLineEdit, QPlainTextEdit, QComboBox { background:white; border:1px solid #dce4ee; border-radius:5px; padding:7px; }
QTableWidget { font-size:12px; background:white; alternate-background-color:white; border:1px solid #dce4ee; gridline-color:#dce4ee; selection-background-color:#eaf2ff; selection-color:#20344e; }
QHeaderView::section { font-size:12px; background:#f3f6fa; color:#63748a; border:0; border-bottom:1px solid #dce4ee; padding:11px 10px; font-weight:400; }
QPushButton#quoteManagementLink { color:#2463bd; border:0; background:transparent; padding:2px 0; text-align:left; }
QWidget#quoteManagementAdjust QLabel { background:transparent; }
QLabel#quoteManagementBatchTitle { font-weight:600; }
QLabel#quoteManagementBatchScope { color:#63748a; font-size:12px; }
QLabel#quoteManagementBatchStatus { color:#2463bd; font-size:12px; }
QFrame#quoteManagementBatch { border:0; border-bottom:1px solid #dce4ee; background:white; }
QWidget#quoteManagementAdjustCell { background:white; }
QWidget#quoteManagementAdjustCell[batchMatch="true"] { background:#f3f8ff; }
QTabWidget::pane { background:white; border:1px solid #dce4ee; border-radius:5px; }
QTabBar::tab { background:white; border:0; border-bottom:2px solid transparent; padding:12px 15px; color:#20344e; }
QTabBar::tab:selected { color:#2463bd; border-bottom-color:#2463bd; }
QTextBrowser { background:white; border:1px solid #dce4ee; }
"""

# Logical pixels; reuse the approved light-action control for all page actions.
ADJUST_METRICS = dict(product_width=174, factor_width=130, field_gap=12,
                      section_gap=14, row_height=88,
                      columns=(280, 64, 130, 130, 90, 110))


def button(text, callback, primary=False):
    control = QPushButton(text)
    control.setObjectName('scheme2PrimaryAction' if primary else 'scheme2PrimaryGhost')
    control.clicked.connect(callback)
    control.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return control


def table(headers):
    control = QTableWidget(0, len(headers))
    control.setHorizontalHeaderLabels(headers)
    control.setWordWrap(True)
    control.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    control.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    control.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    control.verticalHeader().hide()
    control.horizontalHeader().setStretchLastSection(True)
    return control


def fill(control, rows, editable=()):
    with QSignalBlocker(control):
        control.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if c not in editable:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                control.setItem(r, c, cell)
        control.resizeRowsToContents()
        for r in range(control.rowCount()):
            control.setRowHeight(r, max(44, control.rowHeight(r)))


def factor_text(value):
    return f'{float(value):.4f}'.rstrip('0').rstrip('.') or '0'


class PriceInputDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        if index.column() not in (0,2,5): return super().paint(painter,option,index)
        background=QStyleOptionViewItem(option); self.initStyleOption(background,index); background.text=''
        background.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem,background,painter,background.widget)


class AttachmentPriceDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        import scheme2_ui as ui
        self.item = deepcopy(item)
        self.setWindowTitle('附件价格')
        self.setStyleSheet(PAGE_STYLE)
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        self.grid = table(('附件', '每台用量', '附件单价', '附件金额', '折扣范围'))
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        rows = []
        for row in self.item.get('attachments') or []:
            qty = float(row.get('quantity') or 1)
            amount = ui._popup_quick_amount(row)
            rows.append((row.get('item_name') or row.get('model_code') or '附件', qty,
                         f'{abs(amount / qty):.2f}', f'{amount:,.2f}',
                         '参与折扣' if quick_discount_category(row) else '原价锁定'))
        fill(self.grid, rows, (2,))
        for i, row in enumerate(self.item.get('attachments') or []):
            if not quick_discount_category(row):
                cell = self.grid.item(i, 2)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        layout.addWidget(self.grid)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self.accept); actions.rejected.connect(self.reject); layout.addWidget(actions)

    def accept(self):
        self.grid.clearFocus()
        try:
            pending = deepcopy(self.item)
            for index, row in enumerate(pending.get('attachments') or []):
                if quick_discount_category(row):
                    model.attachment_unit_price(pending, index, self.grid.item(index, 2).text())
            self.item = pending
        except ValueError as error:
            self.error.setText(str(error)); return
        super().accept()


class AdjustQuoteDialog(QWidget):
    HEADERS = ('产品 / 规格', '数量', '折后单价', '折后总价', '原有折扣', '调整折扣')

    def __init__(self, items, number, parent=None):
        super().__init__(parent)
        self.items = deepcopy(items); model.original_discounts(self.items)
        self.original_items = deepcopy(self.items); self.reviewing = False; self.inputs = {}
        self._result = QDialog.DialogCode.Rejected; self._loop = None
        self.errors = {}; self.number = number
        self.setWindowTitle('调整报价'); self.resize(940, 580)
        self.setObjectName('quoteManagementAdjust')
        self.setStyleSheet(PAGE_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 23, 24, 20); layout.setSpacing(14)
        heading = QHBoxLayout()
        self.title = QLabel(f'调整报价  V{max(1, number-1)} → V{number}'); self.title.setObjectName('scheme2PageTitle')
        self.cancel_button = apply_light_action(button('取消调价', self.reject))
        heading.addWidget(self.title, 1); heading.addWidget(self.cancel_button); layout.addLayout(heading)
        if parent is not None and hasattr(parent, 'scheme2_company'):
            layout.addWidget(QLabel(parent.scheme2_company.currentText()))
        sheet = QFrame(); sheet.setObjectName('quoteManagementSheet'); layout.addWidget(sheet,1)
        sheet_layout = QVBoxLayout(sheet); sheet_layout.setContentsMargins(16,16,16,16); sheet_layout.setSpacing(12)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        body=QWidget(); body.setStyleSheet('background:white;'); scroll.setWidget(body); sheet_layout.addWidget(scroll,1)
        layout=QVBoxLayout(body); layout.setContentsMargins(0,0,0,0); layout.setSpacing(12)
        self.build_batch_controls(layout)
        self.grid = table(self.HEADERS)
        self.grid.setItemDelegate(PriceInputDelegate(self.grid))
        self.grid.setObjectName('quoteManagementAdjustTable')
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.horizontalHeader().setStretchLastSection(False)
        self.grid.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for index,width in enumerate(ADJUST_METRICS['columns']): self.grid.setColumnWidth(index,width)
        grid_height = min(500, 48 + max(1,len(items))*ADJUST_METRICS['row_height'])
        self.grid.setFixedHeight(grid_height)
        self.draw()
        self.grid.cellChanged.connect(self.changed)
        layout.addWidget(self.grid)
        self.attachment_panel = QFrame(); self.attachment_panel.setObjectName('quoteManagementSheet')
        self.attachment_layout = QVBoxLayout(self.attachment_panel); self.attachment_panel.hide()
        layout.addWidget(self.attachment_panel)
        self.review_grid = table(('产品 / 规格','原单价','调整后单价','单价变化','金额变化'))
        self.review_grid.horizontalHeader().setStretchLastSection(False)
        self.review_grid.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col in range(1,5): self.review_grid.setColumnWidth(col,145)
        self.review_grid.setFixedHeight(48+max(1,len(items))*44)
        self.review_grid.hide(); layout.addWidget(self.review_grid)
        self.total = QLabel(); self.total.setObjectName('quoteManagementAmountValue')
        layout.addWidget(QLabel('调价原因（必填）'))
        self.reason = QPlainTextEdit(); self.reason.setMaximumHeight(90); layout.addWidget(self.reason)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        layout.addStretch(1)
        sheet_layout.addWidget(self.total, 0, Qt.AlignmentFlag.AlignRight)
        actions = QHBoxLayout(); actions.addWidget(QLabel(f'保存为 V{number} · 不覆盖旧版本')); actions.addStretch(1)
        self.back_button = apply_light_action(button('返回修改', self.back)); self.back_button.hide(); actions.addWidget(self.back_button)
        self.primary = apply_light_action(button('核对调价', self.accept, True), ('核对调价', f'确认保存 V{number}'))
        actions.addWidget(self.primary); sheet_layout.addLayout(actions)
        self.refresh_total()

    def build_batch_controls(self, layout):
        import scheme2_ui as ui
        self.batch_panel = QFrame(); self.batch_panel.setObjectName('quoteManagementBatch')
        panel = QVBoxLayout(self.batch_panel); panel.setContentsMargins(0,0,0,14)
        panel.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel('批量调整折扣'); title.setObjectName('quoteManagementBatchTitle')
        self.batch_scope = QLabel(); self.batch_scope.setObjectName('quoteManagementBatchScope')
        heading.addWidget(title); heading.addWidget(self.batch_scope); heading.addStretch(1)
        panel.addLayout(heading)
        fields = QHBoxLayout(); fields.setSpacing(ADJUST_METRICS['field_gap'])
        self.batch_product = QComboBox(); self.batch_product.setAccessibleName('批量调价产品')
        self.batch_product.setFixedWidth(ADJUST_METRICS['product_width'])
        for product in dict.fromkeys(ui._cost_product(item) for item in self.items):
            self.batch_product.addItem(product, product)
        self.batch_factor = QueryLineEdit(); self.batch_factor.setAccessibleName('批量调整折扣')
        self.batch_factor.setFixedWidth(ADJUST_METRICS['factor_width'])
        self.batch_factor.setAlignment(Qt.AlignmentFlag.AlignRight)
        if self.items: self.batch_factor.setText(factor_text(self.items[0].get('quick_discount',1)))
        fields.addWidget(filter_field('产品', self.batch_product, 'quoteManagementBatchProduct'))
        fields.addWidget(filter_field('调整折扣', self.batch_factor, 'quoteManagementBatchFactor'))
        self.batch_apply = apply_light_action(button('应用到同产品', self.apply_batch_factor))
        fields.addWidget(self.batch_apply, 0, Qt.AlignmentFlag.AlignBottom); fields.addStretch(1)
        panel.addLayout(fields)
        self.batch_feedback = QLabel(); self.batch_feedback.setWordWrap(True)
        self.batch_feedback.setObjectName('quoteManagementBatchStatus'); panel.addWidget(self.batch_feedback)
        layout.addWidget(self.batch_panel)
        self.batch_product.currentIndexChanged.connect(self.batch_product_changed)
        self.batch_factor.returnPressed.connect(self.apply_batch_factor)

    def batch_rows(self):
        import scheme2_ui as ui
        product = self.batch_product.currentData()
        return [row for row,item in enumerate(self.items) if ui._cost_product(item) == product]

    def update_batch_scope(self):
        import scheme2_ui as ui
        rows = self.batch_rows(); matched = set(rows)
        quantity = sum(ui._row_values(self.items[row])[11] for row in rows)
        self.batch_scope.setText(f'{self.batch_product.currentText()} · {len(rows)} 项 / {quantity:g} 台' if rows else '暂无产品')
        self.batch_apply.setEnabled(bool(rows) and not self.reviewing)
        self.batch_product.setEnabled(bool(self.items)); self.batch_factor.setEnabled(bool(rows))
        with QSignalBlocker(self.grid):
            for row in range(self.grid.rowCount()):
                for column in range(self.grid.columnCount()):
                    self.grid.item(row,column).setBackground(QColor('#f3f8ff' if row in matched else 'white'))
                    host = self.grid.cellWidget(row,column)
                    if host is not None:
                        host.setProperty('batchMatch',row in matched)
                        host.style().unpolish(host); host.style().polish(host); host.update()

    def batch_product_changed(self):
        rows = self.batch_rows()
        self.update_batch_scope()
        self.batch_feedback.setText(f'将调整以下 {len(rows)} 项 {self.batch_product.currentText()} 产品' if rows else '')

    def apply_batch_factor(self):
        if self.reviewing: return
        rows = self.batch_rows()
        if not rows:
            self.error.setText('请先选择产品。'); return
        # Replacing matching row inputs can repair them. Incomplete attachment
        # edits or another product's invalid input must never be silently lost.
        for key in self.errors:
            if len(key) != 2 or key[0] not in rows:
                self.error.setText('请先修正其他产品的单价、折扣或附件价格。'); return
        try:
            value = model.decimal_input(self.batch_factor.text(),4,10)
            pending = deepcopy(self.items)
            for row in rows: model.set_factor(pending[row],value)
        except ValueError as error:
            self.error.setText(str(error)); return
        self.items = pending
        self.errors = {key:value for key,value in self.errors.items() if key[0] not in rows}
        self.attachment_panel.hide()
        self.draw(); self.error.clear(); self.refresh_total()
        self.batch_feedback.setText(f'已将 {len(rows)} 项 {self.batch_product.currentText()} 产品的折扣统一调整为 {factor_text(value)}')

    def exec(self):
        # This is a page in the quote stack, not an extra dialog surface.
        self._loop = QEventLoop(self); self.show(); self._loop.exec()
        return self._result

    def finish(self, result):
        self._result = result; self.hide()
        if self._loop is not None: self._loop.quit()

    def reject(self): self.finish(QDialog.DialogCode.Rejected)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.reject()
        else: super().keyPressEvent(event)

    def draw(self):
        with QSignalBlocker(self.grid):
            import scheme2_ui as ui
            rows = []
            for item in self.items:
                values = ui._row_values(item)
                product = ui._cost_product(item)
                name = f'{product} · {values[1]}' if product not in ('—',values[1]) else values[1]
                rows.append((f'{name}\n{values[3]}', values[11], f'{values[15]:.2f}',
                             f'{values[16]:,.2f}', factor_text(item['quote_original_discount']),
                             factor_text(item.get('quick_discount', 1))))
            fill(self.grid, rows, (2, 5))
            self.inputs = {}
            for row in range(len(rows)):
                self.grid.setRowHeight(row, ADJUST_METRICS['row_height'])
                for col in range(1,6):
                    self.grid.item(row,col).setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                        (Qt.AlignmentFlag.AlignHCenter if col==1 else Qt.AlignmentFlag.AlignRight))
                for col in (0,2,5): self.grid.item(row,col).setForeground(QColor('transparent'))
                product = QWidget(); product.setObjectName('quoteManagementAdjustCell')
                product_layout = QVBoxLayout(product); product_layout.setContentsMargins(10,6,10,6)
                product_layout.addWidget(QLabel(rows[row][0]))
                link = button('附件价格', lambda _=False,r=row: self.attachment_row(r)); link.setObjectName('quoteManagementLink')
                product_layout.addWidget(link); self.grid.setCellWidget(row,0,product)
                for col in (2,5):
                    host = QWidget(); host.setObjectName('quoteManagementAdjustCell')
                    host_layout = QHBoxLayout(host); host_layout.setContentsMargins(8,6,8,6)
                    editor = QLineEdit(self.grid.item(row,col).text()); editor.setFixedWidth(104 if col==2 else 78)
                    editor.setAlignment(Qt.AlignmentFlag.AlignRight)
                    editor.setAccessibleName(f'第{row+1}行' + ('折后单价' if col==2 else '调整折扣'))
                    editor.textEdited.connect(lambda text,r=row,c=col:self.grid.item(r,c).setText(text))
                    host_layout.addStretch(1); host_layout.addWidget(editor); self.grid.setCellWidget(row,col,host)
                    self.inputs[row,col] = editor
            self.update_batch_scope()
            if not self.batch_feedback.text(): self.batch_product_changed()

    def changed(self, row, column):
        if column not in (2, 5): return
        candidate = deepcopy(self.items[row])
        try:
            text = self.grid.item(row, column).text()
            (model.set_unit_price if column == 2 else model.set_factor)(candidate, text)
        except ValueError as error:
            self.errors[(row, column)] = str(error)
            self.error.setText(str(error)); self.total.setText('调整后报价总额：—'); return
        self.errors.pop((row, column), None)
        self.items[row] = candidate
        import scheme2_ui as ui
        values = ui._row_values(candidate)
        with QSignalBlocker(self.grid):
            self.grid.item(row, 3).setText(f'{values[16]:,.2f}')
            other = 5 if column == 2 else 2
            self.grid.item(row, other).setText(factor_text(candidate['quick_discount']) if other == 5 else f'{values[15]:.2f}')
            self.inputs[row,other].setText(self.grid.item(row,other).text())
            if not self.inputs[row,column].hasFocus(): self.inputs[row,column].setText(text)
        self.error.setText(next(iter(self.errors.values()), '')); self.refresh_total()

    def refresh_total(self):
        import scheme2_ui as ui
        total = money_sum(ui._row_values(item)[16] for item in self.items)
        self.total.setText('调整后报价总额：' + ('—' if self.errors else f'¥ {total:,.2f}'))

    def attachments(self):
        row = self.grid.currentRow()
        if row < 0:
            self.error.setText('请先选择一行产品。'); return
        if self.errors:
            self.error.setText('请先修正单价或折扣。'); return
        import scheme2_ui as ui
        while self.attachment_layout.count():
            entry = self.attachment_layout.takeAt(0)
            if entry.widget(): entry.widget().deleteLater()
        heading = QHBoxLayout(); heading.addWidget(QLabel('附件价格 · 每台用量')); heading.addStretch(1)
        heading.addWidget(button('收起', self.attachment_panel.hide))
        host = QWidget(); host.setLayout(heading); self.attachment_layout.addWidget(host)
        grid = table(('附件','用量','附件面价单价','面价金额','折扣后金额','分摊范围'))
        attachments = self.items[row].get('attachments') or []
        values=[]
        for attachment in attachments:
            qty=float(attachment.get('quantity') or 1); amount=ui._popup_quick_amount(attachment)
            eligible=bool(quick_discount_category(attachment))
            values.append((attachment.get('item_name') or attachment.get('model_code') or '附件',qty,
                '',f'{amount:,.2f}',f'{money(amount*self.items[row].get("quick_discount",1) if eligible else amount):,.2f}',
                '参与折扣 / 分摊' if eligible else '原价锁定'))
        fill(grid,values)
        for index,attachment in enumerate(attachments):
            qty=float(attachment.get('quantity') or 1)
            editor=QLineEdit(f'{abs(ui._popup_quick_amount(attachment)/qty):.2f}')
            editor.setReadOnly(not bool(quick_discount_category(attachment)))
            editor.textEdited.connect(lambda text,r=row,i=index,g=grid:self.change_attachment(r,i,text,g))
            grid.setCellWidget(index,2,editor)
        grid.setFixedHeight(min(240,48+len(attachments)*44))
        self.attachment_layout.addWidget(grid); self.attachment_panel.show()

    def change_attachment(self,row,index,text,grid):
        candidate=deepcopy(self.items[row])
        try: model.attachment_unit_price(candidate,index,text)
        except ValueError as error:
            self.errors['attachment',row,index]=str(error); self.error.setText(str(error)); self.refresh_total(); return
        self.errors.pop(('attachment',row,index),None); self.items[row]=candidate
        import scheme2_ui as ui
        amount=ui._popup_quick_amount(candidate['attachments'][index])
        grid.item(index,3).setText(f'{amount:,.2f}')
        grid.item(index,4).setText(f'{money(amount*candidate.get("quick_discount",1)):,.2f}')
        self.draw(); self.error.setText(next(iter(self.errors.values()),'')); self.refresh_total()

    def attachment_row(self, row):
        self.grid.selectRow(row); self.attachments()

    def back(self):
        self.reviewing = False; self.grid.show(); self.review_grid.hide()
        self.batch_panel.show(); self.update_batch_scope()
        self.reason.setReadOnly(False); self.back_button.hide(); self.primary.setText('核对调价')
        self.title.setText(f'调整报价  V{max(1,self.number-1)} → V{self.number}')

    def accept(self):
        self.grid.clearFocus()
        if self.errors:
            self.error.setText(next(iter(self.errors.values()))); return
        if not self.reason.toPlainText().strip():
            self.error.setText('请填写调价原因。'); return
        if len(self.reason.toPlainText().strip()) > 160:
            self.error.setText('调价原因最多160字。'); return
        if self.reviewing:
            self.finish(QDialog.DialogCode.Accepted); return
        import scheme2_ui as ui
        rows = []
        for before,after in zip(self.original_items,self.items):
            a,b = ui._row_values(before),ui._row_values(after)
            rows.append((f'{b[1]}\n{b[3]}',f'{a[15]:,.2f}',f'{b[15]:,.2f}',
                         f'{money_sum((b[15],-a[15])):+,.2f}',f'{money_sum((b[16],-a[16])):+,.2f}'))
        fill(self.review_grid,rows)
        self.attachment_panel.hide()
        self.reviewing = True; self.grid.hide(); self.review_grid.show(); self.reason.setReadOnly(True)
        self.batch_panel.hide()
        self.back_button.show(); self.primary.setText(f'确认保存 V{self.number}')
        self.title.setText(f'核对本次调价  V{max(1,self.number-1)} → V{self.number}')


class QuoteManagement:
    def __init__(self, window):
        import scheme2_ui as ui
        self.window = window; self.page_number = 1; self.rows = []; self.list_epoch = 0
        self.history_version = None; self.latest_workspace = None; self.pending_adjust = False
        self.edit_baseline = None
        window._qm_state = model.restore_state(None)
        window._quote_order_nature = 'UNCLASSIFIED'
        window._qm_document_started = False
        window._qm_historical_export_supported = False
        self.root = QStackedWidget(); self.root.setObjectName('scheme2QuotePage')
        self.root.setStyleSheet(PAGE_STYLE)
        self.list_page = QWidget(); self.detail_page = QWidget()
        self.list_page.setObjectName('quoteManagementListPage'); self.detail_page.setObjectName('quoteManagementDetail')
        self.root.addWidget(self.list_page); self.root.addWidget(self.detail_page)
        old = window.scheme2_quote_page
        window.stack.removeWidget(old); window.stack.insertWidget(ui.QUOTE_ROUTE, self.root)
        self.build_list(); self.build_detail(old)
        for nav in window.nav_buttons:
            if nav.text() == '报价单': nav.setText('报价单管理')
        window.nav_routes = tuple((route, '报价单管理' if route == ui.QUOTE_ROUTE else label, *tail)
                                 for route, label, *tail in window.nav_routes)
        self.contract_page = QWidget(); self.contract_route = window.stack.addWidget(self.contract_page)
        contract = QVBoxLayout(self.contract_page)
        title = QLabel('合同管理'); title.setObjectName('scheme2PageTitle'); contract.addWidget(title)
        self.contract_source = QLabel(); self.contract_source.setWordWrap(True); contract.addWidget(self.contract_source)
        self.contract_source.setText('请先在报价单列表选择一条报价单，再点击“生成合同”。')
        contract.addWidget(QLabel('合同管理功能将在后续版本接入，当前尚未生成正式合同。'))
        contract.addWidget(button('返回报价单列表', self.show_list)); contract.addStretch(1)
        contract_nav = QPushButton('合同管理'); contract_nav.setObjectName('navButton'); contract_nav.setCheckable(True)
        contract_nav.clicked.connect(lambda: window.show_section(self.contract_route))
        contract_nav.setFixedHeight(window.nav_buttons[0].height())
        nav_layout = window.scheme2_nav.layout()
        nav_layout.insertWidget(nav_layout.indexOf(window.nav_buttons[-1])+1, contract_nav)
        window.nav_buttons.append(contract_nav); self.contract_nav = contract_nav
        window.nav_routes = (*window.nav_routes, (self.contract_route, '合同管理', '', None))
        window.scheme2_company.currentTextChanged.connect(lambda *_: self.customer_changed())
        self.status_timer = QTimer(window); self.status_timer.setInterval(300)
        self.status_timer.timeout.connect(self.status_changed); self.status_timer.start()
        from quote_delivery import QuoteDelivery
        self.delivery = QuoteDelivery(self)

    def build_list(self):
        layout = QVBoxLayout(self.list_page)
        layout.setContentsMargins(24,23,24,24); layout.setSpacing(18)
        top = QHBoxLayout(); title = QLabel('报价单管理'); title.setObjectName('scheme2PageTitle')
        heading = QVBoxLayout(); heading.setSpacing(4); heading.addWidget(title)
        top.addLayout(heading); top.addStretch(1)
        self.contract_button = apply_light_action(button('生成合同', self.contract, True)); self.contract_button.setEnabled(False)
        top.addWidget(self.contract_button); layout.addLayout(top)
        filter_frame = QFrame(); filter_frame.setObjectName('quoteManagementCustomer')
        filters = QGridLayout(filter_frame); filters.setContentsMargins(15,12,15,12)
        filters.setHorizontalSpacing(METRICS['filter_gap']); filters.setVerticalSpacing(METRICS['filter_gap'])
        self.filters = {}
        for key, label in (('scheme_no','报价单编号'), ('company','客户'), ('creator','创建人')):
            editor = QueryLineEdit(); editor.setPlaceholderText('请输入' + label)
            editor.setObjectName('quoteManagementFilter_' + key); editor.setAccessibleName(label)
            self.filters[key] = editor
        self.filters['product'] = SchemeComboBox()
        self.filters['product'].setAccessibleName('产品筛选')
        self.filters['updated_from'] = DateFilter('quoteManagementUpdatedFrom', '更新时间开始日期')
        self.filters['updated_to'] = DateFilter('quoteManagementUpdatedTo', '更新时间结束日期')
        self.product_sync = QTimer(self.list_page); self.product_sync.setSingleShot(True)
        self.product_sync.timeout.connect(self.sync_filter_products)
        source = self.window.product_combo.model()
        for signal in (source.rowsInserted, source.rowsRemoved, source.modelReset, source.dataChanged):
            signal.connect(lambda *_: self.product_sync.start())
        self.sync_filter_products()
        self.status = SchemeComboBox(); self.status.setAccessibleName('状态筛选')
        for text, code in (('全部',''), ('草稿','DRAFT'), ('已报价','QUOTED'), ('合同','CONTRACT'), ('修订中','REVISING'), ('已归档','ARCHIVED'), ('已作废','VOID')):
            self.status.addItem(text, code)
        self.status.setCurrentIndex(self.status.findData('QUOTED'))
        self.filters['order_nature'] = SchemeComboBox()
        for code, caption in (('', '全部'), *nature.LABELS.items()):
            self.filters['order_nature'].addItem(caption, code)
        self.filters['order_nature'].setAccessibleName('订单性质筛选')
        for column, (label, key) in enumerate((('报价单编号','scheme_no'), ('客户','company'), ('产品','product'), ('创建人','creator'))):
            filters.addWidget(filter_field(label, self.filters[key], 'quoteManagementField_' + key),0,column)
            filters.setColumnStretch(column,1)
        filters.addWidget(filter_field('状态', self.status, 'quoteManagementField_status'),1,0)
        filters.addWidget(filter_field('订单性质', self.filters['order_nature'], 'quoteManagementField_order_nature'),2,0)
        dates = QHBoxLayout(); dates.setContentsMargins(0,0,0,0); dates.setSpacing(8)
        dates.addWidget(self.filters['updated_from'],1); dates.addWidget(QLabel('-'))
        dates.addWidget(self.filters['updated_to'],1)
        filters.addWidget(filter_field('更新时间', dates, 'quoteManagementField_updated'),1,1,1,2)
        actions = QHBoxLayout(); actions.setContentsMargins(0,0,0,0); actions.setSpacing(METRICS['action_gap'])
        self.query_button = button('查询', lambda: self.load_list(1), True)
        self.reset_button = button('重置', self.reset_search)
        for control in (self.query_button, self.reset_button):
            apply_light_action(control); actions.addWidget(control)
        actions.addStretch(1)
        filters.addLayout(actions,1,3,Qt.AlignmentFlag.AlignBottom)
        for editor in (*self.filters.values(), self.status):
            editor.setMinimumWidth(0 if not isinstance(editor,DateFilter) else 96)
            editor.setFixedHeight(METRICS['field_height'])
            editor.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            if isinstance(editor,QLineEdit):editor.returnPressed.connect(lambda: self.load_list(1))
        layout.addWidget(filter_frame)
        self.list_sheet = QFrame(); self.list_sheet.setObjectName('quoteManagementSheet')
        sheet = QVBoxLayout(self.list_sheet); sheet.setContentsMargins(0,0,0,0); sheet.setSpacing(0)
        caption = QHBoxLayout(); caption.setContentsMargins(16,13,16,13)
        caption.addWidget(QLabel('报价单列表')); caption.addStretch(1)
        self.selection_caption = QLabel('请选择一条报价单，再生成合同'); caption.addWidget(self.selection_caption)
        sheet.addLayout(caption)
        self.list_table = table(('选择', '报价单编号', '客户', '订单性质', '状态 / 版本', '含税金额（元）', '更新人 / 时间', '操作'))
        self.list_table.setObjectName('quoteManagementList'); self.list_table.setColumnWidth(0, 46); self.list_table.setColumnWidth(1, 210)
        self.row_group = QButtonGroup(self.list_table); self.row_group.setExclusive(True)
        self.list_table.horizontalHeader().setStretchLastSection(False)
        for index,width in enumerate((46,205,150,85,115,135,160,65)): self.list_table.setColumnWidth(index,width)
        self.list_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.list_table.itemSelectionChanged.connect(self.selection_changed)
        self.list_table.cellDoubleClicked.connect(lambda row, _column: self.open_row(row))
        sheet.addWidget(self.list_table)
        layout.addWidget(self.list_sheet)
        footer = QHBoxLayout(); self.list_status = QLabel('请选择报价单'); self.list_status.setWordWrap(True)
        footer.addWidget(self.list_status, 1)
        footer.addWidget(QLabel('生成合同后进入合同管理'))
        self.previous_page = button('上一页', lambda: self.load_list(max(1, self.page_number - 1)))
        self.next_page = button('下一页', lambda: self.load_list(self.page_number + 1))
        self.retry_list = button('重试', lambda: self.load_list(self.page_number))
        for control in (self.previous_page,self.next_page,self.retry_list):
            control.hide(); footer.addWidget(control)
        layout.addLayout(footer); layout.addStretch(1)
        self.fit_list()

    def sync_filter_products(self):
        from quote_scheme_center import _configured_product_options
        target = self.filters['product']; options = [('全部',''), *_configured_product_options(self.window)]
        if options == [(target.itemText(i),target.itemData(i)) for i in range(target.count())]:return
        selected = target.currentData()
        with QSignalBlocker(target):
            target.clear()
            for label,value in options:target.addItem(label,value)
            target.setCurrentIndex(max(0,target.findData(selected)))

    def fit_list(self):
        # Content-sized like the approved sheet; long lists scroll within the
        # available page rather than reserving an empty full-height viewport.
        self.list_table.setFixedHeight(min(430, self.list_table.horizontalHeader().height() +
            sum(self.list_table.rowHeight(r) for r in range(self.list_table.rowCount())) + 4))

    def build_detail(self, old):
        layout = QVBoxLayout(self.detail_page)
        layout.setContentsMargins(24,23,24,20); layout.setSpacing(12)
        breadcrumb = QHBoxLayout()
        breadcrumb.addWidget(button('报价单管理', self.show_list)); breadcrumb.addStretch(1)
        layout.addLayout(breadcrumb)
        top = QHBoxLayout(); self.heading = QLabel('报价单详情'); self.heading.setObjectName('scheme2PageTitle')
        top.addWidget(self.heading, 1)
        self.save_button = button('保存草稿', self.save)
        self.discard_button = button('放弃修改', self.discard)
        self.adjust_button = button('调整报价', self.adjust, True)
        self.latest_button = button('回到最新版本', self.restore_latest)
        self.detail_contract_button = button('生成合同', self.contract_from_detail)
        w = self.window
        # The approved header owns print/export; the quote-list page has no
        # actions for an unrelated active workspace in the old bottom dock.
        for control in (w.scheme2_quote_print, w.scheme2_quote_export):
            if control.parentWidget() is not None and control.parentWidget().layout() is not None:
                control.parentWidget().layout().removeWidget(control)
            control.setParent(self.detail_page)
            control.setObjectName('scheme2PrimaryGhost')
            control.show()
        w._scheme2_action_dock_entries = [(b,routes) for b,routes in w._scheme2_action_dock_entries
            if b not in (w.scheme2_quote_print, w.scheme2_quote_export)]
        for control in (w.scheme2_quote_print, w.scheme2_quote_export, self.detail_contract_button, self.adjust_button, self.latest_button):
            top.addWidget(control)
        layout.addLayout(top)
        customer = QFrame(); customer.setObjectName('quoteManagementCustomer')
        customer_column = QVBoxLayout(customer); customer_column.setContentsMargins(16,12,16,12)
        customer_layout = QHBoxLayout(); customer_column.addLayout(customer_layout)
        field = w.scheme2_quote_company_field
        if field.parentWidget() is not None and field.parentWidget().layout() is not None:
            field.parentWidget().layout().removeWidget(field)
        field.setParent(customer); customer_layout.addWidget(field,1)
        field.setToolTip('可选择已有客户，也可输入新客户')
        self.nature_group = QButtonGroup(customer)
        self.nature_controls = {}
        customer_layout.addWidget(QLabel('订单性质 *'))
        for code in ('INTERNAL', 'EXTERNAL'):
            control = QRadioButton(nature.LABELS[code]); control.setObjectName('quoteOrderNature' + code.title())
            control.setAccessibleName('订单性质：' + nature.LABELS[code]); self.nature_group.addButton(control)
            self.nature_controls[code] = control; customer_layout.addWidget(control)
            control.clicked.connect(lambda _checked=False, code=code: self.nature_changed(code))
        customer_layout.addStretch(1)
        customer_layout.addWidget(self.save_button); customer_layout.addWidget(self.discard_button)
        self.nature_help = QLabel(); self.nature_help.setWordWrap(True); customer_column.addWidget(self.nature_help)
        layout.addWidget(customer)
        header = old.layout().takeAt(0)
        if header and header.layout():
            while header.layout().count():
                item = header.layout().takeAt(0)
                if item.widget(): item.widget().hide()
        old.setObjectName('quoteManagementDocument')
        amount_frame = QFrame(); amount_frame.setObjectName('quoteManagementAmount')
        amount_layout = QHBoxLayout(amount_frame); amount_layout.setContentsMargins(16,10,16,10)
        self.meta = QLabel(); self.meta.setWordWrap(True); amount_layout.addWidget(self.meta,1)
        self.amount = QLabel(); self.amount.setObjectName('quoteManagementAmountValue'); amount_layout.addWidget(self.amount)
        layout.addWidget(amount_frame)
        self.tabs = QTabWidget(); self.tabs.setObjectName('quoteManagementTabs')
        self.tabs.addTab(old, '报价单')
        self.items_table = table(('名称', '规格', '数量', '折后单价', '折后总价', '原有折扣', '调整折扣'))
        self.tabs.addTab(self.items_table, '报价明细')
        self.history = table(('版本', '客户', '报价总额', '修改时间', '操作人', '调价原因', '操作'))
        self.tabs.addTab(self.history, '调价历史')
        comparison = QWidget(); compare_layout = QVBoxLayout(comparison); choices = QHBoxLayout()
        self.from_version = QComboBox(); self.to_version = QComboBox()
        self.compare_clear = button('清除', self.clear_comparison)
        self.compare_clear.setToolTip('清除版本选择，显示全部版本与上一版的对比')
        self.from_version.setAccessibleName('原版本');self.to_version.setAccessibleName('对比版本')
        choices.addWidget(self.from_version); choices.addWidget(QLabel('对比')); choices.addWidget(self.to_version)
        choices.addWidget(self.compare_clear); choices.addStretch(1)
        compare_layout.addLayout(choices)
        self.compare_table = table(('版本对比', '产品', '数量', '原折后单价', '新折后单价', '变化明细'))
        self.compare_table.setObjectName('quoteManagementVersionComparison')
        for column,width in enumerate((155,150,80,120,120)):
            self.compare_table.setColumnWidth(column,width)
        self.compare_table.horizontalHeader().sectionResized.connect(lambda *_:self.compare_table.resizeRowsToContents())
        compare_layout.addWidget(self.compare_table); self.tabs.addTab(comparison, '版本对比')
        preview_page = QWidget(); preview_layout = QVBoxLayout(preview_page); actions = QHBoxLayout()
        actions.addWidget(button('打印', lambda: self.window.scheme2_quote_print.click()))
        actions.addWidget(button('导出 Excel', self.export_selected, True)); actions.addStretch(1)
        preview_layout.addLayout(actions); self.preview = QTextBrowser(); preview_layout.addWidget(self.preview)
        self.tabs.addTab(preview_page, '预览与导出'); layout.addWidget(self.tabs, 1)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        self.from_version.currentIndexChanged.connect(self.compare)
        self.to_version.currentIndexChanged.connect(self.compare)
        self.tabs.currentChanged.connect(lambda *_: self.refresh())

    @property
    def state(self): return self.window._qm_state

    def operator(self):
        editor = getattr(self.window, 'quote_scheme_operator_name', None)
        return editor.text().strip() if editor else ''

    def sync(self):
        w = self.window
        if self.history_version is None and (self.state.get('versions') or getattr(w, '_qm_document_started', False)):
            model.sync_latest(self.state, w.draft_items, w.scheme2_company.currentText(), self.operator(), w._quote_scheme_quote_date, nature.current(w))
        return deepcopy(self.state)

    def snapshot(self): return self.sync()

    def load_state(self, payload):
        self.history_version = None; self.latest_workspace = None
        self.window._qm_view_history = False
        source = payload.get('quote_management')
        pending = getattr(self,'revision_source',None)
        if not source and pending and pending['scheme_no']==self.window._quote_scheme_id and self.window._quote_scheme_status=='REVISING':
            source = pending['state']
        self.window._qm_state = model.restore_state(source)
        document = payload.get('document') or {}
        self.window._quote_order_nature = nature.normalize(document.get('order_nature', payload.get('order_nature')))
        self.window._quote_order_nature_locked = False
        if 'company' in payload:
            with QSignalBlocker(self.window.scheme2_company): self.window.scheme2_company.setCurrentText(str(payload.get('company') or ''))
        self.window._qm_document_started = bool(self.window.draft_items)
        if self.state['versions'] and self.state['versions'][-1].get('sealed') and self.window._quote_scheme_status == 'REVISING':
            entry = model.append_version(self.state, self.window.draft_items, self.window.scheme2_company.currentText(),
                '创建修订版', self.operator(), self.window._quote_scheme_quote_date, nature.current(self.window))
            entry['revision_draft'] = True
            entry['pending_confirmation'] = True
            entry.pop('confirmed', None)
        self.sync()
        if self.state['versions'] and self.window._quote_scheme_status in ('QUOTED','CONTRACT','ARCHIVED','VOID'):
            self.state['versions'][-1]['sealed'] = True
        self.remember_saved()

    def generated(self):
        self.window._qm_document_started = True
        self.restore_latest(refresh=False); self.sync()
        self.window._qm_entry_pending = True
        self.root.setCurrentWidget(self.detail_page); self.tabs.setCurrentIndex(0); self.refresh()

    def show_detail(self):
        self.window._qm_document_started = True
        self.root.setCurrentWidget(self.detail_page); self.tabs.setCurrentIndex(getattr(self,'entry_tab',0)); self.entry_tab = 0; self.refresh()
        from scheme2_ui import _position_scheme2_action_dock
        _position_scheme2_action_dock(self.window)
        if self.edit_baseline is None: self.remember_saved()
        if self.pending_adjust:
            self.pending_adjust = False; QTimer.singleShot(0, self.adjust)

    def show_list(self):
        if getattr(self.window,'_detail_contract_busy',False):return
        self.restore_latest(refresh=False)
        self.window._qm_show_list = True
        self.window.show_section(2)

    def reset_search(self):
        for editor in self.filters.values():
            if isinstance(editor,QLineEdit):editor.clear()
            else:editor.setCurrentIndex(0)
        self.status.setCurrentIndex(self.status.findData('QUOTED')); self.load_list(1)

    def list_filters(self, page):
        values = {key: editor.text().strip() if isinstance(editor,QLineEdit) else str(editor.currentData() or '')
                  for key,editor in self.filters.items()}
        for key in ('updated_from','updated_to'):
            if values[key] and (len(values[key]) != 10 or not QDate.fromString(values[key],'yyyy-MM-dd').isValid()):
                raise ValueError('更新时间请输入 YYYY-MM-DD 格式的有效日期，或通过日历选择。')
        if values['updated_from'] and values['updated_to'] and values['updated_from'] > values['updated_to']:
            raise ValueError('开始日期不能晚于结束日期，请重新选择更新时间范围。')
        values.update(page=page,page_size=20,status=self.status.currentData() or '')
        return {key:value for key,value in values.items() if value != ''}

    def load_list(self, page=1):
        import quote_scheme_center as centre
        try: query = self.list_filters(page)
        except ValueError as error:
            self.list_status.setText(str(error)); return
        self.list_epoch += 1; epoch = self.list_epoch
        self.page_number = page; self.rows = []; fill(self.list_table, [])
        self.contract_button.setEnabled(False); self.list_status.setText('正在加载报价单…')
        self.selection_caption.setText('请选择一条报价单，再生成合同'); self.retry_list.hide(); self.fit_list()
        def loaded(result):
            if epoch != self.list_epoch: return
            self.rows = list(result.get('items') or [])
            rows = [('', q['scheme_no'] + '\n' + str(q.get('product_summary') or ''), q.get('company_name') or '未选择客户',
                     nature.LABELS[nature.normalize(q.get('order_nature'))],
                     centre.STATUS_TEXT.get(q.get('status'), q.get('status', '')) + f"\nV{q.get('quote_version') or q.get('version_no', 1)}",
                     '—' if q.get('quoted_amount') is None else f"{float(q['quoted_amount']):,.2f}",
                     str(q.get('last_editor_name') or q.get('creator_name') or '') + '\n' + self.updated_time(q.get('updated_at')), '') for q in self.rows]
            fill(self.list_table, rows)
            for r in range(len(rows)):
                self.list_table.setRowHeight(r, 80)
                radio = QRadioButton(); radio.setAccessibleName('选择报价单 ' + self.rows[r]['scheme_no'])
                radio.clicked.connect(lambda _=False,r=r: self.list_table.selectRow(r))
                self.row_group.addButton(radio)
                selection = QWidget(); selection_layout = QHBoxLayout(selection)
                selection_layout.setContentsMargins(0,0,0,0)
                selection_layout.addWidget(radio,0,Qt.AlignmentFlag.AlignCenter)
                self.list_table.setCellWidget(r, 0, selection)
                actions = QWidget(); action_layout = QVBoxLayout(actions); action_layout.setContentsMargins(8,6,8,6); action_layout.setSpacing(2)
                for label, tab in (('查看',0),('导出',4)):
                    if label=='导出' and self.rows[r].get('can_write') is False:continue
                    action = button(label, lambda _=False,r=r,t=tab:self.open_row(r,t)); action.setObjectName('quoteManagementLink')
                    action_layout.addWidget(action)
                self.list_table.setCellWidget(r, 7, actions)
            total = int(result.get('total',len(rows)))
            self.list_status.setText(f"共 {total} 份报价单 · 单选" + (f' · 第{page}页' if total>20 else ''))
            self.previous_page.setVisible(total>20 or page>1); self.previous_page.setEnabled(page>1)
            self.next_page.setVisible(total>20 or page>1); self.next_page.setEnabled(page*20<total)
            if not rows: self.list_status.setText('没有符合条件的报价单，请更换关键词或重置查询。')
            self.fit_list()
        def failed(message):
            if epoch == self.list_epoch:
                self.list_status.setText('报价单加载失败，请重试。'); self.list_status.setToolTip(str(message)); self.retry_list.show()
        centre._run(self.window, 'GET', '/api/quote-schemes?' + urllib.parse.urlencode(query), None, loaded, failed)

    @staticmethod
    def updated_time(value):
        stamp = QDateTime.fromString(str(value or ''),Qt.DateFormat.ISODateWithMs)
        if not stamp.isValid():stamp = QDateTime.fromString(str(value or ''),Qt.DateFormat.ISODate)
        # Match the business date used by the server-side date range.
        return stamp.toTimeZone(QTimeZone(b'Asia/Shanghai')).toString('yyyy-MM-dd HH:mm:ss') if stamp.isValid() else str(value or '')[:19]

    def selection_changed(self):
        index=self.list_table.currentRow()
        eligible = 0 <= index < len(self.rows) and self.rows[index].get('source_kind')!='LEDGER_CONTRACT' and self.rows[index].get('can_write') is not False and self.rows[index].get('order_nature') == 'EXTERNAL' and self.rows[index].get('status') in ('QUOTED','CONTRACT','ARCHIVED','REVISING')
        self.contract_button.setEnabled(eligible)
        self.contract_button.setToolTip('仅外部正式报价可生成合同')
        selection = self.list_table.cellWidget(self.list_table.currentRow(), 0)
        radio = selection.findChild(QRadioButton) if selection is not None else None
        if isinstance(radio, QRadioButton): radio.setChecked(True)
        if 0 <= self.list_table.currentRow() < len(self.rows):
            q = self.rows[self.list_table.currentRow()]
            self.selection_caption.setText(f"已选择 {q['scheme_no']} · V{q.get('quote_version') or q.get('version_no',1)}")

    def open_row(self, row, tab=0):
        if not 0 <= row < len(self.rows): return
        import quote_scheme_center as centre
        self.entry_tab = tab
        centre._open_scheme(self.window, self.rows[row]['scheme_no'], 2)

    def contract(self):
        row = self.list_table.currentRow()
        if not 0 <= row < len(self.rows): return
        q = self.rows[row]
        if q.get('can_write') is False or q.get('order_nature') != 'EXTERNAL':return
        amount = '—' if q.get('quoted_amount') is None else f"¥ {float(q['quoted_amount']):,.2f}"
        self.contract_source.setText(f"来源报价单：{q['scheme_no']}\n报价版本：V{q.get('quote_version') or q.get('version_no', 1)}\n客户：{q.get('company_name') or '未选择客户'}\n报价金额：{amount}")
        self.window.show_section(self.contract_route)

    def refresh(self):
        import scheme2_ui as ui
        w = self.window
        if not hasattr(self, 'tabs'): return
        self.sync()
        selected = self.history_version or len(self.state['versions']) or 1
        self.heading.setText(f'报价单详情 · V{selected}' + (' · 历史只读' if self.history_version else ''))
        if getattr(w,'_name_scope_foreign',False):self.heading.setText(self.heading.text()+' · 他人报价，仅可查看')
        amount = money_sum(ui._row_values(item)[16] for item in w.draft_items)
        self.meta.setText(f"{w._quote_scheme_id or '未登记草稿'}　　V{selected}　　{w._quote_scheme_quote_date}　　{nature.label(w)}\n报价总额 · 含税人民币")
        self.nature_group.setExclusive(False)
        for code, control in self.nature_controls.items():
            with QSignalBlocker(control): control.setChecked(code == nature.current(w))
        self.nature_group.setExclusive(True)
        self.nature_help.setText('正式版本的订单性质已锁定。' if nature.locked(w) else
            '请选择内部或外部；未选择时可以保存草稿。' if nature.current(w) == 'UNCLASSIFIED' else
            '内部报价可打印、导出，不进入合同管理。' if nature.current(w) == 'INTERNAL' else '外部正式报价可用于生成合同。')
        self.amount.setText(f'¥ {amount:,.2f}')
        readonly = w._quote_scheme_read_only or self.history_version is not None
        w.scheme2_company.setEnabled(not readonly and not getattr(w, '_scheme2_document_busy', False))
        self.save_button.setEnabled(not readonly and not getattr(w, '_scheme2_document_busy', False))
        self.discard_button.setEnabled(not readonly and not getattr(w, '_scheme2_document_busy', False))
        self.adjust_button.setEnabled(bool(w.draft_items) and self.history_version is None and w._quote_scheme_status != 'VOID')
        self.latest_button.setVisible(self.history_version is not None)
        fill(self.items_table, [(v[1], v[3], v[11], f'{v[15]:,.2f}', f'{v[16]:,.2f}',
             factor_text(item.get('quote_original_discount', item.get('quick_discount', 1))), factor_text(item.get('quick_discount', 1)))
             for item in w.draft_items for v in [ui._row_values(item)]])
        versions = [version for version in self.state['versions'] if not version.get('pending_confirmation')]
        fill(self.history, [(f"V{v['version']}", v['company'], f"{v['amount']:,.2f}", v['updated_at'], v['operator'], v['reason'], '') for v in versions])
        for row, version in enumerate(versions):
            if self.history.cellWidget(row, 6) is None:
                self.history.setCellWidget(row, 6, button('查看', lambda _=False, n=version['version']: self.view_version(n)))
        with QSignalBlocker(self.from_version), QSignalBlocker(self.to_version):
            before, after = self.from_version.currentData(), self.to_version.currentData()
            document_key=w._quote_scheme_id
            if getattr(self,'_compare_document_key',None)!=document_key:
                before=after=None
            self._compare_document_key=document_key
            self.from_version.clear(); self.to_version.clear()
            self.from_version.addItem('全部版本',None);self.to_version.addItem('全部版本',None)
            for version in versions:
                if version.get('revision_draft'):continue
                self.from_version.addItem(f"V{version['version']}", version['version'])
                self.to_version.addItem(f"V{version['version']}", version['version'])
            self.from_version.setCurrentIndex(max(0, self.from_version.findData(before)))
            self.to_version.setCurrentIndex(max(0, self.to_version.findData(after)))
        self.compare(); self.preview.setHtml(ui._printable_quote_html(w))
        if self.history_version is not None:
            w.scheme2_company.setEnabled(False)
        self.status_changed()

    def clear_comparison(self):
        with QSignalBlocker(self.from_version),QSignalBlocker(self.to_version):
            self.from_version.setCurrentIndex(0);self.to_version.setCurrentIndex(0)
        self.compare()

    def compare(self):
        from quote_version_comparison import comparison_groups,change_details
        groups=comparison_groups(self.state['versions'],self.from_version.currentData(),self.to_version.currentData())
        rows=[];summary_rows=[]
        for group in groups:
            label=f"V{group['current']}（首次报价）" if group['previous'] is None else f"V{group['previous']} → V{group['current']}"
            for row in group['rows']:
                left,right=row['left'],row['right'];item=right or left
                quantity=str(item['quantity'])
                if left and right and left['quantity']!=right['quantity']:
                    quantity=f"{left['quantity']} → {right['quantity']}"
                old='—' if left is None or left['unit'] is None else f"{left['unit']:,.2f}"
                new='—' if right is None or right['unit'] is None else f"{right['unit']:,.2f}"
                if row['summary']:summary_rows.append(len(rows))
                rows.append((label,'本版合计' if row['summary'] else item['name'],quantity,old,new,
                    change_details(left,right,initial=group['previous'] is None)))
        fill(self.compare_table,rows)
        for row in range(self.compare_table.rowCount()):
            cell=self.compare_table.item(row,5);cell.setToolTip(cell.text())
        for row in summary_rows:
            for column in range(self.compare_table.columnCount()):
                cell=self.compare_table.item(row,column)
                font=cell.font();font.setBold(True);cell.setFont(font)
                cell.setBackground(QColor('#e6f0fb'))

    def customer_changed(self):
        if not getattr(self.window, '_quote_scheme_loading', False) and self.history_version is None:
            self.sync(); self.refresh()

    def status_changed(self):
        w = self.window
        from quote_detail_contract import unavailable_reason
        reason=unavailable_reason(w)
        self.detail_contract_button.setEnabled(not reason)
        self.detail_contract_button.setToolTip(reason or '使用当前查看的报价生成合同；首次报价直接确认，无需调整或修订。')
        if hasattr(self, 'delivery'): self.delivery.refresh()
        if hasattr(w, 'quote_scheme_save_status'):
            controller=getattr(self,'detail_contract_controller',None)
            contract_failure=controller.feedback_message() if controller is not None else ''
            self.feedback.setText(contract_failure or w.quote_scheme_save_status.text())
        busy = getattr(w, '_scheme2_document_busy', False) or bool(w._quote_scheme_export_context)
        if getattr(w,'_name_scope_foreign',False):
            for control in (self.adjust_button,self.save_button,self.discard_button,w.scheme2_quote_print,w.scheme2_quote_export):control.setEnabled(False)
            w.scheme2_company.setEnabled(False)
            for control in self.nature_controls.values(): control.setEnabled(False)
            return
        self.adjust_button.setEnabled(bool(w.draft_items) and self.history_version is None and not busy and w._quote_scheme_status != 'VOID')
        self.save_button.setEnabled(not w._quote_scheme_read_only and self.history_version is None and not busy)
        self.discard_button.setEnabled(not w._quote_scheme_read_only and self.history_version is None and not busy)
        w.scheme2_company.setEnabled(not w._quote_scheme_read_only and self.history_version is None and not busy)
        for control in self.nature_controls.values():
            control.setEnabled(not w._quote_scheme_read_only and self.history_version is None and not busy and not nature.locked(w))
        if nature.current(w) == 'UNCLASSIFIED':
            w.scheme2_quote_print.setEnabled(False); w.scheme2_quote_export.setEnabled(False)

    def nature_changed(self, code):
        w = self.window
        if w._quote_scheme_read_only or self.history_version is not None or nature.locked(w) or getattr(w, '_scheme2_document_busy', False): return
        w._quote_order_nature = code
        for version in self.state.get('versions', []):
            if not version.get('sealed') and not version.get('confirmed'): version['order_nature'] = code
        self.sync(); w.refresh_summary()
        from quote_scheme_center import _schedule_save
        _schedule_save(w)

    def contract_from_detail(self):
        controller=getattr(self,'detail_contract_controller',None)
        if controller is not None:controller.start()
        else:self.feedback.setText('合同模块尚未就绪，请稍后重试。')

    def save(self):
        import quote_scheme_center as centre
        if self.history_version is not None or self.window._quote_scheme_read_only: return
        from scheme2_ui import _commit_quote_text_editor
        _commit_quote_text_editor(self.window)
        self.sync()
        if self.window._quote_scheme_id:
            centre._schedule_save(self.window); self.window._quote_scheme_save_timer.stop(); centre._save(self.window)
        else: centre._ensure_created(self.window)

    def remember_saved(self, snapshot=None):
        if self.history_version is not None: return
        if snapshot is not None:
            self.edit_baseline = dict(items=deepcopy(snapshot.get('draft_items') or []),
                company=str(snapshot.get('company') or ''), order_nature=nature.normalize((snapshot.get('document') or {}).get('order_nature', snapshot.get('order_nature'))), state=model.restore_state(snapshot.get('quote_management')))
        else:
            self.edit_baseline = dict(items=deepcopy(self.window.draft_items),
                company=self.window.scheme2_company.currentText(), order_nature=nature.current(self.window), state=deepcopy(self.state))

    def discard(self):
        w = self.window
        if self.edit_baseline is None or w._quote_scheme_read_only or getattr(w, '_scheme2_document_busy', False): return
        source = deepcopy(self.edit_baseline); w._quote_scheme_loading = True
        try:
            w.draft_items = source['items']; w._qm_state = source['state']
            w._quote_order_nature = source['order_nature']
            with QSignalBlocker(w.scheme2_company): w.scheme2_company.setCurrentText(source['company'])
            w.refresh_summary()
        finally: w._quote_scheme_loading = False
        self.refresh(); self.save()

    def adjust(self):
        import quote_scheme_center as centre
        w = self.window
        if getattr(w,'_name_scope_foreign',False):return
        if self.history_version is not None or getattr(w, '_scheme2_document_busy', False): return
        if w._quote_scheme_read_only:
            if w._quote_scheme_status not in ('QUOTED','CONTRACT'):
                QMessageBox.information(w, '报价只读', '请先在报价方案中恢复或修订后再调整。'); return
            operator = centre._require_operator(w, True)
            if not operator: return
            # Old formal quotes have no inferred classification. Open the
            # revision detail first so the operator can classify without repricing.
            self.pending_adjust = nature.current(w) != 'UNCLASSIFIED'
            self.revision_source = dict(scheme_no=w._quote_scheme_id,state=deepcopy(self.state))
            centre._run(w, 'POST', '/api/quote-schemes/' + urllib.parse.quote(w._quote_scheme_id) + '/revision',
                dict(expected_version=w._quote_scheme_version, operator_name=operator),
                lambda result: centre._open_scheme(w, result['scheme_no'], 2),
                lambda message: (setattr(self, 'pending_adjust', False), self.feedback.setText('创建修订失败：' + str(message))))
            return
        self.sync()
        revision_draft = bool(self.state['versions'] and self.state['versions'][-1].get('revision_draft'))
        number = len(self.state['versions']) + (0 if revision_draft else 1)
        dialog = AdjustQuoteDialog(w.draft_items, number, w)
        self.root.addWidget(dialog); dialog.setWindowFlags(Qt.WindowType.Widget)
        self.root.setCurrentWidget(dialog)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self.root.setCurrentWidget(self.detail_page); self.root.removeWidget(dialog)
        if not accepted:
            dialog.deleteLater(); return
        candidate = dict(items=dialog.items, company=w.scheme2_company.currentText(), order_nature=nature.current(w))
        reference = self.state['versions'][-2] if revision_draft and len(self.state['versions']) > 1 else self.state['versions'][-1]
        if dialog.items == w.draft_items and model.same_document(candidate, reference):
            self.feedback.setText('报价未发生变化，无需生成新版本。'); dialog.deleteLater(); return
        if revision_draft:
            self.state['versions'][-1] = model.make_version(dialog.items, w.scheme2_company.currentText(), number,
                dialog.reason.toPlainText().strip(), self.operator(), w._quote_scheme_quote_date, nature.current(w))
        else:
            model.append_version(self.state, dialog.items, w.scheme2_company.currentText(), dialog.reason.toPlainText().strip(), self.operator(), w._quote_scheme_quote_date)
        self.state['versions'][-1]['confirmed'] = True
        w.draft_items = deepcopy(dialog.items); w.refresh_summary(); self.tabs.setCurrentIndex(0)
        self.refresh(); self.save(); dialog.deleteLater()

    def view_version(self, number):
        import quote_scheme_center as centre
        if getattr(self.window, '_scheme2_document_busy', False) or self.window._quote_scheme_export_context: return
        workspace = self.latest_workspace or dict(items=self.window.draft_items,
            company=self.window.scheme2_company.currentText(), order_nature=nature.current(self.window))
        if number == len(self.state['versions']) and model.same_document(workspace, self.state['versions'][number-1]):
            self.restore_latest(); self.tabs.setCurrentIndex(0); return
        w = self.window
        if self.latest_workspace is None:
            self.sync()
            if w._quote_scheme_save_timer.isActive():
                w._quote_scheme_save_timer.stop(); centre._save(w)
            self.latest_workspace = dict(items=deepcopy(w.draft_items), company=w.scheme2_company.currentText(),
                                         read_only=w._quote_scheme_read_only, date=w._quote_scheme_quote_date, order_nature=nature.current(w))
        entry = self.state['versions'][number-1]
        self.history_version = number; w._qm_view_history = True; w._quote_scheme_loading = True
        try:
            w.draft_items = deepcopy(entry['items']); w._quote_scheme_quote_date = entry['quote_date']
            with QSignalBlocker(w.scheme2_company): w.scheme2_company.setCurrentText(entry['company'])
            centre._apply_read_only(w, True); w.refresh_summary()
        finally: w._quote_scheme_loading = False
        self.tabs.setCurrentIndex(0); self.refresh()

    def restore_latest(self, refresh=True):
        import quote_scheme_center as centre
        w = self.window
        if self.latest_workspace is None: return
        if getattr(w, '_scheme2_document_busy', False) or w._quote_scheme_export_context: return
        source = self.latest_workspace; self.history_version = None; w._qm_view_history = False
        self.latest_workspace = None; w._quote_scheme_loading = True
        try:
            w.draft_items = source['items']; w._quote_scheme_quote_date = source['date']
            with QSignalBlocker(w.scheme2_company): w.scheme2_company.setCurrentText(source['company'])
            w.scheme2_company.setEnabled(not source['read_only'])
            centre._apply_read_only(w, source['read_only']); w.refresh_summary()
        finally: w._quote_scheme_loading = False
        if refresh: self.refresh()
        if not source['read_only'] and w._quote_scheme_dirty_seq>w._quote_scheme_saved_seq:
            w._quote_scheme_save_timer.start(500)

    def export_selected(self): self.window.scheme2_quote_export.click()


def install_quote_management(namespace):
    cls = namespace['MainWindow']
    if getattr(cls, '_quote_management_installed', False): return
    cls._quote_management_installed = True
    prior_init, prior_section, prior_refresh = cls.__init__, cls.show_section, cls.refresh_summary

    def init(window, *args, **kwargs):
        prior_init(window, *args, **kwargs)
        window.quote_management = QuoteManagement(window)

    def section(window, index):
        manager = getattr(window, 'quote_management', None)
        if manager is None: return prior_section(window, index)
        if getattr(window,'_detail_contract_busy',False):return
        delivery=getattr(manager,'delivery',None)
        if delivery is not None and delivery.cost_active and index != 3: delivery.leave_cost(refresh=False)
        if getattr(window, '_scheme2_document_busy', False) and (index != 2 or getattr(window._scheme2_document_controller, 'kind', '') != 'generate'):
            return
        if index == manager.contract_route:
            window.stack.setCurrentIndex(index)
            for nav in window.nav_buttons: nav.setChecked(nav is manager.contract_nav)
            from scheme2_ui import _apply_responsive
            _apply_responsive(window); return
        if index != 2: manager.restore_latest(refresh=False)
        manager.contract_nav.setChecked(False)
        result = prior_section(window, index)
        if index == 2:
            if getattr(window, '_qm_entry_pending', False):
                window._qm_entry_pending = False; manager.show_detail()
            else:
                manager.restore_latest(refresh=False)
                manager.root.setCurrentWidget(manager.list_page); manager.load_list(1)
                from scheme2_ui import _position_scheme2_action_dock
                _position_scheme2_action_dock(window)
            window._qm_show_list = False
        return result

    def refresh(window):
        result = prior_refresh(window)
        manager = getattr(window, 'quote_management', None)
        if manager is not None: manager.refresh()
        return result

    cls.__init__, cls.show_section, cls.refresh_summary = init, section, refresh
