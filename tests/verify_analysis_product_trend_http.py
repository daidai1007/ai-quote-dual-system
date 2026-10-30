"""Native charts through the real name-scoped API and a disposable PostgreSQL."""
from copy import deepcopy
import json,unittest,urllib.request
from pathlib import Path
import verify_contract_management as base
import quote_analysis as ui

class ProductTrendHttpTests(unittest.TestCase):
    setUpClass=classmethod(base.ContractTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ContractTests.tearDownClass.__func__)
    setUp=base.ContractTests.setUp
    api=base.ContractTests.api
    settled=base.ContractTests.settled
    close_window=base.ContractTests.close_window
    configure_template=base.ContractTests.configure_template

    def route(self,path,payload=None):
        request=urllib.request.Request(self.config['base']+'/api'+path,
            data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8'),
            headers={'X-AI-Quote-Key':self.config['key'],'Authorization':'Bearer '+self.config['session']['token'],'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as result:return json.load(result)

    def test_real_frozen_product_totals_actual_contract_trend_and_reopen_leave_workspace_unchanged(self):
        self.configure_template('xlsx')
        self.p.inputs['contract_no'].setText('LOCAL-CHART-CONTRACT')
        self.p.generate();self.settled()
        self.assertIsNotNone(self.p.record,self.p.notice.text());record=deepcopy(self.p.record)
        items=[dict(name='本机JP产品',product_code='JP_SINGLE',quantity=2,quick_discount=1,
          quote_display=dict(name='本机JP产品',quantity=2,unit_price=50,total=100,discount=1)),
          dict(name='本机超宽产品',product_code='JP_WIDE_EXP',quantity=1,quick_discount=1,
          quote_display=dict(name='本机超宽产品',quantity=1,unit_price=80,total=80,discount=1))]
        snapshot=dict(company='本机测试客户 A',document=dict(order_nature='EXTERNAL'),analysis_customer=dict(customer_code='LOCAL-A'),
          scheme_summary=dict(company='本机测试客户 A',quoted_amount=180,product_summary='JP；JP WIDE'),draft_items=items)
        made=self.route('/quote-schemes',dict(snapshot=snapshot,operator_name='本机人员甲'))
        no=made['scheme_no']
        self.route('/quote-schemes/'+no+'/export-result',dict(expected_version=1,operator_name='本机人员甲',kind='XLSX',succeeded=True,snapshot=snapshot))
        before=self.route('/quote-schemes/'+no);workspace=deepcopy(self.w.draft_items)
        page=self.w.quote_analysis_page;page.period.setCurrentIndex(3)
        self.w.show_section(self.w.quote_analysis_route);base.wait(lambda:page.worker is None and page.data is not None)
        groups={r['product_code']:r for r in page.product_chart.rows}
        self.assertEqual(groups['JP']['amount'],'100.00');self.assertEqual(groups['JP']['quantity'],2)
        self.assertEqual(groups['JP WIDE']['amount'],'80.00');self.assertEqual(groups['JP WIDE']['quantity'],1)
        self.assertEqual(sum(r['contract_count'] for r in page.chart.rows),1)
        self.assertTrue(page.data['contract_trend_available']);self.assertEqual(self.route('/quote-schemes/'+no),before)
        page.product_quantity.click();self.assertEqual(page.product_chart.metric,'quantity')
        page.show_product_details('JP WIDE')
        grid=page._detail_dialog.findChild(ui.QTableWidget,'analysisDetailTable')
        self.assertEqual(grid.item(0,4).text(),'¥ 80.00');page._detail_dialog.close()
        output=Path(__file__).resolve().parents[1]/'.codex-tmp'/'product-trend-http-qa';output.mkdir(parents=True,exist_ok=True)
        self.w.resize(1600,1000);base.APP.processEvents()
        page.product_card.grab().save(str(output/'product-card.png'));page.trend_card.grab().save(str(output/'trend-card.png'))
        event=next(r for r in page.data['contract_quoted_details'] if r['event_kind']=='CONTRACT')
        page.show_details('date',event['event_date'])
        grid=page._detail_dialog.findChild(ui.QTableWidget,'analysisDetailTable')
        row=next(i for i in range(grid.rowCount()) if grid.item(i,0).text()=='合同')
        grid.cellDoubleClicked.emit(row,0);self.settled()
        self.assertEqual(self.p.record['record_id'],record['record_id'])
        self.assertEqual(self.p.record['file_sha256'],record['file_sha256'])
        self.assertEqual(self.w.draft_items,workspace)

if __name__=='__main__':unittest.main(verbosity=2)
