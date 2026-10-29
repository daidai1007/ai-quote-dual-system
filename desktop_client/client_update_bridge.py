"""Automatic, signed intermediate release for clients with a fixed startup timer.

The intermediate release has its own version and a real progress window. Its
receipt confirms only that intermediate release. The final release still uses
the name-login startup protocol and must show its main window after login.
Nothing here changes the server, trust key, channel, or business authentication.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

from client_update_core import (ENTRY, UpdateError, atomic_json, cache_root, digest,
                                download_update, load_config, read_json, reject_links,
                                restore_backup, safe_member, update_lock,
                                verify_manifest, version_tuple)

RESOURCE = "_internal/automatic-update/bridge.json"
POINTER = "automatic-bridge-active.json"
TRUST_FIELDS = ("enabled", "manifest_url", "public_key", "channel", "lan_http_origin")


def clean_environment():
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("AI_QUOTE_UPDATE_HEALTH_"):
            env.pop(key)
    return env


def configuration(bridge_version, final_envelope, config):
    final = verify_manifest(final_envelope, config)
    if version_tuple(bridge_version) >= version_tuple(final["version"]):
        raise UpdateError("过渡版本必须低于最终版本")
    return {"schema": 1, "bridge_version": bridge_version, "final_envelope": final_envelope}


def transaction_path(path, install):
    path = Path(path).absolute()
    reject_links(path)
    if (path.name != "job.json" or path.parent.parent.resolve() != cache_root(install).resolve()
            or not re.fullmatch(r"[a-f0-9]{32}", path.parent.name)):
        raise UpdateError("自动兼容升级事务路径无效")
    return path


def trusted_job(path, install, config):
    reject_links(install)
    path = transaction_path(path, install)
    job = read_json(path)
    if Path(job["install_root"]).resolve() != Path(install).resolve():
        raise UpdateError("自动兼容升级安装目录不一致")
    if any(job["config"].get(key) != config.get(key) for key in TRUST_FIELDS):
        raise UpdateError("自动兼容升级的更新源或公钥发生变化")
    release = verify_manifest(job["envelope"], config)
    package = path.parent / "package.zip"
    reject_links(package)
    if package.stat().st_size != release["size"] or digest(package) != release["sha256"]:
        raise UpdateError("自动兼容升级缓存包校验失败")
    return path, job


def package_entry_hash(path):
    with zipfile.ZipFile(Path(path).parent / "package.zip") as archive:
        entries = [item for item in archive.infolist() if item.filename == ENTRY]
        if len(entries) != 1:
            raise UpdateError("过渡程序包主程序无效")
        with archive.open(entries[0]) as stream:
            sha = hashlib.sha256()
            while block := stream.read(1024 * 1024):
                sha.update(block)
            return sha.hexdigest()


def validate_backups(path, job):
    """Validate ALL rollback inputs before allowing the first restore mutation."""
    with zipfile.ZipFile(Path(path).parent / "package.zip") as archive:
        names = [safe_member(item.filename) for item in archive.infolist() if not item.is_dir()]
    records = job.get("backup_files", [])
    if (len(names) != len(set(name.casefold() for name in names))
            or len(records) != len(names) or {r["path"] for r in records} != set(names)):
        raise UpdateError("原版本备份记录不完整")
    entry_record = next((record for record in records if record["path"] == ENTRY), None)
    if not entry_record or entry_record.get("existed") is not True or entry_record.get("sha256") != job["old_exe_sha256"]:
        raise UpdateError("原版本主程序备份记录不一致")
    for record in records:
        safe_member(record["path"])
        if type(record["existed"]) is not bool:
            raise UpdateError("原版本备份记录无效")
        if record["existed"]:
            backup = Path(path).parent / "backup" / record["path"]
            reject_links(backup)
            if digest(backup) != record["sha256"]:
                raise UpdateError("原版本备份校验失败，请保留现场")


def chain_parent(child_path, child):
    """Bind the continuation to the signed bridge package, not arbitrary metadata."""
    install = Path(child["install_root"])
    config = load_config(install)
    transaction_path(child_path, install)
    parent_path, parent = trusted_job(child["automatic_bridge_parent"], install, config)
    if parent["status"] != "completed":
        raise UpdateError("第一步兼容升级尚未完成")
    with zipfile.ZipFile(parent_path.parent / "package.zip") as archive:
        raw = archive.read(RESOURCE)
    if len(raw) > 65536:
        raise UpdateError("自动兼容升级配置过大")
    import json
    spec = json.loads(raw.decode("utf-8"))
    validated = configuration(spec["bridge_version"], spec["final_envelope"], config)
    if (spec.get("schema") != 1
            or parent["envelope"]["release"]["version"] != spec["bridge_version"]
            or child["current_version"] != spec["bridge_version"]
            or child["envelope"] != validated["final_envelope"]
            or child["old_exe_sha256"] != package_entry_hash(parent_path)):
        raise UpdateError("自动兼容升级的两步签名记录不一致")
    if any(child["config"].get(key) != config.get(key) for key in TRUST_FIELDS):
        raise UpdateError("最终升级的更新源或公钥发生变化")
    validate_backups(parent_path, parent)
    return parent_path, parent


def restore_original(parent_path, parent):
    install = Path(parent["install_root"])
    with update_lock(install):
        # The final updater has already rolled back its own changes. Do not
        # overwrite an unrelated/currently successful installation.
        if digest(install / ENTRY) != package_entry_hash(parent_path):
            raise UpdateError("当前程序不是过渡版本，已停止恢复以保留现场")
        validate_backups(parent_path, parent)
        restore_backup(parent_path, parent)


def begin(install, spec, health_file, token, version):
    reject_links(install)
    install = Path(install).resolve()
    config = load_config(install)
    validated = configuration(spec["bridge_version"], spec["final_envelope"], config)
    if spec.get("schema") != 1 or version != spec["bridge_version"]:
        raise UpdateError("自动兼容升级版本无效")
    if health_file:
        health = Path(health_file).absolute()
        reject_links(health)
        if health.name != "health.json":
            raise UpdateError("自动兼容升级启动回执路径无效")
        parent_path = health.parent / "job.json"
    else:
        pointer = read_json(cache_root(install) / POINTER)
        parent_path = pointer["parent"]
    parent_path, parent = trusted_job(parent_path, install, config)
    if (parent["status"] not in {"checking", "completed"}
            or parent["envelope"]["release"]["version"] != version
            or (health_file and parent["token"] != token)
            or digest(install / ENTRY) != package_entry_hash(parent_path)):
        raise UpdateError("自动兼容升级的启动身份不一致")
    # The signed package must contain precisely this continuation configuration.
    import json
    with zipfile.ZipFile(parent_path.parent / "package.zip") as archive:
        if json.loads(archive.read(RESOURCE).decode("utf-8")) != spec:
            raise UpdateError("自动兼容升级配置与签名包不一致")
    validate_backups(parent_path, parent)
    runner = parent_path.parent / "runner" / ENTRY
    reject_links(runner)
    if digest(runner) != parent["old_exe_sha256"]:
        raise UpdateError("原更新器恢复副本校验失败")
    state = parent_path.parent / "automatic-bridge-state.json"
    if not state.exists():
        atomic_json(state, {"status": "waiting_for_first_step", "parent": str(parent_path),
                            "target_version": validated["final_envelope"]["release"]["version"]})
    atomic_json(cache_root(install) / POINTER, {"parent": str(parent_path)})
    return {"install": install, "config": config, "spec": validated,
            "parent_path": parent_path, "state": state}


def wait_for_first_step(context, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = read_json(context["parent_path"])
        if job["status"] == "completed":
            if read_json(context["state"]).get("child"):
                return  # A persisted child was only created after step one finished.
            try:
                result = read_json(cache_root(context["install"]) / "last-result.json")
                if result.get("transaction") == str(context["parent_path"]) and result.get("status") == "completed":
                    # The final application's normal updater must not show an
                    # intermediate success banner as if its own update finished.
                    atomic_json(cache_root(context["install"]) / "last-result.json",
                                dict(result, seen=True, automatic_bridge_intermediate=True))
                    return
            except (OSError, ValueError):
                pass
        elif job["status"] != "checking":
            raise UpdateError("第一步兼容升级未成功，请保留现场")
        time.sleep(.1)
    raise UpdateError("第一步兼容升级尚未结束，请保留现场")


def prepare_continuation(context, progress=lambda *_: None):
    wait_for_first_step(context)
    state = read_json(context["state"])
    if state.get("child"):
        path, job = trusted_job(state["child"], context["install"], context["config"])
        if job["status"] not in {"prepared", "applying", "checking", "rollback_failed"}:
            raise UpdateError("最终更新已有处理结果，请保留现场")
    else:
        path = download_update(context["config"], context["spec"]["final_envelope"],
                               context["install"], context["spec"]["bridge_version"], progress)
        job = read_json(path)
    job["automatic_bridge_parent"] = str(context["parent_path"])
    job["parent_pid"] = os.getpid()
    job["workspace"] = read_json(context["parent_path"]).get("workspace", "")
    chain_parent(path, job)
    atomic_json(path, job)
    atomic_json(context["state"], dict(state, status="final_prepared", child=str(path)))
    return path


def launch_continuation(path):
    path = Path(path)
    runner = path.parent / "runner" / ENTRY
    reject_links(runner)
    job = read_json(path)
    if digest(runner) != job["old_exe_sha256"]:
        raise UpdateError("新版更新器副本校验失败")
    return subprocess.Popen([str(runner), "--client-updater", str(path)], cwd=str(runner.parent),
                            env=clean_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def queue_original_restore(context):
    """Reuse the original updater's supported interrupted-transaction recovery.

    Its isolated runtime already exists before our first receipt. Thus a failed
    download/disk-full event does not require another download or executable.
    The bridge exits naturally; the original updater waits for that exact PID.
    """
    path, job = trusted_job(context["parent_path"], context["install"], context["config"])
    if job["status"] != "completed" or digest(context["install"] / ENTRY) != package_entry_hash(path):
        raise UpdateError("无法安全恢复原版本，请保留现场")
    state = read_json(context["state"])
    if state.get("child"):
        child_path = transaction_path(state["child"], context["install"])
        if read_json(child_path)["status"] != "prepared":
            raise UpdateError("最终更新已开始，请保留更新事务及备份")
    validate_backups(path, job)
    runner = path.parent / "runner" / ENTRY
    reject_links(runner)
    if digest(runner) != job["old_exe_sha256"]:
        raise UpdateError("原更新器恢复副本校验失败")
    original = dict(job)
    with update_lock(context["install"]):
        job["status"] = "checking"
        job["parent_pid"] = os.getpid()
        atomic_json(path, job)
        try:
            process = subprocess.Popen([str(runner), "--client-updater", str(path)], cwd=str(runner.parent),
                env=clean_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            atomic_json(path, original)
            raise
    atomic_json(context["state"], dict(state, status="restoring_original"))
    return process


def run_if_configured():
    if not getattr(sys, "frozen", False):
        return False
    install = Path(sys.executable).parent
    resource = install / RESOURCE
    if not resource.is_file():
        return False
    spec = read_json(resource)
    from quote_scheme_center import CLIENT_VERSION
    if version_tuple(CLIENT_VERSION) > version_tuple(spec["bridge_version"]):
        return False  # An obsolete bridge resource cannot intercept a later app.
    context = begin(install, spec, os.getenv("AI_QUOTE_UPDATE_HEALTH_FILE", ""),
                    os.getenv("AI_QUOTE_UPDATE_HEALTH_TOKEN", ""), CLIENT_VERSION)
    run_window(context)
    return True


def run_window(context):
    from PySide6.QtCore import QThread, QTimer, Signal, Qt
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton
    from client_update_runner import acknowledge_startup
    from dialog_style import dialog_style_sheet, button_style
    from progress_style import progress_color_style

    class Worker(QThread):
        progress = Signal(int, int)
        finished_update = Signal(str)

        def run(self):
            try:
                path = prepare_continuation(context, self.progress.emit)
                launch_continuation(path)
                self.finished_update.emit("")
            except Exception as error:
                state = read_json(context["state"])
                atomic_json(context["state"], dict(state, error=str(error)))
                try:
                    queue_original_restore(context)
                    self.finished_update.emit("")
                except Exception as restore_error:
                    self.finished_update.emit(str(error) + "\n" + str(restore_error))

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = QMainWindow()
    window._bridge_allow_close = False
    def close_event(event):
        if window._bridge_allow_close:
            event.accept()
        else:
            event.ignore()
    window.closeEvent = close_event
    window.setWindowTitle("AI 双报价系统 · 自动兼容升级")
    window.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    content = QWidget(); layout = QVBoxLayout(content); window.setCentralWidget(content)
    content.setStyleSheet(dialog_style_sheet())
    label = QLabel("正在自动完成兼容升级，随后请输入姓名。\n请保持此电脑开机联网。")
    label.setWordWrap(True); layout.addWidget(label)
    bar = QProgressBar(); bar.setStyleSheet(progress_color_style()); bar.setRange(0, 0); layout.addWidget(bar)
    close = QPushButton("关闭"); close.setStyleSheet(button_style("primary")); close.hide(); layout.addWidget(close)
    worker = Worker(window)
    worker.progress.connect(lambda now, total: (bar.setMaximum(total), bar.setValue(now)))
    def complete(error):
        window._bridge_allow_close = True
        if error:
            label.setText("兼容升级未完成，请保留备份和现场。\n" + error)
            close.show()
        else:
            window.close(); app.quit()
    worker.finished_update.connect(complete)
    close.clicked.connect(window.close)
    window.resize(520, 180); window.show()
    # This receipt belongs to the INTERMEDIATE version, never the final version.
    # Only emit it after the bridge main window has run its Qt event loop.
    def ready():
        acknowledge_startup(context["spec"]["bridge_version"])
        worker.start()
    QTimer.singleShot(2500, ready)
    app.exec()
    if worker.isRunning():
        worker.wait()
