import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))
import dwg_conversion


class DwgConversionTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(folder)
        self.source = self.root / "电气柜 样本.dwg"
        self.source.write_bytes(b"DWG source")
        self.converter = self.root / "ODAFileConverter.exe"
        self.converter.touch()

    def test_discovery_uses_fixed_drives_and_numerical_version_order(self):
        for version in ("27.9.0", "27.10.0"):
            path = self.root / "Program Files" / "ODA" / f"ODAFileConverter {version}" / self.converter.name
            path.parent.mkdir(parents=True)
            path.touch()
        with patch.dict(os.environ, {"AIQUOTE_ODA_CONVERTER": ""}), patch.object(
            dwg_conversion, "_fixed_drive_roots", return_value=[self.root]
        ):
            self.assertIn("27.10.0", str(dwg_conversion.find_oda_converter(lambda: None)))

    def test_conversion_isolates_qt_and_uses_independent_work_directories(self):
        def run(args, **kwargs):
            self.assertEqual(Path(args[0]), self.converter)
            self.assertEqual(kwargs["cwd"], self.converter.parent)
            self.assertEqual(args[3:], ["ACAD2018", "DXF", "0", "1", "*.dwg"])
            self.assertEqual(kwargs["env"].get("QT_QPA_PLATFORM"), "windows" if os.name == "nt" else None)
            self.assertNotIn("QT_PLUGIN_PATH", kwargs["env"])
            self.assertNotIn("QT_QPA_PLATFORM_PLUGIN_PATH", kwargs["env"])
            self.assertEqual((Path(args[1]) / self.source.name).read_bytes(), b"DWG source")
            (Path(args[2]) / self.source.with_suffix(".dxf").name).write_bytes(b"DXF output")
            return subprocess.CompletedProcess(args, 0, "", "")

        environment = {"QT_QPA_PLATFORM": "offscreen", "QT_PLUGIN_PATH": "other-qt",
                       "QT_QPA_PLATFORM_PLUGIN_PATH": "other-platform"}
        with patch.dict(os.environ, environment), patch.object(dwg_conversion.subprocess, "run", side_effect=run):
            first, second = (dwg_conversion.convert_dwg_to_dxf(self.source, self.root, self.converter) for _ in range(2))
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b"DXF output")
        self.assertEqual(second.read_bytes(), b"DXF output")
        self.assertEqual(self.source.read_bytes(), b"DWG source")

    def test_missing_output_and_timeout_remain_visible(self):
        attempts = [subprocess.CompletedProcess([], 0, "", ""), subprocess.TimeoutExpired([], 90)]
        with patch.object(dwg_conversion.subprocess, "run", side_effect=attempts):
            with self.assertRaisesRegex(RuntimeError, "未生成有效的 DXF"):
                dwg_conversion.convert_dwg_to_dxf(self.source, self.root, self.converter)
            with self.assertRaisesRegex(RuntimeError, "DWG 转换超时"):
                dwg_conversion.convert_dwg_to_dxf(self.source, self.root, self.converter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
