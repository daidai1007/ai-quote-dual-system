"""Start the recovered V3 client with the source-controlled layout layer."""

from __future__ import annotations

import importlib.abc
import importlib.util
import json
import marshal
import os
import pathlib
import re
import subprocess
import sys
import types
import urllib.request

from PyInstaller.loader.pyimod01_archive import (
    PYZ_ITEM_PKG,
    ZlibArchiveReader,
)

from layout_refresh import install_layout_refresh
from recognition_repair import install_recognition_repair


_DLL_DIRECTORY_HANDLES = []
_REQUIRED_CLOUD_API_BUILD = "2026-08-26-signed-attachments-v1"
_DEFAULT_RENDER_API_URL = "https://ai-quote-dual-test.onrender.com/api/quotes/calculate-dual"
_FONT_SIZE_PATTERN = re.compile(
    r"font-size\s*:\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>pt|px)",
    re.IGNORECASE,
)
_COMPACT_HEIGHT_PATTERN = re.compile(
    r"(?P<name>min-height|max-height)\s*:\s*"
    r"(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>px|pt)",
    re.IGNORECASE,
)
# The recovered V3 core hard-codes its application font at 10pt inside
# ``install_application_font``; the UI scaling pass bumps that literal to 11pt.
_APPLICATION_FONT_BASE_SIZE = 10
_APPLICATION_FONT_SCALED_SIZE = 11


def _install_source_render_config(namespace: dict) -> None:
    """Give the recovered core the same Render defaults as source main.py.

    ``main.raw`` predates the source configuration loader.  Without this
    bridge, launching ``v3_launcher.py`` uses the recovered localhost default
    even though ``desktop_client/main.py`` and the packaged client point to
    Render.  Packaged mode keeps its existing adjacent client_config behavior.
    """

    if getattr(sys, "frozen", False):
        return
    config: dict = {}
    source_root = pathlib.Path(__file__).resolve().parents[1]
    for config_path in (
        source_root / "client_config.json",
        source_root.parent / "AIQuoteDualSystem" / "client_config.json",
    ):
        if not config_path.is_file():
            continue
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            config.update({key: loaded[key] for key in ("api_url", "api_key") if loaded.get(key)})
            break
    namespace["API_URL"] = str(
        os.getenv("AI_QUOTE_API_URL")
        or config.get("api_url")
        or _DEFAULT_RENDER_API_URL
    ).strip()
    namespace["API_KEY"] = str(
        os.getenv("AI_QUOTE_API_KEY") or config.get("api_key") or ""
    ).strip()


def _install_silent_windows_subprocesses() -> None:
    """Prevent PDF/OCR helper programs from flashing console windows.

    Several recognition libraries create their own ``subprocess.Popen`` calls,
    so fixing only the preview renderer does not cover the full recognition
    pipeline.  Applying the Windows flags at the shared Popen boundary keeps
    every helper process hidden while preserving its stdout/stderr pipes.
    """

    if os.name != "nt" or getattr(subprocess, "_ai_quote_silent_popen", False):
        return

    original_popen = subprocess.Popen
    create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    create_new_console = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010))

    def silent_popen(*args, **kwargs):
        flags = int(kwargs.get("creationflags", 0) or 0)
        flags &= ~create_new_console
        kwargs["creationflags"] = flags | create_no_window

        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        return original_popen(*args, **kwargs)

    subprocess.Popen = silent_popen
    subprocess._ai_quote_silent_popen = True


def _format_ui_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.1f}".rstrip("0").rstrip(".")


def _scale_ui_style_text(text: str) -> str:
    """Increase every explicit font by one step and keep compact rows usable."""

    def scale_font(match: re.Match) -> str:
        size = float(match.group("size")) + 1.0
        return f"font-size: {_format_ui_number(size)}{match.group('unit')}"

    def scale_height(match: re.Match) -> str:
        size = float(match.group("size"))
        if 16.0 <= size <= 64.0:
            size += 4.0
        return (
            f"{match.group('name')}: {_format_ui_number(size)}"
            f"{match.group('unit')}"
        )

    return _COMPACT_HEIGHT_PATTERN.sub(
        scale_height,
        _FONT_SIZE_PATTERN.sub(scale_font, text),
    )


