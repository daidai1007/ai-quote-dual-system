"""Run the locally installed DWG converter for both preview and recognition."""

import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import mkdtemp


_QT_VARIABLES = {"QT_PLUGIN_PATH", "QT_QPA_PLATFORM", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_GENERIC_PLUGINS"}


def _fixed_drive_roots():
    if os.name == "nt":
        for drive in os.listdrives():
            if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)) == 3:
                yield Path(drive)


def find_oda_converter(find_existing):
    configured = os.environ.get("AIQUOTE_ODA_CONVERTER")
    if configured and Path(configured).is_file():
        return Path(configured)
    existing = find_existing()
    if existing:
        return Path(existing)

    installations = []
    for root in _fixed_drive_roots():
        for directory in ("Program Files", "Program Files (x86)"):
            installations.extend((root / directory / "ODA").glob("ODAFileConverter*/ODAFileConverter.exe"))
    return max(
        (path for path in installations if path.is_file()),
        key=lambda path: tuple(int(part) for part in re.findall(r"\d+", path.parent.name)),
        default=None,
    )


def convert_dwg_to_dxf(source, work_root, converter):
    if converter is None:
        raise RuntimeError("未找到 ODA DWG 转换组件。请安装 ODA File Converter 或设置 AIQUOTE_ODA_CONVERTER。")

    converter = Path(converter).resolve(strict=True)
    source = Path(source).resolve(strict=True)
    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="dwg-", dir=work_root))
    source_dir, target_dir = folder / "source", folder / "dxf"
    source_dir.mkdir()
    target_dir.mkdir()
    shutil.copy2(source, source_dir / source.name)

    # The converter ships its own Qt runtime and Windows platform plugin.
    env = {key: value for key, value in os.environ.items() if key.upper() not in _QT_VARIABLES}
    if os.name == "nt":
        env["QT_QPA_PLATFORM"] = "windows"
    try:
        process = subprocess.run(
            [str(converter), str(source_dir), str(target_dir), "ACAD2018", "DXF", "0", "1", "*.dwg"],
            cwd=converter.parent, env=env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("DWG 转换超时，请检查图纸及 ODA 转换器。") from exc

    output = target_dir / (source.stem + ".dxf")
    if process.returncode == 0 and output.is_file() and output.stat().st_size:
        return output
    detail = (process.stderr or process.stdout).strip()
    if not detail:
        detail = f"退出代码 {process.returncode}，未生成有效的 DXF 文件"
    raise RuntimeError(f"DWG 转换失败：{detail}")


def install_dwg_conversion(namespace):
    tools = namespace["DrawingRecognitionTools"]
    find_existing = tools._find_oda_converter

    def convert(source, work_root):
        return convert_dwg_to_dxf(source, work_root, find_oda_converter(find_existing))

    tools._convert_dwg_to_dxf = staticmethod(convert)
