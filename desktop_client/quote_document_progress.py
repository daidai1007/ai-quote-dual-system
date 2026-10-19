"""Observable, read-only quote preview checks and existing export feedback."""
import copy
import json
import logging
import re
import time
from types import MethodType
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QStyle, QVBoxLayout, QWidget

from attachment_v2_client import confirmation_payload, attachment_snapshot_needs_refresh
from progress_style import PROGRESS_COLORS

LOGGER = logging.getLogger("ai_quote.client")
UPDATE_INTERVAL_MS = 100
SNAPSHOT_REFRESH_CONCURRENCY = 2
FEEDBACK_SHOW_DELAY_MS = 300
FEEDBACK_SUCCESS_VISIBLE_MS = 2000
FEEDBACK_METRICS = dict(max_width=760, line_height=26, track_height=4, track_radius=2,
                        spacing=6, font_px=12, icon_size=16)
FEEDBACK_COLORS = dict(text=PROGRESS_COLORS['text'], primary=PROGRESS_COLORS['fill'],
                       track=PROGRESS_COLORS['track'], success='#3B6D11', error='#B91C1C')


class _FeedbackLabel(QLabel):
    """Single-line feedback that cannot push recovery actions off the page."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ''
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_feedback(self, text):
        self.full_text = text
        self.setAccessibleName(text)
        self._elide()

    def _elide(self):
        # Render the success check with Qt's icon; some deployed CJK fonts do
        # not contain U+2713. Keep the full accessible message unchanged.
        text = self.full_text.removeprefix('✓ ')
        self.setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(1, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


def failure_info(value):
    text = str(value)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    reason = str(data.get("message") or text)
    issues = [issue for issue in (data.get("issues") or []) if isinstance(issue, dict)]
    if not issues:
        match = re.search(r"第(\d+)行报价（([^）]+)）的[“\"]([^”\"]+)[”\"]：([^\n]+)", reason)
        if match:
            issues = [dict(line_number=int(match[1]), product_name=match[2],
                           attachment_name=match[3], reason=match[4])]
    for issue in issues:
        detail = (f"第{issue.get('line_number', '?')}行报价（{issue.get('product_name') or '未命名'}）的"
                  f"“{issue.get('attachment_name') or '附件'}”：{issue.get('reason') or '附件校验失败'}")
        name, problem = str(issue.get('attachment_name') or ''), str(issue.get('reason') or '')
        if detail not in reason and not (name and problem and name in reason and problem in reason):
            reason += "\n" + detail
    return reason, issues


class QuoteDocumentProgress:
    def __init__(self, window, namespace, ui):
        self.window, self.namespace, self.ui = window, namespace, ui
        self.busy = False
        self.kind = "generate"
        self.reason, self.issues = "", []
        self.registration_retry = None
        self.file_exported = False
        self.success_text = ''
        self.widgets = {}
        self.feedback = {}
        self.state = 'idle'
        self.feedback_kind = self.kind
        self.show_timer = self.hide_timer = None
        for kind, layout in (("generate", window.scheme2_cost_generate.parentWidget().parentWidget().layout()),
                             ("export", window.scheme2_quote_page.layout())):
            host = QWidget()
            host.setObjectName('quoteDocumentFeedback')
            host.setMaximumWidth(FEEDBACK_METRICS['max_width'])
            host.setStyleSheet('QWidget#quoteDocumentFeedback { background:transparent; border:0; }')
            column = QVBoxLayout(host)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(FEEDBACK_METRICS['spacing'])
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(FEEDBACK_METRICS['spacing'])
            success_icon = QLabel(host)
            icon_size = FEEDBACK_METRICS['icon_size']
            success_icon.setFixedSize(icon_size, icon_size)
            success_icon.setPixmap(window.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton).pixmap(icon_size, icon_size))
            success_icon.setAccessibleName('已完成')
            success_icon.hide()
            label = _FeedbackLabel(host)
            label.setMinimumHeight(FEEDBACK_METRICS['line_height'])
            bar = ui._ClickableProgressBar()
            bar.setObjectName("quoteDocumentProgress")
            bar.setTextVisible(False)
            bar.setFixedHeight(FEEDBACK_METRICS['track_height'])
            bar.setMinimumWidth(0)
            bar.setStyleSheet(f"""
                QProgressBar#quoteDocumentProgress {{ background:{FEEDBACK_COLORS['track']}; border:0; border-radius:{FEEDBACK_METRICS['track_radius']}px; }}
                QProgressBar#quoteDocumentProgress::chunk {{ background:{FEEDBACK_COLORS['primary']}; border-radius:{FEEDBACK_METRICS['track_radius']}px; }}
            """)
            bar.clicked.connect(self.details)
            retry = QPushButton('重试')
            details = QPushButton('查看详情')
            retry.clicked.connect(self.retry)
            details.clicked.connect(self.details)
            locate = QPushButton("定位问题附件")
            locate.clicked.connect(self.locate)
            for button in (retry, details, locate):
                button.setObjectName('scheme2PrimaryGhost')
                button.hide()
            row.addWidget(success_icon)
            row.addWidget(label, 1)
            row.addWidget(retry)
            row.addWidget(details)
            row.addWidget(locate)
            column.addLayout(row)
            column.addWidget(bar)
            layout.insertWidget(layout.count() - 1 if kind == "generate" else 1, host)
            host.hide()
            self.widgets[kind] = (host, bar, locate)
            self.feedback[kind] = dict(label=label, success_icon=success_icon, retry=retry, details=details)
        self.timer = QTimer(window)
        self.timer.setInterval(UPDATE_INTERVAL_MS)
        self.timer.timeout.connect(self.refresh)
        self.original_export = window.confirm_and_export
        window.confirm_and_export = MethodType(lambda owner: self.export(), window)
        window._scheme2_document_request_progress = self.request_progress
        self._hook_export()

    def begin(self, kind):
        self._stop_feedback_timers()
        # Restore the previous task's exact enabled states before capturing a
        # new task (also used by explicit workspace reset/retry tests).
        self._restore_controls()
        for host, _bar, _locate in self.widgets.values():
            host.hide()
        self.kind, self.busy = kind, True
        self.feedback_kind, self.state = kind, 'busy'
        self.reason, self.issues = "", []
        self.registration_retry = None
        self.file_exported = False
        self.success_text = ''
        self.trace = uuid4().hex
        self.started = self.phase_started = time.monotonic()
        self.finished_at = None
        self.phase_times = []
        self.step, self.label = 0, ""
        self.window._scheme2_document_busy = True
        self.disabled_controls = [(control, control.isEnabled()) for control in (
            self.window.summary_table, self.window.scheme2_quote_preview, self.window.scheme2_cost_sidebar,
            *self.window.scheme2_cost_action_buttons[:-2])]
        for control, _enabled in self.disabled_controls:
            control.setEnabled(False)
        host, bar, locate = self.widgets[kind]
        bar.setRange(0, 4 if kind == "generate" else 5)
        bar.setProperty("failed", False)
        bar.setCursor(Qt.CursorShape.ArrowCursor)
        bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        locate.hide()
        self.timer.start()
        self.set_stage(1, "校验清单")
        self.sync_buttons()
        self._schedule_feedback('show_timer', FEEDBACK_SHOW_DELAY_MS, self._show_busy)

    def _restore_controls(self):
        for control, enabled in getattr(self, 'disabled_controls', []):
            control.setEnabled(enabled)
        self.disabled_controls = []

    def _stop_feedback_timers(self):
        for name in ('show_timer', 'hide_timer'):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                setattr(self, name, None)

    def _schedule_feedback(self, name, delay, callback):
        trace = self.trace
        timer = QTimer(self.window)
        timer.setSingleShot(True)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        setattr(self, name, timer)
        def dispatch():
            # A stopped timer can already have a queued timeout. Never let an
            # older completion collapse a new task's progress/error feedback.
            if getattr(self, name, None) is not timer:
                return
            setattr(self, name, None)
            timer.deleteLater()
            if trace == self.trace:
                callback()
        timer.timeout.connect(dispatch)
        timer.start(delay)

    def _show_busy(self):
        if self.busy and self.state == 'busy':
            self.widgets[self.kind][0].show()

    def _collapse_feedback(self):
        if not self.busy and self.state == 'success':
            for host, _bar, _locate in self.widgets.values():
                host.hide()
            self.state = 'idle'

    def retry(self):
        if self.reason and not self.busy:
            if self.registration_retry is not None:
                self.registration_retry()
            else:
                self.generate() if self.kind == 'generate' else self.export()

    def registration_started(self, retry):
        """The workbook exists; from here recovery must never export it again."""
        if not self.busy:
            self.begin('export')
        self.file_exported = True
        self.registration_retry = retry
        self.reason, self.issues = '', []
        self.widgets['export'][1].setMaximum(6)
        self.set_stage(6, '文件已导出，正在登记方案')
        self.widgets['export'][0].show()
        self.sync_buttons()

    def registration_failed(self, message):
        self.fail(message)

    def registration_completed(self, status_text):
        self.success_text = f'✓ 文件已导出，方案已登记（{status_text}）'
        self.reason, self.issues = '', []
        self.registration_retry = None
        self.end()

    def set_stage(self, step, label):
        if step != self.step:
            if self.step:
                self.phase_times.append((self.label, time.monotonic() - self.phase_started))
            LOGGER.info("document phase mode=%s trace=%s step=%s elapsed=%.3fs", self.kind,
                        self.trace, step, time.monotonic() - self.started)
            self.phase_started = time.monotonic()
        self.step, self.label = step, label
        self.refresh()

    def refresh(self):
        if not hasattr(self, "started"):
            return
        _host, bar, _locate = self.widgets[self.kind]
        now = self.finished_at if self.finished_at is not None else time.monotonic()
        total = now - self.started
        elapsed = now - self.phase_started
        label = "失败" if self.reason else self.label
        text = f"{self.step}/{bar.maximum()} {label} · 已用时 {total:.1f}秒"
        bar.setFormat(text)
        bar.setValue(self.step)
        bar.setAccessibleName(f"{self.step}/{bar.maximum()} {self.label}")
        bar.setToolTip((self.reason + "\n点击查看完整失败详情" if self.reason else self.label)
                       + f"\n本阶段：{elapsed:.1f}秒；累计：{total:.1f}秒\n处理编号：{self.trace}")
        feedback = self.feedback[self.feedback_kind]
        _host, visible_bar, locate = self.widgets[self.feedback_kind]
        failed = self.state == 'failed'
        if failed:
            operation = '生成' if self.kind == 'generate' else '导出'
            attachment = str(self.issues[0].get('attachment_name') or '') if self.issues else ''
            message = f'{operation}失败：{attachment}校验未通过' if attachment else f'{operation}失败，请查看详情后重试。'
            if self.file_exported:
                message = '文件已导出，方案登记失败，请重试登记。'
        elif self.state == 'success':
            message = self.success_text or ('✓ 报价单已生成' if self.kind == 'generate' else '✓ 报价单已导出')
        else:
            stage = self.label if self.label.startswith(('正在', '文件已导出')) else '正在' + self.label
            message = f'{stage}… · 已用时 {total:.1f} 秒'
        feedback['label'].set_feedback(message)
        color = FEEDBACK_COLORS['error' if failed else 'success' if self.state == 'success' else 'text']
        style = f"color:{color}; font-size:{FEEDBACK_METRICS['font_px']}px;"
        if feedback['label'].styleSheet() != style:
            feedback['label'].setStyleSheet(style)
        feedback['label'].setToolTip(bar.toolTip())
        feedback['retry'].setVisible(failed)
        feedback['retry'].setText('重试登记' if self.file_exported else '重试')
        feedback['details'].setVisible(failed)
        feedback['success_icon'].setVisible(self.state == 'success')
        locate.setVisible(failed and bool(self.issues))
        visible_bar.setVisible(self.state == 'busy')

    def sync_buttons(self):
        self.window.scheme2_cost_generate.setEnabled(not self.busy and bool(self.window.draft_items))
        self.window.scheme2_quote_export.setEnabled(not self.busy and bool(self.window.draft_items))
        self.window.scheme2_cost_generate.setText("生成中…" if self.busy and self.kind == "generate" else
                                                "重试生成" if self.reason and self.kind == "generate" else "生成报价单")
        self.window.scheme2_quote_export.setText("登记中…" if self.busy and self.file_exported else
                                                "重试登记" if self.reason and self.file_exported else
                                                "正在导出…" if self.busy and self.kind == "export" else
                                                "重试导出" if self.reason and self.kind == "export" else "导出报价单")

    def end(self, cancelled=False):
        self.busy = False
        self.finished_at = time.monotonic()
        self.window._scheme2_document_busy = False
        self.timer.stop()
        self._stop_feedback_timers()
        self._restore_controls()
        finished = getattr(self.window, 'quote_scheme_export_finished', None)
        if self.kind == 'export' and callable(finished):
            finished()
        self.state = 'failed' if self.reason else 'idle' if cancelled else 'success'
        if self.state == 'success' and self.kind == 'generate' and self.window.stack.currentIndex() == self.ui.QUOTE_ROUTE:
            # Generation navigates away from cost calculation. Put the small
            # success message next to the quote-sheet actions the user now sees.
            self.feedback_kind = 'export'
        for host, _bar, _locate in self.widgets.values():
            host.hide()
        self.refresh()
        self.sync_buttons()
        if self.state in ('failed', 'success'):
            self.widgets[self.feedback_kind][0].show()
        if self.state == 'success':
            self._schedule_feedback('hide_timer', FEEDBACK_SUCCESS_VISIBLE_MS, self._collapse_feedback)

    def reset(self):
        """Return both document flows to idle and invalidate queued prechecks."""
        self.trace = uuid4().hex
        self._stop_feedback_timers()
        self.state = 'idle'
        self.phase_times = []
        self.finished_at = None
        self.busy = False
        self.window._scheme2_document_busy = False
        self.timer.stop()
        self._restore_controls()
        self.reason, self.issues = "", []
        self.registration_retry = None
        self.file_exported = False
        self.success_text = ''
        self.step, self.label, self.snapshot = 0, "", ""
        for name in ("started", "phase_started"):
            if hasattr(self, name):
                delattr(self, name)
        for host, bar, locate in self.widgets.values():
            host.hide()
            locate.hide()
            bar.reset()
            bar.setFormat("")
            bar.setToolTip("")
            bar.setAccessibleName("")
            bar.setProperty("failed", False)
            bar.setCursor(Qt.CursorShape.ArrowCursor)
            bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bar.style().unpolish(bar)
            bar.style().polish(bar)
        for feedback in self.feedback.values():
            feedback['label'].set_feedback('')
            feedback['label'].setToolTip('')
            feedback['retry'].hide()
            feedback['details'].hide()
            feedback['success_icon'].hide()
        self.sync_buttons()

    def fail(self, value):
        if not hasattr(self, "started"):
            self.begin("export")
        self.reason, self.issues = failure_info(value)
        _host, bar, locate = self.widgets[self.kind]
        bar.setProperty("failed", True)
        bar.setCursor(Qt.CursorShape.PointingHandCursor)
        bar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        locate.setVisible(bool(self.issues))
        LOGGER.error("document failed mode=%s trace=%s step=%s elapsed=%.3fs reason=%s issues=%s", self.kind,
                     self.trace, self.step, time.monotonic() - self.started,
                     self.reason, json.dumps(self.issues, ensure_ascii=False))
        self.end()

    def validate(self, items):
        if not items:
            raise ValueError("报价清单为空，请先加入产品。")
        for number, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ValueError(f"第{number}行报价数据无效。")
            self.set_stage(2 if self.kind == "generate" else 1, f"检查附件 {number}/{len(items)}")
            LOGGER.info("document row checked trace=%s line=%s product=%s attachments=%s", self.trace,
                        number, item.get('name') or item.get('product_code'), len(item.get('attachments') or []))
            for attachment in item.get("attachments") or []:
                if isinstance(attachment, dict) and not attachment.get("custom") and attachment.get("status") in ("ERROR", "PENDING_MANUAL"):
                    missing = "、".join(attachment.get("pending_manual_dimensions") or [])
                    reason = attachment.get("error") or ("缺少人工尺寸：" + missing if missing else "附件成本计算失败")
                    name = attachment.get("item_name") or "未命名附件"
                    raise ValueError(f"第{number}行报价（{item.get('name') or item.get('product_code') or '未命名'}）的“{name}”：{reason}")
        frozen = self.ui._quote_export_items_snapshot(self.window, items)
        return confirmation_payload({"items": frozen}, validate=True)["items"]

    def prepare_snapshots(self, ready):
        """Explicit legacy snapshot repair; current generate/export freeze popup rows."""
        try:
            pending = [(number, item) for number, item in enumerate(self.window.draft_items, 1)
                       if isinstance(item, dict) and attachment_snapshot_needs_refresh(item)]
        except Exception as error:
            self.fail(error)
            return
        if not pending:
            ready()
            return
        trace = self.trace
        state = dict(next=0, active=0, completed=0, error=None, done=False, pumping=False)

        def current():
            return self.busy and self.trace == trace and not state["done"]

        def progress():
            label = (f"附件更新失败，等待剩余 {state['active']} 行" if state["error"] else
                     f"更新附件快照，已完成 {state['completed']}/{len(pending)} 行")
            self.set_stage(2 if self.kind == "generate" else 1, label)

        def launch(number, item):
            started, settled = time.monotonic(), False
            LOGGER.info("refresh attachment snapshot trace=%s line=%s old_line=%s", self.trace, number, item.get("quote_line_id"))

            def finish(success, message=None):
                nonlocal settled
                if settled or not current():
                    return
                settled = True
                state["active"] -= 1
                LOGGER.info("attachment snapshot completed trace=%s line=%s success=%s elapsed=%.3fs",
                            trace, number, success, time.monotonic() - started)
                if success:
                    state["completed"] += 1
                elif state["error"] is None:
                    try:
                        data = json.loads(str(message))
                    except (ValueError, TypeError):
                        data = None
                    if isinstance(data, dict):
                        reason = data.get("message") or str(message)
                        issues = [issue for issue in (data.get("issues") or []) if isinstance(issue, dict)]
                    else:
                        reason, issues = failure_info(message)
                    state["error"] = json.dumps({
                        "message":f"第{number}行报价（{item.get('name') or item.get('product_code')}）：{reason}",
                        "issues":[{**issue,"line_number":number,
                                   "product_name":item.get('name') or item.get('product_code')} for issue in issues],
                    }, ensure_ascii=False)
                progress()
                if not state["pumping"]:
                    pump()

            try:
                refresh = getattr(self.window, "refresh_draft_attachment_snapshot", None)
                if not callable(refresh):
                    raise RuntimeError("附件快照更新功能不可用，请更新客户端。")
                refresh(item, lambda:finish(True), lambda message:finish(False, message))
            except Exception as error:
                finish(False, error)

        def pump():
            if not current():
                return
            state["pumping"] = True
            try:
                while (state["active"] < SNAPSHOT_REFRESH_CONCURRENCY
                       and state["next"] < len(pending) and state["error"] is None):
                    number, item = pending[state["next"]]
                    state["next"] += 1
                    state["active"] += 1
                    progress()
                    launch(number, item)
            finally:
                state["pumping"] = False
            if not state["active"]:
                state["done"] = True
                if state["error"]:
                    self.fail(state["error"])
                elif state["next"] == len(pending):
                    ready()
        pump()

    def generate(self):
        if self.busy:
            return
        if getattr(self.window, '_quote_scheme_pending_export', None):
            QMessageBox.information(self.window, '方案待登记', '文件已导出，请先重试方案登记，无需重新生成报价单。')
            return
        self.begin("generate")
        trace = self.trace
        def current():
            return self.busy and self.trace == trace
        def check():
            if not current():
                return
            try:
                items = copy.deepcopy(self.window.draft_items)
                self.snapshot = json.dumps(items, sort_keys=True, ensure_ascii=False, default=str)
                self.set_stage(2, "逐行检查附件")
                checked = self.validate(items)
                self.set_stage(3, "服务端预检")
                worker = self.namespace["ApiWorker"](self.window.base_url().rstrip('/') + '/api/quotes/preview-check',
                    {"quote_id":"PREVIEW_" + self.trace, "items":checked}, self.window)
                self.preview_worker = worker
                worker.succeeded.connect(lambda body: self.preview_done(body) if current() else None)
                worker.failed.connect(lambda error: self.fail(error) if current() else None)
                worker.finished.connect(worker.deleteLater)
                worker.start()
            except Exception as error:
                self.fail(error)
        # Popup edits have already completed their preview calculation. Freeze
        # those rows instead of writing another catalogue-priced snapshot.
        QTimer.singleShot(0, check)

    def preview_done(self, body):
        if not body.get("valid") or body.get("persisted") is not False:
            self.fail("服务端未返回有效的报价预检结果，请重试。")
            return
        current = json.dumps(self.window.draft_items, sort_keys=True, ensure_ascii=False, default=str)
        if current != self.snapshot:
            self.fail("预检期间报价清单已变化，请重新生成报价单。")
            return
        self.set_stage(4, "显示报价单")
        self.window.show_section(self.ui.QUOTE_ROUTE)
        self.end()

    def export(self):
        if self.busy:
            return
        prepare = getattr(self.window, 'quote_scheme_prepare_export', None)
        if callable(prepare) and not prepare():
            return
        self.begin("export")
        self.start_export()

    def start_export(self):
        try:
            self.set_stage(1, "逐行检查附件")
            self.validate(copy.deepcopy(self.window.draft_items))
            if not self.window.scheme2_company.currentText().strip():
                raise ValueError("请选择下单公司后再导出报价单。")
            self.set_stage(1, "选择保存位置")
            self.original_export()
            active = False
            for name in ("confirm_worker", "export_worker"):
                worker = getattr(self.window, name, None)
                try:
                    active |= bool(worker and worker.isRunning())
                except RuntimeError:
                    pass
            if self.busy and not active:
                self.set_stage(1, "已取消导出")
                self.end(cancelled=True)
        except Exception as error:
            self.fail(error)

    def request_progress(self, event):
        if not self.busy:
            return
        endpoint = event.get("endpoint")
        step = 3 if self.kind == "generate" else 4 if endpoint == "confirm" else 2
        label = "服务端预检" if self.kind == "generate" else "确认报价并写入历史" if endpoint == "confirm" else "服务端预检"
        if event.get("attempt", 1) > 1:
            label += f"（重试 {event['attempt']}）"
        self.set_stage(step, label)

    def _hook_export(self):
        original_busy = self.window.set_export_busy
        def busy(owner, active, message=""):
            if self.busy and self.kind == "export" and active:
                if "Excel 已生成" in message or "写入公司历史" in message:
                    self.set_stage(4, "确认报价并写入历史")
                elif "Excel" in message:
                    self.set_stage(3, "生成 Excel 临时文件")
                else:
                    self.set_stage(2, "服务端预检")
            result = original_busy(active, message)
            self.sync_buttons()
            return result
        self.window.set_export_busy = MethodType(busy, self.window)
        for name in ("confirmation_failed", "export_failed", "persistence_failed", "finalization_failed"):
            original = getattr(self.window, name, None)
            if callable(original):
                def failed(owner, message, callback=original):
                    self.fail(message)
                    return callback(self.reason)
                setattr(self.window, name, MethodType(failed, self.window))
        original_success = self.window.export_succeeded
        def succeeded(owner, *args, **kwargs):
            self.set_stage(5, "正式报价单已生成")
            self.end()
            return original_success(*args, **kwargs)
        self.window.export_succeeded = MethodType(succeeded, self.window)

    def details(self):
        if not self.reason:
            return
        box = QMessageBox(QMessageBox.Icon.Warning, "报价处理失败详情", self.reason,
                          QMessageBox.StandardButton.Close, self.window)
        box.setTextFormat(Qt.TextFormat.PlainText)
        now = self.finished_at if self.finished_at is not None else time.monotonic()
        phases = [*self.phase_times, (self.label, now - self.phase_started)]
        timings = '\n'.join(f'{label}：{elapsed:.1f}秒' for label, elapsed in phases)
        box.setDetailedText(f"累计耗时：{now-self.started:.1f}秒\n各阶段耗时：\n{timings}\n处理编号：{self.trace}\n" + self.reason)
        locate = box.addButton("定位问题附件", QMessageBox.ButtonRole.ActionRole) if self.issues else None
        retry = box.addButton("重试", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if locate is not None and box.clickedButton() is locate:
            self.locate()
        elif box.clickedButton() is retry:
            self.retry()

    def locate(self):
        if not self.issues:
            return
        issue = self.issues[0]
        index = int(issue.get("line_number", 0)) - 1
        if not 0 <= index < len(self.window.draft_items):
            return
        self.window.show_section(self.ui.COST_ROUTE)
        self.window.summary_table.selectRow(index)
        self.window.summary_table.scrollToItem(self.window.summary_table.item(index, 1))
        editor = self.ui.AttachmentEditor(self.window, self.window.draft_items[index])
        for row, source in enumerate(self.window.draft_items[index].get("attachments") or []):
            if (source.get("item_name") == issue.get("attachment_name") or
                    issue.get("attachment_price_id") is not None and source.get("attachment_price_id") == issue["attachment_price_id"]):
                editor.table.selectRow(row)
                editor.table.scrollToItem(editor.table.item(row, editor.COL_NAME))
                break
        editor.exec()
