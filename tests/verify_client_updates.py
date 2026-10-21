"""Local HTTP + signed ZIP + real Windows processes; no production writes."""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from update_test_support import LocalSource, ROOT
from client_update_core import (ENTRY, UpdateError, Cancelled, apply_update, atomic_json,
                                check_release, digest, download_update, load_config,
                                read_json, safe_member, update_lock, validate_url, version_tuple)
import client_update_core as core
import client_update_runner as runner


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quote-update-tests-")
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "profile")})
        self.env.start(); self.addCleanup(self.temp.cleanup); self.addCleanup(self.env.stop)
        self.fixture = LocalSource(self.root)
        self.addCleanup(self.fixture.close)

    def prepared(self, **kwargs):
        return download_update(self.fixture.config, self.fixture.envelope, self.fixture.install,
                               "2026.10.20.04", copy_runner=False, **kwargs)

    def test_default_disabled_never_requests_network(self):
        self.assertEqual(load_config(self.root), {"enabled": False})
        with patch.object(core, "open_url", side_effect=AssertionError("No network allowed")):
            self.assertIsNone(check_release({"enabled": False}, "2026.10.20.04"))

    def test_signed_loopback_manifest_and_numerical_version(self):
        self.assertEqual(check_release(self.fixture.config, "2026.10.20.04"), self.fixture.envelope)
        self.assertIsNone(check_release(self.fixture.config, "2026.10.20.05"))
        self.assertIsNone(check_release(self.fixture.config, "2026.10.20.10"))
        self.assertGreater(version_tuple("2026.10.20.10"), version_tuple("2026.10.20.9"))
        for value in ("1.2.3", "1.2.3.4.5", "x", "-1.2.3.4"):
            with self.assertRaises(UpdateError): version_tuple(value)

    def test_signature_and_trusted_key_cannot_be_replaced_by_server(self):
        bad = deepcopy(self.fixture.envelope); bad["release"]["notes"] = "tampered"
        atomic_json(self.fixture.web / "manifest.json", bad)
        with self.assertRaises(UpdateError): check_release(self.fixture.config, "2026.10.20.04")
        config = dict(self.fixture.config, public_key="A" * 44)
        with self.assertRaises(UpdateError): core.verify_manifest(self.fixture.envelope, config)

    def test_bad_channel_and_product_rejected(self):
        for change in ({"channel": "public"}, {"product": "Other"}, {"size": -1}, {"size": core.MAX_PACKAGE + 1}):
            envelope = self.fixture.resign(dict(self.fixture.envelope["release"], **change))
            with self.assertRaises(UpdateError): core.verify_manifest(envelope, self.fixture.config)

    def test_only_https_or_loopback_and_same_origin(self):
        for url in ("http://example.org/x", "file:///etc/passwd", "http://user:pw@127.0.0.1/x", "ftp://127.0.0.1/x"):
            with self.assertRaises(UpdateError): validate_url(url)
        validate_url("https://updates.example.org/manifest.json")
        with self.assertRaises(UpdateError): validate_url("https://other.example.org/pkg.zip", "https://updates.example.org/m.json")
        with self.assertRaises(UpdateError): core._SafeRedirect().redirect_request(
            core.urllib.request.Request(self.fixture.url), None, 302, "", {}, "http://example.org/package.zip")

    def test_corrupt_download_never_changes_install(self):
        package = self.fixture.web / Path(self.fixture.envelope["release"]["url"]).name
        value = bytearray(package.read_bytes()); value[-1] ^= 1; package.write_bytes(value)
        with self.assertRaises(UpdateError): self.prepared()
        self.fixture.assert_user_files(self)
        self.assertEqual((self.fixture.install / ENTRY).read_bytes(), b"old-exe")

    def test_truncated_download_rejected(self):
        package = self.fixture.web / Path(self.fixture.envelope["release"]["url"]).name
        package.write_bytes(package.read_bytes()[:10])
        with self.assertRaises(UpdateError): self.prepared()

    def test_cancel_has_no_install_side_effects(self):
        with self.assertRaises(Cancelled): self.prepared(cancelled=lambda: True)
        self.assertEqual((self.fixture.install / ENTRY).read_bytes(), b"old-exe")
        self.fixture.assert_user_files(self)

    def test_protected_paths_traversal_windows_names_and_duplicates_rejected(self):
        for name in ("../escape.exe", "_internal/../client_config.json", "C:/escape.exe", "_internal\\escape.exe",
                     "client_config.json", "update_config.json", "output/a.xlsx", "orders/a.aiquote",
                     "_internal/client_config.json", "_internal/x.key", "_internal/x.pem",
                     "_internal/other/cacert.pem", "_internal/NUL.dll", "_internal/x. ",
                     "/absolute.exe", "_internal//x", "_internal/./x"):
            with self.subTest(name=name), self.assertRaises(UpdateError): safe_member(name)
        self.fixture.repack([(ENTRY, b"new"), ("_internal/a.dll", b"a"), ("_internal/A.dll", b"b")])
        with self.assertRaises(UpdateError): self.prepared()

    def test_signed_zip_cannot_overwrite_config(self):
        self.fixture.repack([(ENTRY, b"new"), ("client_config.json", b"stolen")])
        with self.assertRaises(UpdateError): self.prepared()
        self.fixture.assert_user_files(self)

    def test_real_public_ca_bundle_build_stage_and_install(self):
        from make_client_update import build
        value = (ROOT.parent / "AIQuoteDualSystem" / core.PUBLIC_CA_BUNDLE).read_bytes()
        path = self.fixture.source / core.PUBLIC_CA_BUNDLE
        path.parent.mkdir(parents=True); path.write_bytes(value)
        self.fixture.envelope = build(self.fixture.source, self.fixture.root / "with-ca", self.fixture.key,
                                      "2026.10.20.05", self.fixture.url, "Public CA bundle")
        # Serve the newly built real-layout package through the existing fixture.
        release = self.fixture.envelope["release"]
        shutil.copy2(self.fixture.root / "with-ca" / Path(release["url"]).name,
                     self.fixture.web / Path(release["url"]).name)
        job = self.prepared()
        self.assertEqual(apply_update(job, lambda _: True)["status"], "completed")
        self.assertEqual((self.fixture.install / core.PUBLIC_CA_BUNDLE).read_bytes(), value)
        self.fixture.assert_user_files(self)

    def test_private_or_invalid_pem_at_ca_path_is_rejected(self):
        values = [b"not a certificate", b"-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----",
                  (ROOT.parent / "AIQuoteDualSystem" / core.PUBLIC_CA_BUNDLE).read_bytes()
                  + b"\n-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"]
        for value in values:
            with self.subTest(value=value[:20]):
                self.fixture.repack([(ENTRY, b"new"), (core.PUBLIC_CA_BUNDLE, value)])
                with self.assertRaises(UpdateError): self.prepared()
                self.assertEqual((self.fixture.install / ENTRY).read_bytes(), b"old-exe")

    def test_build_rejects_private_key_disguised_as_ca_bundle(self):
        from make_client_update import build
        path = self.fixture.source / core.PUBLIC_CA_BUNDLE
        path.parent.mkdir(parents=True); path.write_bytes(b"-----BEGIN PRIVATE KEY-----\nsecret")
        with self.assertRaises(UpdateError):
            build(self.fixture.source, self.fixture.root / "bad-ca", self.fixture.key,
                  "2026.10.20.05", self.fixture.url, "Invalid CA")

    def test_zip_symlink_and_expansion_limit(self):
        package = self.fixture.web / Path(self.fixture.envelope["release"]["url"]).name
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr(ENTRY, b"new")
            info = zipfile.ZipInfo("_internal/link"); info.create_system = 3; info.external_attr = 0o120777 << 16
            archive.writestr(info, b"../../config")
        self.fixture.resign(dict(self.fixture.envelope["release"], sha256=digest(package), size=package.stat().st_size))
        with self.assertRaises(UpdateError): self.prepared()
        self.fixture.repack([(ENTRY, b"new")])
        with patch.object(core, "MAX_EXPANDED", 1), self.assertRaises(UpdateError): self.prepared()

    def test_download_stage_does_not_install_and_excludes_private_files(self):
        path = self.prepared(); job = read_json(path)
        self.assertEqual(job["status"], "prepared")
        self.assertNotIn("client_config.json", job["files"])
        self.assertNotIn("private/signing.key", job["files"])
        self.assertEqual((self.fixture.install / "_internal/version.txt").read_text(), "2026.10.20.04\nhealthy")

    def test_success_preserves_all_user_files_and_retains_backup(self):
        path = self.prepared()
        result = apply_update(path, lambda _: True)
        self.assertEqual(result["status"], "completed")
        self.assertIn("2026.10.20.05", (self.fixture.install / "_internal/version.txt").read_text())
        self.assertTrue((path.parent / "backup" / ENTRY).is_file())
        self.fixture.assert_user_files(self)
        with self.assertRaises(UpdateError): apply_update(path, lambda _: True)

    def test_unhealthy_version_restores_every_managed_file(self):
        path = self.prepared()
        result = apply_update(path, lambda _: False)
        self.assertEqual(result["status"], "rolled_back")
        self.assertFalse((self.fixture.install / "_internal/new-library.dll").exists())
        for name, value in self.fixture.preserved.items(): self.assertEqual((self.fixture.install / name).read_bytes(), value)

    def test_copy_failure_rolls_back_partial_install(self):
        path = self.prepared(); real = core.atomic_copy; count = 0
        def fail_once(source, target):
            nonlocal count
            count += 1
            if count == 2: raise PermissionError("simulated lock")
            return real(source, target)
        with patch.object(core, "atomic_copy", side_effect=fail_once):
            self.assertEqual(apply_update(path, lambda _: True)["status"], "rolled_back")
        self.fixture.assert_user_files(self)
        self.assertIn("2026.10.20.04", (self.fixture.install / "_internal/version.txt").read_text())

    def test_interrupted_transaction_can_restore_from_journal(self):
        path = self.prepared()
        class SimulatedPowerLoss(BaseException): pass
        with self.assertRaises(SimulatedPowerLoss):
            apply_update(path, lambda _: (_ for _ in ()).throw(SimulatedPowerLoss()))
        self.assertEqual(read_json(path)["status"], "checking")
        self.assertEqual(apply_update(path, lambda _: True)["status"], "rolled_back")
        self.fixture.assert_user_files(self)

    def test_stale_install_and_tampered_cache_rejected(self):
        path = self.prepared()
        (path.parent / "package.zip").write_bytes(b"tampered")
        with self.assertRaises(UpdateError): apply_update(path, lambda _: True)
        self.assertEqual(read_json(path)["status"], "prepared")
        path = self.prepared(); (self.fixture.install / ENTRY).write_bytes(b"other-version")
        with self.assertRaises(UpdateError): apply_update(path, lambda _: True)

    def test_extracted_tree_tampering_cannot_install_unsigned_content(self):
        path = self.prepared(); (path.parent / "payload" / ENTRY).write_bytes(b"tampered")
        self.assertEqual(apply_update(path, lambda _: True)["status"], "completed")
        self.assertEqual((self.fixture.install / ENTRY).read_bytes(), b"old-exe")

    def test_low_disk_and_downgrade_rejected(self):
        with patch.object(shutil, "disk_usage", return_value=shutil._ntuple_diskusage(1, 1, 0)), self.assertRaises(UpdateError): self.prepared()
        envelope = self.fixture.resign(dict(self.fixture.envelope["release"], version="2026.10.20.03"))
        with self.assertRaises(UpdateError): self.prepared()

    def test_exclusive_transaction_lock(self):
        with update_lock(self.fixture.install), self.assertRaises((OSError, UpdateError)):
            with update_lock(self.fixture.install): pass

    def test_rollback_failure_not_reported_as_restored(self):
        path = self.prepared()
        with patch.object(core, "restore_backup", side_effect=OSError("locked")), self.assertRaisesRegex(UpdateError, "恢复旧版本未完成"):
            apply_update(path, lambda _: False)
        self.assertEqual(read_json(path)["status"], "rollback_failed")


