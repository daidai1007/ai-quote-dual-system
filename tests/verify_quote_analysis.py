"""Real Qt analysis route: async scope changes, failure, drilldown, close and result registration.

Synthetic service responses only; no installed configuration or user documents.
"""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"desktop_client"))
from PySide6.QtCore import QTimer, QRect, QSignalBlocker
from PySide6.QtGui import QCloseEvent, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QDialogButtonBox
import quote_analysis as ui
import quote_scheme_center as schemes
import v3_launcher

app=QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns=v3_launcher.load_v3_namespace()
ns['install_application_font'](app)
PRODUCT_TYPES=('JA','JC','JE','JK','JM','JP','JP WIDE','JQ','JS','JS WIDE','操作台')

def wait(predicate):
    end=time.monotonic()+8
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Qt analysis condition timed out')

def response(customer='',product='JP'):
    band=dict(key='1',label='0.80–<0.85',won=24,lost=6,sample=30,rate=80.0,eligible=True)
    row=dict(scheme_no='BJ-20261021-000001',customer_code='A',customer_name='本机示例客户 A',
             status='QUOTED',formal_date='2026-10-21',created_date='2026-10-21',formal_version=1,can_record=True,
             amount='200.20',creator='测试',updated_at='2026-10-21',products=[dict(product_code='JP',product_name='JP',amount='200.20')])
    comparison=lambda code,name:{'name':name,'sample':30,'best':[band],code[0]:code[1]}
    return dict(product_filter_mode='family-v1',summary=dict(schemes=1,quoted=1,drafts=0,amount='200.20',average='200.20',amount_coverage=1,active_customers=1,failures=0),
        customers=[dict(code='A',name='本机示例客户 A'),dict(code='B',name='本机示例客户 B')],
        products=[dict(code='JP',name='JP'),dict(code='JE',name='JE')],outcomes_available=True,
        trend=[dict(date='2026-10-21',count=1)],ranking=[dict(customer_code='A',name='本机示例客户 A',amount='200.20',count=1)],
        costs={'material_cost':'20.00'},cost_coverage=1,recent=[row],details=[row],failures=[],outcome_records=[],
        discount=dict(product_code=product or 'JP',sample=30,bands=[band],best=[band],records=[],
            customer_comparison=[comparison(('customer_code','A'),'本机示例客户 A'),comparison(('customer_code','B'),'本机示例客户 B')],
            product_comparison=[comparison(('product_code','JP'),'JP'),comparison(('product_code','JE'),'JE')]))

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='quote-analysis-ui-')
        self.addCleanup(self.temp.cleanup)
        self.requests=[]
        self.error=None
        self.held=[]
        self.hold=False
        def start(worker):
            self.requests.append((worker.url,deepcopy(worker.payload)))
            def done():
                if self.error:worker.failed.emit(self.error)
                elif worker.payload is not None:worker.succeeded.emit({'recorded':True,'revision':1})
                else:
                    params=urllib.parse.parse_qs(urllib.parse.urlsplit(worker.url).query)
                    worker.succeeded.emit(response(params.get('customer',[''])[0],params.get('product',['JP'])[0]))
                worker.finished.emit()
            if self.hold:self.held.append(done)
            else:QTimer.singleShot(5,done)
        for p in (patch.dict(os.environ,LOCALAPPDATA=self.temp.name),
                  patch.object(ns['MainWindow'],'load_catalogs',lambda *_:None),
                  patch.object(ns['MainWindow'],'refresh_formula_inputs',lambda *_:None),
                  patch.object(ui.AnalysisWorker,'start',start)):
            p.start();self.addCleanup(p.stop)
        self.window=ns['MainWindow']()
        with QSignalBlocker(self.window.product_combo):
            self.window.product_combo.clear()
            self.window.product_combo.addItem('请选择产品',None)
            for name in PRODUCT_TYPES:self.window.product_combo.addItem(name,name)
        class Screen:
            def availableGeometry(self):return QRect(0,0,1920,1080)
        self.window.screen=lambda:Screen()
        self.window.resize(1366,900)
        self.window.show()
        self.page=self.window.quote_analysis_page
        self.addCleanup(self.close)

    def close(self):
        for done in self.held:done()
        self.held.clear()
        app.processEvents()
        self.window._quote_scheme_save_timer.stop()
        self.window._quote_scheme_id=''
        self.window._scheme2_dirty=False
        self.window.close()
        app.processEvents()

    def load(self):
        self.window.show_section(self.window.quote_analysis_route)
        wait(lambda:self.page.worker is None)

    def test_fifth_route_is_lazy_async_and_keeps_working_quote_state(self):
        self.assertEqual(self.requests,[])
        self.window.draft_items=[{'name':'本机未完成产品','quick_discount':.85}]
        before=deepcopy(self.window.draft_items)
        self.load()
        self.assertEqual([b.text() for b in self.window.nav_buttons],['选型配置','成本计算','报价单管理','报价方案','报价分析','合同管理'])
        self.assertEqual(sum(b.isChecked() for b in self.window.nav_buttons),1)
        self.assertEqual(self.window.draft_items,before)
        self.assertEqual(self.page.recent.rowCount(),1)
        self.assertEqual(self.page.customer.count(),3)
        with patch.object(schemes,'_open_scheme') as opened:
            self.page.open_recent(0)
            opened.assert_called_once_with(self.window,'BJ-20261021-000001')
        self.window.show_section(1)
        self.assertEqual(self.window.draft_items,before)
        self.assertFalse(self.window.quote_analysis_nav_button.isChecked())
        self.assertEqual(self.window.findChild(ui.QScrollArea,'mainScroll').widget().maximumHeight(),16777215)

    def test_customer_product_selection_comparisons_and_reset(self):
        self.load()
        self.page.customer.setCurrentIndex(self.page.customer.findData('A'))
        wait(lambda:self.page.worker is None)
        self.assertIn('customer=A',self.requests[-1][0])
        self.page.pick_discount_product(1)
        wait(lambda:self.page.worker is None)
        self.assertIn('customer=A',self.requests[-1][0])
        self.assertIn('product=JE',self.requests[-1][0])
        self.page.pick_discount_customer(1)
        wait(lambda:self.page.worker is None)
        self.assertIn('customer=B',self.requests[-1][0])
        self.assertIn('product=JE',self.requests[-1][0])
        self.page.reset()
        wait(lambda:self.page.worker is None)
        self.assertEqual(self.page.customer.currentData(),'')
        self.assertEqual(self.page.product.currentData(),'')

    def test_product_selectors_mirror_all_configuration_types_not_observed_codes(self):
        self.load()
        p=self.page
        expected=['全部产品',*PRODUCT_TYPES]
        for combo in (p.product,p.discount_product):
            self.assertEqual([combo.itemText(i) for i in range(combo.count())],expected)
            self.assertFalse(combo.isEditable())
        source_value=self.window.product_combo.currentData()
        # A type without historical records must remain selectable after each
        # response, even when result.products contains only the old subset.
        p.product.setCurrentIndex(p.product.findData('JC'))
        wait(lambda:p.worker is None)
        self.assertEqual(p.product.currentData(),'JC')
        self.assertIn('product=JC',self.requests[-1][0])
        self.assertEqual(self.window.product_combo.currentData(),source_value)
        p.tabs.setCurrentIndex(1)
        for name in ('JP WIDE','JQ','JS WIDE','操作台'):
            p.discount_product.setCurrentIndex(p.discount_product.findData(name))
            wait(lambda:p.worker is None)
            self.assertEqual(p.product.currentData(),name)
            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(self.requests[-1][0]).query)['product'],[name])
        # Capture the actual popup, not a drawing of the intended UI.
        output=ROOT/'outputs/quote-analysis-qa'
        output.mkdir(parents=True,exist_ok=True)
        for label,combo in (('top',p.product),('discount',p.discount_product)):
            combo.showPopup();app.processEvents()
            self.assertTrue(combo.view().window().grab().save(str(output/f'products-{label}-{os.getenv("QT_SCALE_FACTOR","1")}.png')))
            combo.hidePopup()
        p.reset();wait(lambda:p.worker is None)
        self.assertEqual(p.product.currentData(),'')
        self.assertEqual([p.product.itemText(i) for i in range(p.product.count())],expected)

    def test_product_selectors_follow_async_catalogue_without_query_storms(self):
        self.load()
        p=self.page
        p.product.setCurrentIndex(p.product.findData('JQ'))
        wait(lambda:p.worker is None)
        before=len(self.requests)
        with QSignalBlocker(self.window.product_combo):
            self.window.product_combo.clear()
            for name in reversed(PRODUCT_TYPES):self.window.product_combo.addItem(name,name)
        wait(lambda:not p.product_sync.isActive())
        self.assertEqual([p.product.itemText(i) for i in range(p.product.count())],['全部产品',*reversed(PRODUCT_TYPES)])
        self.assertEqual(p.product.currentData(),'JQ')
        self.assertEqual(p.discount_product.currentData(),'JQ')
        self.assertEqual(len(self.requests),before)
        self.window.product_combo.removeItem(self.window.product_combo.findData('JQ'))
        wait(lambda:not p.product_sync.isActive() and p.worker is None and len(self.requests)==before+1)
        self.assertEqual(p.product.currentData(),'')
        self.assertNotIn('product',urllib.parse.parse_qs(urllib.parse.urlsplit(self.requests[-1][0]).query))

    def test_removed_product_during_query_discards_stale_scope_and_reloads_once(self):
        self.load()
        p=self.page
        p.product.setCurrentIndex(p.product.findData('JQ'))
        wait(lambda:p.worker is None)
        self.hold=True
        p.reload()
        before=len(self.requests)
        self.window.product_combo.removeItem(self.window.product_combo.findData('JQ'))
        wait(lambda:p.pending_reload and p.product.currentData()=='')
        self.assertIsNone(p.data)
        self.hold=False
        self.held.pop()()
        wait(lambda:p.worker is None and len(self.requests)==before+1)
        self.assertNotIn('product',urllib.parse.parse_qs(urllib.parse.urlsplit(self.requests[-1][0]).query))
        self.assertEqual(p.data['discount']['product_code'],'JP')

    def test_old_api_product_semantics_are_not_shown_as_current_statistics(self):
        self.load()
        data=response();data.pop('product_filter_mode')
        self.page.loaded(data)
        self.assertIsNone(self.page.data)
        self.assertIn('部署配套 API',self.page.notice.text())
        self.assertEqual(self.page.recent.rowCount(),0)
        self.assertFalse(self.page.record_button.isEnabled())

    def test_approved_layout_hierarchy_cards_charts_and_local_dimensions(self):
        self.load()
        self.window.resize(1600,1000)
        app.processEvents()
        p=self.page
        self.assertLess(p.tabs.mapTo(p,p.tabs.rect().bottomLeft()).y(),p.filter_card.mapTo(p,p.filter_card.rect().topLeft()).y())
        self.assertEqual(p.dashboard_grid.itemAtPosition(0,0).widget(),p.trend_card)
        self.assertEqual(p.dashboard_grid.itemAtPosition(0,1).widget(),p.ranking_card)
        self.assertEqual(p.dashboard_grid.itemAtPosition(0,2).widget(),p.cost_card)
        self.assertLessEqual(p.chart.height(),200)
        self.assertGreaterEqual(p.kpis['amount'][0].height(),96)
        self.assertLess(p.recent.y(),80,'recent table must sit immediately below its heading')
        self.assertIsInstance(p.costs,ui.CostDonut)
        self.assertIsInstance(p.ranking,ui.CustomerRankChart)
        p.costs.selected.emit()
        cost_table=p._detail_dialog.findChild(ui.QTableWidget,'analysisDetailTable')
        self.assertEqual(cost_table.item(0,1).text(),'¥ 20.00')
        p._detail_dialog.close()
        self.assertFalse(p.extra_filters.isVisible())
        p.more_button.click();app.processEvents()
        self.assertTrue(p.extra_filters.isVisible())
        p.tabs.setCurrentIndex(1)
        p.discount_customer.setCurrentIndex(p.discount_customer.findData('B'))
        wait(lambda:p.worker is None)
        self.assertEqual(p.customer.currentData(),'B')
        p.discount_product.setCurrentIndex(p.discount_product.findData('JE'))
        wait(lambda:p.worker is None)
        self.assertEqual(p.product.currentData(),'JE')
        self.assertIn('customer=B',self.requests[-1][0])
        self.assertIn('product=JE',self.requests[-1][0])
        self.assertGreaterEqual(p.best_metric.height(),86)
        self.assertIsNotNone(p.bands.cellWidget(0,4))
        self.assertEqual(p.bands.item(0,4).text(),'','rate text must appear only beside the bar, never beneath it')

    def test_failure_clears_stale_values_and_close_waits_for_request(self):
        self.load()
        self.hold=True
        self.page.reload()
        self.assertIsNone(self.page.data)
        self.assertEqual(self.page.recent.rowCount(),0)
        event=QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.error='本机模拟离线'
        self.held.pop()()
        wait(lambda:self.page.worker is None)
        self.assertIn('离线',self.page.notice.text())
        self.assertEqual(self.page.kpis['amount'][0].text(),'报价总金额\n—')
        self.assertFalse(self.page.record_button.isEnabled())
        self.error=None;self.hold=False
        self.page.reload();wait(lambda:self.page.worker is None)
        self.assertIsNotNone(self.page.data)

    def test_outcome_registration_separate_from_prices_and_requires_identity(self):
        self.load()
        self.page.record_dialog()
        dialog=self.page._record_dialog
        edits=dialog.findChildren(QLineEdit)
        opportunity=next(e for e in edits if e.placeholderText().startswith('必须填写'))
        opportunity.setText('LOCAL-OPPORTUNITY')
        actor=next(e for e in edits if e.maxLength()==100)
        actor.setText('本机测试人员')
        buttons=dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Save).click()
        wait(lambda:self.page.worker is None and len(self.requests)>=3)
        post=next(payload for url,payload in self.requests if payload is not None)
        self.assertEqual(post['customer_code'],'A')
        self.assertEqual(post['product_code'],'JP')
        self.assertEqual(post['opportunity_key'],'LOCAL-OPPORTUNITY')
        self.assertNotIn('discount',post)
        self.assertNotIn('amount',post)

    def test_no_outcomes_empty_and_screens_at_multiple_sizes(self):
        self.load()
        data=response();data['outcomes_available']=False
        self.page.loaded(data)
        self.assertFalse(self.page.record_button.isEnabled())
        self.assertIn('迁移',self.page.notice.text())
        data['outcomes_available']=True
        data['discount'].update(sample=0,best=[],records=[])
        self.page.loaded(data)
        self.assertIn('暂无',self.page.best.text())
        output=ROOT/'outputs/quote-analysis-qa'
        output.mkdir(parents=True,exist_ok=True)
        self.page.loaded(response())
        for width,height in ((1920,1080),(1560,910),(1366,900),(1092,614),(910,512)):
            self.window.resize(width,height)
            app.processEvents()
            for tab in (0,1):
                self.page.tabs.setCurrentIndex(tab);app.processEvents()
                self.assertTrue(self.page.rect().contains(self.page.query_button.geometry().center()))
                self.assertTrue(self.page.tabs.isVisible())
                # A scaled global QSS minimum must not override the analytics
                # field's fixed height and paint below its parent (DPI 125%+).
                for editor in (self.page.period,self.page.customer,self.page.product,
                               self.page.status,self.page.creator,
                               self.page.discount_customer,self.page.discount_product):
                    if not editor.isVisibleTo(self.page):
                        continue
                    self.assertEqual(editor.height(),ui.METRICS['field_height'])
                    self.assertLessEqual(editor.minimumHeight(),editor.maximumHeight())
                    self.assertTrue(editor.parentWidget().rect().contains(editor.geometry()),
                                    (editor.objectName(),editor.geometry(),editor.parentWidget().rect()))
                origin=self.page.mapTo(self.window,self.page.rect().topLeft())
                self.assertLess(origin.y(),60,'analysis must start at the top, not in a legacy tall canvas')
                main=self.window.findChild(ui.QScrollArea,'mainScroll')
                wait(lambda:self.page.mapTo(self.window,self.page.rect().bottomRight()).y()<=self.window.height()+2)
                self.assertEqual(main.verticalScrollBarPolicy(),ui.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.window.grab().save(str(output/f'analysis-{os.getenv("QT_SCALE_FACTOR","1")}-{width}-{tab}.png'))

if __name__=='__main__':unittest.main(verbosity=2)
