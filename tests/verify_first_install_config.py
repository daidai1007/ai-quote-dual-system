"""First-install configuration never inherits developer secrets or local state."""
import base64
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packaging'), str(ROOT / 'desktop_client')]
from build_first_install import public_business_config, public_update_config, readme, scan_release, build


class FirstInstallConfigTests(unittest.TestCase):
    def test_only_public_business_url_and_empty_key_are_copied(self):
        source = {'api_url': 'https://api.example.org/api/quotes/calculate-dual', 'api_key': 'developer-private',
                  'password': 'private', 'last_order': {'name': 'private'}, 'drawings': ['private.pdf']}
        clean = public_business_config(source)
        self.assertEqual(clean, {'api_url': source['api_url'], 'api_key': ''})
        self.assertEqual(source['api_key'], 'developer-private')

    def test_business_url_cannot_smuggle_credentials(self):
        for url in ('https://name:password@example.org/api', 'https://example.org/api?key=secret',
                    'https://example.org/api#secret', 'http://example.org/api', 'file:///C:/private'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_business_config({'api_url': url})

    def test_update_configuration_only_contains_public_allowlisted_fields(self):
        value = {'enabled': True, 'channel': 'local', 'manifest_url': 'http://192.168.35.160:8897/stable/manifest.json',
                 'lan_http_origin': 'http://192.168.35.160:8897', 'public_key': base64.b64encode(bytes(32)).decode(),
                 'private_key': 'must-not-copy', 'api_key': 'must-not-copy', 'operator': 'developer'}
        clean = public_update_config(value)
        self.assertEqual(len(clean), 5)
        self.assertNotIn('private_key', clean)
        self.assertNotIn('api_key', clean)
        self.assertNotIn('operator', clean)

    def test_disabled_or_unpinned_updates_are_not_shipped(self):
        value = {'enabled': True, 'channel': 'local', 'manifest_url': 'http://192.168.35.160:8897/stable/manifest.json',
                 'lan_http_origin': 'http://192.168.35.160:8897', 'public_key': base64.b64encode(bytes(32)).decode()}
        for update in ({**value, 'enabled': False}, {**value, 'lan_http_origin': ''}, {**value, 'public_key': 'invalid'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                public_update_config(update)

    def test_readme_explains_separate_api_authorization(self):
        text = readme('2026.10.20.05', {'manifest_url': 'http://192.168.35.160:8897/stable/manifest.json',
                                      'lan_http_origin': 'http://192.168.35.160:8897'})
        self.assertIn('api_key', text)
        self.assertIn('无需另装 Python', text)
        self.assertIn('不含开发电脑', text)

    def test_new_server_is_preserved_in_config_and_readme(self):
        origin = 'http://192.168.35.212:8898'
        value = {'enabled': True, 'channel': 'local', 'manifest_url': origin + '/stable/manifest.json',
                 'lan_http_origin': origin, 'public_key': base64.b64encode(bytes(32)).decode()}
        self.assertEqual(public_update_config(value), value)
        text = readme('2026.10.20.05', value)
        self.assertIn(value['manifest_url'], text)
        self.assertIn('内网更新服务器', text)
        self.assertNotIn('192.168.35.160', text)

    def test_shortcuts_use_the_actual_updatable_entry_name(self):
        text = (ROOT / 'packaging/AIQuoteDualSystem.nsi').read_text(encoding='utf-8-sig')
        self.assertIn('!define APP_EXE "AIQuoteDualSystem_layout_v0.exe"', text)
        self.assertNotIn('layout_v6.exe', text)
        self.assertIn('IfFileExists "$INSTDIR\\client_config.json" keep_client_config', text)
        self.assertIn('IfFileExists "$INSTDIR\\update_config.json" keep_update_config', text)

    def test_defender_scan_error_never_approves_release(self):
        with patch('build_first_install.subprocess.run', return_value=SimpleNamespace(returncode=2)):
            with self.assertRaisesRegex(RuntimeError, 'do not distribute'):
                scan_release(Path('unused.exe'), Path('unused-report'))

    def test_defender_missing_or_unprotected_scan_never_approves_release(self):
        base = {'result': 'no_threats_detected', 'antivirus_enabled': True,
                'realtime_protection_enabled': True, 'protection_and_exclusion_settings_unchanged': True,
                'scans': [{'no_threats_detected': True, 'exit_code': 0},
                          {'no_threats_detected': True, 'exit_code': 0}]}
        for value in ({**base, 'realtime_protection_enabled': False}, {**base, 'scans': []},
                      {**base, 'protection_and_exclusion_settings_unchanged': False},
                      {**base, 'scans': [{'no_threats_detected': False, 'exit_code': 2}] * 2}):
            with self.subTest(value=value), patch('build_first_install.subprocess.run', return_value=SimpleNamespace(returncode=0)), \
                    patch('build_first_install.read_json', return_value=value):
                with self.assertRaisesRegex(RuntimeError, 'do not distribute'):
                    scan_release(Path('unused.exe'), Path('unused-report'))

    def test_defender_stage_and_installer_are_both_release_gates(self):
        source = (ROOT / 'packaging/build_first_install.py').read_text(encoding='utf-8')
        self.assertIn("stage_scan = scan_release(stage, output / 'defender-stage')", source)
        self.assertIn("installer_scan = scan_release(installer, output / 'defender-installer')", source)
        self.assertLess(source.index('installer_scan = scan_release'), source.index("output / 'SHA256SUMS.txt'"))

    def test_unapproved_build_cannot_be_created_in_http_download_root(self):
        with self.assertRaisesRegex(ValueError, 'outside the HTTP download root'):
            build(SimpleNamespace(output=str(ROOT.parent / 'AIQuoteUpdates' / 'must-not-build')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
