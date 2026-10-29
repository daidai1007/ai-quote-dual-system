"""Source-only subprocess fixture. Never starts the installed business EXE."""
from pathlib import Path
import os
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("AI_QUOTE_V3_CORE_ROOT", str(ROOT.parent / "AIQuoteDualSystem/_internal/v3_core"))
os.environ["AI_QUOTE_API_URL"] = "http://127.0.0.1:9/api/quotes/calculate-dual"
os.environ["AI_QUOTE_API_KEY"] = "synthetic-only"
import client_update_bridge as bridge
import client_update_runner as runner
from client_update_core import ENTRY, atomic_json, read_json

MODE, JOB, SCENARIO = sys.argv[1:4]
JOB = Path(JOB)
TEST = Path(os.environ["AI_QUOTE_BRIDGE_TEST_ROOT"])
assert TEST in JOB.parents


def record(name, **value):
    atomic_json(TEST / ("probe-" + name + ".json"), dict(value, pid=os.getpid(), monotonic=time.monotonic()))


def launch_probe(args, **kwargs):
    # Retain the real launcher's path/hash checks and process environment; only
    # replace the synthetic fixture's non-executable file with this source probe.
    path = Path(args[0])
    assert TEST in path.parents and path.name == ENTRY
    mode = "updater" if len(args) == 3 and args[1] == "--client-updater" else (
        "client" if kwargs.get("env", {}).get("AI_QUOTE_UPDATE_HEALTH_FILE") else "original")
    job = args[2] if mode == "updater" else str(JOB)
    with (TEST / ("probe-" + mode + ".log")).open("ab") as log:
        kwargs.update(stdout=log, stderr=log)
        process = ORIGINAL_POPEN([sys.executable, str(Path(__file__)), mode, job, SCENARIO], **kwargs)
    CHILDREN.append(process)
    return process


ORIGINAL_POPEN = subprocess.Popen
CHILDREN = []
record(MODE + "-started")
if MODE == "bridge":
    job = read_json(JOB)
    spec = read_json(Path(job["install_root"]) / bridge.RESOURCE)
    context = bridge.begin(job["install_root"], spec, os.environ["AI_QUOTE_UPDATE_HEALTH_FILE"],
                           os.environ["AI_QUOTE_UPDATE_HEALTH_TOKEN"], spec["bridge_version"])
    with patch.object(subprocess, "Popen", side_effect=launch_probe):
        bridge.run_window(context)
elif MODE == "updater":
    with patch.object(subprocess, "Popen", side_effect=launch_probe):
        result = runner.execute_job(JOB)
    atomic_json(TEST / "probe-updater-result.json", result)
    record("updater-child-results", children=[dict(pid=p.pid, returncode=p.poll()) for p in CHILDREN])
elif MODE == "original":
    record("original-restarted", install_root=read_json(JOB)["install_root"])
elif MODE == "client":
    from PySide6.QtCore import QSettings, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialog
    import name_login as login
    import quote_scheme_center as centre

    # This subprocess simulates the signed fixture's final release, which can
    # predate the source workbench version being built today.
    centre.CLIENT_VERSION = read_json(JOB)["envelope"]["release"]["version"]
    # Bind before fixtures load client_update_ui's imported version constant.
    import v3_launcher
    from verify_name_login_endpoint import LoginServer

    disabled = TEST / "disabled-updates.json"
    atomic_json(disabled, {})
    os.environ["AI_QUOTE_UPDATE_CONFIG"] = str(disabled)
    os.environ["AI_QUOTE_ORDER_CACHE_ROOT"] = str(TEST / "order-cache")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(TEST / "settings"))
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    namespace = v3_launcher.load_v3_namespace()
    namespace["MainWindow"].load_catalogs = lambda self: None
    namespace["_name_login_core_main"] = lambda: namespace["MainWindow"]()
    original_exec = login.NameLoginDialog.exec
    def enter(dialog):
        record("name-wait", session_exists=login.session() is not None)
        def action():
            record("name-action", scenario=SCENARIO)
            if SCENARIO == "cancel":
                dialog.reject()
            else:
                dialog.name.setText("离线合成测试人员"); dialog.enter.click()
        timer = QTimer(dialog); timer.setSingleShot(True)
        timer.setTimerType(Qt.TimerType.PreciseTimer); timer.timeout.connect(action); timer.start(35500)
        return original_exec(dialog)

    server = LoginServer()
    with server:
        namespace["API_URL"] = server.base + "/api/quotes/calculate-dual"
        namespace["_name_connection_headers"] = lambda: {"X-AI-Quote-Key": "synthetic-only"}
        with patch.object(login.NameLoginDialog, "exec", enter), \
                patch.object(centre.QuoteSchemeWorker, "run", lambda worker: worker.succeeded.emit(dict(items=[], total=0))), \
                patch("urllib.request.urlopen", side_effect=server.open_local):
            window = namespace["main"]()
            if window is not None:
                window.show()
                record("main-visible", scope=window.name_scope_label.text())
                stop = QTimer()
                def stopped():
                    if (TEST / "stop").exists():
                        window._quote_scheme_id = ""; window._scheme2_dirty = False
                        window._quote_scheme_save_timer.stop(); window.close(); app.quit()
                stop.timeout.connect(stopped); stop.start(100)
                app.exec()
                record("main-closed")
else:
    raise AssertionError(MODE)
record(MODE + "-exited")
