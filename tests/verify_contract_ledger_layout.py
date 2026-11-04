"""Native V3 ledger geometry at Windows DPI scales; no remote API or real files."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=str(ROOT/'test-output/contract-layout/private-cache')
import sys,json,hashlib,unittest
sys.path.insert(0,str(ROOT/'desktop_client'))
from unittest.mock import patch,Mock
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QLineEdit,QComboBox,QPushButton
from PySide6.QtCore import QRect,QPoint,QSettings
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
import name_login,contract_management as contracts,contract_ledger_ui as ledger,v3_launcher,client_update_ui

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(ROOT/'test-output/contract-layout/private-settings'))
APP=QApplication.instance() or QApplication([])
NS=v3_launcher.load_v3_namespace();Window=NS['MainWindow']
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');NS['install_application_font'](APP)
OUT=ROOT/'test-output/contract-layout';OUT.mkdir(parents=True,exist_ok=True)
SCALE=os.environ.get('QT_SCALE_FACTOR','1')
name='本机布局测试人员'
name_login.set_session(dict(token='T'*43,person=dict(display_name=name,user_id='name-user:'+hashlib.sha256(name.encode()).hexdigest(),identity_mode='NAME_ONLY',scope='OWN')))

def rect_in(widget,parent):return QRect(widget.mapTo(parent,QPoint(0,0)),widget.size())
def snapshot(panel):
    widgets=panel.findChildren(QWidget)
    return [dict(kind=type(w).__name__,name=w.objectName(),text=w.text() if isinstance(w,(QLabel,QLineEdit,QPushButton)) else '',
       geometry=[rect_in(w,panel).x(),rect_in(w,panel).y(),w.width(),w.height()],minimum=[w.minimumSizeHint().width(),w.minimumSizeHint().height()])
       for w in widgets if w.isVisible() and isinstance(w,(QLabel,QLineEdit,QComboBox,QPushButton))]

class LedgerLayout(unittest.TestCase):
    def setUp(self):
        screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        self.patches=[patch.object(Window,'screen',return_value=screen),patch.object(Window,'load_catalogs',lambda *_:None),patch.object(Window,'refresh_formula_inputs',lambda *_:None),
          patch.object(NS['ApiWorker'],'start',lambda *_:None),patch.object(contracts.ContractManagement,'reload',lambda *_:None),patch.object(ledger.LedgerContractPanel,'reload',lambda *_:None),
          patch.object(client_update_ui,'UpdateController',lambda *_:None),patch('urllib.request.urlopen',side_effect=AssertionError('Network blocked in layout tests'))]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.w=Window();self.w._quote_scheme_save_timer.stop();self.w._history_price_timer.stop()
        self.p=self.w.contract_management;self.l=self.p.ledger;self.addCleanup(self.cleanup)
        self.w.show();self.w.show_section(self.w.contract_management_route);self.p.source_mode.setCurrentIndex(1)
    def cleanup(self):
        self.p.unsaved=False;self.p.profile_dirty=False;self.l.unsaved=False;self.w.hide();self.w.deleteLater();APP.processEvents()
    def settle(self):
        for _ in range(5):APP.processEvents();QTest.qWait(20)
    def capture(self,tag):
        self.settle();self.assertTrue(self.w.grab().save(str(OUT/f'{tag}-scale-{SCALE}.png')))
        (OUT/f'{tag}-scale-{SCALE}.json').write_text(json.dumps(snapshot(self.l),ensure_ascii=False,indent=2),encoding='utf-8')
    def assert_form_layout(self):
        card=self.l.customer.parentWidget()
        fields=[self.l.customer,self.l.template,self.l.filename,self.l.sheet,self.l.search,self.l.source_note]
        fields += [w for w in card.findChildren(QLabel) if w.isVisible() and w not in fields]
        for i,first in enumerate(fields):
            a=rect_in(first,card)
            self.assertGreaterEqual(first.height(),first.minimumSizeHint().height(),f'{type(first).__name__} clipped: {first.geometry()} min {first.minimumSizeHint()}')
            self.assertTrue(card.rect().contains(a),f'Field extends outside form: {first.geometry()}')
            for other in fields[i+1:]:self.assertFalse(a.intersects(rect_in(other,card)),f'Controls overlap: {type(first).__name__} / {type(other).__name__}')
        self.assertGreater(self.l.sheet.width(),self.l.sheet.fontMetrics().horizontalAdvance('工作表名称'))
        self.assertEqual(self.l.select_scroll.horizontalScrollBar().maximum(),0)
        next_button=next(b for b in self.l.findChildren(QPushButton) if b.text().startswith('下一步'))
        area=rect_in(next_button,self.l.stack.currentWidget())
        self.assertTrue(self.l.stack.currentWidget().rect().contains(area),'Next action clipped')
    def test_empty_ledger_form_does_not_overlap(self):
        for width,height in [(1536,800),(1366,768),(1024,700)]:
            with self.subTest(width=width,height=height):
                self.w.resize(width,height);self.capture(f'empty-{width}x{height}');self.assert_form_layout()
    def test_notice_and_long_template_source_sheet_remain_scrollable(self):
        self.p.notice.setText('合同台账和模板已加载，请选择台账并核对合同。')
        self.l.template.addItem('客户专属合同模板 · '+'保留备注与公司条款 '*15,1)
        self.l.filename.setText('G:/合成测试/'+('很长的台账文件名'*20)+'.xlsx')
        self.l.sheet.addItem('方圆接手2025 · '+'这是工作表名称'*12,'TEST')
        self.l.source_note.setText('仅读取台账，不修改原文件。\n示例读取提示：请选择已确认记录；缺少信息时先核对。\n多条记录按原规则组合合同。')
        self.w.resize(1366,704);self.capture('notice-long-content');self.assert_form_layout()
        for field in (self.l.customer,self.l.template,self.l.filename,self.l.sheet,self.l.search):
            self.l.select_scroll.ensureWidgetVisible(field);self.settle()
            self.assertTrue(self.l.select_scroll.viewport().rect().contains(rect_in(field,self.l.select_scroll.viewport())),f'Cannot scroll to {type(field).__name__}')
    def test_selection_and_customer_business_state_survive_resize_and_mode_switch(self):
        self.l.sheet.addItem('合成工作表','SYNTHETIC');self.l.search.setText('合成产品')
        self.l.selected_keys={'LOCAL-1','LOCAL-2'};self.l.filename.setText('synthetic.xlsx')
        before=(self.l.customer.currentData(),self.l.sheet.currentData(),self.l.search.text(),set(self.l.selected_keys))
        for width,height in [(1024,700),(1536,800),(1366,768)]:
            self.w.resize(width,height);self.p.source_mode.setCurrentIndex(0);self.settle();self.p.source_mode.setCurrentIndex(1);self.settle();self.assert_form_layout()
            self.assertEqual((self.l.customer.currentData(),self.l.sheet.currentData(),self.l.search.text(),self.l.selected_keys),before)

if __name__=='__main__':unittest.main()
