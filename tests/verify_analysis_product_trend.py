"""Approved native layout and interactions using actual API aggregation output."""
from copy import deepcopy
import json,os,shutil,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import verify_quote_analysis as fixture
import quote_scheme_center as schemes
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

ROOT=Path(__file__).resolve().parents[1]

def response(customer='',product=''):
    command="import {chartFixture} from './tests/helpers/analysis_product_fixture.mjs'; process.stdout.write(JSON.stringify(chartFixture(JSON.parse(process.argv[1]))));"
    return json.loads(subprocess.check_output([shutil.which('node'),'--input-type=module','-e',command,json.dumps({'customer':customer,'product':product})],cwd=ROOT,text=True,encoding='utf-8'))

class ProductTrendTests(unittest.TestCase):
    load=fixture.AnalysisTests.load
    close=fixture.AnalysisTests.close
    def setUp(self):
        fixture.AnalysisTests.setUp(self)
        def actual_filters(*_):
            params=parse_qs(urlsplit(self.requests[-1][0]).query)
            return response(params.get('customer',[''])[0],params.get('product',[''])[0])
        p=patch.object(fixture,'response',actual_filters);p.start();self.addCleanup(p.stop)
        self.output=ROOT/'.codex-tmp'/'product-trend-qa';self.output.mkdir(parents=True,exist_ok=True)

    def test_actual_api_groups_metric_switch_keyboard_drilldown_and_contract_open(self):
        self.load();p=self.page
        self.assertEqual(len(p.product_chart.rows),6)
        self.assertIn('17 台',p.product_scope.text());self.assertIn('2,100.00',p.product_scope.text())
        self.assertEqual(p.product_chart.buttons[0].row['product_code'],'JP')
        p.product_quantity.click()
        self.assertEqual(p.product_chart.metric,'quantity');self.assertTrue(p.product_quantity.isChecked());self.assertFalse(p.product_amount.isChecked())
        p.product_quantity.click();self.assertTrue(p.product_quantity.isChecked(),'one display metric must stay selected')
        fixture.app.processEvents()
        target=next(b for b in p.product_chart.buttons if b.row['product_code']=='JP WIDE')
        target.setFocus();QTest.keyClick(target,Qt.Key.Key_Return);fixture.app.processEvents()
        grid=p._detail_dialog.findChild(fixture.ui.QTableWidget,'analysisDetailTable')
        self.assertEqual(grid.rowCount(),1);self.assertEqual(grid.item(0,3).text(),'2');self.assertEqual(grid.item(0,4).text(),'¥ 300.00')
        with patch.object(schemes,'_open_scheme') as opened:
            grid.cellDoubleClicked.emit(0,0);opened.assert_called_once_with(self.window,'BJ-20261029-000901')
        self.assertIn('合同',p.chart.accessibleName());self.assertNotIn('新建',p.chart.accessibleName())
        p.show_details('date','2026-10-28')
        grid=p._detail_dialog.findChild(fixture.ui.QTableWidget,'analysisDetailTable')
        self.assertEqual(grid.item(0,0).text(),'合同')
        with patch.object(self.window.contract_management,'open_contract_record') as opened:
            grid.cellDoubleClicked.emit(0,0);opened.assert_called_once_with('synthetic-contract-a')

    def test_filters_empty_missing_metadata_failure_and_old_api_never_show_stale_bars(self):
        self.load();p=self.page
        before=deepcopy(self.window.draft_items)
        p.product.setCurrentIndex(p.product.findData('JS WIDE'));fixture.wait(lambda:p.worker is None)
        self.assertEqual([r['product_code'] for r in p.product_chart.rows],['JS WIDE'])
        self.assertIn('200.00',p.product_scope.text());self.assertIn('1 台',p.product_scope.text())
        p.product.setCurrentIndex(p.product.findData('JA'));fixture.wait(lambda:p.worker is None)
        self.assertEqual(p.product_chart.buttons,[]);self.assertTrue(p.product_chart.empty.isVisible())
        data=response();data['product_breakdown'][0].update(amount=None,quantity=None,amount_coverage=0,quantity_coverage=0)
        p.loaded(data);self.assertIn('缺失',p.product_scope.text())
        self.assertIn('—',p.product_chart.buttons[-1].toolTip())
        self.hold=True;p.reload();self.assertEqual(p.product_chart.rows,[])
        self.error='本机连接失败';self.held.pop()();fixture.wait(lambda:p.worker is None)
        self.assertEqual(p.product_chart.rows,[]);self.assertIsNone(p.data)
        old=response();old.pop('product_breakdown');old.pop('contract_quoted_trend');old.pop('contract_quoted_details')
        p.loaded(old);self.assertIn('更新配套 API',p.product_scope.text());self.assertEqual(p.chart.rows,[])
        self.assertEqual(self.window.draft_items,before)

    def test_scheme_one_full_width_native_layout_and_scaling(self):
        self.load();p=self.page;w=self.window
        for width in (1600,1366,1024):
            w.resize(width,1000);fixture.app.processEvents();QTest.qWait(40)
            if width>=1500:
                self.assertEqual(p.dashboard_grid.itemAtPosition(1,0).widget(),p.product_card)
                self.assertEqual(p.dashboard_grid.itemAtPosition(1,2).widget(),p.product_card)
            self.assertGreater(p.product_card.mapTo(p.overview,p.product_card.rect().topLeft()).y(),p.trend_card.mapTo(p.overview,p.trend_card.rect().bottomLeft()).y())
            for button in p.product_chart.buttons:self.assertGreater(button.width(),200)
            w.grab().save(str(self.output/f'overview-{os.getenv("QT_SCALE_FACTOR","1")}-{width}.png'))
        w.resize(1600,1000);fixture.app.processEvents()
        p.product_card.grab().save(str(self.output/f'product-card-{os.getenv("QT_SCALE_FACTOR","1")}.png'))
        p.trend_card.grab().save(str(self.output/f'trend-card-{os.getenv("QT_SCALE_FACTOR","1")}.png'))
        p.tabs.setCurrentIndex(1);fixture.app.processEvents();p.tabs.setCurrentIndex(0);fixture.app.processEvents()
        self.assertTrue(p.product_card.isVisible())

if __name__=='__main__':unittest.main(verbosity=2)
