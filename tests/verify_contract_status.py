"""Contract state at real Qt entry points, synthetic data and isolated settings."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch, Mock
import unittest
import verify_quote_analysis as fixture
import contract_management as contracts
import quote_scheme_center as schemes
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import QTimer

NO='BJ-20261029-000901'

class ContractStatusTests(unittest.TestCase):
    setUp=fixture.AnalysisTests.setUp
    load=fixture.AnalysisTests.load
    close=fixture.AnalysisTests.close

    def test_all_status_filters_include_contract_and_generation_keeps_prices(self):
        w=self.window
        for combo in (w.quote_scheme_status_filter,w.quote_management.status,self.page.status):
            self.assertGreaterEqual(combo.findData('CONTRACT'),0)
            self.assertEqual(combo.itemText(combo.findData('CONTRACT')),'合同')
        w._quote_scheme_id=NO;w._quote_scheme_status='QUOTED';w._quote_scheme_version=4
        w.draft_items=[{'name':'本机产品','formula':{'cost':173.21},'quick_discount':.75}]
        before=deepcopy(w.draft_items)
        contracts.contract_schemes_changed(w,[dict(scheme_no=NO,status='CONTRACT',lock_version=5)])
        self.assertEqual(w._quote_scheme_status,'CONTRACT');self.assertEqual(w._quote_scheme_version,5)
        self.assertEqual(w.draft_items,before)
        contracts.contract_schemes_changed(w,[dict(scheme_no='OTHER',status='CONTRACT',lock_version=99)])
        self.assertEqual(w._quote_scheme_version,5)

    def test_ledger_scheme_opens_actual_contract_without_loading_cost_workspace(self):
        w=self.window;before=deepcopy(w.draft_items)
        with patch.object(w.contract_management,'open_contract_record') as opened:
            schemes._apply_opened_scheme(w,dict(scheme_no=NO,status='CONTRACT',source_kind='LEDGER_CONTRACT',contract_record_id='synthetic-record'))
            opened.assert_called_once_with('synthetic-record')
        self.assertEqual(w.draft_items,before)
        actions=schemes._row_actions(w,dict(scheme_no=NO,status='CONTRACT',source_kind='LEDGER_CONTRACT'))
        self.addCleanup(actions.deleteLater)
        self.assertEqual([b.text() for b in actions.findChildren(QPushButton)],['查看合同'])

    def test_contract_kpi_drilldown_and_real_status_visuals(self):
        self.load();p=self.page;w=self.window
        data=fixture.response();normal=deepcopy(data['details'][0])
        contract={**normal,'scheme_no':NO,'status':'CONTRACT','source_kind':'LEDGER_CONTRACT','formal_date':None,'contract_amount':'650.30','can_record':False}
        data['details']=[normal,contract];data['recent']=[contract,normal]
        data['summary'].update(schemes=2,contracts=1,contract_amount='650.30')
        p.loaded(data)
        self.assertEqual(p.kpis['contracts'][0].text(),'合同\n1')
        self.assertIn('650.30',p.kpis['contracts'][0].note)
        with patch.object(p,'detail_dialog') as shown:
            p.show_details('contracts')
            self.assertEqual([r['scheme_no'] for r in shown.call_args.args[3]],[NO])
        w.resize(1519,986);fixture.app.processEvents()
        output=Path(__file__).resolve().parents[1]/'.codex-tmp'/'contract-status-qa'
        output.mkdir(parents=True,exist_ok=True)
        w.grab().save(str(output/'analysis-contract.png'))
        row=dict(scheme_no=NO,status='CONTRACT',source_kind='LEDGER_CONTRACT',company_name='本机合同示例客户',product_summary='本机产品',quoted_amount=650.30,version_no=1,creator_name='本机测试人员',last_editor_name='本机测试人员',updated_at='2026-10-29',lock_version=1,can_write=True)
        def start(worker):
            def done():
                worker.succeeded.emit(dict(items=[row],total=1,page=1,page_size=20))
                worker.finished.emit()
            QTimer.singleShot(5,done)
        with patch.object(schemes.QuoteSchemeWorker,'start',start):
            w.show_section(schemes.SCHEME_ROUTE)
            fixture.wait(lambda:w._quote_scheme_list_worker is None)
        self.assertEqual(w.quote_scheme_table.item(0,3).text(),'合同')
        fixture.app.processEvents()
        w.grab().save(str(output/'scheme-contract.png'))

if __name__=='__main__':unittest.main()
