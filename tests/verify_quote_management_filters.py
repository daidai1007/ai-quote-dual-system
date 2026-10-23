"""Real Qt quotation filters with offline transport and synthetic records."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
TEMP=tempfile.TemporaryDirectory(prefix='qm-filters-')
os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=TEMP.name
os.environ['AI_QUOTE_UPDATE_CONFIG']=str(Path(TEMP.name)/'updates.json')
Path(os.environ['AI_QUOTE_UPDATE_CONFIG']).write_text('{}',encoding='utf-8')

from PySide6.QtCore import QDate, QSettings, QRect, QSignalBlocker, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QRadioButton, QStyle, QStyleOptionButton
import quote_scheme_center as centre
import scheme2_ui as ui
import v3_launcher

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,TEMP.name)
APP=QApplication.instance() or QApplication([])
NS=v3_launcher.load_v3_namespace();NS['install_application_font'](APP)
NS['MainWindow'].load_catalogs=lambda self:None
NS['ApiWorker'].run=lambda self:self.failed.emit('offline test')
OUT=Path(os.environ.get('AI_QUOTE_FILTER_SCREENSHOT_DIR',str(ROOT/'test-output'/'quote-filters-screenshots')))


def wait(predicate,seconds=5):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        APP.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Offline Qt request timed out')


class QuoteFilters(unittest.TestCase):
    def setUp(self):
        self.requests=[]
        def run(worker):
            self.requests.append(parse_qs(urlparse(worker.url).query))
            worker.succeeded.emit(dict(total=21,items=[dict(scheme_no='BJ-20261022-000001',company_name='合成测试客户',
                product_summary='JQ',creator_name='测试创建人',last_editor_name='测试更新人',status='QUOTED',order_nature='EXTERNAL',
                version_no=1,lock_version=1,quoted_amount=1234.56,updated_at='2026-10-21T16:30:00+00:00')]))
        self.worker=patch.object(centre.QuoteSchemeWorker,'run',run);self.worker.start()
        self.network=patch('urllib.request.urlopen',side_effect=AssertionError('External network forbidden'));self.network.start()
        screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        self.screen=patch.object(NS['MainWindow'],'screen',return_value=screen);self.screen.start()
        self.w=NS['MainWindow']();self.m=self.w.quote_management
        self.w.resize(1510,960);self.w.show();ui._set_nav_collapsed(self.w,False,manual=True)
        with QSignalBlocker(self.w.product_combo):
            self.w.product_combo.clear();self.w.product_combo.addItem('请选择产品',None)
            for name in ('JQ','JE','JP'):self.w.product_combo.addItem(name,name+'_TEST')
        wait(lambda:self.m.filters['product'].count()==4)
        self.m.show_list();self.loaded()

    def loaded(self):wait(lambda:not self.w._quote_scheme_workers and self.m.list_table.rowCount()==1)

    def tearDown(self):
        wait(lambda:not self.w._quote_scheme_workers)
        self.w._quote_scheme_save_timer.stop();self.w._quote_scheme_id='';self.w._scheme2_dirty=False
        self.w.close();self.w.deleteLater();APP.processEvents()
        self.worker.stop();self.network.stop();self.screen.stop()

    def test_default_combined_query_pagination_and_reset(self):
        self.assertEqual(self.requests[-1],dict(page=['1'],page_size=['20'],status=['QUOTED']))
        values=dict(scheme_no='BJ-20261022',company='合成测试客户',creator='测试创建人',
                    updated_from='2026-10-01',updated_to='2026-10-22')
        for key,value in values.items():self.m.filters[key].setText(' '+value+' ')
        product=self.m.filters['product'];product.setCurrentIndex(product.findData('JQ'))
        self.m.query_button.click();self.loaded()
        expected={key:[value] for key,value in values.items()}
        expected.update(product=['JQ'],status=['QUOTED'],page=['1'],page_size=['20'])
        self.assertEqual(self.requests[-1],expected)
        self.m.next_page.click();self.loaded();expected['page']=['2'];self.assertEqual(self.requests[-1],expected)
        self.m.status.setCurrentIndex(self.m.status.findData('VOID'))
        self.m.reset_button.click();self.loaded()
        self.assertEqual(self.requests[-1],dict(page=['1'],page_size=['20'],status=['QUOTED']))
        self.m.status.setCurrentIndex(self.m.status.findData(''));self.m.query_button.click();self.loaded()
        self.assertNotIn('status',self.requests[-1])

    def test_dates_calendar_invalid_inputs_and_single_bound(self):
        start,end=self.m.filters['updated_from'],self.m.filters['updated_to']
        self.assertEqual(start.placeholderText(),'请选择日期');self.assertEqual(end.text(),'')
        start._show_calendar();APP.processEvents()
        self.assertTrue(start.calendar_popup.isVisible());self.assertEqual(start.calendar.selectedDate(),QDate.currentDate())
        start._selected(QDate(2026,10,22));self.assertEqual(start.text(),'2026-10-22')
        for invalid in ('2026-02-30','2026-1-01','not-a-date'):
            before=len(self.requests);start.setText(invalid);self.m.query_button.click();APP.processEvents()
            self.assertEqual(len(self.requests),before);self.assertIn('有效日期',self.m.list_status.text())
        start.setText('2026-10-23');end.setText('2026-10-22')
        before=len(self.requests);self.m.query_button.click();APP.processEvents()
        self.assertEqual(len(self.requests),before);self.assertIn('开始日期不能晚于',self.m.list_status.text())
        start.clear();self.m.query_button.click();self.loaded()
        self.assertEqual(self.requests[-1]['updated_to'],['2026-10-22']);self.assertNotIn('updated_from',self.requests[-1])

    def test_enter_catalog_refresh_and_beijing_display(self):
        self.assertEqual(self.m.list_table.item(0,6).text(),'测试更新人\n2026-10-22 00:30:00')
        editor=self.m.filters['company'];editor.setFocus();QTest.keyClicks(editor,'example')
        QTest.keyClick(editor,Qt.Key.Key_Return);self.loaded()
        self.assertEqual(self.requests[-1]['company'],['example']);self.assertFalse(self.w.draft_items)
        product=self.m.filters['product'];product.setCurrentIndex(product.findData('JE'))
        before=len(self.requests);self.w.product_combo.addItem('JK','JK_TEST')
        wait(lambda:product.findData('JK')>=0)
        self.assertEqual(product.currentData(),'JE');self.assertEqual(len(self.requests),before)

    def test_actual_layout_at_normal_and_small_window(self):
        OUT.mkdir(parents=True,exist_ok=True)
        labels={label.text() for label in self.m.list_page.findChildren(QLabel)}
        self.assertTrue({'报价单编号','客户','产品','创建人','状态','更新时间'}<=labels)
        self.assertNotIn('报价单编号 / 客户',labels)
        for width,height in ((1510,960),(1280,860),(1024,768)):
            self.w.resize(width,height);APP.processEvents();QTest.qWait(40)
            radio=self.m.list_table.cellWidget(0,0).findChild(QRadioButton)
            option=QStyleOptionButton();radio.initStyleOption(option)
            indicator=radio.style().subElementRect(QStyle.SubElement.SE_RadioButtonIndicator,option,radio)
            center=radio.mapTo(self.m.list_table.viewport(),indicator.center())
            cell_center=self.m.list_table.visualItemRect(self.m.list_table.item(0,0)).center()
            self.assertLessEqual(abs(center.x()-cell_center.x()),1)
            self.assertLessEqual(abs(center.y()-cell_center.y()),1)
            self.m.list_table.clearSelection();radio.setChecked(False);QTest.mouseClick(radio,Qt.MouseButton.LeftButton)
            self.assertEqual(self.m.list_table.currentRow(),0);self.assertTrue(radio.isChecked())
            self.assertTrue(self.m.contract_button.isEnabled())
            radio.setChecked(False);self.m.list_table.clearSelection();self.m.list_table.selectRow(0)
            self.assertTrue(radio.isChecked())
            fields=[*self.m.filters.values(),self.m.status,self.m.query_button,self.m.reset_button]
            for field in fields:
                self.assertTrue(field.isVisible());self.assertGreaterEqual(field.width(),55)
                rect=field.mapTo(self.m.list_page,field.rect().topLeft())
                self.assertLessEqual(rect.x()+field.width(),self.m.list_page.width())
            self.w.grab().save(str(OUT/f'quote-filters-{width}.png'))


if __name__=='__main__':unittest.main()
