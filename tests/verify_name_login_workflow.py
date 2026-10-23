"""Ordinary name completes the existing real Qt -> real XLSX regression.
Business transports are synthetic and offline, exactly as the base workflow.
"""
import hashlib
import unittest
import verify_quote_analysis_full_workflow as workflow
import name_login

class NameWorkflow(workflow.FullWorkflow):
 def setUp(self):
  name='首次报价的普通测试人员'
  name_login.set_session(dict(token='T'*43,expires_at='2030-01-01T00:00:00+00:00',person=dict(
   user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),display_name=name,
   scope='OWN',can_view_all_quotes=False,identity_mode='NAME_ONLY')))
 def tearDown(self):name_login._state=None

if __name__=='__main__':unittest.main(verbosity=2)
