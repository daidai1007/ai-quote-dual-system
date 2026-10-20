"""Explicit LAN HTTP pins. Real HTTP is routed to loopback, never exposed on LAN."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from functools import partial
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from update_test_support import LocalSource, QuietHandler, build
import client_update_core as core
import client_update_runner as runner


class LanHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quote-lan-update-")
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, LOCALAPPDATA=str(Path(self.temp.name) / "profile"))
        self.env.start(); self.addCleanup(self.env.stop)
        self.fixture = LocalSource(Path(self.temp.name))
        self.addCleanup(self.fixture.close)
        self.pin = f"http://192.168.50.20:{self.fixture.server.server_port}"
        self.config = dict(self.fixture.config, manifest_url=self.pin + "/manifest.json", lan_http_origin=self.pin)
        self.connections, self.requests = [], []
        self.redirects = {}
        owner = self
        class Handler(QuietHandler):
            def do_GET(self):
                owner.requests.append((self.path, dict(self.headers)))
                if self.path in owner.redirects:
                    self.send_response(302); self.send_header("Location", owner.redirects[self.path]); self.end_headers()
                else:
                    super().do_GET()
        self.fixture.server.RequestHandlerClass = partial(Handler, directory=str(self.fixture.web))
        self.envelope = self.fixture.resign(dict(self.fixture.envelope["release"],
                                                url=self.fixture.envelope["release"]["url"].replace(self.fixture.url, self.pin)))

    @contextmanager
    def local_transport(self):
        """Exercise urllib redirects/headers normally; substitute TCP routing ONLY."""
        owner = self
        def connect(connection):
            owner.connections.append((connection.host, connection.port))
            if (connection.host, connection.port) != ("192.168.50.20", owner.fixture.server.server_port):
                raise AssertionError("Unapproved network connection attempted")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(connection.timeout)
            sock.connect(("127.0.0.1", owner.fixture.server.server_port))
            connection.sock = sock
        with patch.object(http.client.HTTPConnection, "connect", connect):
            yield

    def prepare(self):
        return core.download_update(self.config, self.envelope, self.fixture.install, "2026.10.20.04", copy_runner=False)

    def test_private_http_is_denied_without_explicit_pin(self):
        for address in ("10.0.0.5", "172.16.0.5", "192.168.1.100"):
            with self.subTest(address=address), self.assertRaises(core.UpdateError):
                core.validate_url(f"http://{address}:8897/manifest.json")
        config = dict(self.config); config.pop("lan_http_origin")
        with patch.object(http.client.HTTPConnection, "connect", side_effect=AssertionError("Network must not start")):
            with self.assertRaises(core.UpdateError): core.check_release(config, "2026.10.20.04")

    def test_only_three_rfc1918_ranges_and_exact_port_are_allowed(self):
        for address in ("10.0.0.1", "10.255.255.254", "172.16.0.1", "172.31.255.254", "192.168.0.1", "192.168.255.254"):
            pin = f"http://{address}:8897"
            self.assertEqual(core.validate_url(pin + "/stable/m.json", lan_http_origin=pin), ("http", address, 8897))
        for address in ("8.8.8.8", "172.15.1.1", "172.32.0.1", "192.0.0.1", "100.64.0.1", "169.254.169.254",
                        "127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255"):
            pin = f"http://{address}:8897"
            with self.subTest(address=address), self.assertRaises(core.UpdateError): core.validate_url(pin, lan_http_origin=pin)
        self.assertEqual(core.validate_url("http://192.168.1.100/a", lan_http_origin="http://192.168.1.100:80/"), ("http", "192.168.1.100", 80))

    def test_pin_never_allows_another_ip_port_or_scheme(self):
        for url in ("http://192.168.50.21:8897/a", "http://10.0.0.1:8897/a", "http://127.0.0.1/a",
                    self.pin.replace("http:", "https:") + "/a", self.pin.replace(str(self.fixture.server.server_port), "1") + "/a"):
            with self.subTest(url=url), self.assertRaises(core.UpdateError): core.validate_url(url, lan_http_origin=self.pin)

    def test_no_domains_dns_rebinding_wildcards_cidr_or_ipv6_aliases(self):
        for value in ("http://updates.company.internal:8897", "http://192.168.1.100.example.org:8897", "http://*.company:8897",
                      "http://192.168.0.0/16", "http://192.168.1.*:8897", "http://3232235876:8897", "http://0xc0a80164:8897",
                      "http://192.168.001.100:8897", "http://192.168.1.100.:8897", "http://[::ffff:192.168.1.100]:8897",
                      "http://[fd00::1]:8897", "http://[fe80::1%25eth0]:8897"):
            with self.subTest(value=value), patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS must not be used")), self.assertRaises(core.UpdateError):
                core.validate_url(value, lan_http_origin=value)

    def test_malformed_and_credential_urls_are_rejected_before_parsing(self):
        for value in (self.pin + "/path", self.pin + "?x=1", self.pin + "?", self.pin + "#",
                      "http://@192.168.50.20:8897", "http://user:pw@192.168.50.20:8897", "http://192.168.50.20:0",
                      "http://192.168.50.20:65536", "http://192.168.50.20:", self.pin + "\n", self.pin + "\t",
                      " http://192.168.50.20:8897", "http://192.168.50.20\\@8.8.8.8", [], True, 1):
            with self.subTest(value=value), self.assertRaises(core.UpdateError):
                core.validate_url(self.pin + "/manifest.json", lan_http_origin=value)
        for url in (self.pin + "/a\nb", self.pin + "/a#", self.pin + "/a b", "http://192.168.50.20%2e:8897/a"):
            with self.assertRaises(core.UpdateError): core.validate_url(url, lan_http_origin=self.pin)

    def test_config_loaded_only_if_manifest_matches_pin(self):
        config_file = Path(self.temp.name) / "update-config.json"
        with patch.dict(os.environ, AI_QUOTE_UPDATE_CONFIG=str(config_file)):
            core.atomic_json(config_file, self.config)
            self.assertEqual(core.load_config(self.fixture.install), self.config)
            core.atomic_json(config_file, dict(self.config, manifest_url="http://192.168.50.21/manifest.json"))
            with self.assertRaises(core.UpdateError): core.load_config(self.fixture.install)
            core.atomic_json(config_file, dict(self.config, enabled=False, lan_http_origin="*"))
            self.assertEqual(core.load_config(self.fixture.install), {"enabled": False})

    def test_real_http_download_with_pin_keeps_config_and_business_files(self):
        with self.local_transport(), patch.dict(os.environ, HTTP_PROXY="http://untrusted.invalid:1"):
            self.assertEqual(core.check_release(self.config, "2026.10.20.04"), self.envelope)
            job = self.prepare()
        self.assertEqual(core.read_json(job)["config"]["lan_http_origin"], self.pin)
        self.assertEqual(core.apply_update(job, lambda _: True)["status"], "completed")
        self.fixture.assert_user_files(self)
        self.assertTrue(self.connections)
        self.assertTrue(all(host == "192.168.50.20" for host, port in self.connections))
        for path, headers in self.requests:
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("X-API-Key", headers)
            self.assertNotIn("Proxy-Authorization", headers)

    def test_same_origin_redirects_for_manifest_and_package_are_allowed(self):
        self.redirects["/alias.json"] = "/manifest.json"
        config = dict(self.config, manifest_url=self.pin + "/alias.json")
        target = self.envelope["release"]["url"]
        self.redirects["/download.zip"] = target
        self.envelope = self.fixture.resign(dict(self.envelope["release"], url=self.pin + "/download.zip"))
        with self.local_transport():
            self.assertEqual(core.check_release(config, "2026.10.20.04"), self.envelope)
            self.prepare()
        self.assertGreaterEqual(len(self.connections), 4)

    def test_manifest_redirect_cannot_escape_even_to_other_private_ip(self):
        for target in ("http://192.168.50.21:8897/manifest.json", "http://8.8.8.8/manifest.json", "http://updates.company/manifest.json",
                       self.pin.replace(str(self.fixture.server.server_port), "1") + "/manifest.json", "http://127.0.0.1/manifest.json"):
            self.redirects["/escape.json"] = target
            with self.subTest(target=target), self.local_transport(), self.assertRaises(core.UpdateError):
                core.check_release(dict(self.config, manifest_url=self.pin + "/escape.json"), "2026.10.20.04")
        self.assertEqual(len(self.connections), 5)

    def test_signed_package_url_and_download_redirect_cannot_escape(self):
        for target in ("http://192.168.50.21:8897/a.zip", "http://8.8.8.8/a.zip", "http://localhost/a.zip", "https://example.org/a.zip"):
            envelope = self.fixture.resign(dict(self.envelope["release"], url=target))
            with self.subTest(target=target), self.assertRaises(core.UpdateError): core.verify_manifest(envelope, self.config)
        self.envelope = self.fixture.resign(dict(self.envelope["release"], url=self.pin + "/escape.zip"))
        self.redirects["/escape.zip"] = "http://192.168.50.21:8897/a.zip"
        with self.local_transport(), self.assertRaises(core.UpdateError): self.prepare()
        self.fixture.assert_user_files(self)
        self.assertEqual(len(self.connections), 1)

    def test_http_does_not_bypass_signature_or_integrity(self):
        invalid = deepcopy(self.envelope); invalid["release"]["notes"] = "tampered HTTP response"
        core.atomic_json(self.fixture.web / "manifest.json", invalid)
        with self.local_transport(), self.assertRaises(core.UpdateError): core.check_release(self.config, "2026.10.20.04")
        package = self.fixture.web / Path(self.envelope["release"]["url"]).name
        package.write_bytes(b"tampered package")
        with self.local_transport(), self.assertRaises(core.UpdateError): self.prepare()
        self.fixture.assert_user_files(self)

    def test_failed_new_version_still_restores_all_files_under_lan_policy(self):
        with self.local_transport(): job = self.prepare()
        result = core.apply_update(job, lambda _: False)
        self.assertEqual(result["status"], "rolled_back")
        self.assertFalse((self.fixture.install / "_internal/new-library.dll").exists())
        for name, data in self.fixture.preserved.items(): self.assertEqual((self.fixture.install / name).read_bytes(), data)

    def test_packaging_requires_explicit_pin_too(self):
        output = Path(self.temp.name) / "new-release"
        base_url = self.pin + "/v6"
        with self.assertRaises(core.UpdateError):
            build(self.fixture.source, output, self.fixture.key, "2026.10.20.06", base_url, "LAN build")
        self.assertFalse(output.exists())
        envelope = build(self.fixture.source, output, self.fixture.key, "2026.10.20.06", base_url, "LAN build", lan_http_origin=self.pin)
        self.assertEqual(core.verify_manifest(envelope, self.config)["version"], "2026.10.20.06")

    @unittest.skipUnless(os.name == "nt", "Windows native process simulation")
    def test_real_native_process_success_and_rollback_with_lan_job_config(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory(prefix="quote-lan-native-") as folder:
                fixture = LocalSource(Path(folder), real_exe=True, fail=fail)
                children = []
                parent = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(.2)"])
                pin = f"http://192.168.50.20:{fixture.server.server_port}"
                config = dict(fixture.config, manifest_url=pin + "/manifest.json", lan_http_origin=pin)
                envelope = fixture.resign(dict(fixture.envelope["release"], url=fixture.envelope["release"]["url"].replace(fixture.url, pin)))
                original_fixture = self.fixture; self.fixture = fixture
                try:
                    with self.local_transport():
                        job = core.download_update(config, envelope, fixture.install, "2026.10.20.04", copy_runner=False)
                    data = core.read_json(job); data["parent_pid"] = parent.pid; core.atomic_json(job, data)
                    launch = runner.launch_client
                    def track(*args, **kwargs):
                        process = launch(*args, **kwargs); children.append(process); return process
                    with patch.object(runner, "launch_client", side_effect=track):
                        result = runner.execute_job(job, health_timeout=4, parent_timeout=4)
                    self.assertEqual(result["status"], "rolled_back" if fail else "completed", result)
                    fixture.assert_user_files(self)
                finally:
                    self.fixture = original_fixture
                    for process in [parent, *children]:
                        if process.poll() is None: process.terminate()
                        process.wait(timeout=10)
                    fixture.close()


if __name__ == "__main__": unittest.main(verbosity=2)