def _scale_ui_code(code: types.CodeType) -> types.CodeType:
    """Apply typography scaling to styles and rich text embedded in V3 code."""

    constants = []
    changed = False
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            replacement = _scale_ui_code(value)
        elif (
            code.co_qualname == "install_application_font"
            and value == _APPLICATION_FONT_BASE_SIZE
        ):
            replacement = _APPLICATION_FONT_SCALED_SIZE
        elif isinstance(value, str) and (
            "font-size" in value or "min-height" in value or "max-height" in value
        ):
            replacement = _scale_ui_style_text(value)
        else:
            replacement = value
        constants.append(replacement)
        changed = changed or replacement != value
    return code.replace(co_consts=tuple(constants)) if changed else code


def _install_cloud_export_validation(namespace: dict) -> None:
    """Adapt the recovered V3 export guard to the Render/Neon API contract."""

    main_window = namespace.get("MainWindow")
    api_headers = namespace.get("api_headers")
    if main_window is None or not callable(api_headers):
        raise RuntimeError("Cloud API compatibility layer could not be installed.")

    def request_json(url: str) -> dict:
        request = urllib.request.Request(
            url,
            headers=api_headers(),
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def validate_export_environment(self) -> None:
        base_url = self.base_url()
        try:
            health = request_json(base_url + "/health")
        except Exception as exc:
            raise RuntimeError(
                "双报价云端服务不可用，请检查网络、接口地址和访问密钥后重试。"
            ) from exc

        build = str(health.get("build") or "") if isinstance(health, dict) else ""
        if health.get("ok") is not True or build != _REQUIRED_CLOUD_API_BUILD:
            raise RuntimeError(
                "双报价接口版本不兼容"
                f"（当前：{build or '未知'}，需要：{_REQUIRED_CLOUD_API_BUILD}）。"
                "请更新客户端或联系维护人员。"
            )

        try:
            database_health = request_json(base_url + "/api/health/database")
        except Exception as exc:
            raise RuntimeError(
                "云端数据库状态检查失败，请稍后重试或联系维护人员。"
            ) from exc

        checks = database_health.get("checks") or {}
        checks_ready = isinstance(checks, dict) and all(
            value is True for value in checks.values()
        )
        if database_health.get("ready") is not True or not checks_ready:
            raise RuntimeError(
                "云端数据库尚未准备好，暂不能确认或导出报价。"
            )

    main_window.validate_export_environment = validate_export_environment


def _resource_root() -> pathlib.Path:
    configured_root = str(os.getenv("AI_QUOTE_V3_CORE_ROOT") or "").strip()
    if configured_root:
        return pathlib.Path(configured_root).resolve()
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return pathlib.Path(frozen_root) / "v3_core"
    return pathlib.Path(__file__).resolve().parent / "v3_core"


class _BundleResourceReader(importlib.abc.ResourceReader):
    """Expose PyInstaller-collected package data to importlib.resources."""

    def __init__(self, package_root: pathlib.Path):
        self.package_root = package_root

    def open_resource(self, resource):
        return (self.package_root / resource).open("rb")

    def resource_path(self, resource):
        return str(self.package_root / resource)

    def is_resource(self, name):
        return (self.package_root / name).is_file()

    def contents(self):
        if not self.package_root.is_dir():
            return []
        return [path.name for path in self.package_root.iterdir()]

    def files(self):
        return self.package_root


class _RawModuleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, core_root: pathlib.Path):
        self.core_root = core_root
        self.modules = {path.stem: path for path in core_root.glob("*.raw")}

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "desktop_client":
            return importlib.util.spec_from_loader(fullname, self, is_package=True)
        key = fullname.rsplit(".", 1)[-1]
        if key in self.modules and (
            fullname == key or fullname.startswith("desktop_client.")
        ):
            return importlib.util.spec_from_loader(fullname, self, is_package=False)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        if module.__name__ == "desktop_client":
            module.__path__ = []
            module.__file__ = str(self.core_root.parent / "__init__.py")
            return
        key = module.__name__.rsplit(".", 1)[-1]
        module.__file__ = str(self.core_root / f"{key}.py")
        code = marshal.loads(self.modules[key].read_bytes())
        exec(code, module.__dict__)