@unittest.skipUnless(os.name == "nt", "Windows process lifecycle tests")
class WindowsProcessTests(unittest.TestCase):
    def run_case(self, fail):
        with tempfile.TemporaryDirectory(prefix="quote-real-update-") as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            fixture = LocalSource(Path(folder), real_exe=True, fail=fail)
            children = []
            parent = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(.2)"])
            try:
                path = download_update(fixture.config, fixture.envelope, fixture.install, "2026.10.20.04", copy_runner=False)
                job = read_json(path); job["parent_pid"] = parent.pid; atomic_json(path, job)
                original = runner.launch_client
                def track(*args, **kwargs):
                    process = original(*args, **kwargs); children.append(process); return process
                with patch.object(runner, "launch_client", side_effect=track):
                    result = runner.execute_job(path, health_timeout=4, parent_timeout=4)
                self.assertEqual(result["status"], "rolled_back" if fail else "completed", result)
                fixture.assert_user_files(self)
                expected = "2026.10.20.04" if fail else "2026.10.20.05"
                self.assertIn(expected, (fixture.install / "_internal/version.txt").read_text())
                self.assertEqual(len(children), 2 if fail else 1)
                if fail: self.assertIsNotNone(children[0].poll())
            finally:
                for process in [parent, *children]:
                    if process.poll() is None: process.terminate()
                    process.wait(timeout=10)
                fixture.close()

    def test_real_update_new_process_health_and_restart(self): self.run_case(False)
    def test_real_failed_new_process_and_restored_old_restart(self): self.run_case(True)

    def test_parent_still_running_never_replaced(self):
        process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(10)"])
        try:
            with self.assertRaises(UpdateError): runner.wait_for_parent(process.pid, .05)
            self.assertIsNone(process.poll())
        finally:
            process.terminate(); process.wait(timeout=10)


if __name__ == "__main__": unittest.main(verbosity=2)
