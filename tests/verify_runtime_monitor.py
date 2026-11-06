"""Meaningful runtime isolation checks; never contacts a business or monitor host."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'desktop_client'))
import monitor_settings as settings
import quote_monitor
import runtime_monitor


def wait(predicate):
    deadline = time.monotonic()+4
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.02)
    raise AssertionError('Runtime controller did not settle')


class RuntimeTests(unittest.TestCase):
    def test_real_client_startup_keeps_quote_list_without_monitor_configuration(self):
        from verify_quote_management_filters import QuoteFilters
        case = QuoteFilters()
        controller = None
        with tempfile.TemporaryDirectory() as root, \
                patch.dict(os.environ, AI_QUOTE_MONITOR_CONFIG=str(Path(root) / 'config.json')), \
                patch.object(runtime_monitor, '_controller', None), \
                patch.object(runtime_monitor, 'LocalMonitor') as factory:
            try:
                case.setUp()
                controller = runtime_monitor._controller
                self.assertIsNotNone(controller)
                self.assertTrue(case.w.isVisible())
                self.assertEqual(case.m.list_table.rowCount(), 12)
                self.assertIsNone(controller.runtime)
                factory.assert_not_called()
            finally:
                if controller is not None:
                    controller.close()
                case.tearDown()

    def test_install_keeps_window_initialization_and_reuses_one_controller(self):
        import name_login
        from quote_scheme_center import CLIENT_VERSION
        person = {'user_id': 'name-user:' + 'a' * 64}
        initialized = []

        class Window:
            def __init__(self, value):
                initialized.append(value)

        namespace = {'MainWindow': Window}
        application = Mock()
        with tempfile.TemporaryDirectory() as root:
            config = str(Path(root) / 'config.json')
            with patch.dict(os.environ, AI_QUOTE_MONITOR_CONFIG=config), \
                    patch.object(runtime_monitor, '_controller', None), \
                    patch.object(runtime_monitor, 'RuntimeController') as factory, \
                    patch.object(name_login, 'session', return_value={'person': person}), \
                    patch('PySide6.QtWidgets.QApplication.instance', return_value=application):
                runtime_monitor.install_runtime_monitoring(namespace)
                runtime_monitor.install_runtime_monitoring(namespace)
                Window('first')
                Window('second')
                self.assertEqual(initialized, ['first', 'second'])
                factory.assert_called_once()
                path, version, identity = factory.call_args.args
                self.assertEqual(path, config)
                self.assertEqual(version, CLIENT_VERSION)
                self.assertEqual(identity(), person)
                self.assertEqual(factory.call_args.kwargs['bootstrap'],
                                 Path(runtime_monitor.__file__).resolve().parent / 'monitor-enrollment.json')
                application.aboutToQuit.connect.assert_called_once_with(factory.return_value.close)

    def test_controller_start_failure_preserves_initialized_business_window(self):
        class Window:
            def __init__(self):
                self.business_ready = True

        namespace = {'MainWindow': Window}
        with patch.object(runtime_monitor, '_controller', None), \
                patch.object(runtime_monitor, 'RuntimeController', side_effect=OSError('test startup failure')):
            runtime_monitor.install_runtime_monitoring(namespace)
            window = Window()
            self.assertTrue(window.business_ready)
            self.assertIsNone(runtime_monitor._controller)

    def test_absent_configuration_never_collects_and_identity_receipt_has_no_token(self):
        with tempfile.TemporaryDirectory() as root, patch.object(runtime_monitor, 'LocalMonitor') as factory:
            person = {'user_id': 'name-user:'+'a'*64, 'display_name': '测试', 'identity_mode': 'NAME_ONLY'}
            controller = runtime_monitor.RuntimeController(Path(root)/'config.json', '2026.10.30.9001', lambda: person)
            try:
                wait(lambda: (Path(root)/'identity.json').exists() and controller.state == 'awaiting_configuration')
                self.assertEqual(controller.state, 'awaiting_configuration')
                self.assertEqual(set(json.loads((Path(root)/'identity.json').read_text())),
                                 {'app_id', 'user_id', 'display_name', 'identity_mode', 'app_version'})
                factory.assert_not_called()
            finally: controller.close()

    def test_changed_name_stops_original_runtime_without_reusing_credential(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root)/'config.json'
            settings.atomic_json(config, {'enabled': True, 'app_id': 'ai_quote', 'environment': 'test',
                'device_id': 'TEST-RUNTIME', 'user_id': 'name-user:'+'a'*64, 'app_version': 'test',
                'url': 'http://127.0.0.1:9/api/v1/events', 'api_url': 'http://127.0.0.1:9/api/quotes/calculate-dual',
                'token': 'a'*43})
            person = {'user_id': 'name-user:'+'a'*64}
            with patch.object(runtime_monitor, 'LocalMonitor') as factory:
                factory.return_value.base = {'user_id': person['user_id']}
                controller = runtime_monitor.RuntimeController(config, '2026.10.30.9001', lambda: person)
                try:
                    wait(lambda: controller.runtime is not None)
                    person = {'user_id': 'name-user:'+'b'*64}
                    wait(lambda: controller.state == 'identity_mismatch')
                    factory.return_value.close.assert_called_once()
                    self.assertIsNone(controller.runtime)
                    self.assertEqual(factory.call_count, 1)
                finally: controller.close()

    def test_monitor_origin_is_fixed_and_bad_ca_pin_fails_before_network(self):
        config = {'url': 'https://127.0.0.1:443/api/v1/events'}
        with self.assertRaises(ValueError):
            quote_monitor._monitor_request(config, 'https://other.invalid/api/v1/events', {}, 'a'*43)
        with tempfile.TemporaryDirectory() as root:
            ca = Path(root)/'root.cer'
            ca.write_bytes(b'not a certificate')
            config.update(ca_file=str(ca), ca_sha256='0'*64)
            request = quote_monitor._monitor_request(config, config['url'], {}, 'a'*43)
            with patch.object(quote_monitor.urllib.request, 'build_opener') as opener:
                with self.assertRaisesRegex(ValueError, 'fingerprint'):
                    quote_monitor._monitor_open(request)
                opener.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'DPAPI requires Windows')
    def test_https_test_is_explicit_and_production_cannot_use_loopback_business_http(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root)/'config.json'
            value = {'enabled': False, 'profile': 'https-test', 'environment': 'test', 'app_id': 'ai_quote',
                'user_id': 'TEST-USER', 'device_id': 'TEST-DEVICE', 'app_version': 'test',
                'url': 'https://127.0.0.1:4343/api/v1/events', 'api_url': 'http://127.0.0.1:48087/api/quotes/calculate-dual'}
            secret = {key: value[key] for key in ('app_id','environment','device_id','user_id')}
            secret.update(renewal_id='test', renewal_secret='a'*43)
            settings.save_secret(config.parent/'credential.dpapi', secret)
            settings.atomic_json(config, value)
            self.assertEqual(settings.configuration(config)['environment'], 'test')
            value.update(profile='production', environment='production')
            settings.atomic_json(config, value)
            with self.assertRaises(ValueError): settings.configuration(config)


if __name__ == '__main__': unittest.main()
