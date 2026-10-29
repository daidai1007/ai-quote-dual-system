"""Name-only sessions for the actual recovered startup and request transports.

The server decides scope. Tokens live in memory and are never settings/log data.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import threading
import urllib.request
import urllib.error

from PySide6.QtCore import QThread, Signal, QTimer, QStandardPaths
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,
    QLineEdit,QPushButton,QMessageBox)
from dialog_style import style_dialog, DIALOG_METRICS

_state=None
_epoch=0
_required=False
_thread=threading.local()
_cache_root=None

class LoginCancelled(Exception): pass

def session(): return deepcopy(_state)
def identity_epoch(): return _epoch
def user_id(): return (_state or {}).get('person',{}).get('user_id')
def window_is_current(window,epoch=None):
    return (not getattr(window,'_name_session_closed',False) and not getattr(window,'_name_transitioning',False) and
        getattr(window,'_name_user_id',None)==user_id() and
        (epoch is None or epoch==_epoch))

def set_session(value):
    global _state,_epoch,_cache_root
    person=value.get('person') or {}
    if person.get('identity_mode')!='NAME_ONLY' or person.get('scope') not in ('ALL','OWN') or not re.fullmatch(r'name-user:[0-9a-f]{64}',str(person.get('user_id',''))) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',str(value.get('token',''))):
        raise ValueError('服务端未返回有效的姓名身份。')
    changed=user_id()!=person['user_id']
    _state=deepcopy(value)
    if changed:_epoch+=1
    if _cache_root is None:
        _cache_root=os.environ.get('AI_QUOTE_ORDER_CACHE_ROOT') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=str(Path(_cache_root)/'persons'/person['user_id'].split(':',1)[1])

def clear_session():
    global _state,_epoch
    _state=None;_epoch+=1

class SessionWorker(QThread):
    succeeded=Signal(object)
    failed=Signal(str)
    def __init__(self,url,headers,payload=None,parent=None):
        super().__init__(parent);self.url=url;self.headers=dict(headers);self.payload=deepcopy(payload)
    def run(self):
        try:
            data=None if self.payload is None else json.dumps(self.payload,ensure_ascii=False).encode('utf-8')
            request=urllib.request.Request(self.url,data=data,headers={**self.headers,'Content-Type':'application/json'},method='POST' if data is not None else 'GET')
            with urllib.request.urlopen(request,timeout=30) as response:value=json.loads(response.read().decode('utf-8'))
            self.succeeded.emit(value)
        except urllib.error.HTTPError as error:
            self.http_status=error.code
            try:message=json.loads(error.read().decode('utf-8')).get('message')
            except Exception:message=None
            self.failed.emit(message or '姓名登录服务暂不可用，请检查API是否已更新。')
        except Exception:self.failed.emit('连接失败，当前填写内容已保留，请重试。')

class NameLoginDialog(QDialog):
    def __init__(self,base_url,headers,parent=None,expected_user=None,*,startup=False):
        super().__init__(parent)
        # Initial API_URL is the full calculation endpoint; name switching passes a root.
        self.base_url=str(base_url).strip().split('/api/',1)[0].rstrip('/')
        self.headers=headers;self.expected_user=expected_user
        self.value=None;self.worker=None;self._startup=startup
        self._startup_timer=QTimer(self);self._startup_timer.setInterval(1000)
        self._startup_timer.timeout.connect(self._waiting_for_name)
        self.setWindowTitle('输入姓名');self.setMinimumWidth(420)
        outer=QVBoxLayout(self);outer.setSpacing(DIALOG_METRICS['spacing'])
        outer.addWidget(QLabel('姓名'))
        self.name=QLineEdit();self.name.setMaxLength(100);self.name.setPlaceholderText('请输入您的姓名');outer.addWidget(self.name)
        hint=QLabel('仅按输入姓名识别人员，请使用本人姓名。');hint.setWordWrap(True);outer.addWidget(hint)
        self.error=QLabel();self.error.setWordWrap(True);outer.addWidget(self.error)
        self.enter=QPushButton('进入');self.enter.setObjectName('scheme2PrimaryAction');self.enter.clicked.connect(self.login);outer.addWidget(self.enter)
        self.name.textEdited.connect(lambda _text:self.error.clear() if self.worker is None else None)
        self.name.returnPressed.connect(self.login);style_dialog(self)
    def _report_startup(self,phase):
        if self._startup:
            from client_update_runner import report_startup_phase
            from quote_scheme_center import CLIENT_VERSION
            report_startup_phase(CLIENT_VERSION,phase)
    def _waiting_for_name(self):
        if self.worker is None:self._report_startup('waiting_for_name')
    def showEvent(self,event):
        super().showEvent(event)
        if self._startup:
            self._waiting_for_name();self._startup_timer.start()
    def hideEvent(self,event):
        self._startup_timer.stop();super().hideEvent(event)
    def login(self):
        if self.worker is not None:return
        name=self.name.text().strip()
        if not name:self.error.setText('请输入姓名。');return
        self._startup_timer.stop();self._report_startup('starting_main_window')
        self.enter.setEnabled(False);self.name.setEnabled(False);self.error.setText('正在登录…')
        worker=SessionWorker(self.base_url.rstrip('/')+'/api/name-login',self.headers,{'name':name},self);self.worker=worker
        def loaded(value):
            if self.expected_user and value.get('person',{}).get('user_id')!=self.expected_user:
                self.error.setText('当前任务尚未完成，只能以原姓名重新登录后处理。');return
            self.value=value
        worker.succeeded.connect(loaded);worker.failed.connect(self.error.setText)
        def done():
            self.worker=None;self.enter.setEnabled(True);self.name.setEnabled(True);worker.deleteLater()
            if self.value is not None:self.accept()
            elif self._startup:
                self._waiting_for_name();self._startup_timer.start()
        worker.finished.connect(done);worker.start()
    def reject(self):
        if self.worker is not None:
            self.error.setText('请等待当前登录请求完成。');return
        super().reject()
    def closeEvent(self,event):
        if self.worker is not None:event.ignore()
        else:super().closeEvent(event)

def install_name_transport(namespace):
    original=namespace['api_headers']
    def headers(*args,**kwargs):
        value=dict(original(*args,**kwargs)); frozen=getattr(_thread,'session',_state)
        if frozen:value['Authorization']='Bearer '+frozen['token']
        return value
    namespace['api_headers']=headers
    namespace['_name_connection_headers']=original

def critical_tasks(window):
    manager = getattr(window, 'quote_management', None)
    delivery = getattr(manager, 'delivery', None)
    if getattr(window, '_quote_delivery_output_pending', None) or getattr(delivery, 'pending_send', None): return True
    if getattr(window,'_quote_scheme_pending_export',None) or getattr(window,'_quote_scheme_export_context',None):return True
    if getattr(window,'_scheme2_document_busy',False):return True
    return any(worker.isRunning() for worker in window.findChildren(QThread))

def install_name_login(namespace):
    cls=namespace['MainWindow'];prior_init=cls.__init__
    def init(window,*args,**kwargs):
        if _required and _state is None:
            dialog=NameLoginDialog(namespace['API_URL'],namespace['_name_connection_headers'](),startup=True)
            if dialog.exec()!=QDialog.DialogCode.Accepted:raise LoginCancelled()
            set_session(dialog.value)
        window._name_user_id=user_id();window._name_identity_epoch=_epoch
        prior_init(window,*args,**kwargs)
        if _state is None:return
        person=_state['person'];editor=window.quote_scheme_operator_name
        editor.setText(person['display_name']);editor.setReadOnly(True)
        window.quote_scheme_operator_button.clicked.disconnect()
        window.quote_scheme_operator_button.clicked.connect(lambda:switch_or_renew(window,namespace))
        scope_text=('全部报价 · 可操作' if person.get('can_manage_all_quotes') is True
                    else '全部报价' if person['scope']=='ALL' else '仅本人报价')
        window.quote_scheme_operator_button.setText(person['display_name']+' · '+scope_text)
        window.quote_scheme_operator_button.setToolTip('当前姓名及报价操作范围；点击重新登录或切换姓名。仅姓名识别，不能证明真实身份。')
        # Identity is visible outside the scheme page too.
        badge=QLabel(window.quote_scheme_operator_button.text());badge.setWordWrap(True)
        switch=QPushButton('切换姓名');switch.setToolTip('重新登录或切换姓名');switch.clicked.connect(lambda:switch_or_renew(window,namespace))
        leave=QPushButton('退出登录');leave.clicked.connect(lambda:logout(window,namespace))
        sidebar=window.scheme2_nav.layout();sidebar.insertWidget(max(0,sidebar.count()-2),badge);sidebar.insertWidget(max(0,sidebar.count()-2),switch)
        sidebar.insertWidget(max(0,sidebar.count()-2),leave)
        window.name_scope_label=badge;window.name_switch_button=switch;window.name_logout_button=leave
    cls.__init__=init
    worker=namespace['ApiWorker'];prior_worker_init=worker.__init__;prior_run=worker.run
    def worker_init(self,*args,**kwargs):
        prior_worker_init(self,*args,**kwargs);self._name_frozen_session=session()
        parent=self.parent()
        while parent is not None:
            if hasattr(parent,'_name_user_id'):
                if not window_is_current(parent):self._name_blocked=True
                break
            parent=parent.parent()
    def run(self):
        if getattr(self,'_name_blocked',False):
            self.failed.emit('旧姓名请求已停止，请重新操作。');return
        _thread.session=self._name_frozen_session
        try:return prior_run(self)
        finally:del _thread.session
    worker.__init__,worker.run=worker_init,run
    namespace['_name_login_core_main']=namespace['main']
    def main():
        global _required
        _required=True
        try:return namespace['_name_login_core_main']()
        except LoginCancelled:return
    namespace['main']=main

def switch_or_renew(window,namespace):
    if getattr(window,'_name_switch_worker',None) is not None:return
    pending=critical_tasks(window)
    unsaved=getattr(window,'_scheme2_dirty',False) or getattr(window,'_quote_scheme_dirty_seq',0)>getattr(window,'_quote_scheme_saved_seq',0)
    expected=user_id() if pending or unsaved else None
    if expected:
        QMessageBox.information(window,'当前任务尚未完成','可用原姓名重新登录；切换其他姓名前，请先保存本机进度并完成保存、导出或登记任务。')
    old=session();dialog=NameLoginDialog(window.base_url(),namespace['_name_connection_headers'](),window,expected)
    if dialog.exec()!=QDialog.DialogCode.Accepted:return
    new=dialog.value
    if new['person']['user_id']==old['person']['user_id']:
        set_session(new);window._name_identity_epoch=_epoch
        window.quote_scheme_save_status.setText('已重新登录，可继续处理原任务。');return
    if critical_tasks(window) or getattr(window,'_scheme2_dirty',False) or window._quote_scheme_dirty_seq>window._quote_scheme_saved_seq:
        QMessageBox.information(window,'当前任务尚未完成','登录期间有新的后台任务或未保存内容，尚未切换姓名；请先处理当前工作。');return
    window._name_transitioning=True;window.setEnabled(False)
    # The next person's data is never loaded before logout is acknowledged.
    worker=SessionWorker(window.base_url()+'/api/name-logout',{**namespace['_name_connection_headers'](),'Authorization':'Bearer '+old['token']},{},window)
    window._name_switch_worker=worker;outcome={}
    worker.succeeded.connect(lambda result:outcome.update(ok=True))
    def failed(message):
        if getattr(worker,'http_status',None)==401:outcome.update(ok=True)  # The old session is already invalid.
        else:QMessageBox.information(window,'切换未完成',message+'；当前姓名和工作区已保留。')
    worker.failed.connect(failed)
    def done():
        window._name_switch_worker=None;worker.deleteLater()
        if not outcome.get('ok'):
            window._name_transitioning=False;window.setEnabled(True);return
        def replace():
            window._name_session_closed=True;window._quote_scheme_save_timer.stop();window.hide()
            set_session(new)
            app=QApplication.instance();app.setQuitOnLastWindowClosed(False)
            replacement=namespace['MainWindow']();replacement.show();app._name_main_window=replacement
            window._scheme2_dirty=False;window.close();window.deleteLater();app.setQuitOnLastWindowClosed(True)
        QTimer.singleShot(0,replace)
    worker.finished.connect(done);worker.start()

def logout(window,namespace):
    if getattr(window,'_name_switch_worker',None) is not None:return
    if critical_tasks(window) or getattr(window,'_scheme2_dirty',False) or window._quote_scheme_dirty_seq>window._quote_scheme_saved_seq:
        QMessageBox.information(window,'当前任务尚未完成','请先保存本机进度，并完成后台保存、导出或登记任务后退出登录。');return
    old=session();window._name_transitioning=True;window.setEnabled(False)
    worker=SessionWorker(window.base_url()+'/api/name-logout',{**namespace['_name_connection_headers'](),'Authorization':'Bearer '+old['token']},{},window)
    window._name_switch_worker=worker;outcome={}
    worker.succeeded.connect(lambda _:outcome.update(ok=True))
    def failed(message):
        if getattr(worker,'http_status',None)==401:outcome.update(ok=True)
        else:QMessageBox.information(window,'退出未完成',message+'；当前姓名和工作区已保留。')
    worker.failed.connect(failed)
    def done():
        window._name_switch_worker=None;worker.deleteLater()
        if not outcome.get('ok'):
            window._name_transitioning=False;window.setEnabled(True);return
        def login_again():
            app=QApplication.instance();app.setQuitOnLastWindowClosed(False)
            window._name_session_closed=True;window._quote_scheme_save_timer.stop();window.hide();clear_session()
            dialog=NameLoginDialog(window.base_url(),namespace['_name_connection_headers']())
            if dialog.exec()==QDialog.DialogCode.Accepted:
                set_session(dialog.value);replacement=namespace['MainWindow']();replacement.show();app._name_main_window=replacement
            window._scheme2_dirty=False;window.close();window.deleteLater();app.setQuitOnLastWindowClosed(True)
            if session() is None:app.quit()
        QTimer.singleShot(0,login_again)
    worker.finished.connect(done);worker.start()
