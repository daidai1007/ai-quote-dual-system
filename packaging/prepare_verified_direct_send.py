"""Prepare a direct-send delivery only after recorded Defender/functional gates."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from client_update_core import atomic_json, digest, read_json, reject_links


def require_scan(value):
    assert value.get('result') == 'no_threats_detected'
    assert value.get('scanner_signature') == 'Valid Microsoft'
    for key in ('antivirus_enabled', 'realtime_protection_enabled', 'protection_and_exclusion_settings_unchanged'):
        assert value.get(key) is True, key
    assert value.get('quarantine_restored') is False
    assert value.get('manual_sample_upload_performed') is False
    assert {scan.get('mode') for scan in value['scans']} == {'archive-aware-forensic', 'normal-custom'}
    assert all(scan.get('exit_code') == 0 and scan.get('no_threats_detected') is True for scan in value['scans'])


def main(args):
    build_dir, verify_dir, destination = (Path(value).resolve() for value in (args.build, args.verification, args.output))
    if not destination.is_relative_to(ROOT.parent / 'AIQuoteDualSystem_Installer') or destination.exists():
        raise ValueError('Use a fresh direct-send directory inside AIQuoteDualSystem_Installer')
    reject_links(destination)
    build = read_json(build_dir / 'first-install-build.json')
    verification = read_json(verify_dir / 'verification-result.json')
    require_scan(build['defender_stage_scan'])
    require_scan(build['defender_installer_scan'])
    for key in ('installer_extraction_matches_stage', 'business_api_key_empty', 'online_update_configured',
                'live_lan_signed_manifest_check', 'same_version_not_offered', 'previous_version_recognizes_release'):
        assert verification.get(key) is True, key
    assert verification['startup']['main_window_started'] is True
    assert verification['startup']['clean_profile'] is True
    assert verification['developer_secret_audit']['developer_secret_matches'] == 0
    assert build['developer_credentials_included'] is False and build['user_documents_included'] is False
    assert verification['update_origin'] == build['update_origin'], 'Verified server differs from release server'
    installer = Path(build['installer'])
    assert digest(installer) == build['installer_sha256'] == verification['installer_sha256']
    assert build['entry_sha256'] == verification['packaged_source']['sha256']
    destination.mkdir(parents=True)
    for name in (installer.name, '安装说明.txt', 'SHA256SUMS.txt'):
        shutil.copy2(build_dir / name, destination / name)
    assert digest(destination / installer.name) == build['installer_sha256']
    signatures = build['defender_installer_scan']['signature_version_after']
    notice = f'''{build['version']} 安装前安全检查

本目录仅含可交付文件，可通过公司允许的 U 盘、文件共享或企业聊天发送。
不需要通过浏览器下载，也不要求关闭任何安全防护。

安装前
1. 各电脑先更新杀毒软件病毒库。使用 Defender 时，在 Windows 安全中心的
   “病毒和威胁防护”页面检查防护更新。本次本机复核版本为 {signatures}。
2. 核对安装 EXE 的 SHA-256，再对收到的文件扫描；未检出威胁后才继续安装。
   本次 EXE：{installer.name}
   SHA-256：{build['installer_sha256'].upper()}
3. 如仍明确报毒，停止安装，保留检测名称、病毒库版本及文件哈希，交管理员复核。
   不恢复已隔离样本，不添加排除项，不关闭实时或云保护，不绕过公司安全策略。
4. Windows“未知发布者”或 SmartScreen 下载信誉提醒不等同于病毒检测；
   本 EXE 尚无 Authenticode 发布者签名，如被公司策略阻止请交管理员处理。

本次检查结论与边界
本次完整解包目录和最终安装 EXE 均通过取证及普通扫描，当前未检出威胁。
扫描结论仅适用于本次文件哈希和记录的病毒库版本，不是绝对安全保证，
也不是微软正式给出的误报裁定。此前其他安装包的扫描记录不能代替本次检查。
本次没有改变安装格式或压缩方式规避检测，没有主动上传样本，也没有关闭防护、
新增排除项或恢复隔离项。

业务与更新配置
业务仍连接原线上 Render API；安装包 api_key 留空，须由管理员单独配置业务授权。
内网更新地址：{verification['manifest_url']}
仅允许的内网更新源：{build['update_origin']}
验证公钥已配置，用户配置、订单、图纸和导出文件不在本交付包中。
'''
    (destination / '安装前安全检查.txt').write_text(notice, encoding='utf-8-sig')
    report = {
        'product': build['product'], 'version': build['version'],
        'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'installer_name': installer.name, 'installer_sha256': build['installer_sha256'],
        'installer_bytes': build['installer_bytes'], 'entry_sha256': build['entry_sha256'],
        'scan_signatures': signatures,
        'payload_scans_clear': True, 'final_installer_scans_clear': True,
        'antivirus_and_realtime_protection_kept_enabled': True,
        'no_exclusion_or_protection_setting_changes': True, 'no_quarantined_item_restored': True,
        'manual_sample_upload_performed': False, 'vendor_false_positive_ruling_received': False,
        'assessment': 'Current staged payload and final installer passed both recorded Defender scan modes.',
        'limitation': 'Local verification only; no scan is an absolute guarantee; receiving PCs must update protection and rescan.',
        'windows_authenticode': build['windows_authenticode'],
        'credentials_and_user_documents_included': False,
        'render_business_api_preserved': True, 'business_api_key_empty': True, 'lan_update_configured': True,
        'update_origin': build['update_origin'], 'manifest_url': verification['manifest_url'],
        'installer_payload_files_verified': verification['installer_payload_files_verified'],
        'files_and_python_modules_secret_audited': verification['developer_secret_audit']['files_and_python_modules_scanned'],
        'clean_profile_startup_passed': True, 'live_lan_manifest_check_passed': True,
        'quarantined_web_download_copy_republished': False,
    }
    atomic_json(destination / '安全复核记录.json', report)
    print('DIRECT_SEND_DELIVERY=' + str(destination), flush=True)
    print('INSTALLER_SHA256=' + digest(destination / installer.name), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True)
    parser.add_argument('--verification', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
