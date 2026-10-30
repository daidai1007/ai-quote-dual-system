"""Send a formal document face, without importing it into the recipient workspace."""
from copy import deepcopy
from types import SimpleNamespace
from hashlib import sha256
import urllib.error
import urllib.parse
import urllib.request
import json
from uuid import uuid4

from PySide6.QtCore import Qt, QThread, Signal, QSaveFile, QIODevice, QSignalBlocker
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QCheckBox, QPlainTextEdit, QLineEdit, QScrollArea, QTextBrowser, QFileDialog,
    QFrame, QTabWidget, QComboBox, QRadioButton, QTableWidgetItem, QAbstractItemView, QHeaderView)

import quote_scheme_center as schemes
from quote_management import button, table, fill
from dialog_style import style_dialog, DIALOG_METRICS

METRICS_DELIVERY = dict(margin=24, gap=12, dialog_width=540, colleagues_height=170)
NATURE = {'INTERNAL': '内部', 'EXTERNAL': '外部'}


def quote_html(document):
    import scheme2_ui as ui
    adapter = SimpleNamespace(_quote_order_nature=document['order_nature'], quote_management=SimpleNamespace(history_version=None))
    return ui._printable_quote_html(adapter, document=document)


class DeliveryDownload(QThread):
    succeeded = Signal(bytes)
    failed = Signal(str)

    def __init__(self, url, headers, digest, parent):
        super().__init__(parent)
        self.url, self.headers, self.digest = url, headers, digest

    def run(self):
        try:
            req = urllib.request.Request(self.url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=45) as response:
                if response.headers.get('X-Quote-Document-SHA256') != self.digest:
                    raise ValueError('服务器返回的报价版本与当前收到的版本不一致。')
                if 'spreadsheetml.sheet' not in response.headers.get('Content-Type', ''):
                    raise ValueError('服务器未返回有效的 Excel 报价单。')
                content = response.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024 or not content.startswith(b'PK'):
                    raise ValueError('Excel 报价单内容无效或过大。')
                if sha256(content).hexdigest() != response.headers.get('X-Content-SHA256'):
                    raise ValueError('Excel 报价单完整性校验失败，请重新下载。')
            self.succeeded.emit(content)
        except urllib.error.HTTPError as error:
            try: message = json.loads(error.read().decode('utf-8')).get('message')
            except (ValueError, UnicodeError): message = None
            self.failed.emit(message or '下载失败，请检查连接后重试。')
        except Exception as error:
            self.failed.emit(str(error))


