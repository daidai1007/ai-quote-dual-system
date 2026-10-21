"""Opt-in, non-blocking update UI using the workbench's shared visual tokens."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)
from client_update_core import (ENTRY, Cancelled, UpdateError, atomic_json, cache_root,
                                check_release, download_update, load_config, read_json)
from client_update_runner import acknowledge_startup
from dialog_style import DIALOG_COLORS, DIALOG_METRICS, button_style, style_dialog
from progress_style import progress_color_style
from quote_scheme_center import CLIENT_VERSION
from ui_typography import BODY_PX, FONT_FAMILY_QSS, SECTION_TITLE_PX

LOGGER = logging.getLogger("ai_quote.client")
METRICS = {"dialog_width": 550, "dialog_height": 430, "banner_inset": 10,
           "startup_delay": 1500, "health_delay": 2500}
CHECK_BUTTON_METRICS = {"radius": 8, "inset": 10, "border": 1}
CHECK_BUTTON_COLORS = {"text": "#0B326B", "disabled": "#5A7AAB"}


def check_button_style():
    """Sidebar utility action; dialog actions keep their shared button style."""
    # Inherit navigation typography/height, including the workbench resize pass.
    # Local fixed font/height rules would drift from the other sidebar actions.
    c, m = DIALOG_COLORS, CHECK_BUTTON_METRICS
    return f"""
QPushButton#clientCheckUpdateButton {{ min-width:0; padding:0 {m['inset']-m['border']}px;
    border:{m['border']}px solid transparent; border-radius:{m['radius']}px;
    color:{CHECK_BUTTON_COLORS['text']}; background:transparent; text-align:left; }}
