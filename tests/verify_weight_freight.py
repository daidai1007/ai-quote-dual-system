"""Per-set weight freight through actual V3 controls, saved JSON, PDF and XLSX."""
from copy import deepcopy
from decimal import Decimal
import json,os,re,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from unittest.mock import Mock,patch
from PySide6.QtCore import QRect

import verify_quote_export_customer as fixture
from verify_quote_document_progress import app,wait,ui,ns
from freight_state import self_made_weight,sync_item_freight,AUTO_FREIGHT_BASIS
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtGui import QTextDocument
import quote_scheme_center as schemes


class WeightFreight(unittest.TestCase):
    clean_window=fixture.ExportCustomer.clean_window
    export=fixture.ExportCustomer.export
    posts=fixture.ExportCustomer.posts

    def setUp(self):
        screen=Mock(wraps=app.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        p=patch.object(ns['MainWindow'],'screen',return_value=screen);p.start();self.addCleanup(p.stop)
        fixture.ExportCustomer.setUp(self)
        self.w=self.window
        item=self.w.draft_items[0]
        item.update(freight_fee=0,freight_mode='AUTO',freight_basis=AUTO_FREIGHT_BASIS,
            product_family='JP',model_code='800*600*1800',width_mm=800,height_mm=1800,depth_mm=600,
            coating_type='橘纹',formula_discount=1,quick_discount=1,labor_multiplier=1,
            single_door_count=1,double_door_count=0)
        item['formula']['corrected_material_weight_kg']=42.5
        item['attachments']=[dict(item_name='侧板',quantity=2,weight_kg=2.5,
            attachment_price_id=99,status='CALCULATED',formula_unit_cost=10,formula_amount=20,quick_amount=20,
            material_cost=6,spray_cost=1,auxiliary_cost=1,labor_cost=2)]
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.m.show_detail();app.processEvents()

    @property
    def item(self):return self.w.draft_items[0]

    def assert_equal_weight_freight(self,expected):
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.item['freight_fee'],expected)
        table=self.w.summary_table
        self.assertEqual(table.item(0,ui.HEADERS.index('运费')).text(),f'{expected:,.2f}')
        self.assertEqual(table.item(0,ui.HEADERS.index('自制件重量')).text(),f'{expected:,.2f}')

    def reopen(self):
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        saved=deepcopy(self.server['snapshot']);self.w.draft_items=[]
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop();return saved

    def test_live_result_automatic_manual_and_restore_weight_button(self):
        self.w.freight_state.reset()
        self.w.current_result={'formula':deepcopy(self.item['formula']),'quick':deepcopy(self.item['quick'])}
        self.w.attachments=deepcopy(self.item['attachments'])
        self.w.refresh_discounted_totals()
        self.assertEqual(self.w.freight_spin.value(),47.5)
        self.w.freight_spin.setValue(7)
        self.assertEqual(self.w.freight_state.mode,'MANUAL')
        self.w.attachments[0]['weight_kg']=3
        self.w.refresh_discounted_totals();self.assertEqual(self.w.freight_spin.value(),7)
        self.w.freight_auto_button.click()
        self.assertEqual(self.w.freight_spin.value(),48.5)
        self.assertEqual(self.w.freight_state.mode,'AUTO')

    def test_default_uses_cabinet_and_attachment_weights_then_order_quantity_once(self):
        self.assert_equal_weight_freight(47.5)
        self.assertEqual(ui._row_values(self.item)[9],12.38)  # Quote 247.50 * 5%, rounded per unit.
        column=ui.HEADERS.index('数量')
        self.w.summary_table.item(0,column).setText('3')
        self.assert_equal_weight_freight(47.5)
        self.assertEqual(self.item['quantity'],3)
        self.assertEqual(self.w.summary_table.item(1,ui.HEADERS.index('自制件重量')).text(),'142.50')
        self.item['quick_discount']=0;self.w.refresh_summary()
        self.assertEqual(ui._row_values(self.item)[15],47.5)
        self.assertEqual(ui._row_values(self.item)[16],142.5)  # Freight is not discounted.

    def test_ganged_set_and_deduction_pending_missing_weights(self):
        self.item.update(quantity=3,ganged_cabinet_count=2,ganged_cabinets=[{},{}])
        self.item['formula']['corrected_material_weight_kg']=100
        self.item['attachments']=[dict(weight_kg=3,quantity=1,ganged_cabinet_index=0),
            dict(weight_kg=4,quantity=2,ganged_cabinet_index=1),
            dict(item_name='安装板',weight_kg=2,quantity=2,attachment_price_sign=-1),
            dict(weight_kg=50,quantity=1,status='PENDING_MANUAL'),dict(weight_kg=float('nan'),quantity=1),
            dict(weight_kg=99,quantity=float('nan'))]
        self.assertEqual(self_made_weight(self.item),Decimal(107))
        sync_item_freight(self.item);self.assertEqual(self.item['freight_fee'],107)
        self.item['formula']['corrected_material_weight_kg']=0
        self.item['attachments']=[dict(weight_kg=3,quantity=1,attachment_price_sign=-1)]
        self.assertEqual(self_made_weight(self.item),0)

    def test_attachment_popup_quantity_and_weight_recalculation_update_automatic_freight(self):
        self.assert_equal_weight_freight(47.5)
        editor=ui.AttachmentEditor(self.w,self.item)
        editor.table.cellWidget(0,editor.COL_QUANTITY).setValue(3);editor.accept();editor.close()
        self.assert_equal_weight_freight(50)
        self.item['attachments'][0]['weight_kg']=3.5
        self.assert_equal_weight_freight(53)

    def test_manual_zero_remains_after_weight_changes_and_reopen(self):
        self.w.summary_table.item(0,ui.HEADERS.index('运费')).setText('0')
        self.assertEqual(self.item['freight_mode'],'MANUAL')
        self.item['attachments'][0]['weight_kg']=8
        self.w.refresh_summary();self.assertEqual(self.item['freight_fee'],0)
        self.reopen();self.assertEqual(self.item['freight_mode'],'MANUAL')
        self.assertEqual(self.item['freight_fee'],0)
        self.w._draft_drawing_refs.clear();self.w.load_draft_item(self.item)
        self.assertEqual(self.w.freight_state.mode,'MANUAL');self.assertEqual(self.w.freight_spin.value(),0)

    def test_automatic_mode_is_saved_without_memory_only_refs(self):
        self.assert_equal_weight_freight(47.5)
        saved=self.reopen();self.assertEqual(saved['draft_items'][0]['freight_mode'],'AUTO')
        self.item['attachments'][0]['weight_kg']=3
        self.assert_equal_weight_freight(48.5)
        self.w._draft_drawing_refs.clear();self.w.load_draft_item(self.item)
        self.assertEqual(self.w.freight_state.mode,'AUTO');self.assertEqual(self.w.freight_spin.value(),48.5)

    def test_legacy_and_historical_amounts_do_not_reprice_on_view(self):
        self.item.pop('freight_mode');self.item.pop('freight_basis');self.item['freight_fee']=70
        self.w.refresh_summary();self.assertEqual(self.item['freight_fee'],70)
        self.item.update(freight_mode='AUTO',freight_basis=AUTO_FREIGHT_BASIS)
        self.w._quote_scheme_read_only=True
        self.w.refresh_summary();self.assertEqual(self.item['freight_fee'],70)
        frozen=ui._quote_export_items_snapshot(self.w)
        self.assertEqual(frozen[0]['freight_fee'],70)

    def test_rounding_matches_weight_display_and_never_reapplies_waste(self):
        self.item['formula'].update(corrected_material_weight_kg=2.675,net_material_weight_kg=1,waste_factor=1.2)
        self.item['attachments']=[]
        self.assert_equal_weight_freight(2.68)
        self.item.update(quantity=100)
        self.item['formula']['corrected_material_weight_kg']=0.004
        self.assert_equal_weight_freight(0)
        self.assertEqual(self.w.summary_table.item(1,ui.HEADERS.index('自制件重量')).text(),'0.40')

    def test_generate_synchronizes_freight_before_freezing_precheck(self):
        self.item['attachments'][0]['weight_kg']=4
        self.controller.generate();wait(lambda:not self.controller.busy)
        self.assertEqual(self.controller.state,'success',self.controller.reason)
        self.assertEqual(self.item['freight_fee'],50.5)
        checks=[payload for endpoint,payload in self.requests if endpoint.endswith('/preview-check')]
        self.assertEqual(checks[-1]['items'][0]['freight_fee'],50.5)

    def test_save_and_export_commit_latest_weight_before_freezing_receipt(self):
        self.item['attachments'][0]['weight_kg']=4
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(self.server['snapshot']['draft_items'][0]['freight_fee'],50.5)
        self.item['attachments'][0]['weight_kg']=5
        self.export();self.assertTrue(self.path.exists(),self.messages)
        receipt=self.posts()[-1]['snapshot']
        self.assertEqual(receipt['draft_items'][0]['freight_fee'],52.5)
        self.assertEqual(receipt['quote_management']['versions'][-1]['items'][0]['freight_fee'],52.5)
        for sheet in ('报价','成本'):
            self.assertEqual(float(fixture.workbook_cell(self.path,sheet,'G11')),
                ui._row_values(self.item)[16] if sheet=='报价' else ui._row_values(self.item)[18])
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(self.path) as book:
            shared=[''.join(node.itertext()) for node in ET.fromstring(book.read('xl/sharedStrings.xml'))]
            for sheet in ('xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'):
                cells=ET.fromstring(book.read(sheet)).findall('.//m:c',ns)
                header=next(cell for cell in cells if cell.get('t')=='s' and shared[int(cell.find('m:v',ns).text)]=='运费')
                column=re.match('[A-Z]+',header.get('r'))[0]
                value=next(cell for cell in cells if cell.get('r')==column+'11').findtext('m:v',namespaces=ns)
                self.assertEqual(float(value),52.5)  # Current per-set audit column; G11 already scales by quantity.

    def test_pdf_preview_and_cost_screen_use_same_automatic_amount(self):
        self.assert_equal_weight_freight(47.5)
        rendered=ui._printable_quote_html(self.w)
        expected=ui._row_values(self.item)
        with tempfile.TemporaryDirectory() as folder:
            pdf=Path(folder)/'synthetic-weight.pdf'
            printer=QPrinter(QPrinter.PrinterMode.HighResolution);printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            document=QTextDocument();document.setHtml(rendered);document.print_(printer)
            from pypdf import PdfReader
            printed=''.join(''.join(page.extract_text() for page in PdfReader(pdf).pages).split())
            self.assertIn(f'{expected[15]:,.2f}',printed);self.assertIn(f'{expected[16]:,.2f}',printed)
        if os.environ.get('AI_QUOTE_WEIGHT_FREIGHT_SCREENSHOTS'):
            out=Path(os.environ['AI_QUOTE_WEIGHT_FREIGHT_SCREENSHOTS']);out.mkdir(parents=True,exist_ok=True)
            self.w.resize(1519,987);self.w.show();self.w.show_section(ui.COST_ROUTE);app.processEvents()
            self.w.summary_table.selectRow(0)
            scroll=self.w.summary_table.horizontalScrollBar();scroll.setValue(scroll.maximum());app.processEvents()
            self.assertTrue(self.w.grab().save(str(out/'cost-auto-weight-freight.png')))

if __name__=='__main__':unittest.main(verbosity=2)