class SendQuoteDialog(QDialog):
    def __init__(self, delivery, version, people, parent=None):
        super().__init__(parent)
        self.delivery, self.version = delivery, deepcopy(version)
        self.setWindowTitle('发送给同事'); self.setObjectName('quoteSendDialog')
        self.resize(METRICS_DELIVERY['dialog_width'], 550)
        layout = QVBoxLayout(self); layout.setSpacing(DIALOG_METRICS['spacing'])
        d = version['document']
        summary = QLabel(f"{d['customer']} · {NATURE[d['order_nature']]}报价\n"
                         f"{d['scheme_no']}　V{d['quote_version']}\n报价金额　¥ {d['total']:,.2f}")
        summary.setTextFormat(Qt.TextFormat.PlainText); summary.setWordWrap(True); layout.addWidget(summary)
        layout.addWidget(QLabel('接收同事 *（可多选）'))
        self.choices = {}; host = QWidget(); self.people_layout = QVBoxLayout(host)
        for person in people: self.add_person(person['name'])
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(host)
        scroll.setMaximumHeight(METRICS_DELIVERY['colleagues_height']); layout.addWidget(scroll)
        extra = QHBoxLayout(); self.extra_name = QLineEdit(); self.extra_name.setPlaceholderText('其他同事的登录姓名')
        self.extra_name.setAccessibleName('其他同事的登录姓名'); extra.addWidget(self.extra_name, 1)
        self.add_button = button('添加姓名', self.add_extra); extra.addWidget(self.add_button); layout.addLayout(extra)
        layout.addWidget(QLabel('附言（选填，最多200字）'))
        self.note = QPlainTextEdit(); self.note.setAccessibleName('发送附言'); self.note.setMaximumHeight(80); layout.addWidget(self.note)
        hint = QLabel('发送当前正式报价及对应版本成本明细。同事可查看、打印和导出报价单；修改、修订沿用原有权限。')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.error = QLabel(); self.error.setTextFormat(Qt.TextFormat.PlainText); self.error.setWordWrap(True); layout.addWidget(self.error)
        actions = QHBoxLayout(); actions.addStretch(1)
        self.cancel = button('取消', self.reject); self.confirm = button('确认发送', self.send, True)
        actions.addWidget(self.cancel); actions.addWidget(self.confirm); layout.addLayout(actions)
        style_dialog(self)

    def add_person(self, name):
        if name in self.choices: return self.choices[name]
        control = QCheckBox(name); self.choices[name] = control; self.people_layout.addWidget(control); return control

    def add_extra(self):
        import name_login
        name = self.extra_name.text().strip()
        own = (name_login.session() or {}).get('person', {}).get('display_name')
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            self.error.setText('请输入有效的同事登录姓名。'); return
        if name == own: self.error.setText('不能发送给当前登录人。'); return
        self.add_person(name).setChecked(True); self.extra_name.clear(); self.error.clear()

    def set_busy(self, busy):
        self.confirm.setEnabled(not busy); self.cancel.setEnabled(not busy)
        locked = busy or self.delivery.pending_send is not None
        for control in [*self.choices.values(), self.note, self.extra_name, self.add_button]: control.setEnabled(not locked)

    def send(self):
        if self.delivery.pending_send is None:
            selected = [name for name, control in self.choices.items() if control.isChecked()]
            note = self.note.toPlainText().strip()
            if not selected: self.error.setText('请至少选择一位接收同事。'); return
            if len(note) > 200: self.error.setText('附言最多200字。'); return
            self.delivery.pending_send = dict(request_id=str(uuid4()), recipient_names=selected, note=note,
                scheme_no=self.version['document']['scheme_no'], source_version_no=self.version['source_version_no'],
                quote_version=self.version['quote_version'])
        self.set_busy(True); self.error.setText('正在发送…')
        def sent(result):
            if result.get('sent') is not True: failed('服务器未确认发送结果。'); return
            names = '、'.join(self.delivery.pending_send['recipient_names']); self.delivery.pending_send = None
            self.error.clear(); self.set_busy(False); self.accept()
            self.delivery.sent_notice.setText('已发送给 ' + names + ' · V' + str(self.version['quote_version']))
            if self.delivery.manager.tabs.currentIndex() == self.delivery.records_index: self.delivery.load_records()
            else: self.delivery.manager.tabs.setCurrentIndex(self.delivery.records_index)
        def failed(message):
            self.error.setText('发送结果未确认：' + message + '\n重试会核对同一条发送记录，不会重复发送。')
            self.set_busy(False); self.confirm.setText('重试发送')
        self.delivery.request('POST', '', deepcopy(self.delivery.pending_send), sent, failed)

    def reject(self):
        if self.delivery.pending_send is not None:
            self.error.setText('发送结果尚未确认，请重试核对本次发送结果后再关闭。'); return
        super().reject()


