"""Exercise the actual health guards without starting Qt or writing quotations."""

import ast
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def load_guard(filename, constant):
    tree = ast.parse((ROOT / "desktop_client" / filename).read_text(encoding="utf-8-sig"))
    required = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == constant for target in node.targets)
    )
    if filename == "v3_launcher.py":
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "_install_cloud_export_validation")
    else:
        window = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "MainWindow")
        function = next(node for node in window.body if isinstance(node, ast.FunctionDef)
                        and node.name == "validate_export_environment")
    namespace = dict(json=json, urllib=urllib, sys=types.SimpleNamespace(frozen=True),
                     Path=Path, application_root=lambda: ROOT,
                     shutil=types.SimpleNamespace(which=lambda _: None), api_headers=lambda: {})
    exec(compile(ast.Module(body=[required, function], type_ignores=[]), filename, "exec"), namespace)
    if filename == "v3_launcher.py":
        window = type("Window", (), {})
        namespace["_install_cloud_export_validation"]({"MainWindow": window, "api_headers": lambda: {}})
        guard = window.validate_export_environment
    else:
        guard = namespace["validate_export_environment"]
    return namespace[constant], guard


class HealthGuardTests(unittest.TestCase):
    def test_confirmation_and_export_require_healthy_matching_api_and_database(self):
        for filename, constant in [("v3_launcher.py", "_REQUIRED_CLOUD_API_BUILD"),
                                   ("main.py", "REQUIRED_EXPORT_API_BUILD")]:
            build, guard = load_guard(filename, constant)
            good_health = {"ok": True, "build": build}
            good_database = {"ready": True, "checks": {"connection": True, "catalogs": True}}
            cases = [
                ("healthy", good_health, good_database, True),
                ("wrong build", {"ok": True, "build": "incompatible-build"}, good_database, False),
                ("missing build", {"ok": True}, good_database, False),
                ("not ok", {"ok": False, "build": build}, good_database, False),
                ("truthy ok", {"ok": 1, "build": build}, good_database, False),
                ("invalid health", [], good_database, False),
                ("health unavailable", OSError("offline"), good_database, False),
                ("database unavailable", good_health, OSError("offline"), False),
                ("not ready", good_health, {**good_database, "ready": False}, False),
                ("truthy ready", good_health, {**good_database, "ready": 1}, False),
                ("missing ready", good_health, {"checks": {"catalogs": True}}, False),
                ("failed check", good_health, {"ready": True, "checks": {"a": True, "b": False}}, False),
                ("truthy check", good_health, {"ready": True, "checks": {"a": 1}}, False),
                ("empty checks", good_health, {"ready": True, "checks": {}}, False),
                ("missing checks", good_health, {"ready": True}, False),
                ("invalid checks", good_health, {"ready": True, "checks": [True]}, False),
                ("invalid database", good_health, [], False),
            ]
            for label, health, database, accepted in cases:
                with self.subTest(client=filename, case=label):
                    responses = [value if isinstance(value, Exception) else
                                 io.BytesIO(json.dumps(value).encode()) for value in [health, database]]
                    with patch.object(urllib.request, "urlopen", side_effect=responses) as request:
                        window = types.SimpleNamespace(base_url=lambda: "https://health-test.invalid")
                        if accepted:
                            guard(window)
                            self.assertEqual([call.args[0].full_url for call in request.call_args_list],
                                             [window.base_url() + "/health", window.base_url() + "/api/health/database"])
                        else:
                            with self.assertRaises(RuntimeError):
                                guard(window)


if __name__ == "__main__":
    unittest.main()
