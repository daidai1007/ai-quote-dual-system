"""Recovered startup retries use newly provisioned credentials; no real service."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

import verify_name_login as fixture
from verify_name_login import APP, NS, login, person, QTimer
from PySide6.QtWidgets import QDialog


class StartupConfigReload(unittest.TestCase):
    setUp=fixture.LoginTests.setUp
    tearDown=fixture.LoginTests.tearDown
    window=fixture.LoginTests.window

    def test_real_startup_retries_after_config_edit_without_restarting(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'client_config.json'
            config.write_text(json.dumps({'api_url':'https://offline.invalid/api/quotes/calculate-dual','api_key':''}),encoding='utf-8')
            calls=[];errors=[];dialogs=[];phase=[0];deadline=time.monotonic()+8
            def gateway(request,**kwargs):
                self.assertEqual(request.full_url,'https://offline.invalid/api/name-login')
                key=request.get_header('X-ai-quote-key')
                calls.append(key)
                if key!='synthetic-provisioned':
                    raise urllib.error.HTTPError(request.full_url,401,'Unauthorized',{},
                        io.BytesIO(b'{"error":"unauthorized","message":"invalid client access key"}'))
                return io.BytesIO(json.dumps(person('首次登录配置测试人员')).encode('utf-8'))
            def operate():
                dialog=APP.activeModalWidget() if not dialogs else dialogs[0]
                try:
                    self.assertIsInstance(dialog,login.NameLoginDialog)
                    if not dialogs:dialogs.append(dialog)
                    self.assertLess(time.monotonic(),deadline,'startup login timed out')
                    if phase[0]==0:
                        dialog.name.setText('首次登录配置测试人员')
                        dialog.enter.click();phase[0]=1
                    elif dialog.worker is None:
                        if phase[0]==1:
                            self.assertIn('未读取到',dialog.error.text())
                            config.write_text(json.dumps({'api_url':'https://offline.invalid/api/quotes/calculate-dual',
                                                          'api_key':'synthetic-provisioned'}),encoding='utf-8')
                            dialog.enter.click();phase[0]=2
                        elif dialog.result()==QDialog.DialogCode.Accepted:
                            return
                    QTimer.singleShot(10,operate)
                except BaseException as error:
                    errors.append(error)
                    if isinstance(dialog,QDialog):dialog.reject()
            with patch.dict(NS,{'API_URL':'https://offline.invalid/api/quotes/calculate-dual','API_KEY':'',
                                'load_client_config':lambda:json.loads(config.read_text(encoding='utf-8'))}),\
                 patch.dict(os.environ,{'AI_QUOTE_API_KEY':'','AI_QUOTE_API_URL':''}),\
                 patch('urllib.request.urlopen',side_effect=gateway):
                login._required=True
                QTimer.singleShot(0,operate)
                window=self.window()
                self.assertFalse(errors,repr(errors))
                self.assertEqual(calls,[None,'synthetic-provisioned'])
                self.assertEqual(NS['_name_connection_headers']().get('X-AI-Quote-Key'),'synthetic-provisioned')
                self.assertEqual(window._name_user_id,person('首次登录配置测试人员')['person']['user_id'])


if __name__=='__main__':unittest.main(verbosity=2)