class _OriginalPyzFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Fallback importer for dependencies bundled with the verified V3 EXE."""

    def __init__(self, archive_path: pathlib.Path):
        self.archive = ZlibArchiveReader(str(archive_path))
        bundle_root = archive_path.parent.parent
        if not (bundle_root / "rapidocr").is_dir():
            deployed_root = archive_path.parents[2] / "AIQuoteDualSystem" / "_internal"
            if deployed_root.is_dir():
                bundle_root = deployed_root
        self.bundle_root = bundle_root

    def _module_file(self, fullname: str, is_package: bool) -> pathlib.Path:
        module_path = self.bundle_root.joinpath(*fullname.split("."))
        return module_path / "__init__.py" if is_package else module_path.with_suffix(".py")

    def find_spec(self, fullname, path=None, target=None):
        entry = self.archive.toc.get(fullname)
        if entry is None:
            return None
        is_package = entry[0] == PYZ_ITEM_PKG
        module_file = self._module_file(fullname, is_package)
        spec = importlib.util.spec_from_loader(
            fullname,
            self,
            origin=str(module_file),
            is_package=is_package,
        )
        if is_package:
            spec.submodule_search_locations = [str(module_file.parent)]
        return spec

    def create_module(self, spec):
        return None

    def get_resource_reader(self, fullname):
        entry = self.archive.toc.get(fullname)
        if entry is None or entry[0] != PYZ_ITEM_PKG:
            return None
        return _BundleResourceReader(
            self._module_file(fullname, True).parent
        )

    def exec_module(self, module):
        entry = self.archive.toc[module.__name__]
        is_package = entry[0] == PYZ_ITEM_PKG
        module_file = self._module_file(module.__name__, is_package)
        module.__file__ = str(module_file)
        if is_package:
            module.__path__ = [str(module_file.parent)]
        code = self.archive.extract(module.__name__)
        exec(code, module.__dict__)


def load_v3_namespace() -> dict:
    _install_silent_windows_subprocesses()
    core_root = _resource_root()
    main_path = core_root / "main.raw"
    if not main_path.exists():
        raise RuntimeError(f"V3 client core is missing: {main_path}")

    dependency_archive = core_root / "original.pyz"
    if not dependency_archive.exists():
        raise RuntimeError(f"V3 dependency archive is missing: {dependency_archive}")

    if not getattr(sys, "frozen", False):
        dependency_root = (
            core_root.parent
            if core_root.parent.name.lower() == "_internal"
            else core_root.parents[1] / "AIQuoteDualSystem" / "_internal"
        )
        if dependency_root.is_dir():
            dependency_text = str(dependency_root)
            if dependency_text not in sys.path:
                sys.path.insert(0, dependency_text)
            if hasattr(os, "add_dll_directory"):
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(dependency_text))

    sys.meta_path.insert(0, _OriginalPyzFinder(dependency_archive))
    sys.meta_path.insert(0, _RawModuleFinder(core_root))
    namespace = {
        "__name__": "v3_core_main",
        "__file__": str(pathlib.Path(__file__).resolve().with_name("main.py")),
        "__package__": None,
    }
    main_code = _scale_ui_code(marshal.loads(main_path.read_bytes()))
    exec(main_code, namespace)
    _install_source_render_config(namespace)
    _install_cloud_export_validation(namespace)
    install_recognition_repair(namespace)
    install_layout_refresh(namespace)
    return namespace


def main() -> None:
    namespace = load_v3_namespace()
    namespace["main"]()


if __name__ == "__main__":
    main()
