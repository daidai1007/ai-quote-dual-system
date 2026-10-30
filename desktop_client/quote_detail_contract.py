"""One detail-page action confirms the current quote and opens its contract.

The first quotation needs no adjustment, revision, fake export or list selection.
Already formal historical quotations resolve by their displayed version, never
by the database lock version or whichever list row happened to be selected.
"""
from copy import deepcopy
from hashlib import sha256
import json,time,urllib.parse
from uuid import uuid4
from PySide6.QtCore import QObject,QTimer


def viewed_version(window):
    manager=window.quote_management
    number=manager.history_version or manager.state.get('current') or len(manager.state.get('versions',[])) or 1
    return int(number)


def unavailable_reason(window):
    import name_login
    from quote_order_nature import current
    if not name_login.window_is_current(window):return '姓名会话已变化，请在当前姓名窗口操作。'
    if getattr(window,'_name_scope_foreign',False):return '该报价不在本人可操作范围。'
    if getattr(window,'_detail_contract_busy',False):return '正在确认当前报价并准备合同…'
    if getattr(window,'_scheme2_document_busy',False) or window._quote_scheme_export_context or window._quote_scheme_pending_export:return '请先完成当前报价输出或登记。'
    if window._quote_scheme_status=='VOID':return '已作废报价不能生成合同。'
    if current(window)!='EXTERNAL':return '仅外部报价可生成合同，请先确认订单性质。'
    if not window.draft_items:return '请先完成产品成本计算并生成报价单。'
    if not window.scheme2_company.currentText().strip():return '请先填写本次报价客户。'
    manager=window.quote_management
    entry=next((v for v in manager.state.get('versions',[]) if v.get('version')==viewed_version(window)),{})
    if entry.get('pending_confirmation'):return '当前修订内容尚未确认，请先核对报价。'
    return ''


