"""Independent updater process; never terminates the user's parent process."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

from client_update_core import (ENTRY, UpdateError, apply_update, atomic_json,
                                cache_root, read_json)

STARTUP_PROTOCOL = "name-login-v1"


def wait_for_parent(pid, timeout=120):
    if pid <= 0 or pid == os.getpid():
        raise UpdateError("更新进程的父进程无效")
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # Already exited.
                return
            raise UpdateError("无法确认原客户端已经退出")
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise UpdateError("原客户端仍在运行，本次未替换任何文件")
        finally:
            kernel.CloseHandle(handle)
    else:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(.1)
        raise UpdateError("原客户端仍在运行，本次未替换任何文件")


def assert_entry_unlocked(path):
    if os.name != "nt":
        return
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise UpdateError("客户端文件仍被占用，未修改程序；请关闭其他客户端后重试")
    kernel.CloseHandle(handle)


def launch_client(job, health=False):
    env = dict(os.environ)
    for name in ("AI_QUOTE_UPDATE_HEALTH_FILE", "AI_QUOTE_UPDATE_HEALTH_TOKEN", "AI_QUOTE_UPDATE_HEALTH_VERSION",
                 "AI_QUOTE_UPDATE_HEALTH_PROTOCOL"):
        env.pop(name, None)
    if health:
        env.update(AI_QUOTE_UPDATE_HEALTH_FILE=job["health_file"], AI_QUOTE_UPDATE_HEALTH_TOKEN=job["token"],
                   AI_QUOTE_UPDATE_HEALTH_VERSION=job["envelope"]["release"]["version"],
                   AI_QUOTE_UPDATE_HEALTH_PROTOCOL=STARTUP_PROTOCOL)
    args = [str(Path(job["install_root"]) / ENTRY)]
    if job.get("workspace"):
        args.append(job["workspace"])
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, cwd=job["install_root"], env=env, creationflags=flags)


def check_new_client(job, timeout=30, progress=lambda _message: None):
    path = Path(job["health_file"])
    path.unlink(missing_ok=True)
    process = launch_client(job, health=True)
    healthy = False
    try:
        deadline = time.monotonic() + timeout
        phase, waiting_stamp = None, None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                receipt = read_json(path)
                identity_matches = (receipt.get("token") == job["token"] and
                                    receipt.get("version") == job["envelope"]["release"]["version"])
                healthy = identity_matches and set(receipt) == {"token", "version"}
                if identity_matches and receipt.get("protocol") == STARTUP_PROTOCOL:
                    current = receipt.get("phase")
                    if current == "waiting_for_name":
                        # A responsive login screen may wait indefinitely for the user.
                        # A frozen screen stops its Qt heartbeat and still fails closed.
                        stamp = path.stat().st_mtime_ns
                        if phase != current or stamp != waiting_stamp:
                            deadline = time.monotonic() + timeout
                            waiting_stamp = stamp
                        if phase != current:
                            progress("请在新客户端中输入姓名，提交后检查主窗口启动")
                        phase = current
                    elif current == "starting_main_window":
                        if phase != current:
                            deadline = time.monotonic() + timeout
                            progress("正在检查主窗口启动")
                        phase = current
            except (OSError, ValueError):
                pass
            if healthy:
                # A receipt followed by immediate death is not healthy startup.
                time.sleep(.5)
                healthy = process.poll() is None
                return healthy
            time.sleep(.1)
        return False
    finally:
        if not healthy and process.poll() is None:
            # Only the process created above, never a user/other client PID.
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as error:
                raise UpdateError("新版本无法退出，停止恢复以避免损坏正在使用的文件") from error


def execute_job(job_path, progress=lambda *_: None, health_timeout=30, parent_timeout=120):
    job_path = Path(job_path).resolve()
    job = read_json(job_path)
    result_path = cache_root(job["install_root"]) / "last-result.json"
    bridge_parent = None
    try:
        wait_for_parent(int(job["parent_pid"]), parent_timeout)
        assert_entry_unlocked(Path(job["install_root"]) / ENTRY)
        if job.get("automatic_bridge_parent"):
            from client_update_bridge import chain_parent
            bridge_parent = chain_parent(job_path, job)
        job["health_file"] = str(job_path.parent / "health.json")
        atomic_json(job_path, job)
        progress(0, 100, "正在备份旧版本")
        def health(value):
            progress(0, 100, "正在检查新版本启动")
            return check_new_client(value, health_timeout, lambda message: progress(0, 100, message))
        result = apply_update(job_path,
                              health,
                              lambda now, total: progress(now, total, "正在替换程序文件"))
        if result["status"] == "rolled_back" and bridge_parent:
            from client_update_bridge import restore_original
            parent_path, parent = bridge_parent
            restore_original(parent_path, parent)
            result.update(version=parent["current_version"], automatic_bridge_parent=str(parent_path),
                          message="更新失败，已恢复升级前的原版本：" + result["message"])
        result["transaction"] = str(job_path)
        atomic_json(result_path, result)
        if result["status"] == "rolled_back":
            launch_client(bridge_parent[1] if bridge_parent else job)
        return result
    except Exception as error:
        result = {"status": "failed", "message": str(error), "transaction": str(job_path)}
        if bridge_parent and read_json(job_path).get("status") in {"prepared", "rolled_back"}:
            # Verification/backup can fail before apply_update enters its own
            # rollback block. Restore the original release in this case too.
            try:
                from client_update_bridge import restore_original
                parent_path, parent = bridge_parent
                restore_original(parent_path, parent)
                result.update(status="rolled_back", version=parent["current_version"],
                              message="更新失败，已恢复升级前的原版本：" + str(error),
                              automatic_bridge_parent=str(parent_path))
                launch_client(parent)
            except Exception as restore_error:
                result["message"] += "；原版本恢复未完成，请保留现场：" + str(restore_error)
        atomic_json(result_path, result)
        return result


def acknowledge_startup(version):
    path = os.getenv("AI_QUOTE_UPDATE_HEALTH_FILE", "")
    token = os.getenv("AI_QUOTE_UPDATE_HEALTH_TOKEN", "")
    expected = os.getenv("AI_QUOTE_UPDATE_HEALTH_VERSION", "")
    if path and token and version == expected:
        _write_startup_receipt(path, {"token": token, "version": version})


def _write_startup_receipt(path, value):
    # Windows readers briefly hold the destination without delete sharing.
    # Keep atomic replacement, retrying only this transient sharing conflict.
    for attempt in range(20):
        try:
            atomic_json(path, value)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.01)


def report_startup_phase(version, phase):
    """Progress is never a healthy receipt; only the main window can confirm it."""
    if phase not in {"waiting_for_name", "starting_main_window"}:
        raise ValueError("Unknown startup phase")
    path = os.getenv("AI_QUOTE_UPDATE_HEALTH_FILE", "")
    token = os.getenv("AI_QUOTE_UPDATE_HEALTH_TOKEN", "")
    expected = os.getenv("AI_QUOTE_UPDATE_HEALTH_VERSION", "")
    if (path and token and version == expected
            and os.getenv("AI_QUOTE_UPDATE_HEALTH_PROTOCOL") == STARTUP_PROTOCOL):
        _write_startup_receipt(path, {"token": token, "version": version,
                                     "protocol": STARTUP_PROTOCOL, "phase": phase})


def main(job_path):
    """Native progress window, running from the isolated old runtime copy."""
    from PySide6.QtCore import QThread, Signal, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton
    from dialog_style import style_dialog, button_style
    from progress_style import progress_color_style

    class Worker(QThread):
        progress = Signal(int, int, str)
        result = Signal(object)
        def run(self):
            try:
                result = execute_job(job_path, self.progress.emit)
            except Exception as error:
                result = {"status": "failed", "message": "无法执行更新：" + str(error)}
            self.result.emit(result)

    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = QFont(); font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    app.setFont(font)
    dialog = QDialog()
    dialog.setWindowTitle("安装软件更新")
    dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    layout = QVBoxLayout(dialog)
    label = QLabel("正在等待原客户端安全退出…")
    label.setWordWrap(True)
    layout.addWidget(label)
    bar = QProgressBar(); bar.setStyleSheet(progress_color_style())
    layout.addWidget(bar)
    close = QPushButton("关闭"); close.setStyleSheet(button_style("primary")); close.hide()
    layout.addWidget(close)
    worker = Worker(dialog)
    dialog.setMinimumWidth(420)
    worker.progress.connect(lambda now, total, text: (label.setText(text), bar.setMaximum(total), bar.setValue(now)))
    def complete(result):
        label.setText(result["message"])
        bar.setRange(0, 100); bar.setValue(100 if result["status"] == "completed" else 0)
        close.show()
        dialog.setProperty("updateFinished", True)
    worker.result.connect(complete)
    close.clicked.connect(dialog.accept)
    # Escape/header close cannot destroy a running worker.
    dialog.reject = lambda: QDialog.reject(dialog) if not worker.isRunning() else None
    def close_event(event):
        if worker.isRunning(): event.ignore()
        else: event.accept()
    dialog.closeEvent = close_event
    style_dialog(dialog)
    dialog.show()
    worker.start()
    return app.exec()
