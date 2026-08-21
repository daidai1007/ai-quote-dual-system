# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

packaging_dir = Path(SPEC).resolve().parent
repo_root = packaging_dir.parent

a = Analysis(
    [str(repo_root / 'desktop_client' / 'v3_launcher.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AIQuoteDualSystem_layout_v6',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(packaging_dir / 'assets' / 'AIQuoteDualSystem.ico'),
    version=str(packaging_dir / 'version_info.txt'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AIQuoteDualSystem_layout_v6',
)