QPushButton#clientCheckUpdateButton:hover {{ background:{c['selected']}; }}
QPushButton#clientCheckUpdateButton:pressed {{ background:{c['hover']}; }}
QPushButton#clientCheckUpdateButton:focus {{ border-color:{c['focus']}; }}
QPushButton#clientCheckUpdateButton:disabled {{ color:{CHECK_BUTTON_COLORS['disabled']}; background:transparent; }}
"""


class UpdateTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, function, parent):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            value = self.function(self)
            if not self.isInterruptionRequested():
                self.succeeded.emit(value)
        except Cancelled:
            pass
        except Exception as error:
            if not self.isInterruptionRequested():
                LOGGER.warning("client update task failed: %s", error)
                self.failed.emit(str(error))


class UpdateDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window)
        self.controller = controller
        self.setWindowTitle("软件更新")
        self.setObjectName("clientUpdateDialog")
        self.setModal(False)
        self.resize(METRICS["dialog_width"], METRICS["dialog_height"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 0, 18, 18)
        outer.setSpacing(DIALOG_METRICS["spacing"])
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(); column = QVBoxLayout(content)
        scroll.setStyleSheet(f"background:{DIALOG_COLORS['background']}; border:0;")
        content.setStyleSheet(f"background:{DIALOG_COLORS['background']};")
        column.setContentsMargins(6, 16, 6, 12); column.setSpacing(12)
        self.heading = QLabel(); self.heading.setWordWrap(True)
        self.heading.setObjectName("clientUpdateTitle")
        self.description = QLabel(); self.description.setWordWrap(True); self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.notes = QLabel(); self.notes.setWordWrap(True); self.notes.setTextFormat(Qt.TextFormat.PlainText)
        self.progress = QProgressBar(); self.progress.setStyleSheet(progress_color_style())
        self.progress.setRange(0, 100)
        self.safe = QLabel("你的连接配置、本地订单、图纸和已导出文件将保留。")
        self.safe.setWordWrap(True)
        self.safe.setStyleSheet(f"background:{DIALOG_COLORS['selected']}; padding:10px; border-radius:6px;")
        self.details = QLabel(); self.details.setWordWrap(True); self.details.setTextFormat(Qt.TextFormat.PlainText)
        for widget in (self.heading, self.description, self.notes, self.progress, self.safe, self.details):
            column.addWidget(widget)
        column.addStretch(1)
        scroll.setWidget(content); outer.addWidget(scroll, 1)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        self.secondary = QPushButton(); self.primary = QPushButton()
        self.secondary.setStyleSheet(button_style("secondary")); self.primary.setStyleSheet(button_style("primary"))
        self.secondary.setAutoDefault(False); self.primary.setAutoDefault(False)
        buttons.addWidget(self.secondary); buttons.addWidget(self.primary); outer.addLayout(buttons)
        self.secondary.clicked.connect(controller.secondary_action)
        self.primary.clicked.connect(controller.primary_action)
        style_dialog(self)

    def refresh(self):
        c = self.controller
        text = c.presentation()
        self.heading.setText(text[0]); self.description.setText(text[1])
        self.notes.setText(c.envelope["release"].get("notes", "") if c.envelope and c.state == "available" else "")
        self.notes.setVisible(bool(self.notes.text()))
        self.progress.setVisible(c.state in {"downloading", "ready", "completed"})
        self.progress.setValue(c.percent)
        self.progress.setFormat("准备独立更新进程…" if c.state == "downloading" and c.percent == 100 else "%p%")
        self.details.setText(c.error)
        self.details.setVisible(bool(c.error))
        self.primary.setText(text[2]); self.secondary.setText(text[3])
        self.primary.setEnabled(c.state not in {"checking", "downloading", "preparing"})
        self.secondary.setEnabled(c.state != "preparing")
        self.safe.setVisible(c.state not in {"disabled", "checking", "current"})
        area = self.screen().availableGeometry()
        self.resize(min(METRICS["dialog_width"], max(280, area.width()-32)),
                    min(METRICS["dialog_height"], max(280, area.height()-32)))


class UpdateController(QObject):
    def __init__(self, window, install_root=None, config=None, startup=True):
        super().__init__(window)
        self.window = window
        self.install_root = Path(install_root or (Path(sys.executable).parent if getattr(sys, "frozen", False)
                                                  else Path(__file__).resolve().parents[2] / "AIQuoteDualSystem"))
        self.frozen = bool(getattr(sys, "frozen", False))
        self.state, self.error, self.percent = "idle", "", 0
        self.envelope = None
        self.job_path = None
        self.worker = None
        self.dialog = None
        self.pending_restart = False
        self.close_after_worker = False
        self.manual_check = False
        self._last_result = None
        try:
            self.config = config if config is not None else load_config(self.install_root)
        except Exception as error:
            self.config = {"enabled": False}; self.error = str(error)
        self._build_ui()
        if startup and self.config.get("enabled"):
            QTimer.singleShot(METRICS["startup_delay"], self.check)
        # Delayed acknowledgement occurs only after actual MainWindow creation.
        QTimer.singleShot(METRICS["health_delay"], lambda: acknowledge_startup(CLIENT_VERSION))
        self.result_timer = QTimer(self); self.result_timer.setInterval(1000)
        self.result_timer.timeout.connect(self.read_result); self.result_timer.start()
        self.read_result()

    def _build_ui(self):
        c = DIALOG_COLORS
        self.banner = QFrame(); self.banner.setObjectName("clientUpdateBanner")
        self.banner.setStyleSheet(f"QFrame#clientUpdateBanner {{background:{c['selected']}; border:1px solid {c['border']}; border-radius:6px;}}")
        row = QHBoxLayout(self.banner); row.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel(); self.label.setWordWrap(True); self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setStyleSheet(f"font-family:{FONT_FAMILY_QSS}; font-size:{BODY_PX}px; color:{c['title']}; background:transparent; border:0;")
        self.detail_button = QPushButton("查看更新"); self.detail_button.setStyleSheet(button_style("primary"))
        self.detail_button.clicked.connect(self.show_dialog)
        self.later_button = QPushButton("稍后提醒"); self.later_button.setStyleSheet(button_style("secondary"))
        self.later_button.clicked.connect(self.banner.hide)
        row.addWidget(self.label, 1); row.addWidget(self.detail_button); row.addWidget(self.later_button)
        self.banner.hide()
        original = self.window.takeCentralWidget()
        host = QWidget(); column = QVBoxLayout(host); column.setContentsMargins(0, 0, 0, 0); column.setSpacing(0)
        column.addWidget(self.banner)
        if original is not None: column.addWidget(original, 1)
        self.window.setCentralWidget(host)
        self.check_button = QPushButton("检查更新"); self.check_button.setObjectName("clientCheckUpdateButton")
        self.check_button.setStyleSheet(check_button_style())
        self.check_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_button.setAccessibleName("检查软件更新")
        self.check_button.setToolTip(f"检查软件更新 · 当前版本：{CLIENT_VERSION}")
        self.check_button.clicked.connect(lambda: self.check(manual=True))
        nav = getattr(self.window, "scheme2_nav", None)
        if nav is not None and nav.layout() is not None:
            nav.layout().insertWidget(max(0, nav.layout().count()-1), self.check_button)

    def presentation(self):
        version = self.envelope["release"]["version"] if self.envelope else ""
        return {
            "idle": ("软件更新", "点击检查是否有新版本。", "检查更新", "关闭"),
            "disabled": ("更新源尚未配置", "当前处于本地开发阶段，未启用自动下载或公网发布。", "检查更新", "关闭"),
            "checking": ("正在检查更新", "你可以关闭此窗口，继续处理报价。", "正在检查…", "后台检查"),
            "current": ("当前已是最新版本", f"当前版本：{CLIENT_VERSION}", "重新检查", "关闭"),
            "available": (f"发现新版本 {version}", f"当前版本：{CLIENT_VERSION} → {version}", "下载更新", "稍后提醒"),
            "downloading": ("正在后台下载更新", "下载期间可以收起窗口，继续处理报价。下载后不会自动安装。", "正在下载…", "取消下载"),
            "ready": ("更新已准备就绪", "更新包签名及完整性校验通过。重启前会先将当前填写、报价和图纸保存为本机恢复文件。", "保存进度并重启更新", "稍后安装"),
            "preparing": ("正在保存当前进度", "保存成功后才会关闭客户端；失败则留在当前界面。", "正在保存…", "请稍候"),
            "completed": ("更新成功", "当前版本已启动，原有配置与本地文件均已保留。", "继续使用", "关闭"),
            "rolled_back": ("更新失败，已恢复旧版本", "你可以继续使用旧版，稍后重新检查更新。", "重新检查", "继续使用旧版"),
            "error": ("更新未完成", "本次未安装新版本。当前客户端仍可继续使用。", "重新检查", "关闭"),
        }[self.state]

    def refresh(self):
        title, description, *_ = self.presentation()
        self.label.setText(title + (f" · {self.percent}%" if self.state == "downloading" else ""))
        self.label.setToolTip(description)
        self.detail_button.setText("查看更新" if self.state == "available" else "查看状态")
        self.later_button.setVisible(self.state not in {"checking", "downloading", "preparing"})
        if self.state not in {"idle", "disabled", "current", "checking"}: self.banner.show()
        if self.dialog is not None: self.dialog.refresh()

    def show_dialog(self):
        if self.dialog is None: self.dialog = UpdateDialog(self)
        self.dialog.refresh(); self.dialog.show(); self.dialog.raise_(); self.dialog.activateWindow()

    def _task(self, function, success):
        if self.worker is not None: return False
        worker = UpdateTask(function, self.window); self.worker = worker
        worker.succeeded.connect(success)
        worker.failed.connect(self.failed)
        worker.progress.connect(self.download_progress)
        def done():
            self.worker = None
            worker.deleteLater()
            if self.close_after_worker:
                self.close_after_worker = False; QTimer.singleShot(0, self.window.close)
        worker.finished.connect(done); worker.start()
        return True

    def check(self, manual=False):
        if not manual and self.state in {"completed", "rolled_back"}:
            return
        if self.worker is not None:
            if manual: self.show_dialog()
            return
        if self.state in {"ready", "preparing"}:
            if manual: self.show_dialog()
            return
        self.manual_check = manual
        if not self.config.get("enabled"):
            self.state = "disabled"; self.refresh()
            if manual: self.show_dialog()
            return
        self.state = "checking"; self.error = ""; self.refresh()
        if manual: self.show_dialog()
        self._task(lambda worker: check_release(self.config, CLIENT_VERSION), self.checked)

    def checked(self, envelope):
        self.envelope = envelope
        self.state = "available" if envelope else "current"
        self.refresh()

    def failed(self, message):
        self.error = message; self.state = "error"; self.refresh()

    def download_progress(self, now, total):
        self.percent = min(100, int(now * 100 / max(total, 1))); self.refresh()

    def start_download(self):
        if self.worker is not None or not self.envelope: return
        self.error = ""; self.percent = 0; self.state = "downloading"; self.refresh()
        def downloaded(path):
            self.job_path = Path(path); self.state = "ready"; self.percent = 100; self.refresh()
        self._task(lambda worker: download_update(self.config, self.envelope, self.install_root,
                                                  CLIENT_VERSION, worker.progress.emit,
                                                  worker.isInterruptionRequested, copy_runner=self.frozen), downloaded)

    def secondary_action(self):
        if self.state == "downloading" and self.worker:
            self.worker.requestInterruption(); self.state = "available"; self.percent = 0
        if self.dialog: self.dialog.hide()
        if self.state == "available": self.banner.hide()

    def primary_action(self):
        if self.state == "available": self.start_download()
        elif self.state == "ready": self.restart()
        elif self.state == "completed": self.dialog.hide()
        else: self.check(manual=True)

    def busy_reason(self):
        if getattr(self.window, "quote_calculation_in_progress", False): return "请等待报价计算完成后再更新。"
        if getattr(self.window, "_quote_scheme_pending_export", None): return "请先完成报价方案导出登记。"
        if getattr(self.window, "_quote_scheme_registration_busy", False): return "请先完成报价方案登记。"
        for worker in self.window.findChildren(QThread):
            try:
                if worker.isRunning(): return "请等待当前网络、图纸或保存任务完成后再更新。"
            except RuntimeError: pass
        return ""

    def restart(self):
        if not self.job_path or self.state != "ready": return
        reason = self.busy_reason()
        if not self.frozen: reason = "源码运行模式不替换现用客户端。请使用本地模拟测试或隔离打包副本验证安装。"
        if reason:
            self.error = reason; self.refresh(); return
        self.state = "preparing"; self.error = ""; self.refresh()
        # File capture is explicit, synchronous, and must succeed before close.
        try:
            import scheme2_ui
            workspace = self.job_path.parent / ("更新前进度" + scheme2_ui.ORDER_WORKSPACE_SUFFIX)
            payload = scheme2_ui._order_workspace_payload(self.window)
            scheme2_ui._write_order_workspace_file("更新前本机恢复", payload, workspace)
            job = read_json(self.job_path); job["workspace"] = str(workspace)
            atomic_json(self.job_path, job)
        except Exception as error:
            self.state = "ready"; self.error = "当前进度保存失败，未关闭客户端：" + str(error)
            self.refresh(); return
        self.window._scheme2_dirty = False
        self.pending_restart = True
        if self.dialog: self.dialog.hide()
        if not self.window.close():
            self.pending_restart = False; self.state = "ready"
            self.error = "客户端尚未退出，请先完成当前保存或处理任务。"
            self.refresh(); self.show_dialog()

    def before_close(self, event):
        if self.worker is not None:
            self.close_after_worker = True; self.worker.requestInterruption(); event.ignore(); return False
        return True

    def launch_pending(self):
        if not self.pending_restart: return
        runner = self.job_path.parent / "runner" / ENTRY
        if not runner.is_file(): raise UpdateError("独立更新程序缺失，未关闭客户端")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([str(runner), "--client-updater", str(self.job_path)],
                         cwd=str(runner.parent), creationflags=flags)
        self.pending_restart = False

    def read_result(self):
        path = cache_root(self.install_root) / "last-result.json"
        try:
            stamp = path.stat().st_mtime_ns
            if stamp == self._last_result: return
            self._last_result = stamp
            result = read_json(path)
            # Only display a result once per install; no stale success on every launch.
            if result.get("seen"): return
            if result.get("status") == "completed": self.state = "completed"; self.percent = 100
            elif result.get("status") == "rolled_back": self.state = "rolled_back"
            else: self.state = "error"
            self.error = result.get("message", ""); self.refresh()
            result["seen"] = True; atomic_json(path, result)
        except (OSError, ValueError): pass


def install_client_updates(namespace):
    cls = namespace["MainWindow"]
    if getattr(cls, "_client_updates_installed", False): return
    cls._client_updates_installed = True
    original_init, original_close = cls.__init__, cls.closeEvent
    def init(window, *args, **kwargs):
        original_init(window, *args, **kwargs)
        window.client_updates = UpdateController(window)
    def close(window, event):
        controller = getattr(window, "client_updates", None)
        if controller and not controller.before_close(event): return
        original_close(window, event)
        if controller and event.isAccepted():
            try: controller.launch_pending()
            except Exception as error:
                event.ignore(); controller.pending_restart = False; controller.state = "ready"
                controller.error = str(error); controller.refresh(); controller.show_dialog()
    cls.__init__, cls.closeEvent = init, close
