"""Ordinary name completes the existing real Qt -> real XLSX regression.
Business transports are synthetic and offline, exactly as the base workflow.
"""
import hashlib
import unittest
from copy import deepcopy
from unittest.mock import patch
import verify_quote_analysis_full_workflow as workflow
import name_login

class NameWorkflow(workflow.FullWorkflow):
 def setUp(self):
  name='首次报价的普通测试人员'
  name_login.set_session(dict(token='T'*43,expires_at='2030-01-01T00:00:00+00:00',person=dict(
   user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),display_name=name,
   scope='OWN',can_view_all_quotes=False,identity_mode='NAME_ONLY')))
 def tearDown(self):name_login._state=None

class RevisionWorkflow(NameWorkflow):
 def setUp(self):
  name='戴晨丽'
  name_login.set_session(dict(token='R'*43,expires_at='2030-01-01T00:00:00+00:00',person=dict(
   user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),display_name=name,
   scope='ALL',can_view_all_quotes=True,identity_mode='NAME_ONLY')))

 def test_product_to_actual_xlsx_with_analysis_installed(self):
  import quote_scheme_center as schemes
  original=workflow.reg.ExportRegistration
  reopened=[]
  def fixture():
   harness=original();setup=harness.setUp
   def initialize():
    setup();w=harness.window;harness.server['can_write']=True
    generate=harness.controller.generate
    def revise_then_generate():
     snapshot=schemes._snapshot(w)
     snapshot['_name_workspace_scope']={'owner_user_id':'old-local-identity','read_only':True}
     harness.server.update(status='REVISING',snapshot=deepcopy(snapshot),can_write=True)
     schemes._apply_opened_scheme(w,deepcopy(harness.server),route=workflow.ui.COST_ROUTE)
     self.assertFalse(w._name_scope_foreign);self.assertFalse(w._quote_scheme_read_only)
     self.assertEqual(w._quote_scheme_status,'REVISING');reopened.append(True)
     generate()
    w.scheme2_cost_generate.clicked.disconnect();w.scheme2_cost_generate.clicked.connect(revise_then_generate)
   harness.setUp=initialize
   return harness
  with patch.object(workflow.reg,'ExportRegistration',side_effect=fixture):
   workflow.FullWorkflow.test_product_to_actual_xlsx_with_analysis_installed(self)
  self.assertEqual(reopened,[True])

class GlobalOperatorsWorkflow(unittest.TestCase):
 def test_all_three_generate_print_snapshot_and_actual_xlsx_for_foreign_revision(self):
  import quote_scheme_center as schemes
  original=workflow.reg.ExportRegistration
  for name in ['戴晨丽','姜艳娟','翟晓峰']:
   with self.subTest(name=name):
    name_login.set_session(dict(token='G'*43,expires_at='2030-01-01T00:00:00+00:00',person=dict(
     user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),display_name=name,
     scope='ALL',can_view_all_quotes=True,can_manage_all_quotes=True,identity_mode='NAME_ONLY')))
    case=workflow.FullWorkflow('test_product_to_actual_xlsx_with_analysis_installed');reopened=[]
    def fixture():
     harness=original();setup=harness.setUp
     def initialize():
      setup();w=harness.window;harness.server.update(can_write=True,creator_user_id='foreign-original-owner',creator_name='本机原创建人')
      self.assertIn('全部报价 · 可操作',w.name_scope_label.text());generate=harness.controller.generate
      def reopen():
       saved=schemes._snapshot(w);saved['_name_workspace_scope']={'owner_user_id':'foreign-original-owner','read_only':True}
       harness.server.update(status='REVISING',snapshot=deepcopy(saved))
       schemes._apply_opened_scheme(w,deepcopy(harness.server),route=workflow.ui.COST_ROUTE)
       self.assertFalse(w._name_scope_foreign);self.assertFalse(w._quote_scheme_read_only);reopened.append(True);generate()
      w.scheme2_cost_generate.clicked.disconnect();w.scheme2_cost_generate.clicked.connect(reopen)
     harness.setUp=initialize
     return harness
    try:
     with patch.object(workflow.reg,'ExportRegistration',side_effect=fixture):case.test_product_to_actual_xlsx_with_analysis_installed()
     self.assertEqual(reopened,[True])
    finally:case.doCleanups();name_login._state=None

if __name__=='__main__':unittest.main(verbosity=2)
