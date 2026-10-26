"""Copied order keeps only manual name choices; matching/pricing remain live."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
import verify_copied_quote_reprice as old
import attachment_v2_client as v2
import attachment_category_browser as rules
import layout_refresh as layout
import scheme2_ui as ui

base=old.base


class CopiedAttachmentNames(unittest.TestCase):
    setUp=old.CopiedQuoteReprice.setUp
    def tearDown(self):
        # These tests deliberately leave an edited configuration unsaved.
        # Dispose only their temporary window without a real user dialog.
        self.w._scheme2_dirty=False
        self.w._quote_scheme_dirty_seq=self.w._quote_scheme_saved_seq
        self.w._quote_scheme_save_timer.stop()
        old.CopiedQuoteReprice.tearDown(self)
    sample=old.CopiedQuoteReprice.sample
    copy_and_edit=old.CopiedQuoteReprice.copy_and_edit
    submit_ordinary=old.CopiedQuoteReprice.submit_ordinary
    transport=old.CopiedQuoteReprice.transport
    response=old.CopiedQuoteReprice.response
    catalog=old.CopiedQuoteReprice.catalog

    def test_copy_edit_keeps_names_not_old_model_size_count_or_manual_dimensions(self):
        original=self.sample()
        original['attachments'][0].update(quantity=17,width_mm=111,height_mm=222,depth_mm=333,
            specification='OLD-SPEC',model_code='OLD-MODEL',manual_inputs={'旧尺寸':123})
        original['attachments'].append(dict(item_name='玻璃门',category_level1='控制柜附件',quantity=8,
            model_code='OLD-GLASS',manual_inputs={'玻璃门高度':900,'玻璃门宽度':600},
            width_mm=600,height_mm=900,attachment_price_id=555,ganged_cabinet_index=1))
        before=deepcopy(original);copied=self.copy_and_edit(original)
        self.assertEqual([row['item_name'] for row in self.w.attachments],['风机测试','木托','玻璃门'])
        for row in self.w.attachments:
            self.assertEqual(row['quantity'],1)
            for field in ('manual_inputs','width_mm','height_mm','depth_mm','specification','model_code',
                          'ganged_cabinet_index','attachment_selection_id','quote_line_id'):
                self.assertNotIn(field,row)
        self.assertTrue(self.w._attachment_names_manual_only)
        self.assertEqual(copied['attachment_selection_mode'],'manual_names')
        self.assertEqual(original,before)

    def test_sizes_models_and_prices_are_matched_to_new_configuration_by_same_name(self):
        original=self.sample()
        original['attachments']=[dict(item_name='侧板',category_level1='侧板',quantity=7,model_code='OLD',
            attachment_price_id=1,height_mm=2000,depth_mm=600,manual_inputs={'旧尺寸':10},quick_amount=777)]
        self.copy_and_edit(original)
        self.w.quote_spec_edit.setText('800*420*1700')
        self.w.height_spin.setValue(1700);self.w.depth_spin.setValue(420)
        catalog=[dict(item_name='侧板',category_level1='侧板',attachment_price_id=2,
                      model_code='NEW',height_mm=1800,depth_mm=400,price=530)]
        selected=self.w.attachments[0]
        matched=v2.match_quote_attachment(self.w,selected,catalog)
        self.assertEqual((matched['attachment_price_id'],matched['model_code']),(2,'NEW'))
        self.assertAlmostEqual(matched['unit_price_override'],530*(1700+420)/(1800+400),places=5)
        self.assertEqual(selected['quantity'],1)
        self.assertNotIn('manual_inputs',selected)

    def test_selected_names_do_not_change_when_door_transform_defaults_change(self):
        self.copy_and_edit(self.sample())
        self.w.attachments.append(dict(item_name='原来选择的门变形',category_level1='门变形',quantity=1))
        before=deepcopy(self.w.attachments)
        with patch.object(layout,'_door_transform_context',return_value=('JP',(0,2))):
            self.assertFalse(layout._sync_door_transform_defaults(self.w))
        self.assertEqual(self.w.attachments,before)
        ui._remove_scheme2_attachment(self.w,len(self.w.attachments)-1)
        self.assertNotIn('原来选择的门变形',[row['item_name'] for row in self.w.attachments])

    def test_only_names_are_manual_quantities_can_follow_new_door_counts(self):
        row=dict(item_name='门限位器',category_level1='门限位器',quantity=1,selection_source='manual')
        window=SimpleNamespace(_attachment_names_manual_only=True,ganged_cabinets=[],
            door_counts=lambda:(0,2),attachments=[row],attachment_default_opt_outs=set(),
            attachment_default_quantity_overrides=set(),update_attachment_view=lambda:None)
        self.assertTrue(layout._sync_door_count_default_quantities(window,previous_counts=(1,0)))
        self.assertEqual(row['quantity'],4)
        window.attachment_default_quantity_overrides={rules.DEFAULT_DOOR_LIMITER}
        row['quantity']=9
        layout._sync_door_count_default_quantities(window,previous_counts=(1,0))
        self.assertEqual(row['quantity'],9,'a new manual quantity edit remains respected')

    def test_real_picker_does_not_add_defaults_and_allows_explicit_manual_selection(self):
        original=self.sample();original['attachments']=original['attachments'][:1]
        self.copy_and_edit(original)
        catalog=self.catalog()['items']+[
            dict(attachment_price_id=102,item_name='门限位器',category_level1='门限位器',price=10,unit='件'),
            dict(attachment_price_id=103,item_name='A4资料盒',category_level1='资料盒',price=20,unit='个')]
        def start(worker):
            def reply():
                if 'catalog?v=2' in worker.url:
                    worker.succeeded.emit(dict(data_version='copied-names-fixture',items=deepcopy(catalog)))
                else:worker.failed.emit('offline preview not needed')
                worker.finished.emit()
            QTimer.singleShot(1,reply)
        with patch.object(base.ns['ApiWorker'],'start',start):
            dialog=base.ns['AttachmentDialog'](deepcopy(self.w.attachments),api_url=self.w.base_url(),
                parent=self.w,target_dimensions=(800,1800,600))
            self.addCleanup(dialog.close)
            base.pump(lambda:len(getattr(dialog,'catalog',[]))==3)
            self.assertEqual(dialog.prepare_default_selections(),0)
            self.assertEqual([row['item_name'] for row in dialog.attachments],['风机测试'])
            dialog.rebuild_table()
            self.assertEqual([row['item_name'] for row in dialog.attachments],['风机测试'])
            dialog.toggle_default_selection(rules.DEFAULT_DOOR_LIMITER)
            self.assertIn('门限位器',[row['item_name'] for row in dialog.attachments])
            selected=dialog.collect_attachments(show_errors=False)
            self.assertIsNotNone(selected)
            self.assertIn('风机测试',[row['item_name'] for row in selected])
            dialog.close()
            empty=base.ns['AttachmentDialog']([],api_url=self.w.base_url(),parent=self.w,
                target_dimensions=(800,1800,600))
            self.addCleanup(empty.close)
            base.pump(lambda:len(getattr(empty,'catalog',[]))==3)
            self.assertEqual(empty.attachments,[],'an empty manual name list stays empty')
            empty.close()
            self.w._attachment_names_manual_only=False
            normal=base.ns['AttachmentDialog']([],api_url=self.w.base_url(),parent=self.w,
                target_dimensions=(800,1800,600))
            self.addCleanup(normal.close)
            base.pump(lambda:len(getattr(normal,'catalog',[]))==3)
            self.assertIn('门限位器',[row['item_name'] for row in normal.attachments])

    def test_saved_copy_reprices_without_mutating_original_and_keeps_selection_mode(self):
        original=self.sample();before=deepcopy(original)
        self.copy_and_edit(original);self.submit_ordinary()
        saved=self.w.draft_items[1]
        self.assertEqual(saved['attachment_selection_mode'],'manual_names')
        self.assertEqual(saved['attachments'][0]['quick_amount'],25)
        self.assertEqual(saved['attachments'][0]['formula_amount'],11)
        self.assertEqual(saved['attachments'][0]['quantity'],1)
        self.assertEqual(original,before)
        restored=json.loads(json.dumps(saved))
        self.w.load_draft_item(restored)
        self.assertTrue(self.w._attachment_names_manual_only)
        self.assertEqual([x['item_name'] for x in self.w.attachments],['风机测试','木托'])

    def test_page_state_restore_and_reset_do_not_leak_manual_names_into_new_quote(self):
        original=self.sample();self.copy_and_edit(original)
        state=ui._capture_scheme2_page_state(self.w)
        self.w._attachment_names_manual_only=False;self.w.attachments=[]
        ui._restore_scheme2_page_state(self.w,state)
        self.assertTrue(self.w._attachment_names_manual_only)
        self.assertEqual([x['item_name'] for x in self.w.attachments],['风机测试','木托'])
        self.w.reset_current_cabinet()
        self.assertFalse(self.w._attachment_names_manual_only)
        self.w.load_draft_item(original)
        self.assertFalse(self.w._attachment_names_manual_only)

    def test_manual_rename_is_not_reverted_by_future_price_merge(self):
        source=v2.copied_attachment_name_selection(dict(item_name='风机旧名称',quantity=4))
        item=dict(attachments=[source],formula={},quick={})
        dialog=ui.AttachmentEditor(self.w,item);self.addCleanup(dialog.close)
        dialog.table.item(0,dialog.COL_NAME).setText('人工新名称');dialog.accept()
        row=item['attachments'][0]
        self.assertEqual(row['copied_attachment_name'],'人工新名称')
        self.assertEqual(v2.merge_cost(row,dict(item_name='目录名称',quantity=1,formula_amount=2,
                                              quick_amount=3,status='FIXED'))['item_name'],'人工新名称')

    def test_different_old_rows_with_same_name_are_one_new_logical_choice(self):
        original=self.sample()
        original['attachments'].append({**original['attachments'][0],'quantity':8,'model_code':'OTHER'})
        self.copy_and_edit(original)
        self.assertEqual([row['item_name'] for row in self.w.attachments],['风机测试','木托'])
        self.assertEqual(self.w.attachments[0]['quantity'],1)

    def test_old_deduction_quantity_is_not_reused_when_only_name_is_copied(self):
        row=v2.copied_attachment_name_selection(dict(item_name='安装板',quantity=2,attachment_price_sign=-1))
        self.assertEqual(row['item_name'],'安装板')
        self.assertEqual(row['quantity'],1)
        self.assertNotIn('attachment_price_sign',row)

    def test_new_copy_prices_and_names_survive_actual_workbook_export(self):
        self.copy_and_edit(self.sample());self.submit_ordinary()
        self.w._quote_order_nature='EXTERNAL'
        saved=self.w.draft_items[1]
        items=ui._quote_export_items_snapshot(self.w,[saved])
        self.assertEqual(items[0]['attachments'][0]['item_name'],'风机测试')
        self.assertEqual(items[0]['attachments'][0]['quantity'],1)
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='copied-name-export-') as temporary:
            payload=Path(temporary)/'quote.json';output=Path(temporary)/'quote.xlsx'
            payload.write_text(json.dumps(dict(quote_id='SYNTHETIC-COPY',company_name='合成复制测试客户',
                order_nature='EXTERNAL',items=items),ensure_ascii=False),encoding='utf-8')
            result=subprocess.run(['node','export_dual_quote_workbook.mjs',str(payload),str(output)],
                cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=35)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run(['node','--input-type=module','-e',
                "import ExcelJS from '@excel.js/exceljs';const b=new ExcelJS.Workbook();"
                "await b.xlsx.readFile(process.argv[1]);const s=b.getWorksheet('快速报价单');"
                "console.log(JSON.stringify([s.getCell('F11').value,s.getCell('G11').value,s.getCell('H11').value]));",
                str(output)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),[items[0]['quote_display']['unit_price'],
                items[0]['quote_display']['total'],items[0]['quote_display']['remark']])


if __name__=='__main__':unittest.main(verbosity=2)