class QuoteDelivery:
    def __init__(self, manager):
        self.manager, self.window = manager, manager.window
        self.pending_send = None; self.send_dialog = None; self.received = None; self.epoch = 0; self.page = 1
        self.send_loading = False; self.send_feedback_context = None
        self.output_registration_busy = False
        self.cost_active = False; self.cost_restore = None
        self.window._quote_delivery_output_pending = None
        self.send_button = button('发送给同事', self.start_send, True); self.send_button.setAccessibleName('发送给同事')
        manager.detail_page.layout().itemAt(1).layout().addWidget(self.send_button)
        self.send_status = QLabel(); self.send_status.setAccessibleName('发送状态')
        self.send_status.setTextFormat(Qt.TextFormat.PlainText); self.send_status.setWordWrap(True)
        self.send_status.hide(); manager.detail_page.layout().insertWidget(2, self.send_status)
        self.records_page = QWidget(); box = QVBoxLayout(self.records_page)
        self.sent_notice = QLabel(); self.sent_notice.setTextFormat(Qt.TextFormat.PlainText); self.sent_notice.setWordWrap(True); box.addWidget(self.sent_notice)
        self.records_status = QLabel('当前报价尚未发送'); self.records_status.setWordWrap(True); box.addWidget(self.records_status)
        self.records_table = table(('接收人', '发送版本', '发送人 / 时间', '送达状态', '阅读状态', '附言'))
        box.addWidget(self.records_table); box.addWidget(button('刷新发送记录', self.load_records)); box.addStretch(1)
        self.records_index = manager.tabs.addTab(self.records_page, '发送记录')
        manager.tabs.currentChanged.connect(lambda index: self.load_records() if index == self.records_index else None)
        navigation = QHBoxLayout(); navigation.addWidget(button('报价列表', manager.show_list))
        navigation.addWidget(button('收到的报价', self.show_inbox)); navigation.addStretch(1)
        manager.list_page.layout().insertLayout(1, navigation)
        self.build_inbox(); self.build_received(); self.build_cost_context()

    def request(self, method, suffix, payload, success, failure=None):
        return schemes._run(self.window, method, '/api/quote-deliveries' + suffix, payload, success,
                            failure or (lambda message: self.manager.feedback.setText(message)))

    def build_inbox(self):
        self.inbox_page = QWidget(); self.manager.root.addWidget(self.inbox_page)
        layout = QVBoxLayout(self.inbox_page); layout.setContentsMargins(*([METRICS_DELIVERY['margin']] * 4)); layout.setSpacing(METRICS_DELIVERY['gap'])
        heading = QLabel('报价单管理'); heading.setObjectName('scheme2PageTitle'); layout.addWidget(heading)
        tabs = QHBoxLayout(); tabs.addWidget(button('报价列表', self.manager.show_list)); tabs.addWidget(button('收到的报价', self.show_inbox, True)); tabs.addStretch(1); layout.addLayout(tabs)
        self.inbox_status = QLabel(); self.inbox_status.setWordWrap(True); layout.addWidget(self.inbox_status)
        self.inbox_table = table(('报价编号 / 客户', '发送人 / 时间', '性质 / 版本', '报价金额', '阅读状态', '附言', '操作'))
        self.inbox_table.horizontalHeader().setStretchLastSection(False)
        for column,width in enumerate((210,160,105,115,80,140,120)):self.inbox_table.setColumnWidth(column,width)
        self.inbox_table.horizontalHeader().setSectionResizeMode(5,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.inbox_table)
        actions = QHBoxLayout(); self.previous = button('上一页', lambda: self.load_inbox(max(1, self.page - 1)))
        self.next = button('下一页', lambda: self.load_inbox(self.page + 1))
        self.inbox_retry = button('刷新 / 重试', lambda: self.load_inbox(self.page))
        for control in (self.previous, self.next, self.inbox_retry): actions.addWidget(control)
        actions.addStretch(1); layout.addLayout(actions); layout.addStretch(1)

    def build_received(self):
        import scheme2_ui as ui
        self.received_page = QWidget(); self.manager.root.addWidget(self.received_page)
        layout = QVBoxLayout(self.received_page); layout.setContentsMargins(*([METRICS_DELIVERY['margin']] * 4)); layout.setSpacing(METRICS_DELIVERY['gap'])
        breadcrumb = QHBoxLayout(); breadcrumb.addWidget(button('返回收到的报价', self.show_inbox)); breadcrumb.addStretch(1); layout.addLayout(breadcrumb)
        actions = QHBoxLayout(); self.received_title = QLabel('报价单详情'); self.received_title.setObjectName('scheme2PageTitle')
        actions.addWidget(self.received_title, 1)
        self.print_button = button('打印', self.print_received); self.export_button = button('导出报价单', self.export_received, True)
        actions.addWidget(self.print_button); actions.addWidget(self.export_button); layout.addLayout(actions)
        self.received_meta = QLabel(); self.received_meta.setWordWrap(True); self.received_meta.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.received_meta)
        customer = QFrame(); customer.setObjectName('quoteManagementCustomer'); fields = QHBoxLayout(customer)
        fields.addWidget(QLabel('客户')); self.received_customer = QComboBox(); self.received_customer.setEnabled(False); fields.addWidget(self.received_customer,1)
        fields.addWidget(QLabel('订单性质 *')); self.received_nature = {}
        for code,label in NATURE.items():
            radio=QRadioButton(label);radio.setEnabled(False);fields.addWidget(radio);self.received_nature[code]=radio
        for text in ('保存草稿','放弃修改'):
            control=button(text,lambda:None);control.setEnabled(False);fields.addWidget(control)
        layout.addWidget(customer)
        amount=QFrame();amount.setObjectName('quoteManagementAmount');amount_row=QHBoxLayout(amount)
        self.received_number=QLabel();amount_row.addWidget(self.received_number,1)
        self.received_amount=QLabel();self.received_amount.setObjectName('quoteManagementAmountValue');amount_row.addWidget(self.received_amount);layout.addWidget(amount)
        self.received_tabs=QTabWidget();self.received_tabs.setObjectName('quoteManagementTabs')
        paper=QWidget();paper_layout=QVBoxLayout(paper);self.received_table=ui._new_quote_document_table();paper_layout.addWidget(self.received_table)
        self.received_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.received_tabs.addTab(paper,'报价单')
        self.received_items=table(('名称','规格','数量','折后单价','折后总价','备注'));self.received_tabs.addTab(self.received_items,'报价明细')
        self.received_history=table(('版本','客户','报价总额','查看范围'));self.received_tabs.addTab(self.received_history,'调价历史')
        compare=QLabel('仅收到本次发送版本，未开放其他版本。');self.received_tabs.addTab(compare,'版本对比');self.received_tabs.setTabEnabled(3,False)
        preview_page=QWidget();preview_layout=QVBoxLayout(preview_page);preview_actions=QHBoxLayout()
        preview_actions.addWidget(button('打印',lambda:self.print_button.click()));preview_actions.addWidget(button('导出报价单',lambda:self.export_button.click(),True));preview_actions.addStretch(1);preview_layout.addLayout(preview_actions)
        self.received_preview = QTextBrowser();self.received_preview.setOpenExternalLinks(False);self.received_preview.setOpenLinks(False);preview_layout.addWidget(self.received_preview)
        self.received_tabs.addTab(preview_page,'预览与导出');layout.addWidget(self.received_tabs,1)
        self.output_status = QLabel(); self.output_status.setWordWrap(True); self.output_status.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.output_status)
        self.retry_output = button('重试输出登记', self.register_output); self.retry_output.hide(); layout.addWidget(self.retry_output)
        layout.addWidget(QLabel('仅发送的正式报价版本；修改、修订和合同操作沿用原有权限。'))

    def build_cost_context(self):
        self.cost_banner=QFrame();row=QHBoxLayout(self.cost_banner)
        self.cost_meta=QLabel();self.cost_meta.setWordWrap(True);self.cost_meta.setTextFormat(Qt.TextFormat.PlainText);row.addWidget(self.cost_meta,1)
        row.addWidget(button('返回收到的报价',self.show_inbox))
        body=self.window.scheme2_cost_page.findChild(QFrame,'scheme2CostBody');body.layout().insertWidget(1,self.cost_banner);self.cost_banner.hide()

    def refresh(self):
        w, m = self.window, self.manager
        busy = bool(getattr(w, '_scheme2_document_busy', False) or getattr(w, '_quote_scheme_export_context', None))
        self.send_button.setEnabled(bool(w._quote_scheme_id) and not getattr(w, '_name_scope_foreign', False) and not busy and not self.send_loading and w._quote_scheme_status != 'VOID')
        self.send_button.setText('正在核对…' if self.send_loading else '发送给同事')
        self.send_status.setVisible(bool(self.send_status.text()) and self.send_feedback_context == self.send_context())
        self.send_button.setToolTip('发送当前查看的正式版本；草稿须先打印或导出完成正式登记')
        if self.cost_active:self.enforce_cost_readonly()

    def send_context(self):
        return (self.window._quote_scheme_id, self.manager.history_version or len(self.manager.state.get('versions', [])) or 1)

    def start_send(self):
        if self.pending_send is not None and self.send_dialog is not None:
            self.send_dialog.show(); self.send_dialog.raise_(); return
        w, m = self.window, self.manager
        if not self.send_button.isEnabled(): return
        if schemes._registration_guard(w): return
        context = self.send_context(); scheme_no, number = context
        from quote_order_nature import current
        if current(w) == 'UNCLASSIFIED':
            self.send_feedback_context = context
            if w._quote_scheme_status in ('QUOTED','CONTRACT') or m.history_version is not None:
                message = '当前报价的订单性质为“待分类”，暂不能发送。请回到最新版本，点击“调整报价”创建修订版，选择“内部”或“外部”，核对金额后成功打印或导出，再发送给同事。'
            else:
                message = '请先在客户旁选择订单性质“内部”或“外部”，核对金额后成功打印或导出，再发送给同事。'
            self.send_status.setText(message); self.refresh(); return
        self.send_loading = True; self.send_feedback_context = context
        self.send_status.setText(f'正在核对 V{number} 正式报价版本并加载同事名单…'); self.refresh()
        def failed(message):
            self.send_loading = False
            self.send_status.setText('发送前核对失败：' + str(message)); self.refresh()
        def still_current():
            if self.send_context() == context: return True
            self.send_loading = False; self.refresh(); return False
        def versions_loaded(result):
            if not still_current(): return
            try: value = next((row for row in result.get('items', []) if row['quote_version'] == number), None)
            except (AttributeError, KeyError, TypeError):
                failed('服务器返回的正式版本数据格式异常，请联系管理员核对 API 版本。'); return
            if value is None:
                failed(f'未找到当前 V{number} 的可发送正式版本。请确认该版本已完成打印或导出登记；若已完成，请联系管理员核对正式版本数据。'); return
            def people_loaded(people):
                if not still_current(): return
                try:
                    self.send_dialog = SendQuoteDialog(self, value, people.get('items', []), self.manager.detail_page)
                    self.send_dialog.open(); self.send_loading = False; self.send_status.clear(); self.refresh()
                except Exception as error: failed(error)
            try: self.request('GET', '/colleagues', None, people_loaded, failed)
            except Exception as error: failed(error)
        try: self.request('GET', '/versions?' + urllib.parse.urlencode({'scheme_no': scheme_no}), None, versions_loaded, failed)
        except Exception as error: failed(error)

    def load_records(self):
        no = self.window._quote_scheme_id
        if not no: self.records_status.setText('未登记报价尚无发送记录。'); return
        self.records_status.setText('正在加载发送记录…')
        def loaded(value):
            if self.window._quote_scheme_id != no: return
            rows = value.get('items', [])
            fill(self.records_table, [(r['recipient_name'], f"V{r['quote_version']} · {NATURE.get(r['order_nature'], '待分类')}",
                r['sender_name'] + '\n' + self.manager.updated_time(r['created_at']), '已送达', '已读' if r['read_at'] else '未读', r['note']) for r in rows])
            self.records_status.setText(f"共 {value.get('total',len(rows))} 条记录" + ('（显示最近20条）' if value.get('total',0)>20 else ''))
        self.request('GET', '?' + urllib.parse.urlencode({'mode':'sent', 'scheme_no':no}), None, loaded, self.records_status.setText)

    def show_inbox(self):
        if schemes._registration_guard(self.window): return
        if self.window._quote_delivery_output_pending:
            self.output_status.setText('请先重试输出登记，无需再次打印或导出。'); return
        self.leave_cost()
        self.manager.restore_latest(refresh=False)
        if self.window.stack.currentWidget() is not self.manager.root:
            from scheme2_ui import QUOTE_ROUTE
            self.window._qm_entry_pending = True
            self.window.show_section(QUOTE_ROUTE)
        self.manager.root.setCurrentWidget(self.inbox_page); self.load_inbox(1)

    def load_inbox(self, page=1):
        self.epoch += 1; epoch = self.epoch; self.page = page
        self.inbox_status.setText('正在加载收到的报价…'); fill(self.inbox_table, [])
        self.previous.setEnabled(False); self.next.setEnabled(False)
        def loaded(value):
            if epoch != self.epoch: return
            rows = value.get('items', [])
            fill(self.inbox_table, [(r['scheme_no']+'\n'+r['customer'],r['sender_name']+'\n'+self.manager.updated_time(r['created_at']),
                NATURE.get(r['order_nature'],'待分类')+f" · V{r['quote_version']}",f"¥ {float(r['total']):,.2f}",'已读' if r['read_at'] else '未读',r['note'],'') for r in rows])
            for index, row in enumerate(rows):
                host=QWidget();actions=QVBoxLayout(host);actions.setContentsMargins(4,2,4,2);actions.setSpacing(2)
                for label,target in (('打开报价','quote'),('进入成本计算','cost')):
                    action=button(label,lambda _=False,id=row['delivery_id'],target=target:self.open_received(id,target));action.setObjectName('quoteManagementLink');actions.addWidget(action)
                self.inbox_table.setCellWidget(index,6,host);self.inbox_table.setColumnWidth(6,120)
                self.inbox_table.setRowHeight(index,90)
            total = int(value.get('total',len(rows))); self.inbox_status.setText(f'收到 {total} 份报价 · 第{page}页' if total else '暂未收到同事发送的报价。')
            self.inbox_table.setFixedHeight(min(max(180,self.window.height()-340),430,
                self.inbox_table.horizontalHeader().height()+max(1,len(rows))*90+4))
            self.previous.setEnabled(page > 1); self.next.setEnabled(page * 20 < total)
        def failed(message):
            if epoch == self.epoch: self.inbox_status.setText(message)
        self.request('GET', '?' + urllib.parse.urlencode({'page':page}), None, loaded, failed)

    def open_received(self, delivery_id, target='quote'):
        if self.window._quote_delivery_output_pending: self.output_status.setText('请先重试输出登记。'); return
        self.epoch += 1; epoch = self.epoch
        self.inbox_status.setText('正在打开指定版本…')
        def loaded(value):
            if epoch != self.epoch: return
            self.received = deepcopy(value); d = value['document']
            if target=='cost':self.enter_cost();return
            self.leave_cost()
            self.received_title.setText(f"报价单详情 · V{d['quote_version']}")
            self.received_meta.setText(f"{value['sender_name']} 发送给你 · {self.manager.updated_time(value['sent_at'])}\n"
                f"{d['scheme_no']}　{NATURE[d['order_nature']]}　{d['customer']}　¥ {d['total']:,.2f}\n附言：{value['note'] or '无'}")
            self.received_customer.clear();self.received_customer.addItem(d['customer'])
            for code,radio in self.received_nature.items():radio.setChecked(code==d['order_nature'])
            self.received_number.setText(f"{d['scheme_no']}　V{d['quote_version']}　{d['quote_date']}\n报价总额 · 含税人民币")
            self.received_amount.setText(f"¥ {d['total']:,.2f}")
            import scheme2_ui as ui
            adapter=SimpleNamespace(scheme2_quote_preview=self.received_table,quote_management=SimpleNamespace(history_version=None),_quote_scheme_read_only=True,_quote_order_nature=d['order_nature'])
            ui._refresh_quote_page(adapter,document=d)
            fill(self.received_items,[(r['name'],r['specification'],r['quantity'],f"{r['unit_price']:,.2f}",f"{r['total']:,.2f}",r['remark']) for r in d['items']])
            fill(self.received_history,[(f"V{d['quote_version']}",d['customer'],f"{d['total']:,.2f}",'本次发送的正式版本')])
            self.received_tabs.setCurrentIndex(0);self.received_preview.setHtml(quote_html(d));self.output_status.clear();self.manager.root.setCurrentWidget(self.received_page)
        self.request('GET', '/' + urllib.parse.quote(delivery_id), None, loaded, self.inbox_status.setText)

    def set_output_busy(self, busy):
        busy = busy or self.output_registration_busy
        pending = self.window._quote_delivery_output_pending is not None
        self.print_button.setEnabled(not busy and not pending); self.export_button.setEnabled(not busy and not pending)
        self.retry_output.setVisible(pending); self.retry_output.setEnabled(not busy)

    def enter_cost(self):
        """Use the real COST_ROUTE and table; never load received data as a workspace."""
        import scheme2_ui as ui
        w=self.window
        if self.cost_active:self.leave_cost(refresh=False)
        self.cost_restore=dict(read_only=w._quote_scheme_read_only,edit=w.summary_table.editTriggers(),
            controls=[(control,control.isEnabled()) for control in w.scheme2_cost_page.findChildren(QPushButton)
                      if control not in self.cost_banner.findChildren(QPushButton)],
            back_text=w.scheme2_cost_return.text(),save_active=w._quote_scheme_save_timer.isActive(),
            back_hidden=w.scheme2_cost_return.isHidden(),
            local_active=w._scheme2_order_save_timer.isActive())
        self.cost_active=True;w._quote_scheme_read_only=True
        w._quote_scheme_save_timer.stop();w._scheme2_order_save_timer.stop()
        d=self.received['document']
        self.cost_meta.setText(f"{d['scheme_no']} · V{d['quote_version']} · {d['customer']} · {NATURE[d['order_nature']]}\n"
            '收到的对应版本成本 · 查看模式，不重新计算')
        self.cost_banner.show();w.show_section(ui.COST_ROUTE);self.render_cost();self.enforce_cost_readonly()

    def enforce_cost_readonly(self):
        if not self.cost_active or self.cost_restore is None:return
        links = tuple(self.window.scheme2_cost_selection_values[column]
                      for column in (7, 24))
        for control,_enabled in self.cost_restore['controls']:
            if control not in links:control.setEnabled(False)
        self.window.scheme2_cost_return.setEnabled(True);self.window.scheme2_cost_return.hide()
        self.window.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.window.scheme2_cost_undo.hide()

    def leave_cost(self, refresh=True):
        if not self.cost_active:return
        w=self.window;saved=self.cost_restore;self.cost_active=False;self.cost_restore=None;self.cost_banner.hide()
        w._quote_scheme_read_only=saved['read_only'];w.summary_table.setEditTriggers(saved['edit'])
        for control,enabled in saved['controls']:control.setEnabled(enabled)
        w.scheme2_cost_return.setText(saved['back_text'])
        w.scheme2_cost_return.setVisible(not saved['back_hidden'])
        if refresh:
            import scheme2_ui as ui
            ui._refresh_cost_table(w)
        if saved['save_active']:w._quote_scheme_save_timer.start()
        if saved['local_active']:w._scheme2_order_save_timer.start()

    def render_cost(self):
        if not self.cost_active:return False
        import scheme2_ui as ui
        w=self.window;grid=w.summary_table;d=self.received['document'];snapshot=d.get('cost_snapshot') or {}
        rows=snapshot.get('items') or [];headers=snapshot.get('headers') or []
        selected=grid.currentRow();w._scheme2_refreshing=True
        try:
            with QSignalBlocker(grid):
                grid.setRowCount(len(d['items']))
                for row,face in enumerate(d['items']):
                    data=rows[row].get('columns',[]) if row<len(rows) else []
                    saved=dict(zip(headers,data));saved.update(序号=row+1,名称=face['name'],尺寸=face['specification'],数量=face['quantity'],报价=face['unit_price'],报价总价=face['total'],成本明细='查看')
                    for column,label in enumerate(ui.HEADERS):
                        value=saved.get(label)
                        text='未记录' if value is None else f'{value:,.2f}' if isinstance(value,(int,float)) and column in ui.MONEY_COLUMNS else str(value)
                        cell=QTableWidgetItem(text);cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        if column in (ui.FIXED_QUOTE_COLUMN,ui.DISCOUNTED_QUOTE_COLUMN):
                            font=cell.font();font.setUnderline(True);cell.setFont(font)
                            cell.setToolTip('点击查看本版本保存的单台／单套报价分项。')
                        grid.setItem(row,column,cell)
                    grid.setRowHeight(row,64)
                grid.selectRow(min(max(selected,0),max(len(d['items'])-1,0)))
            w.scheme2_cost_empty.hide();self.sync_cost_selection();self.enforce_cost_readonly()
        finally:w._scheme2_refreshing=False
        return True

    def sync_cost_selection(self):
        if not self.cost_active:return False
        import scheme2_ui as ui
        w=self.window;grid=w.summary_table;row=grid.currentRow()
        ui._fill_cost_selection_detail(w,row,0<=row<grid.rowCount())
        return True

    def show_price_breakdown(self,row,column):
        if not self.cost_active:return
        rows=(self.received['document'].get('cost_snapshot') or {}).get('items') or []
        if not 0<=row<self.window.summary_table.rowCount():return
        import scheme2_ui as ui
        components=rows[row].get('price_breakdown') if row<len(rows) else None
        ui._show_quick_price_breakdown(self.window,None,column,components=components)

    def show_cost_detail(self,row):
        if not self.cost_active or not 0<=row<self.window.summary_table.rowCount():return
        dialog=QDialog(self.window);dialog.setWindowTitle('成本明细 · 收到版本 V'+str(self.received['document']['quote_version']))
        box=QVBoxLayout(dialog)
        import scheme2_ui as ui
        saved=(self.received['document'].get('cost_snapshot') or {}).get('items') or []
        details=saved[row].get('details') or [] if row<len(saved) else []
        if any(detail.get('note')=='附件公式成本分项' for detail in details):
            grid=table(('成本项目','明细项目','本版本保存金额'))
            fill(grid,[(detail.get('type',''),detail.get('name',''),ui._money(
                detail.get('amount') if detail.get('amount') is not None else
                ui.money_product(detail.get('base_amount') or 0,detail.get('factor') if detail.get('factor') is not None else 1))) for detail in details])
        else:
            grid=table(('成本项目','本版本保存值'))
            fill(grid,[(ui.HEADERS[c],self.window.summary_table.item(row,c).text()) for c in range(12,21)])
        box.addWidget(grid);box.addWidget(button('关闭',dialog.accept));dialog.resize(520,450);style_dialog(dialog);dialog.exec()

    def completed_output(self, kind):
        value = self.received
        self.window._quote_delivery_output_pending = dict(delivery_id=value['delivery_id'],output_id=str(uuid4()),
            kind=kind,document_sha256=value['document_sha256'])
        self.register_output()

    def register_output(self):
        pending = self.window._quote_delivery_output_pending
        if not pending or self.output_registration_busy: return
        self.output_registration_busy = True
        self.set_output_busy(True); self.output_status.setText('输出已完成，正在登记…')
        def success(value):
            if value.get('recorded') is not True: failed('服务器尚未确认输出记录。'); return
            self.output_registration_busy = False
            self.window._quote_delivery_output_pending = None; self.set_output_busy(False)
            self.output_status.setText('输出已完成并登记，原报价及其版本保持不变。')
        def failed(message):
            self.output_registration_busy = False
            self.set_output_busy(False); self.output_status.setText('输出已完成，登记未确认：'+message+'。请重试登记，无需重复打印或导出。')
        self.request('POST', '/'+pending['delivery_id']+'/outputs', {k:v for k,v in pending.items() if k!='delivery_id'}, success, failed)

    def print_received(self):
        if not self.received or self.window._quote_delivery_output_pending: return
        self.set_output_busy(True)
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution); dialog = QPrintDialog(printer, self.received_page)
            dialog.setWindowTitle('打印收到的报价单')
            if dialog.exec() != QDialog.DialogCode.Accepted: return
            document = QTextDocument(self.received_page); document.setHtml(quote_html(self.received['document'])); document.print_(printer)
            if printer.printerState() == QPrinter.PrinterState.Error: raise RuntimeError('打印机报告错误，请检查后重试。')
            self.completed_output('PRINT')
        except Exception as error: self.output_status.setText('打印未完成：'+str(error))
        finally: self.set_output_busy(False)

    def export_received(self):
        if not self.received or self.window._quote_delivery_output_pending: return
        d = self.received['document']; name = f"{d['scheme_no']}-V{d['quote_version']}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self.received_page, '导出收到的报价单', name, 'Excel 报价单 (*.xlsx)')
        if not path: return
        if not path.lower().endswith('.xlsx'): path += '.xlsx'
        self.set_output_busy(True); self.output_status.setText('正在下载并保存指定版本…')
        import name_login
        epoch = name_login.identity_epoch(); identity = self.received['delivery_id']
        worker = DeliveryDownload(schemes._base_url(self.window)+'/api/quote-deliveries/'+identity+'/xlsx',
                                  dict(schemes._headers(self.window)), self.received['document_sha256'], self.window)
        self.window._quote_scheme_workers.add(worker)
        def current(): return name_login.window_is_current(self.window, epoch) and self.received and self.received['delivery_id'] == identity
        def success(content):
            if not current(): return
            file = QSaveFile(path)
            if not file.open(QIODevice.OpenModeFlag.WriteOnly): self.output_status.setText('文件无法写入，请检查文件占用或目录权限后重试。'); return
            if file.write(content) != len(content) or not file.commit():
                file.cancelWriting(); self.output_status.setText('文件保存失败，原文件保持不变。'); return
            self.completed_output('XLSX')
        worker.succeeded.connect(success)
        worker.failed.connect(lambda message: self.output_status.setText('导出未完成：'+message) if current() else None)
        def finished(): self.window._quote_scheme_workers.discard(worker); worker.deleteLater(); self.set_output_busy(False)
        worker.finished.connect(finished); worker.start()
