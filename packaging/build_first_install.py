"""Build a credential-free first installer from an already signed program ZIP.

Never copies the installed client directory or changes the development client.
The business API key is intentionally empty; provisioning is out of band.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from client_update_core import (ENTRY, atomic_json, digest, read_json, reject_links,
                                unpack, verify_manifest)
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader


def public_business_config(value):
    url = str(value.get('api_url') or '')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or any(ord(char) <= 32 for char in url)):
        raise ValueError('Business API address must be HTTPS without credentials, query or fragment')
    return {'api_url': url, 'api_key': ''}


def public_update_config(value):
    keys = ('enabled', 'channel', 'manifest_url', 'lan_http_origin', 'public_key')
    result = {key: value[key] for key in keys}
    if result['enabled'] is not True or not result['lan_http_origin']:
        raise ValueError('An explicitly enabled LAN update origin is required')
    if len(base64.b64decode(result['public_key'], validate=True)) != 32:
        raise ValueError('Invalid update verification public key')
    return result


def secret_patterns(business, private_key):
    patterns = []
    key = business.get('api_key')
    if isinstance(key, str) and key:
        patterns.extend((key.encode('utf-8'), key.encode('utf-16le')))
    raw = Path(private_key).read_bytes()
    if len(raw) != 32:
        raise ValueError('Invalid signing-key length')
    patterns.extend((raw, base64.b64encode(raw), raw.hex().encode()))
    return patterns


def audit_no_secrets(folder, patterns):
    """Scan files AND compressed Python code without printing secret values."""
    findings = []
    checked = 0

    def check(label, value):
        nonlocal checked
        checked += 1
        if any(pattern in value for pattern in patterns):
            findings.append(label)

    def scan_pyz(path, label):
        pyz = ZlibArchiveReader(str(path))
        for module in pyz.toc:
            value = pyz.extract(module, raw=True)
            if value is not None:
                check(label + ':' + module, value)

    for path in Path(folder).rglob('*'):
        if not path.is_file():
            continue
        reject_links(path)
        name = path.relative_to(folder).as_posix()
        if path.suffix.lower() in {'.aiquote', '.xlsx', '.xls', '.pdf', '.dwg', '.dxf', '.key'}:
            raise ValueError('User document/private-key path in stage: ' + name)
        if path.name.lower() == '.env' or 'backup' in path.parts or 'AIQuotePrivate' in path.parts:
            raise ValueError('Private directory in stage: ' + name)
        check(name, path.read_bytes())
        if path.suffix.lower() == '.pyz':
            scan_pyz(path, name)
    with tempfile.TemporaryDirectory(prefix='first-installer-secret-audit-') as temp:
        reader = CArchiveReader(str(Path(folder) / ENTRY))
        for name in reader.toc:
            value = reader.extract(name)
            if value is None:
                continue
            check('EXE:' + name, value)
            if name.endswith('.pyz'):
                pyz_path = Path(temp) / 'embedded.pyz'
                pyz_path.write_bytes(value)
                scan_pyz(pyz_path, 'EXE:' + name)
    if findings:
        raise ValueError('Developer secret detected in: ' + ', '.join(findings))
    return {'files_and_python_modules_scanned': checked, 'developer_secret_matches': 0}


def scan_release(path, report):
    """Fail closed; never allow a detected/failed scan to become a release."""
    if os.name != 'nt':
        raise RuntimeError('First-install releases require real Microsoft Defender scans on Windows')
    shell = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
    if not shell:
        raise RuntimeError('An approved PowerShell host is required for the Defender release gate')
    command = [shell, '-NoProfile', '-NonInteractive', '-File',
               str(ROOT / 'packaging/scan_release_with_defender.ps1'),
               '-ScanPath', str(path), '-ReportDirectory', str(report)]
    result = subprocess.run(command, capture_output=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    stdout, stderr = getattr(result, 'stdout', b''), getattr(result, 'stderr', b'')
    if stdout or stderr:
        Path(report).with_name(Path(report).name + '-command.log').write_bytes(stdout + b'\n' + stderr)
    if result.returncode != 0:
        raise RuntimeError('Defender release scan failed; do not distribute. Report: ' + str(report))
    value = read_json(Path(report) / 'scan-result.json')
    if (value.get('result') != 'no_threats_detected' or value.get('antivirus_enabled') is not True
            or value.get('realtime_protection_enabled') is not True
            or value.get('protection_and_exclusion_settings_unchanged') is not True
            or len(value.get('scans', [])) != 2
            or not all(scan.get('no_threats_detected') is True and scan.get('exit_code') == 0
                       for scan in value['scans'])):
        raise RuntimeError('Incomplete Defender release approval; do not distribute')
    return value


def readme(version, update):
    return f'''AI 双报价系统 {version} 首次安装说明

适用：Windows 10/11 64 位电脑。完整运行依赖已包含，无需另装 Python。
这是一份全新安装包，不含开发电脑的 API 密钥、签名私钥、订单、图纸和导出文件。

安装
1. 双击 AIQuoteDualSystem_Setup_v{version}.exe，按向导完成安装。
2. 默认安装到当前用户可写目录，通常不需要管理员权限。
3. 管理员须单独提供获准使用的业务 API 密钥。在安装目录中打开
   client_config.json，只在 api_key 的空引号内填入授权密钥并保存，保留 api_url。
   不要把填写了密钥的配置文件放到更新服务器或公开群聊。
4. 启动客户端。首次报价前，请在报价方案中心填写当前操作人姓名。
   未配置业务授权时，受保护的目录、报价和导出接口可能拒绝访问；这不影响更新检查。

内网在线更新
更新清单：{update['manifest_url']}
仅允许：{update['lan_http_origin']}
启动后后台检查；也可点击左侧“检查更新”。当前已是 {version}，应提示最新版本。
发现更高版本后，人工确认下载，再保存进度并重启安装。
更新包验证签名与 SHA-256，保留用户配置和本地文件；安装失败自动恢复旧版。
内网更新服务器上的更新服务必须保持运行，且服务器不能休眠。
业务 API 和内网更新服务是不同服务；业务 API 若在外网，报价仍需要相应网络访问。

安全
初始安装 EXE 尚无 Windows Authenticode 发布者签名（不同于更新清单的 Ed25519 签名）。
请仅从管理员的可信渠道获取，并核对随附 SHA256SUMS.txt；不要关闭系统安全防护。
如系统阻止安装，请让管理员核实文件，不要绕过公司安全策略。
'''


def build(args):
    output = Path(args.output).resolve()
    stage = output / 'stage'
    if output.is_relative_to(ROOT.parent / 'AIQuoteUpdates'):
        raise ValueError('Build outside the HTTP download root; publish only after release approval')
    if output.exists():
        raise FileExistsError('Use a fresh first-installer output directory: ' + str(output))
    reject_links(output)
    config = public_update_config(read_json(args.update_config))
    envelope = read_json(args.manifest)
    release = verify_manifest(envelope, config)
    if release['version'] != args.version:
        raise ValueError('Signed release version mismatch')
    package = Path(args.manifest).parent / unquote(Path(urlsplit(release['url']).path).name)
    if package.stat().st_size != release['size'] or digest(package) != release['sha256']:
        raise ValueError('Signed source package hash/size mismatch')
    business = read_json(args.business_config)
    clean_business = public_business_config(business)
    for required in (args.nsis, args.private_key):
        if not Path(required).is_file():
            raise FileNotFoundError(required)
    output.mkdir(parents=True)
    files = unpack(package, stage)
    atomic_json(stage / 'client_config.json', clean_business)
    atomic_json(stage / 'update_config.json', config)
    (stage / 'README.txt').write_text(readme(args.version, config), encoding='utf-8-sig')
    (stage / 'output').mkdir()
    for name in ('AIQuoteDualSystem.ico', 'installer_sidebar.bmp', 'installer_header.bmp'):
        shutil.copy2(ROOT / 'packaging/assets' / name, stage / name)
    source_hash = digest(stage / ENTRY)
    for name in ('_internal/python312.dll', '_internal/v3_core/main.raw',
                 '_internal/v3_core/original.pyz', '_internal/PySide6/QtCore.pyd',
                 '_internal/PySide6/QtWidgets.pyd'):
        if not (stage / name).is_file():
            raise ValueError('Missing runtime dependency: ' + name)
    if not list((stage / 'runtime').rglob('pdftoppm.exe')):
        raise ValueError('Missing PDF renderer')
    audit = audit_no_secrets(stage, secret_patterns(business, args.private_key))
    print('Credential and document audit passed: ' + json.dumps(audit), flush=True)
    manifest = {'product': 'AIQuoteDualSystem', 'version': args.version, 'architecture': 'win-x64',
                'entry': ENTRY, 'built_at': datetime.now(timezone.utc).isoformat(),
                'source_update_sha256': release['sha256'], 'entry_sha256': source_hash,
                'requires_business_api_key': True, 'developer_credentials_included': False,
                'user_documents_included': False, 'windows_authenticode': 'NotSigned',
                'update_configured': True, 'update_origin': config['lan_http_origin']}
    atomic_json(stage / 'release-manifest.json', manifest)
    print('Scanning complete unpacked release with Defender...', flush=True)
    stage_scan = scan_release(stage, output / 'defender-stage')
    nsi = ROOT / 'packaging/AIQuoteDualSystem.nsi'
    compile_nsi = output / 'first-install.compile.nsi'
    compile_nsi.write_text(nsi.read_text(encoding='utf-8-sig'), encoding='utf-8-sig')
    numeric_version = '.'.join(str(int(part)) for part in args.version.split('.'))
    print('Compiling first installer...', flush=True)
    with (output / 'nsis-build.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([str(Path(args.nsis).resolve()), '/V3', '/DStageDir=' + str(stage),
                                 '/DOutputDir=' + str(output), '/DAppVersion=' + args.version,
                                 '/DAppVersionNumeric=' + numeric_version, str(compile_nsi)],
                                stdout=log, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('NSIS compilation failed; inspect ' + str(output / 'nsis-build.log'))
    installer = output / ('AIQuoteDualSystem_Setup_v' + args.version + '.exe')
    print('Scanning final installer with Defender...', flush=True)
    installer_scan = scan_release(installer, output / 'defender-installer')
    shutil.copy2(stage / 'README.txt', output / '安装说明.txt')
    checksum = digest(installer)
    (output / 'SHA256SUMS.txt').write_text(checksum + '  ' + installer.name + '\n', encoding='ascii')
    report = {**manifest, 'installer': str(installer), 'installer_bytes': installer.stat().st_size,
              'installer_sha256': checksum, 'stage': str(stage), 'program_files': len(files), 'audit': audit,
              'defender_stage_scan': stage_scan, 'defender_installer_scan': installer_scan,
              'existing_client_modified': False, 'update_feed_modified': False}
    atomic_json(output / 'first-install-build.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--version', required=True)
    result.add_argument('--manifest', required=True)
    result.add_argument('--update-config', required=True)
    result.add_argument('--business-config', required=True)
    result.add_argument('--private-key', required=True, help='Audit only; never packaged or printed')
    result.add_argument('--output', required=True)
    result.add_argument('--nsis', required=True)
    return result


if __name__ == '__main__':
    build(parser().parse_args())
