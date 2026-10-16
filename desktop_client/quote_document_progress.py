"""Observable, read-only quote preview checks and existing export feedback."""
import copy
import json
import logging
import re
import time
from types import MethodType
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QWidget

from attachment_v2_client import confirmation_payload, attachment_snapshot_needs_refresh
from quote_diagnostics import record_event

LOGGER = logging.getLogger("ai_quote.client")
UPDATE_INTERVAL_MS = 100
SNAPSHOT_REFRESH_CONCURRENCY = 2


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
        self.widgets = {}
        for kind, layout in (("generate", window.scheme2_cost_generate.parentWidget().parentWidget().layout()),
                             ("export", window.scheme2_quote_page.layout())):
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            bar = ui._ClickableProgressBar()
            bar.setObjectName("scheme2AddProgress")
            bar.setTextVisible(True)
            bar.setMinimumWidth(ui.ADD_PROGRESS_MIN_WIDTH)
            bar.setMaximumWidth(ui.ADD_PROGRESS_MAX_WIDTH)
            bar.clicked.connect(self.details)
            locate = QPushButton("定位问题附件")
            locate.setObjectName("scheme2PrimaryGhost")
            locate.clicked.connect(self.locate)
            locate.hide()
            row.addWidget(bar, 1)
            row.addWidget(locate)
            row.addStretch(1)
            layout.insertWidget(layout.count() - 1 if kind == "generate" else 1, host)
            host.hide()
            self.widgets[kind] = (host, bar, locate)
        self.timer = QTimer(window)
        self.timer.setInterval(UPDATE_INTERVAL_MS)
        self.timer.timeout.connect(self.refresh)
        self.original_export = window.confirm_and_export
        window.confirm_and_export = MethodType(lambda owner: self.export(), window)
        window._scheme2_document_request_progress = self.request_progress
        self._hook_export()

    def begin(self, kind):
        record_event(self.window, "document_requested", kind=kind,
                     items=len(getattr(self.window, "draft_items", [])))
        self.kind, self.busy = kind, True
        self.reason, self.issues = "", []
        self.trace = uuid4().hex
        self.started = self.phase_started = time.monotonic()
        self.step, self.label = 0, ""
        self.window._scheme2_document_busy = True
        self.disabled_controls = [(control, control.isEnabled()) for control in (
            self.window.summary_table, self.window.scheme2_quote_preview, self.window.scheme2_cost_sidebar,
            *self.window.scheme2_cost_action_buttons[:-2])]
        for control, _enabled in self.disabled_controls:
            control.setEnabled(False)
        host, bar, locate = self.widgets[kind]
        host.show()
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

    def set_stage(self, step, label):
        if step != self.step:
            record_event(self.window, "document_stage", kind=self.kind, step=step, label=label)
            LOGGER.info("document phase mode=%s trace=%s step=%s elapsed=%.3fs", self.kind,
                        self.trace, step, time.monotonic() - self.started)
            self.phase_started = time.monotonic()
        self.step, self.label = step, label
        self.refresh()

    def refresh(self):
        if not hasattr(self, "started"):
            return
        _host, bar, _locate = self.widgets[self.kind]
        total = time.monotonic() - self.started
        elapsed = time.monotonic() - self.phase_started
        label = "失败" if self.reason else self.label
        text = f"{self.step}/{bar.maximum()} {label} · {elapsed:.1f}秒"
        metrics = bar.fontMetrics()
        bar.setFormat(metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                       max(40, bar.width() - self.ui.ADD_PROGRESS_TEXT_PADDING)))
        bar.setValue(self.step)
        bar.setAccessibleName(f"{self.step}/{bar.maximum()} {self.label}")
        bar.setToolTip((self.reason + "\n点击查看完整失败详情" if self.reason else self.label)
                       + f"\n本阶段：{elapsed:.1f}秒；累计：{total:.1f}秒\n处理编号：{self.trace}")

    def sync_buttons(self):
        self.window.scheme2_cost_generate.setEnabled(not self.busy and bool(self.window.draft_items))
        self.window.scheme2_quote_export.setEnabled(not self.busy and bool(self.window.draft_items))
        self.window.scheme2_cost_generate.setText("生成中…" if self.busy and self.kind == "generate" else
                                                "重试生成" if self.reason and self.kind == "generate" else "生成报价单")
        self.window.scheme2_quote_export.setText("正在导出…" if self.busy and self.kind == "export" else
                                                "重试导出" if self.reason and self.kind == "export" else "导出报价单")

    def end(self):
        self.busy = False
        self.window._scheme2_document_busy = False
        self.timer.stop()
        for control, enabled in getattr(self, "disabled_controls", []):
            control.setEnabled(enabled)
        self.refresh()
        self.sync_buttons()

    def fail(self, value):
        if not hasattr(self, "started"):
            self.begin("export")
        self.reason, self.issues = failure_info(value)
        record_event(self.window, "document_failed", kind=self.kind, step=self.step,
                     reason=self.reason[:500], trace=getattr(self, "trace", ""))
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
        self.begin("generate")
        def check():
            try:
                items = copy.deepcopy(self.window.draft_items)
                self.snapshot = json.dumps(items, sort_keys=True, ensure_ascii=False, default=str)
                self.set_stage(2, "逐行检查附件")
                checked = self.validate(items)
                self.set_stage(3, "服务端预检")
                worker = self.namespace["ApiWorker"](self.window.base_url().rstrip('/') + '/api/quotes/preview-check',
                    {"quote_id":"PREVIEW_" + self.trace, "items":checked}, self.window)
                self.preview_worker = worker
                worker.succeeded.connect(self.preview_done)
                worker.failed.connect(self.fail)
                worker.finished.connect(worker.deleteLater)
                worker.start()
            except Exception as error:
                self.fail(error)
        QTimer.singleShot(0, lambda:self.prepare_snapshots(check))

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
        self.begin("export")
        self.prepare_snapshots(self.start_export)

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
                self.end()
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
        box.setDetailedText(f"阶段：{self.label}\n处理编号：{self.trace}\n" + self.reason)
        locate = box.addButton("定位问题附件", QMessageBox.ButtonRole.ActionRole) if self.issues else None
        retry = box.addButton("重试", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if locate is not None and box.clickedButton() is locate:
            self.locate()
        elif box.clickedButton() is retry:
            self.generate() if self.kind == "generate" else self.export()

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