class DetailContractController(QObject):
    def __init__(self,window,page):
        super().__init__(window);self.window=window;self.page=page;self.manager=window.quote_management
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.continue_start)
        self.active=False;self.attempt=None;self.confirmed=False;self.failure=''

    def feedback_message(self):
        """Keep an async failure visible across unrelated save-status refreshes."""
        if self.active or not self.failure:return ''
        import contract_management as contracts
        context=(self.window._quote_scheme_id,viewed_version(self.window),self.manager.history_version)
        expected=(self.context[0] or getattr(self,'created_no',''),self.context[1],self.context[2])
        if context!=expected or self.identity!=(contracts.contract_headers(self.window) or {}):return ''
        return '合同准备未完成：'+self.failure

    def start(self):
        import contract_management as contracts
        import quote_scheme_center as schemes
        from scheme2_ui import _commit_quote_text_editor
        reason=unavailable_reason(self.window)
        if reason:self.manager.feedback.setText(reason);return
        dirty=self.page.has_unsaved() if hasattr(self.page,'has_unsaved') else self.page.unsaved
        if self.page.busy or self.page.queue or dirty or self.page.profile_dirty:
            self.manager.feedback.setText('请先完成或保存当前合同管理中的操作，再生成本次合同。');return
        _commit_quote_text_editor(self.window)
        self.failure='';self.created_no=''
        self.identity=dict(contracts.contract_headers(self.window) or {});self.context=(self.window._quote_scheme_id,viewed_version(self.window),self.manager.history_version)
        self.previous_readonly=self.window._quote_scheme_read_only;self.confirmed=False;self.active=True
        self.window._detail_contract_busy=True;self.window._scheme2_document_busy=True
        self.window._quote_scheme_save_timer.stop();schemes._apply_read_only(self.window,True)
        self.waiting=False;self.deadline=time.monotonic()+65;self.manager.status_changed();self.manager.feedback.setText('正在保存并确认当前报价，随后进入合同生成…')
        self.timer.start();self.continue_start()

    def current(self):
        import contract_management as contracts
        return self.active and self.identity==(contracts.contract_headers(self.window) or {}) and viewed_version(self.window)==self.context[1] and self.manager.history_version==self.context[2] and (not self.context[0] or self.window._quote_scheme_id==self.context[0])

    def continue_start(self):
        if not self.current():self.finish('当前姓名或报价已变化，已取消合同操作。');return
        if time.monotonic()>self.deadline:self.finish('保存等待超时，当前报价已保留，请稍后重试。');return
        if self.waiting:return
        if any(getattr(self.window,k,None) is not None for k in ('_quote_scheme_save_worker','_quote_scheme_create_worker')):return
        self.waiting=True;self.page.request('/bootstrap',None,self.bootstrapped,on_error=self.finish)

    def bootstrapped(self,result):
        if not self.current():self.finish('当前报价已变化，请重新操作。');return
        if not result.get('ready'):self.finish(result.get('message','合同服务尚未启用。'));return
        self.bootstrap=result
        if self.manager.history_version is not None or self.window._quote_scheme_status in ('QUOTED','CONTRACT','ARCHIVED'):
            self.open_formal(result);return
        if self.window._quote_scheme_status not in ('','DRAFT','REVISING'):
            self.finish('当前报价状态不支持生成合同。');return
        import contract_management as contracts
        import quote_scheme_center as schemes
        try:
            snapshot=contracts.freeze_contract_quote(self.window,deepcopy(schemes._snapshot(self.window)))
            versions=snapshot.get('quote_management',{}).get('versions',[])
            if versions:versions[-1]['sealed']=True
            business=deepcopy(snapshot)
            for key in ('scheme_no','version_no'):business.get('document',{}).pop(key,None)
            encoded=json.dumps(business,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            fingerprint=sha256(encoded.encode('utf-8')).hexdigest()
            if not self.attempt or self.attempt[0]!=fingerprint:self.attempt=(fingerprint,str(uuid4()),deepcopy(snapshot))
            self.snapshot=deepcopy(self.attempt[2])
        except (ValueError,KeyError,TypeError) as error:self.finish('当前报价数据待核对：'+str(error));return
        if not self.window._quote_scheme_id:
            schemes._run(self.window,'POST','/api/quote-schemes',dict(snapshot=snapshot,operator_name=self.manager.operator()),self.created,self.finish)
        else:self.confirm()

    def created(self,result):
        if not self.current():self.finish('姓名或报价已变化，已取消合同操作。');return
        import quote_scheme_center as schemes
        self.created_no=result['scheme_no'];schemes._created(self.window,result)
        self.window._quote_scheme_save_timer.stop();self.confirm()

    def confirm(self):
        if not self.current():self.finish('当前报价已变化，请重新操作。');return
        import quote_scheme_center as schemes
        payload=dict(snapshot=self.snapshot,expected_version=self.window._quote_scheme_version,quote_version=self.context[1],request_id=self.attempt[1],operator_name=self.manager.operator())
        schemes._run(self.window,'POST','/api/quote-schemes/'+urllib.parse.quote(self.window._quote_scheme_id)+'/confirm-for-contract',payload,self.confirmed_quote,self.finish)

    def confirmed_quote(self,result):
        if not self.current():self.finish('当前报价已变化，请重新操作。');return
        if not result.get('recorded') or int(result.get('quote_version',0))!=self.context[1]:self.finish('服务器未确认当前报价版本，请核对配套 API。');return
        self.confirmed=True;w=self.window
        w._quote_scheme_status=result['status'];w._quote_scheme_version=int(result['lock_version']);w._quote_scheme_business_version=int(result['source_version_no'])
        w._quote_scheme_last_save_failed=False
        w._quote_scheme_saved_seq=w._quote_scheme_dirty_seq;w._quote_order_nature_locked=True
        w._qm_state=deepcopy(self.snapshot.get('quote_management',self.manager.state));self.manager.remember_saved(self.snapshot)
        self.page.request('/bootstrap',None,self.open_formal,on_error=self.finish)

    def open_formal(self,result):
        if not self.current():self.finish('当前报价已变化，请重新操作。');return
        rows=[r for r in result.get('sources',[]) if r['scheme_no']==self.window._quote_scheme_id]
        if rows and any('quote_version' not in r for r in rows):self.finish('配套 API 尚未提供报价版本对应信息，请更新 API 后重试。');return
        try:matches=[r for r in rows if int(r.get('quote_version',0))==self.context[1] and r.get('order_nature')=='EXTERNAL']
        except (TypeError,ValueError):matches=[]
        if len(matches)!=1:self.finish(f'未找到当前 V{self.context[1]} 的唯一外部正式版本，当前报价已保留；不会切换其他版本。');return
        source=matches[0];page=self.page
        if hasattr(page,'source_mode'):page.source_mode.setCurrentIndex(0)
        page.customer.setCurrentIndex(0);page.customer_changed()
        page.pending_scheme=source['scheme_no'];page.pending_version=int(source['version_no']);page.received(result)
        page.method.setCurrentIndex(page.method.findData('QUICK'))
        self.finish();self.window.show_section(self.manager.contract_route)
        page.notice.setText(f'已带入当前查看的正式报价 V{self.context[1]}，请选择客户模板并核对合同信息。')

    def finish(self,message=''):
        if not self.active:return
        self.timer.stop();self.active=False
        import contract_management as contracts
        import quote_scheme_center as schemes
        same=self.identity==(contracts.contract_headers(self.window) or {})
        self.window._detail_contract_busy=False;self.window._scheme2_document_busy=False
        if same:
            self.failure=str(message)
            schemes._apply_read_only(self.window,True if self.confirmed else self.previous_readonly)
            if not self.window._quote_scheme_read_only and self.window._quote_scheme_dirty_seq>self.window._quote_scheme_saved_seq:self.window._quote_scheme_save_timer.start(500)
            self.manager.refresh()
            if message:self.manager.feedback.setText('合同准备未完成：'+message)
