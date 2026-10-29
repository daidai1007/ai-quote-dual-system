"""Signed two-step updates, genuine old updater timing, real offline name UI.

All program files, keys, HTTP servers, process launches and settings are fixtures.
No production DB/API request, frozen-client build, or installed-client write.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "tests"))
from client_update_core import (ENTRY, UpdateError, apply_update, atomic_json,
                                cache_root, digest, download_update, read_json)
import client_update_bridge as bridge
import client_update_runner as runner
from make_client_update import build
from prepare_automatic_update_bridge import prepare
from update_test_support import LocalSource

OLD, BRIDGE, FINAL = "2026.10.22.01", "2026.10.22.02", "2026.10.23.02"


@contextmanager
def retained_process_fixture(scenario):
    root = ROOT / "outputs/automatic-update-bridge-tests" / (scenario + "-" + uuid.uuid4().hex[:12])
    root.mkdir(parents=True, exist_ok=False)
    print("PROCESS_FIXTURE=" + str(root), flush=True)
    yield str(root)


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.source = LocalSource(root)
        self.install, self.config = self.source.install, self.source.config
        atomic_json(self.install / "update_config.json", self.config)
        self.before = self.snapshot()
        final = self.root / "final-source"
        shutil.copytree(self.source.source, final)
        (final / ENTRY).write_bytes(b"synthetic-final-program")
        (final / "_internal/final-only.txt").write_bytes(b"synthetic-final-library")
        self.final = build(final, self.source.web / "final", self.source.key, FINAL,
                           self.source.url + "/final", "Synthetic final release")
        self.spec = bridge.configuration(BRIDGE, self.final, self.config)
        (self.source.source / ENTRY).write_bytes(b"synthetic-intermediate-program")
        atomic_json(self.source.source / bridge.RESOURCE, self.spec)
        self.envelope = build(self.source.source, self.source.web / "bridge", self.source.key, BRIDGE,
                              self.source.url + "/bridge", "Synthetic intermediate release")
        self.path = download_update(self.config, self.envelope, self.install, OLD)
        self.context = None

    def snapshot(self):
        return {p.relative_to(self.install).as_posix(): digest(p) for p in self.install.rglob("*") if p.is_file()}

    def apply_bridge(self):
        def health(job):
            self.context = bridge.begin(self.install, self.spec, str(self.path.parent / "health.json"), job["token"], BRIDGE)
            return True
        result = apply_update(self.path, health)
        result["transaction"] = str(self.path)
        atomic_json(cache_root(self.install) / "last-result.json", result)
        return self.context

    def close(self):
        self.source.close()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="automatic-bridge-")
        self.profile = patch.dict(os.environ, LOCALAPPDATA=self.temp.name,
                                  AI_QUOTE_UPDATE_CONFIG="", QT_QPA_PLATFORM="offscreen")
        self.profile.start()
        self.fixture = Fixture(self.temp.name)

    def tearDown(self):
        self.fixture.close(); self.profile.stop(); self.temp.cleanup()

    def run_final(self, healthy=True):
        fixture = self.fixture
        context = fixture.apply_bridge()
        path = bridge.prepare_continuation(context)
        self.assertTrue(read_json(cache_root(fixture.install) / "last-result.json")["seen"])
        with patch.object(runner, "wait_for_parent"), \
                patch.object(runner, "check_new_client", return_value=healthy), \
                patch.object(runner, "launch_client") as launch:
            result = runner.execute_job(path)
        return result, path, launch

    def test_success_keeps_the_final_receipt_separate_and_preserves_all_private_files(self):
        result, path, launch = self.run_final()
        self.assertEqual((result["status"], result["version"]), ("completed", FINAL))
        self.assertEqual((self.fixture.install / ENTRY).read_bytes(), b"synthetic-final-program")
        self.assertEqual(read_json(self.fixture.path)["status"], "completed")
        launch.assert_not_called()
        for name, sha in self.fixture.before.items():
            if name == ENTRY or name.startswith("_internal/"): continue
            self.assertEqual(digest(self.fixture.install / name), sha, name)
        self.assertEqual(read_json(path)["workspace"], "")

    def test_cancelled_or_failed_final_startup_restores_original_instead_of_only_bridge(self):
        result, path, launch = self.run_final(False)
        self.assertEqual((result["status"], result["version"]), ("rolled_back", OLD))
        self.assertEqual(self.fixture.snapshot(), self.fixture.before)
        self.assertEqual(read_json(self.fixture.path)["status"], "rolled_back")
        self.assertEqual(launch.call_args.args[0]["current_version"], OLD)

    def test_invalid_final_cached_zip_also_restores_original(self):
        fixture = self.fixture; context = fixture.apply_bridge()
        path = bridge.prepare_continuation(context)
        (path.parent / "package.zip").write_bytes(b"tampered")
        with patch.object(runner, "wait_for_parent"), patch.object(runner, "launch_client"):
            result = runner.execute_job(path)
        self.assertEqual((result["status"], result["version"]), ("rolled_back", OLD))
        self.assertEqual(fixture.snapshot(), fixture.before)

    def test_download_failure_queues_original_updater_recovery_without_new_download(self):
        fixture = self.fixture; context = fixture.apply_bridge()
        (fixture.source.web / "final" / Path(fixture.final["release"]["url"]).name).write_bytes(b"tampered")
        with self.assertRaises(UpdateError): bridge.prepare_continuation(context)
        with patch.object(bridge.subprocess, "Popen") as launch:
            bridge.queue_original_restore(context)
        job = read_json(fixture.path)
        self.assertEqual(job["status"], "checking")
        self.assertEqual(job["parent_pid"], os.getpid())
        self.assertEqual(Path(launch.call_args.args[0][0]), fixture.path.parent / "runner" / ENTRY)
        self.assertEqual(launch.call_args.kwargs["env"].get("AI_QUOTE_UPDATE_HEALTH_FILE"), None)
        result = apply_update(fixture.path, lambda _: self.fail("Recovery must not start a new release"))
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(fixture.snapshot(), fixture.before)

    def test_recovery_launch_failure_keeps_journal_and_client_unchanged(self):
        fixture = self.fixture; context = fixture.apply_bridge(); before = fixture.snapshot()
        journal = read_json(fixture.path)
        with patch.object(bridge.subprocess, "Popen", side_effect=OSError("synthetic launch failure")):
            with self.assertRaises(OSError): bridge.queue_original_restore(context)
        self.assertEqual(read_json(fixture.path), journal)
        self.assertEqual(fixture.snapshot(), before)

    def test_wrong_health_token_rejected_before_bridge_receipt(self):
        fixture = self.fixture
        def health(job):
            with self.assertRaisesRegex(UpdateError, "启动身份"):
                bridge.begin(fixture.install, fixture.spec, str(fixture.path.parent / "health.json"), "wrong", BRIDGE)
            self.assertFalse((fixture.path.parent / "health.json").exists())
            return False
        result = apply_update(fixture.path, health)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(fixture.snapshot(), fixture.before)

    def test_corrupt_original_backup_is_rejected_before_any_original_restore(self):
        fixture = self.fixture; context = fixture.apply_bridge()
        path = bridge.prepare_continuation(context)
        (fixture.path.parent / "backup" / ENTRY).write_bytes(b"tampered original")
        before = fixture.snapshot()
        with patch.object(runner, "wait_for_parent"), patch.object(runner, "launch_client") as launch:
            result = runner.execute_job(path)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(fixture.snapshot(), before); launch.assert_not_called()

    def test_final_target_cannot_be_changed_by_editing_child_job(self):
        fixture = self.fixture; context = fixture.apply_bridge()
        path = bridge.prepare_continuation(context); job = read_json(path)
        job["envelope"]["release"]["version"] = "2026.10.24.01"; atomic_json(path, job)
        before = fixture.snapshot()
        with patch.object(runner, "wait_for_parent"), patch.object(runner, "launch_client") as launch:
            result = runner.execute_job(path)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(fixture.snapshot(), before); launch.assert_not_called()

    def test_unrelated_installation_and_foreign_transaction_are_not_restored(self):
        fixture = self.fixture; context = fixture.apply_bridge()
        path = bridge.prepare_continuation(context); job = read_json(path)
        job["automatic_bridge_parent"] = str(Path(self.temp.name) / "job.json")
        with self.assertRaisesRegex(UpdateError, "事务路径"): bridge.chain_parent(path, job)
        (fixture.install / ENTRY).write_bytes(b"another successful installation")
        before = fixture.snapshot()
        with self.assertRaisesRegex(UpdateError, "不是过渡版本"):
            bridge.restore_original(fixture.path, read_json(fixture.path))
        self.assertEqual(fixture.snapshot(), before)

    def test_restart_resumes_existing_prepared_transaction_and_workspace(self):
        fixture = self.fixture; context = fixture.apply_bridge()
        parent = read_json(fixture.path); parent["workspace"] = "synthetic-private-progress.aiquote"
        atomic_json(fixture.path, parent)
        child = bridge.prepare_continuation(context)
        resumed = bridge.begin(fixture.install, fixture.spec, "", "", BRIDGE)
        self.assertEqual(bridge.prepare_continuation(resumed), child)
        self.assertEqual(read_json(child)["workspace"], parent["workspace"])

    def test_same_or_lower_final_version_and_replaced_public_key_are_rejected(self):
        with self.assertRaises(UpdateError): bridge.configuration(FINAL, self.fixture.final, self.fixture.config)
        config = dict(self.fixture.config, public_key="A" * 44)
        with self.assertRaises(UpdateError): bridge.configuration(BRIDGE, self.fixture.final, config)

    def test_public_configuration_contains_no_private_config_and_will_not_overwrite(self):
        fixture = self.fixture
        output = Path(self.temp.name) / "public/bridge.json"
        manifest = fixture.source.web / "final/manifest.json"
        package = manifest.parent / Path(fixture.final["release"]["url"]).name
        spec = prepare(manifest, package, fixture.install / "update_config.json", BRIDGE, output)
        self.assertEqual(set(spec), {"schema", "bridge_version", "final_envelope"})
        with self.assertRaises(ValueError): prepare(manifest, package, fixture.install / "update_config.json", BRIDGE, output)


class LegacySubprocessTests(unittest.TestCase):
    """The unchanged old algorithm really sees only its fixed 30-second receipt."""
    def scenario(self, scenario):
        with retained_process_fixture(scenario) as temp:
            root = Path(temp)
            with patch.dict(os.environ, LOCALAPPDATA=temp, AI_QUOTE_UPDATE_CONFIG="", QT_QPA_PLATFORM="offscreen",
                            AI_QUOTE_BRIDGE_TEST_ROOT=temp):
                fixture = Fixture(root)
                old_source = subprocess.check_output(["git", "show",
                    "42cab3851ad39208d3a36d80adee1f6a68614497:desktop_client/client_update_runner.py"], cwd=ROOT)
                source_path = root / "old_runner.py"; source_path.write_bytes(old_source)
                spec = importlib.util.spec_from_file_location("fixture_original_runner", source_path)
                old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
                parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.1)"],
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                job = read_json(fixture.path); job["parent_pid"] = parent.pid; atomic_json(fixture.path, job)
                child = None
                log = (root / "probe.log").open("wb")
                def launch(job, health=False):
                    nonlocal child
                    env = bridge.clean_environment()
                    if health:
                        env.update(AI_QUOTE_UPDATE_HEALTH_FILE=job["health_file"],
                            AI_QUOTE_UPDATE_HEALTH_TOKEN=job["token"], AI_QUOTE_UPDATE_HEALTH_VERSION=BRIDGE)
                    self.assertNotIn("AI_QUOTE_UPDATE_HEALTH_PROTOCOL", env)
                    child = subprocess.Popen([sys.executable, str(ROOT / "tests/automatic_bridge_probe.py"),
                        "bridge" if health else "original", str(fixture.path), scenario], env=env,
                        stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    return child
                began = time.monotonic()
                try:
                    with patch.object(old, "launch_client", side_effect=launch):
                        first = old.execute_job(fixture.path)  # Actual original default: 30 seconds.
                    self.assertEqual(first["status"], "completed", (first, (root / "probe.log").read_text(errors="replace")))
                    self.assertLess(time.monotonic() - began, 30)
                    deadline = time.monotonic() + 75
                    pending_seen = False
                    result_path = root / "probe-updater-result.json"
                    while not result_path.exists() and time.monotonic() < deadline:
                        waiting = root / "probe-name-wait.json"
                        if (not pending_seen and waiting.exists()
                                and time.monotonic() - read_json(waiting)["monotonic"] > 31
                                and not (root / "probe-name-action.json").exists()):
                            self.assertFalse((root / "probe-main-visible.json").exists())
                            state = read_json(fixture.path.parent / "automatic-bridge-state.json")
                            receipt = read_json(Path(state["child"]).parent / "health.json")
                            self.assertEqual(receipt["phase"], "waiting_for_name")
                            self.assertNotEqual(set(receipt), {"token", "version"})
                            pending_seen = True
                        time.sleep(.1)
                    self.assertTrue(result_path.exists(), (root / "probe.log").read_text(errors="replace"))
                    result = read_json(result_path)
                    expected = "completed" if scenario == "success" else "rolled_back"
                    self.assertEqual(result["status"], expected, (result, (root / "probe.log").read_text(errors="replace")))
                    self.assertTrue(pending_seen, ("Did not observe actual waiting longer than old 30-second deadline", result,
                                                  (root / "probe.log").read_text(errors="replace")))
                    wait = read_json(root / "probe-name-wait.json")
                    action = read_json(root / "probe-name-action.json")
                    self.assertGreater(action["monotonic"] - wait["monotonic"], 35)
                    self.assertFalse(wait["session_exists"])
                    if scenario == "success":
                        main = read_json(root / "probe-main-visible.json")
                        self.assertLess(main["monotonic"] - action["monotonic"], 30)
                        state = read_json(fixture.path.parent / "automatic-bridge-state.json")
                        final_job = read_json(state["child"])
                        self.assertEqual(read_json(Path(final_job["health_file"])), {"token": final_job["token"], "version": FINAL})
                    else:
                        self.assertEqual(fixture.snapshot(), fixture.before)
                        self.assertEqual(result["version"], OLD)
                        until = time.monotonic() + 5
                        while not (root / "probe-original-restarted.json").exists() and time.monotonic() < until:
                            time.sleep(.1)
                        self.assertTrue((root / "probe-original-restarted.json").exists())
                    print(json.dumps({"scenario": scenario, "old_runner_source_sha256": hashlib.sha256(old_source).hexdigest(),
                        "old_timeout_seconds": 30, "actual_name_wait_seconds": action["monotonic"] - wait["monotonic"],
                        "status": result["status"], "source_process_fixture": True, "frozen_exe_tested": False}, ensure_ascii=False), flush=True)
                finally:
                    (root / "stop").touch()
                    parent.wait(timeout=10)
                    if child is not None:
                        child.wait(timeout=45)
                    # All owned probes must leave before closing their log or
                    # server. Failed integration fixtures remain on disk.
                    for role in ("client", "updater", "original"):
                        until = time.monotonic() + 15
                        while (root / ("probe-" + role + "-started.json")).exists() and not (root / ("probe-" + role + "-exited.json")).exists() and time.monotonic() < until:
                            time.sleep(.1)
                    log.close(); fixture.close()

    def test_actual_old_30_seconds_then_35_seconds_name_wait_and_real_main_window(self):
        self.scenario("success")

    def test_actual_old_30_seconds_then_35_seconds_wait_cancel_restores_all_original_files(self):
        self.scenario("cancel")


if __name__ == "__main__":
    unittest.main(verbosity=2)
