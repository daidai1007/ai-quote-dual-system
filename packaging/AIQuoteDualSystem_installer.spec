# -*- mode: python ; coding: utf-8 -*-

import os
import re
from pathlib import Path

packaging_dir = Path(SPEC).resolve().parent
repo_root = packaging_dir.parent
build_version = os.environ.get('AI_QUOTE_BUILD_VERSION', '2026.08.29')
version_parts = [int(part) for part in build_version.split('.')]
while len(version_parts) < 4:
    version_parts.append(0)
version_parts = version_parts[:4]
version_text = (packaging_dir / 'version_info.txt').read_text(encoding='utf-8-sig')
version_tuple = ', '.join(str(part) for part in version_parts)
version_text = re.sub(r'filevers=\([^)]*\)', f'filevers=({version_tuple})', version_text)
version_text = re.sub(r'prodvers=\([^)]*\)', f'prodvers=({version_tuple})', version_text)
version_text = re.sub(
    r"(StringStruct\(u'(?:FileVersion|ProductVersion)', u')[^']*('\))",
    rf'\g<1>{build_version}\2',
    version_text,
)
generated_version_file = Path(os.environ.get('AI_QUOTE_VERSION_FILE', packaging_dir / 'version_info.generated.txt'))
generated_version_file.parent.mkdir(parents=True, exist_ok=True)
generated_version_file.write_text(version_text, encoding='utf-8')

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
    version=str(generated_version_file),
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
