"""Real V3 front/rear controls; legacy counts, isolated save, PDF/XLSX and requests."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json,os,unittest
from PySide6.QtCore import QSignalBlocker,QTimer,Qt
from PySide6.QtWidgets import QComboBox,QLabel,QMessageBox
import verify_weight_freight as fixture
from verify_quote_document_progress import app,wait,ui,ns,Worker
import layout_refresh as layout
import quote_scheme_center as schemes
from ganged_cabinet_rules import DOOR_POSITION_COUNTS,door_positions_for_counts
from quote_request_context import stamp_quote_response

CASES=[('SINGLE','PANEL',(1,0)),('SINGLE','SINGLE',(2,0)),('SINGLE','DOUBLE',(1,1)),
       ('DOUBLE','PANEL',(0,1)),('DOUBLE','SINGLE',(1,1)),('DOUBLE','DOUBLE',(0,2))]

class FrontRearDoorTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(ns['MainWindow'],'request_history_match',lambda *_:None);p.start();self.addCleanup(p.stop)
        p=patch.object(layout,'_request_history_price_match',lambda *_:None);p.start();self.addCleanup(p.stop)
        self.h=fixture.WeightFreight();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.w=self.h.w
        self.warnings=[]
        warning=patch.object(QMessageBox,"warning",side_effect=lambda *args:self.warnings.append(args[2]));warning.start();self.addCleanup(warning.stop)
        self.w.request_history_match=lambda *_:None
        self.w._scheme2_loading_order=False
        self.w._quote_scheme_loading=True
        self.family('JP')
        self.w._quote_scheme_loading=False
        self.w._quote_scheme_save_timer.stop();self.w._scheme2_order_save_timer.stop()
        self.qt_errors=[]
        p=patch('sys.excepthook',side_effect=lambda kind,error,trace:self.qt_errors.append(error));p.start();self.addCleanup(p.stop)

    def tearDown(self):
        self.w._quote_scheme_save_timer.stop();self.w._scheme2_order_save_timer.stop()
        self.w._history_price_timer.stop()
        self.h.doCleanups()
        self.assertFalse(self.qt_errors,self.qt_errors)

    def family(self,name):
        self.w.product_catalog={name:dict(method='formula',codes={'SINGLE':name+'_SINGLE','DOUBLE':name+'_DOUBLE'})}
        with QSignalBlocker(self.w.product_combo):
            self.w.product_combo.clear();self.w.product_combo.addItem(name,name);self.w.product_combo.setCurrentIndex(0)
        self.w.set_door_counts(1,0)
        layout._sync_main_door_combo_options(self.w)

    def choose(self,front,rear):
        self.w.front_door_combo.setCurrentIndex(self.w.front_door_combo.findData(front))
        self.w.rear_door_combo.setCurrentIndex(self.w.rear_door_combo.findData(rear))
        self.w._quote_scheme_save_timer.stop();self.w._scheme2_order_save_timer.stop()
        app.processEvents()

    def test_six_choices_keep_the_exact_legacy_count_contract(self):
        self.assertEqual([self.w.front_door_combo.itemText(i) for i in range(2)],['单门','双门'])
        self.assertEqual([self.w.rear_door_combo.itemText(i) for i in range(3)],['后背板','单门','双门'])
        self.w.show_section(ui.OPTION_ROUTE);app.processEvents()
        self.assertFalse(self.w.single_door_combo.isVisibleTo(self.w))
        self.assertFalse(self.w.double_door_combo.isVisibleTo(self.w))
        self.assertEqual(self.w.front_door_combo.accessibleName(),'前门')
        self.assertEqual(self.w.rear_door_combo.accessibleName(),'后门')
        for front,rear,counts in CASES:
            with self.subTest(front=front,rear=rear):
                self.choose(front,rear)
                self.assertEqual(self.w.door_counts(),counts)
                self.assertEqual(self.w._door_position,dict(front=front,rear=rear))
                self.assertEqual(layout._current_door_counts(self.w),counts)

    def test_product_limits_width_defaults_and_readonly_are_preserved(self):
        for family in ('JA','JE'):
            self.family(family)
            self.assertTrue(self.w.front_door_combo.model().item(1).isEnabled())
            self.assertEqual([self.w.rear_door_combo.model().item(i).isEnabled() for i in range(3)],[True,False,False])
            self.choose('DOUBLE','PANEL');self.assertEqual(self.w.door_counts(),(0,1))
        for family in ('JK','JM','JQ','JC'):
            self.family(family)
            self.assertFalse(self.w.front_door_combo.model().item(1).isEnabled())
            self.assertEqual(self.w.door_counts(),(1,0))
        self.family('JP');self.w._door_selection_mode=layout.AUTOMATIC_DOOR_SELECTION
        self.w.width_spin.setValue(801);layout._apply_automatic_door_default(self.w)
        self.assertEqual(self.w.front_door_combo.currentText(),'双门')
        self.assertEqual(self.w.rear_door_combo.currentText(),'后背板')
        self.choose('SINGLE','SINGLE');self.w.width_spin.setValue(700)
        self.assertEqual(self.w.door_counts(),(2,0))
        schemes._apply_read_only(self.w,True)
        self.assertFalse(self.w.front_door_combo.isEnabled());self.assertFalse(self.w.rear_door_combo.isEnabled())
        schemes._apply_read_only(self.w,False)
        self.assertTrue(self.w.front_door_combo.isEnabled())
        controller=self.w._scheme2_document_controller
        controller.begin('generate')
        self.assertFalse(self.w.front_door_combo.isEnabled());self.assertFalse(self.w.rear_door_combo.isEnabled())
        controller.end(cancelled=True)
        self.assertTrue(self.w.front_door_combo.isEnabled());self.assertTrue(self.w.rear_door_combo.isEnabled())

    def test_two_mixed_orientations_roundtrip_workspace_and_legacy_fallback(self):
        for front,rear in [('SINGLE','DOUBLE'),('DOUBLE','SINGLE')]:
            self.choose(front,rear)
            state=json.loads(json.dumps(ui._capture_scheme2_page_state(self.w),default=list))
            self.choose('SINGLE','PANEL')
            ui._restore_scheme2_page_state(self.w,state)
            self.assertEqual((self.w.front_door_combo.currentData(),self.w.rear_door_combo.currentData()),(front,rear))
            self.assertEqual(self.w.door_counts(),(1,1))
        legacy=deepcopy(state);legacy.pop('door_position')
        ui._restore_scheme2_page_state(self.w,legacy)
        self.assertEqual(self.w._door_position,dict(front='SINGLE',rear='DOUBLE'))

    def test_order_item_load_save_reopen_and_copy_preserve_orientation(self):
        item=deepcopy(self.h.item)
        item.update(product_family='JP',product_code='JP_SINGLE',single_door_count=1,double_door_count=1,
            variant_code='SINGLE',door_position=dict(front='DOUBLE',rear='SINGLE'))
        self.w.load_draft_item(item)
        self.assertEqual(self.w.door_counts(),(1,1))
        self.assertEqual(self.w._door_position,item['door_position'])
        self.w.draft_items=[item];self.w.refresh_summary();self.w.summary_table.selectRow(0)
        self.w.scheme2_cost_action_buttons[3].click()
        self.assertEqual(self.w.draft_items[1]['door_position'],item['door_position'])
        self.w.quote_management.save();wait(lambda:not self.w._quote_scheme_workers)
        saved=deepcopy(self.h.server)
        schemes._apply_opened_scheme(self.w,saved,ui.OPTION_ROUTE)
        self.assertEqual(self.w._door_position,item['door_position'])
        old=deepcopy(item);old.pop('door_position')
        self.w.load_draft_item(old)
        self.assertEqual(self.w._door_position,dict(front='SINGLE',rear='DOUBLE'))

    def test_default_attachment_quantities_use_counts_not_position_names(self):
        self.w.attachments=[dict(item_name='门限位器',category_level1='门限位器',quantity=1),
                           dict(item_name='门加强筋',category_level1='门加强筋',quantity=1)]
        self.w.attachment_default_opt_outs=set();self.w.attachment_default_quantity_overrides=set()
        for front,rear,counts in CASES:
            self.choose(front,rear)
            self.assertEqual([x['quantity'] for x in self.w.attachments], [counts[0]+2*counts[1]]*2)
        self.w.attachments[0]['quantity']=7
        self.w.attachment_default_quantity_overrides={'door_limiter'}
        # Existing override keys remain covered by the established rule suite;
        # compare both mixed orientations directly: neither changes their counts.
        self.choose('SINGLE','DOUBLE');before=deepcopy(self.w.attachments)
        self.w._door_position=dict(front='DOUBLE',rear='SINGLE');ui._sync_door_position_controls(self.w)
        self.assertEqual(self.w.attachments,before)

    def test_actual_calculation_request_and_added_row_keep_legacy_counts(self):
        requests=[]
        prior=Worker.start
        def calculate(worker):
            if not worker.test_url.endswith('/calculate-dual'):return prior(worker)
            payload=deepcopy(worker.test_payload);requests.append(payload);worker.test_running=True
            result=dict(quote_id=payload['quote_id'],quote_line_id='11111111-1111-4111-8111-111111111111',attachment_contract=2,
                formula_cost=dict(material_cost=80,auxiliary_cost=0,labor_cost=0,spray_cost=0,total_cost=80,
                                  corrected_material_weight_kg=20,product_area_m2=2),
                quick_quote=dict(base_price=200,attachment_fee=0,total_cost=200),attachments=[],risk_flags=[])
            def ready():
                worker.test_running=False;worker.succeeded.emit(stamp_quote_response(worker,result));worker.finished.emit()
            QTimer.singleShot(1,ready)
        self.w._quote_scheme_loading=True;self.w.draft_items=[];self.w.current_result=None
        self.w.model_edit.setText('800*600*1800');self.w.quote_spec_edit.setText('800*600*1800')
        self.w.width_spin.setValue(800);self.w.height_spin.setValue(1800);self.w.depth_spin.setValue(600)
        self.w.attachments=[];self.w.material_combo.clear();self.w.material_combo.addItem('镀锌板','SECC')
        self.w.coating_combo.clear();self.w.coating_combo.addItem('橘纹','橘纹')
        with patch.object(Worker,'start',calculate):
            for front,rear,counts in CASES:
                self.family('JP')
                self.w.model_edit.setText('800*600*1800');self.w.quote_spec_edit.setText('800*600*1800')
                self.w.width_spin.setValue(800);self.w.height_spin.setValue(1800);self.w.depth_spin.setValue(600)
                self.choose(front,rear)
                with QSignalBlocker(self.w.material_combo),QSignalBlocker(self.w.coating_combo):
                    self.w.material_combo.clear();self.w.material_combo.addItem('镀锌板','SECC')
                    self.w.coating_combo.clear();self.w.coating_combo.addItem('橘纹','橘纹')
                self.w.weight_edit.setText('20');self.w.area_edit.setText('2')
                self.w.quantity_spin.setValue(2)
                source_text='图号：SYN-001；物料号：PART-001；门板1.8mm；不含空调；安装板先发'
                self.w.notes_text.setPlainText(source_text)
                self.assertTrue(self.w.selected_product_code(),(self.w.product_catalog,self.w.door_counts()))
                self.w.scheme2_add_button.click()
                self.assertFalse(self.warnings,self.warnings)
                wait(lambda:len(self.w.draft_items)==len(requests) and bool(requests) and not getattr(self.w,'quote_calculation_in_progress',False))
                payload=requests[-1];row=self.w.draft_items[-1]
                self.assertEqual((payload['single_door_count'],payload['double_door_count']),counts)
                self.assertNotIn('front_door',payload);self.assertNotIn('rear_door',payload)
                self.assertEqual(row['door_position'],dict(front=front,rear=rear))
                self.assertEqual((row['single_door_count'],row['double_door_count']),counts)
                self.assertEqual(row['quote_remark_source'],source_text)
                remark=ui._quote_item_remark(row)
                self.assertIn('SYN-001/PART-001',remark)
                self.assertIn('门板1.8mm',remark)
                self.assertIn('不含空调',remark)
                self.assertIn('安装板先发',remark)
        self.w._quote_scheme_loading=False

    def test_ganged_children_keep_positions_and_legacy_request_counts_on_reopen(self):
        specification='(800+800)*600*1800'
        self.w.quote_spec_edit.setText(specification)
        self.assertTrue(layout._sync_ganged_specification(self.w,specification))
        ui._refresh_scheme2_ganged_ui(self.w);app.processEvents()
        self.assertFalse(self.w.front_door_combo.isEnabled())
        for row,front,rear,counts in [(0,'DOUBLE','SINGLE',(1,1)),(1,'SINGLE','DOUBLE',(1,1))]:
            f,b=self.w._ganged_door_position_controls[row]
            with QSignalBlocker(f),QSignalBlocker(b):
                f.setCurrentIndex(f.findData(front));b.setCurrentIndex(b.findData(rear))
            ui._door_position_changed(self.w,f,b,row);app.processEvents()
            child=self.w.ganged_cabinets[row]
            self.assertEqual((child['single_door_count'],child['double_door_count']),counts)
            self.assertEqual(child['door_position'],dict(front=front,rear=rear))
        saved=json.loads(json.dumps(ui._capture_scheme2_page_state(self.w),default=list))
        self.w.ganged_cabinets=[]
        ui._restore_scheme2_page_state(self.w,saved);app.processEvents()
        self.assertEqual([r['door_position'] for r in self.w.ganged_cabinets],
                         [dict(front='DOUBLE',rear='SINGLE'),dict(front='SINGLE',rear='DOUBLE')])
        with patch.object(layout,'_ganged_formula_metrics',return_value=[(20,2),(20,2)]):
            payloads,_,_=layout._build_ganged_quote_payloads(self.w)
        self.assertEqual([(p['single_door_count'],p['double_door_count']) for p in payloads],[(1,1),(1,1)])
        self.assertTrue(all('door_position' not in p for p in payloads))
        item=deepcopy(self.h.item)
        item.update(ganged_cabinets=deepcopy(self.w.ganged_cabinets),ganged_cabinet_count=2,specification=specification)
        self.w.load_draft_item(item);app.processEvents()
        self.assertEqual([r['door_position'] for r in self.w.ganged_cabinets],
                         [dict(front='DOUBLE',rear='SINGLE'),dict(front='SINGLE',rear='DOUBLE')])
        self.assertTrue(all(c.isEnabled() for controls in self.w._ganged_door_position_controls for c in controls))
        self.w.show_section(ui.OPTION_ROUTE);self.w.resize(1519,987);self.w.show();app.processEvents()
        output=Path(os.environ.get('AI_QUOTE_DOOR_POSITION_SCREENSHOT_DIR',str(Path(__file__).resolve().parents[1]/'outputs/front-rear-doors')))
        output.mkdir(parents=True,exist_ok=True)
        self.assertTrue(self.w.grab().save(str(output/'window-ganged.png')))
        schemes._apply_read_only(self.w,True)
        self.assertTrue(all(not c.isEnabled() for controls in self.w._ganged_door_position_controls for c in controls))

    def test_cost_quote_pdf_excel_remain_on_the_saved_legacy_prices(self):
        self.h.item.update(single_door_count=1,double_door_count=1,door_position=dict(front='SINGLE',rear='DOUBLE'))
        before=deepcopy(self.h.item)
        totals=ui._row_values(before)[15:19]
        self.choose('DOUBLE','SINGLE')
        self.h.item['door_position']=deepcopy(self.w._door_position)
        self.assertEqual(ui._row_values(self.h.item)[15:19],totals)
        self.h.export()
        from verify_quote_export_customer import workbook_cell
        self.assertEqual(float(workbook_cell(self.h.path,'报价','F11')),totals[0])
        self.assertEqual(float(workbook_cell(self.h.path,'报价','G11')),totals[1])
        self.assertEqual(self.h.posts()[-1]['snapshot']['draft_items'][0]['door_position'],dict(front='DOUBLE',rear='SINGLE'))
        self.assertIn(f'{totals[1]:,.2f}',ui._printable_quote_html(self.w))
        from PySide6.QtPrintSupport import QPrinter
        from PySide6.QtGui import QTextDocument
        from pypdf import PdfReader
        destination=Path(self.h.folder.name)/'door-position.pdf'
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(destination))
        document=QTextDocument();document.setHtml(ui._printable_quote_html(self.w));document.print_(printer)
        text=''.join(page.extract_text() for page in PdfReader(str(destination)).pages)
        self.assertIn(f'{totals[0]:,.2f}',text);self.assertIn(f'{totals[1]:,.2f}',text)

    def test_actual_visual_front_rear_fields(self):
        output=Path(os.environ.get('AI_QUOTE_DOOR_POSITION_SCREENSHOT_DIR',str(Path(__file__).resolve().parents[1]/'outputs/front-rear-doors')))
        output.mkdir(parents=True,exist_ok=True)
        self.w.show_section(ui.OPTION_ROUTE);self.w.resize(1519,987);self.w.show();app.processEvents()
        for front,rear in [('SINGLE','DOUBLE'),('DOUBLE','SINGLE')]:
            self.choose(front,rear);app.processEvents()
            self.assertTrue(self.w.scheme2_regular_doors.grab().save(str(output/f'{front.lower()}-{rear.lower()}.png')))
            self.assertTrue(self.w.grab().save(str(output/f'window-{front.lower()}-{rear.lower()}.png')))
        self.w.resize(1024,768);app.processEvents()
        self.assertTrue(self.w.front_door_combo.isVisibleTo(self.w))
        self.assertTrue(self.w.rear_door_combo.isVisibleTo(self.w))
        self.assertTrue(self.w.grab().save(str(output/'window-1024.png')))

if __name__=='__main__':unittest.main(verbosity=2)
