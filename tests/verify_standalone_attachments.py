"""Real Qt widgets + production Node formula evaluator + real workbook output.

Transport and catalogue are synthetic, with no production API/DB connection.
"""
import json
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop_client'))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QComboBox, QMessageBox
import scheme2_ui as ui
import standalone_attachment as independent
import standalone_attachment_ui as independent_ui
import layout_refresh
import v3_launcher

app=QApplication.instance() or QApplication([])
ns=v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
Window,Worker=ns['MainWindow'],ns['ApiWorker']

def calculate(sources):
    result=subprocess.run(['node',str(ROOT/'tests/standalone_attachment_fixture.mjs')],input=json.dumps({'attachments':sources}),
                          text=True,encoding='utf-8',capture_output=True,cwd=ROOT,check=True)
    return json.loads(result.stdout)['attachments']

def wait(predicate):
    for _ in range(400):
        app.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Independent attachment operation did not finish')

class StandaloneAttachments(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='standalone-')
        self.addCleanup(self.folder.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,self.folder.name)
        for target,name,value in [(Window,'load_catalogs',lambda *_:None),
                                  (Window,'refresh_formula_inputs',lambda *_:None),
                                  (Worker,'run',lambda worker:worker.failed.emit('offline initialization')),
                                  (ui,'_fit_window_minimum_to_screen',lambda *_:None),
                                  (layout_refresh,'_fit_window_minimum_to_screen',lambda *_:None)]:
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        self.window=w=Window()
        w._scheme2_loading_order=True
        w._quote_scheme_loading=True
        w._quote_scheme_save_timer.stop()
        w._history_price_timer.stop()
        w.draft_items=[]
        w.refresh_summary=lambda:ui._refresh_cost_table(w)
        w.setMinimumSize(1,1);w.resize(1517,984);w.show();w.show_section(ui.COST_ROUTE)
        self.requests=[]
        self.transport_error=None
        def request(_window,sources,succeeded,failed):
            self.requests.append(deepcopy(sources))
            if self.transport_error:QTimer.singleShot(0,lambda:failed(self.transport_error))
            else:
                rows=calculate(sources)
                QTimer.singleShot(0,lambda:succeeded(rows))
        for module in (independent,independent_ui):
            p=patch.object(module,'request',request);p.start();self.addCleanup(p.stop)
        self.addCleanup(self.close_window)

    def close_window(self):
        w=self.window
        for child in app.topLevelWidgets():
            if isinstance(child,QDialog):child.reject()
        w._scheme2_dirty=False;w._quote_scheme_loading=True
        w._quote_scheme_id='';w._quote_scheme_save_timer.stop();w.close()

    def add(self,board=False):
        w=self.window
        w.scheme2_cost_add_independent.click()
        picker=w._standalone_name_picker
        self.assertIsInstance(picker,ui._SchemeAttachmentDialog)
        self.assertIn('侧板',picker.category_names)
        self.assertIn('控制箱附件',picker.category_names)
        if board:picker.direct_checks['安装板'].setChecked(True)
        else:
            picker.category_checks['控制柜附件'].setChecked(True)
            picker.category_combos['控制柜附件'].set_selected_texts(['门限位器'])
        picker.accept()
        wait(lambda:bool(w.draft_items) and w.draft_items[-1]['attachments'][0].get('catalog_version'))
        return w.draft_items[-1]

    def test_fixed_attachment_quantity_copy_and_export_unit(self):
        w=self.window
        w.width_spin.setValue(9999);w.height_spin.setValue(8888);w.depth_spin.setValue(7777)
        cabinet_attachments=deepcopy(w.attachments)
        item=self.add()
        self.assertEqual(w.attachments,cabinet_attachments)
        self.assertTrue(independent.ready(item));self.assertEqual(item['unit'],'件')
        self.assertNotIn('width_mm',self.requests[-1][0])
        w.summary_table.item(0,4).setText('3')
        self.assertEqual(item['quantity'],3)
        editor=ui.AttachmentEditor(w,item)
        self.assertEqual(editor.table.columnCount(),7)
        self.assertTrue(editor.table.cellWidget(0,editor.COL_QUANTITY).isReadOnly())
        editor.accept()
        w.summary_table.selectRow(0);ui._duplicate_selected(w)
        self.assertEqual(len(w.draft_items),2)
        ui._refresh_quote_page(w)
        snapshot=ui._quote_export_items_snapshot(w)
        self.assertEqual(snapshot[0]['quote_display']['unit'],'件')
        self.assertEqual(snapshot[0]['quote_display']['quantity'],3)
        self.assertEqual(snapshot[0]['attachments'][0]['quantity'],1)
        payload=Path(self.folder.name)/'quote.json';xlsx=Path(self.folder.name)/'quote.xlsx'
        payload.write_text(json.dumps({'quote_id':'LOCAL-INDEPENDENT','company':'本机客户','items':snapshot},ensure_ascii=False),encoding='utf-8')
        result=subprocess.run(['node','export_dual_quote_workbook.mjs',str(payload),str(xlsx)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        with ZipFile(xlsx) as z:
            strings=z.read('xl/sharedStrings.xml').decode('utf-8')
            self.assertIn('门限位器',strings);self.assertIn('件',strings)
        if os.getenv('STANDALONE_QA_DIR'):
            Path(os.environ['STANDALONE_QA_DIR']).mkdir(parents=True,exist_ok=True)
            w.grab().save(str(Path(os.environ['STANDALONE_QA_DIR'])/'cost-fixed.png'))

    def test_missing_specification_then_existing_parameter_shell_recalculates(self):
        w=self.window;item=self.add(board=True)
        self.assertFalse(independent.ready(item))
        self.assertEqual(w.summary_table.item(0,10).text(),'—')
        self.assertFalse(w.scheme2_cost_generate.isEnabled())
        w._scheme2_document_controller.sync_buttons()
        self.assertFalse(w.scheme2_cost_generate.isEnabled())
        if os.getenv('STANDALONE_QA_DIR'):
            w.grab().save(str(Path(os.environ['STANDALONE_QA_DIR'])/'cost-pending.png'))
        with self.assertRaisesRegex(ValueError,'尚未完善'):ui._quote_export_items_snapshot(w)
        editor=ui.AttachmentEditor(w,item)
        def select():
            dialog=next(x for x in app.topLevelWidgets() if x.objectName()=='scheme2DimensionDialog' and x.isVisible())
            self.assertEqual(dialog.objectName(),'scheme2DimensionDialog')
            dialog.fields['目录规格'].setCurrentIndex(1)
            dialog.accept()
        QTimer.singleShot(20,select)
        editor.edit_missing_dimensions(0,editor.COL_SPECIFICATION)
        wait(lambda:not getattr(editor,'_pending_reprices',{}))
        source=editor.table.item(0,0).data(ui.ROLE_ROW)
        self.assertEqual(source['standalone_material_code'],'SGCC')
        def complete():
            dialog=next(x for x in app.topLevelWidgets() if x.objectName()=='scheme2DimensionDialog' and x.isVisible())
            self.assertNotIn('材质密度',dialog.fields)
            self.assertNotIn('材质单价',dialog.fields)
            dialog.fields['宽度'].setText('1200')
            self.assertTrue(dialog.confirm_button.isEnabled());dialog.accept()
        QTimer.singleShot(20,complete)
        editor.edit_missing_dimensions(0,editor.COL_SPECIFICATION)
        wait(lambda:not getattr(editor,'_pending_reprices',{}))
        editor.accept()
        self.assertTrue(independent.ready(item))
        self.assertEqual(item['attachments'][0]['standalone_environment']['width_mm'],1200)
        w.summary_table.selectRow(0)
        ui._apply_cost_control(w,'galvanized_price',6)
        ui._apply_cost_control(w,'surface_price',0)
        wait(lambda:independent.ready(item))
        self.assertEqual(item['attachments'][0]['standalone_environment']['material_unit_price'],6)
        self.assertEqual(item['attachments'][0]['spray_cost'],0)
        self.assertNotEqual(item['attachments'][0]['standalone_environment']['width_mm'],w.width_spin.value())
        self.assertTrue(w.scheme2_cost_generate.isEnabled())
        if os.getenv('STANDALONE_QA_DIR'):
            w.grab().save(str(Path(os.environ['STANDALONE_QA_DIR'])/'cost-board-entered-size.png'))

    def test_pending_blocks_even_in_mixed_list_and_readonly_blocks_add(self):
        item=self.add(board=True);w=self.window
        cabinet={'name':'原柜体','product_code':'JP','quantity':2,'attachments':[],
                 'formula':{'material_cost':100,'auxiliary_cost':20,'labor_cost':30,'spray_cost':40,'attachment_fee':0},
                 'quick':{'base_price':300,'total_cost':300}}
        cabinet['manufacturing_cost_basis']=ui.MANUFACTURING_BASIS
        cabinet['tax_cost_basis']=ui.TAX_COST_BASIS
        ui._recalculate_item_management(cabinet)
        original=ui._row_values(cabinet)
        w.draft_items.insert(0,cabinet);w.refresh_summary()
        self.assertEqual(ui._row_values(cabinet),original)
        self.assertFalse(w.scheme2_cost_generate.isEnabled())
        self.assertEqual(w.summary_table.item(2,11).text(),'待完善')
        w._quote_scheme_read_only=True;w.refresh_summary()
        self.assertFalse(w.scheme2_cost_add_independent.isEnabled())
        independent_ui.open_picker(w);self.assertIsNone(getattr(w,'_standalone_name_picker',None))

    def test_old_add_response_cannot_overwrite_new_coefficients(self):
        w=self.window;held=[]
        def hold(_window,sources,succeeded,failed):held.append((deepcopy(sources),succeeded))
        with patch.object(independent_ui,'request',hold),patch.object(independent,'request',hold):
            independent_ui.open_picker(w);picker=w._standalone_name_picker
            picker.category_checks['控制柜附件'].setChecked(True)
            picker.category_combos['控制柜附件'].set_selected_texts(['门限位器'])
            picker.accept();item=w.draft_items[0]
            w.summary_table.selectRow(0)
            ui._apply_cost_control(w,'galvanized_price',88)
            self.assertEqual(len(held),2)
            second=calculate(held[1][0]);held[1][1](second)
            first=calculate(held[0][0]);held[0][1](first)
            self.assertEqual(item['attachments'][0]['standalone_cost_settings']['galvanized_price'],88)
            self.assertTrue(independent.ready(item))

    def test_custom_cost_edit_keeps_visible_price_when_parameter_window_reopens(self):
        w=self.window
        item=independent.new_item({'custom':True,'item_name':'独立临时件'},w.scheme2_defaults)
        source={**item['attachments'][0],'manual_inputs':{'成本单价':12.5,'面价单价':20}}
        independent.update_item(item,calculate([source])[0]);w.draft_items=[item];w.refresh_summary()
        editor=ui.AttachmentEditor(w,item)
        editor.table.cellWidget(0,editor.COL_UNIT_COST).setValue(15)
        editor.accept()
        self.assertEqual(item['attachments'][0]['formula_amount'],15)
        reopened=ui.AttachmentEditor(w,item)
        def verify():
            dialog=next(x for x in app.topLevelWidgets() if x.objectName()=='scheme2DimensionDialog' and x.isVisible())
            self.assertEqual(float(dialog.fields['成本单价'].text()),15)
            dialog.reject()
        QTimer.singleShot(20,verify)
        reopened.edit_missing_dimensions(0,reopened.COL_SPECIFICATION)
        reopened.reject()
        self.assertEqual(calculate(item['attachments'])[0]['formula_amount'],15)

if __name__=='__main__':unittest.main()
