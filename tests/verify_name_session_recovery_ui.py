"""Recovered Qt keeps unfinished work and all existing worker transports resume."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import verify_name_login as fixture
from verify_name_login import login, NS, APP, person, centre
from quote_analysis import AnalysisWorker
from contract_management import ContractWorker

SCHEME_RUN = centre.QuoteSchemeWorker.run


class RecoveryUI(unittest.TestCase):
    setUp = fixture.LoginTests.setUp
    tearDown = fixture.LoginTests.tearDown
    window = fixture.LoginTests.window

    def test_expired_session_resumes_api_scheme_analysis_and_contract_workers_without_replacing_window(self):
        original = person('保留工作区的本机测试人员')
        login.set_session(original)
        window = self.window()
        window.base_url = lambda: 'http://127.0.0.1:12345'
        login._recovery.register(window.base_url())
        window.model_edit.setText('未保存的图号')
        window.quote_spec_edit.setText('1350*400*(1800+200)')
        window.cabinet_body_thickness_spin.setValue(2)
        window.draft_items = [{'name': '未保存柜体', 'quantity': 3, 'remark': '人工备注需要保留'}]
        window.attachments = [{'item_name': '玻璃门', 'manual_inputs': {'宽度': 735, '高度': 1690}, 'quantity': 2}]
        window._scheme2_dirty = True
        window._quote_scheme_pending_export = {'path': '本机待导出.xlsx', 'version': 3}
        before = deepcopy((window.draft_items, window.attachments, window._quote_scheme_pending_export))
        epoch = login.identity_epoch()
        renewed = deepcopy(original)
        renewed['token'] = 'R' * 43
        login_calls, accepted = [], []

        def gateway(request, *args, **kwargs):
            if request.full_url.endswith('/api/name-login'):
                login_calls.append(json.loads(request.data))
                return io.BytesIO(json.dumps(renewed).encode())
            if request.get_header('Authorization') != 'Bearer ' + renewed['token']:
                raise urllib.error.HTTPError(request.full_url, 401, 'expired', {},
                    io.BytesIO(b'{"error":"name_session_required"}'))
            accepted.append(request.full_url)
            return io.BytesIO(b'{"items":[],"total":0,"found":false}')

        # Construct all workers before renewal: each captures the old token.
        workers = [
            NS['ApiWorker'](window.base_url() + '/api/orders/workspace/load', {'order_number': 'local'}, window),
            centre.QuoteSchemeWorker('GET', window.base_url() + '/api/quote-schemes', NS['api_headers'](), parent=window),
            AnalysisWorker(window, '/api/quote-analysis'),
            ContractWorker(window, '/api/contracts/bootstrap'),
        ]
        loaded, failures = [], []
        for worker in workers:
            worker.succeeded.connect(loaded.append)
            worker.failed.connect(failures.append)
        with patch.object(login._recovery, 'open_request', gateway), \
                patch('urllib.request.urlopen', login._recovery), \
                patch.object(centre.QuoteSchemeWorker, 'run', SCHEME_RUN), \
                patch.object(login.NameLoginDialog, 'exec', side_effect=AssertionError('No manual name prompt expected')):
            for worker in workers:
                worker.start()
                self.assertTrue(worker.wait(5000))
                APP.processEvents()
        self.assertEqual(failures, [])
        self.assertEqual(len(loaded), 3)  # Contract worker stores its result for its completion callback.
        self.assertEqual(workers[-1].result, {'items': [], 'total': 0, 'found': False})
        self.assertEqual(len(accepted), 4)
        self.assertEqual(login_calls, [{'name': original['person']['display_name']}])
        self.assertEqual(login.identity_epoch(), epoch)
        self.assertEqual(login.user_id(), original['person']['user_id'])
        self.assertEqual(login.session()['token'], renewed['token'])
        self.assertEqual((window.draft_items, window.attachments, window._quote_scheme_pending_export), before)
        self.assertEqual(window.model_edit.text(), '未保存的图号')
        self.assertEqual(window.quote_spec_edit.text(), '1350*400*(1800+200)')
        self.assertEqual(window.cabinet_body_thickness_spin.value(), 2)
        self.assertTrue(window._scheme2_dirty)
        self.assertTrue(login.window_is_current(window))
        self.assertFalse(getattr(window, '_name_session_closed', False))
        window._quote_scheme_pending_export = None


if __name__ == '__main__':
    unittest.main(verbosity=2)
