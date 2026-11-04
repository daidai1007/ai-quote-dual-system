"""Real startup/catalogue/reconnect workers against a synthetic loopback API.

Unlike layout fixtures, this suite keeps MainWindow.load_catalogs and ApiWorker
intact. All HTTP is restricted to this fixture; settings and caches are private.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
import name_login
import scheme2_ui
import v3_launcher


class LocalAPI:
    def __init__(self):
        self.requests = []
        self.failure = None
        self.unexpected = []
        self.calculations = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                fixture.requests.append(("GET", path, self.headers.get("Authorization")))
                status = 200
                if path == fixture.failure:
                    status, value = 503, {"message": "合成服务暂不可用"}
                elif path == "/health":
                    value = {"ok": True, "service": "ai-quote-dual-api",
                             "build": "2026-09-11-complete-cost-catalogs-v5"}
                elif path == "/api/products/catalog":
                    value = {"items": [{"product_code": "JS_SINGLE", "product_name": "JS",
                              "product_method": "FORMULA", "default_width_mm": 800,
                              "default_depth_mm": 600, "default_height_mm": 1800}]}
                elif path == "/api/companies/catalog":
                    value = {"items": [{"company_code": "SYNTHETIC", "company_name": "合成测试客户"}]}
                elif path == "/api/quote-schemes":
                    value = {"total": 1, "items": [{"scheme_no": "BJ-20990101-000001",
                              "company_name": "合成测试客户", "status": "QUOTED",
                              "quote_version": 1, "order_nature": "EXTERNAL",
                              "quoted_amount": 1234.56, "creator_name": "合成测试人员"}]}
                else:
                    fixture.unexpected.append(("GET", path))
                    status, value = 404, {"message": "Unexpected synthetic endpoint"}
                content = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def do_POST(self):
                path = urlsplit(self.path).path
                if path != "/api/quotes/rematch-quick":
                    fixture.unexpected.append(("POST", path))
                    self.send_error(405)
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.calculations.append(body)
                content = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def open_local(self, request, *args, **kwargs):
        url = urlsplit(request.full_url)
        if (url.scheme, url.hostname, url.port) != ("http", "127.0.0.1", self.server.server_port):
            raise AssertionError("External HTTP is forbidden in startup regression")
        return self.opener.open(request, *args, **kwargs)


class ServiceStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = ROOT / "outputs" / "client-startup-initialization-fix-20261103" / "test-temp"
        cls.temp_root.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="client-service-startup-", dir=cls.temp_root)
        updates = Path(cls.temp.name) / "updates.json"
        updates.write_text('{"enabled":false}', encoding="utf-8")
        cls.api = LocalAPI()
        cls.api.thread.start()
        cls.environment = patch.dict(os.environ, {
            "LOCALAPPDATA": cls.temp.name, "AI_QUOTE_ORDER_CACHE_ROOT": cls.temp.name,
            "AI_QUOTE_UPDATE_CONFIG": str(updates), "AI_QUOTE_API_KEY": "synthetic-only",
            "AI_QUOTE_API_URL": cls.api.base + "/api/quotes/calculate-dual",
        })
        cls.environment.start()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, cls.temp.name)
        cls.app = QApplication.instance() or QApplication([])
        cls.network = patch("urllib.request.urlopen", side_effect=cls.api.open_local)
        cls.network.start()
        cls.ns = v3_launcher.load_v3_namespace()

    @classmethod
    def tearDownClass(cls):
        cls.network.stop()
        cls.environment.stop()
        cls.api.server.shutdown()
        cls.api.server.server_close()
        cls.api.thread.join(5)
        assert Path(cls.temp.name).resolve().parent == cls.temp_root.resolve()
        cls.temp.cleanup()

    def setUp(self):
        self.api.requests.clear()
        self.api.unexpected.clear()
        self.api.calculations.clear()
        self.api.failure = None
        self.errors = []
        self.exception_hook = patch.object(sys, "excepthook", lambda *error: self.errors.append(error))
        self.exception_hook.start()
        name_login._required = False
        name_login.set_session({"token": "T" * 43, "person": {
            "user_id": "name-user:" + hashlib.sha256(b"synthetic-startup").hexdigest(),
            "display_name": "合成测试人员", "identity_mode": "NAME_ONLY", "scope": "OWN"}})
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            for worker in window.findChildren(QThread):
                worker.wait(5000)
            self.app.processEvents()
            window._scheme2_dirty = False
            window.close()
            window.deleteLater()
        self.app.processEvents()
        self.exception_hook.stop()
        self.assertEqual(self.errors, [], "Uncaught Qt/worker exception")
        self.assertEqual(self.api.unexpected, [], "Unexpected synthetic API request")

    def wait(self, predicate, message):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.fail(message)

    def window(self):
        window = self.ns["MainWindow"]()
        self.windows.append(window)
        self.assertTrue(window._scheme2_ui_ready)
        self.assertTrue(hasattr(window, "thickness_surcharge_coefficient_spin"))
        self.assertTrue(hasattr(window, "name_scope_label"))
        self.assertEqual(self.api.requests, [], "Catalogue HTTP started inside constructor")
        window.show()
        return window

    def connected(self, window):
        self.wait(lambda: window.product_combo.count() > 0 and
                  "已连接" in window.scheme2_service_status.text(),
                  "Startup failed: " + window.scheme2_service_status.text())

    def test_startup_loads_real_catalogues_with_name_session(self):
        window = self.window()
        self.connected(window)
        self.wait(lambda: window.scheme2_company.findText("合成测试客户") >= 0,
                  "Company catalogue was not loaded")
        self.assertGreaterEqual(window.product_combo.findText("JS"), 0)
        paths = [path for _, path, _ in self.api.requests]
        self.assertEqual(paths.count("/api/products/catalog"), 1)
        self.assertEqual(paths.count("/api/companies/catalog"), 1)
        for _, path, auth in self.api.requests:
            if path.startswith("/api/"):
                self.assertEqual(auth, "Bearer " + "T" * 43)

    def test_quote_list_loads_through_actual_worker(self):
        window = self.window()
        self.connected(window)
        window.show_section(scheme2_ui.QUOTE_ROUTE)
        manager = window.quote_management
        self.wait(lambda: manager.list_table.rowCount() == 1, "Quotation list did not load")
        self.assertEqual(manager.rows[0]["scheme_no"], "BJ-20990101-000001")
        self.assertEqual(manager.rows[0]["quoted_amount"], 1234.56)

    def test_failed_catalogue_can_reconnect_using_existing_button(self):
        self.api.failure = "/api/products/catalog"
        window = self.window()
        self.wait(lambda: any(path == self.api.failure for _, path, _ in self.api.requests),
                  "No failed catalogue request")
        self.wait(lambda: not any(w.isRunning() for w in window.findChildren(QThread)),
                  "Failure left a running worker")
        self.assertNotIn("正在连接", window.scheme2_service_status.text())
        self.api.failure = None
        retry = window.findChild(QPushButton, "serviceRetryButton")
        self.assertIsNotNone(retry)
        retry.click()
        self.connected(window)
        self.assertGreaterEqual(sum(path == "/api/products/catalog" for _, path, _ in self.api.requests), 2)

    def test_quote_list_failure_is_visible_and_retry_loads_rows(self):
        window = self.window()
        self.connected(window)
        self.api.failure = "/api/quote-schemes"
        window.show_section(scheme2_ui.QUOTE_ROUTE)
        manager = window.quote_management
        self.wait(lambda: "报价单加载失败" in manager.list_status.text(),
                  "List failure was not shown")
        self.assertIn("合成服务暂不可用", manager.list_status.toolTip())
        self.assertEqual(manager.list_table.rowCount(), 0)
        self.assertFalse(manager.retry_list.isHidden())
        self.api.failure = None
        manager.retry_list.click()
        self.wait(lambda: manager.list_table.rowCount() == 1, "List retry did not load rows")
        self.assertEqual(manager.rows[0]["company_name"], "合成测试客户")

    def test_calculation_keeps_default_custom_and_zero_coefficient(self):
        window = self.window()
        self.connected(window)
        for coefficient in (10, 12.5, 0):
            window.thickness_surcharge_coefficient_spin.setValue(coefficient)
            worker = self.ns["ApiWorker"](self.api.base + "/api/quotes/rematch-quick",
                                          {"material_code": "SECC"}, window)
            results, errors = [], []
            worker.succeeded.connect(results.append)
            worker.failed.connect(errors.append)
            worker.start()
            self.wait(lambda: bool(results or errors), "Calculation worker did not finish")
            worker.wait(5000)
            self.assertEqual(errors, [])
            self.assertTrue(results[0]["ok"])
            payload = self.api.calculations[-1]
            self.assertEqual(payload["thickness_surcharge_coefficient"], coefficient)
            self.assertEqual(payload["carbon_steel_unit_price_override"], 4.2)
            self.assertEqual(payload["pricing_basis"], scheme2_ui.PRICING_BASIS)

    def test_get_without_pricing_controls_still_completes(self):
        owner = QObject()
        owner.scheme2_defaults = {"galvanized_price": 4.55, "carbon_price": 4.2, "surface_price": 26}
        worker = self.ns["ApiWorker"](self.api.base + "/health", {}, owner, method="GET")
        results, errors = [], []
        worker.succeeded.connect(results.append)
        worker.failed.connect(errors.append)
        worker.start()
        self.wait(lambda: bool(results or errors), "GET worker did not complete")
        worker.wait(5000)
        self.assertEqual(errors, [])
        self.assertTrue(results[0]["ok"])
        self.assertEqual(worker.payload, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
