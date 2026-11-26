"""Real Qt recovery: explicit dimensions, preserved sale, atomic failure/retry."""
from copy import deepcopy
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
PROFILE=tempfile.TemporaryDirectory(prefix='cost-recovery-qa-')
os.environ['AI_QUOTE_UPDATE_CONFIG']=str(Path(PROFILE.name)/'disabled-updates.json')
Path(os.environ['AI_QUOTE_UPDATE_CONFIG']).write_text('{}',encoding='utf-8')
os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=str(Path(PROFILE.name)/'orders')
socket.socket.connect=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('Recovery regression forbids network'))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QApplication, QScrollArea
import verify_scheme2_cost_combined_layout as fixture
from verify_scheme2_cost_combined_layout import ui, app
from attachment_v2_client import confirmation_inputs
from cost_recovery import pending_rows, suggested_dimension, recover_selected, dimension_dialog


def cabinet(*, pending):
    item=fixture.sample('成本恢复测试柜',1)
    item.update(material_code='SECC',quick_discount=.5,freight_fee=0,freight_mode='MANUAL',
                quick=dict(base_price=1000,attachment_fee=0,total_cost=1000),
                ganged_cabinet_count=2,ganged_cabinets=[dict(width_mm=800,height_mm=1800,depth_mm=600) for _ in range(2)],
                attachments=[],attachment_contract=2,quote_line_id='11111111-1111-4111-8111-111111111111')
    for i,height in enumerate((50,20)):
        row=dict(item_name='分段板',attachment_price_id=101+i,ganged_cabinet_index=i,
                 quantity=1,attachment_price_sign=1,quick_amount=0,formula_amount=0 if pending else 5,
                 formula_unit_cost=0 if pending else 5,cost_method='FORMULA',
                 status='PENDING_MANUAL' if pending else 'CALCULATED',manual_inputs={} if pending else {'分段板高度':height},
                 required_parameters=[dict(name='分段板高度',source='MANUAL',required=True)])
        if pending:row['pending_manual_dimensions']=['分段板高度']
        else:row.update(material_cost=2,auxiliary_cost=1,labor_cost=1,spray_cost=1)
        item['attachments'].append(row)
    item['attachment_confirmation_inputs']=confirmation_inputs(item['attachments'])
    return item


class CostRecovery(unittest.TestCase):
    setUp=fixture.CostCombinedLayout.setUp

    def prepare(self):
        self.addCleanup(lambda:setattr(self.window,'_scheme2_dirty',False))
        self.donor=cabinet(pending=False);self.target=cabinet(pending=True)
        self.window.draft_items=[self.donor,self.target]
        self.window.refresh_summary();self.window.summary_table.selectRow(1);app.processEvents()
        self.window._quote_scheme_save_timer.stop()
        self.dialog_errors=[];self.calls=[]
        self.warnings=patch.object(ui.QMessageBox,'warning').start();self.addCleanup(patch.stopall)
        return self.target

    def respond(self,item,source,success,failed):
        self.calls.append(deepcopy(source))
        calculated={**source,'status':'CALCULATED','formula_amount':5,'formula_unit_cost':5,
                    'quick_amount':100,'material_cost':2,'auxiliary_cost':1,'labor_cost':1,'spray_cost':1}
        calculated.pop('pending_manual_dimensions',None)
        QTimer.singleShot(0,lambda:success(calculated))

    def start(self,*,cancel=False):
        def operate():
            dialog=QApplication.activeModalWidget()
            try:
                self.assertIsInstance(dialog,ui._SchemeDimensionEditor)
                self.assertEqual([float(field.text()) for field in dialog.fields.values()],[50,20])
                if cancel:dialog.reject()
                else:dialog.confirm_button.click()
            except BaseException as error:
                self.dialog_errors.append(error)
                if isinstance(dialog,QDialog):dialog.reject()
        QTimer.singleShot(0,operate)
        recover_selected(self.window)
        deadline=time.monotonic()+5
        while getattr(self.window,'_scheme2_cost_recovery',None) is not None and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        self.assertIsNone(getattr(self.window,'_scheme2_cost_recovery',None))
        self.assertFalse(self.dialog_errors,repr(self.dialog_errors))

    def test_recovery_keeps_price_factor_and_history_and_clears_pending(self):
        target=self.prepare();before=deepcopy(target)
        before_price=ui._row_values(target)[15:17]
        self.window._qm_state=dict(schema=1,current=1,versions=[dict(items=[deepcopy(self.donor)],sealed=True)])
        history=deepcopy(self.window._qm_state)
        self.window.recalculate_draft_attachment=self.respond
        self.start()
        self.assertEqual(len(self.calls),2)
        self.assertEqual([x['manual_inputs']['分段板高度'] for x in self.calls],[50,20])
        self.assertEqual(pending_rows(target),[])
        self.assertEqual(ui._row_values(target)[15:17],before_price)
        self.assertEqual(target['quick_discount'],before['quick_discount'])
        self.assertEqual(target['quick'],before['quick'])
        self.assertEqual(target['attachment_confirmation_inputs'],before['attachment_confirmation_inputs'])
        self.assertTrue(target['attachment_snapshot_dirty'])
        self.assertEqual(self.window._qm_state,history)
        self.assertTrue(target['formula']['cost_allocation']['complete'])
        self.assertNotIn(self.window.summary_table.item(1,13).text(),('待重算','待核对'))
        self.assertEqual(ui._quote_export_items_snapshot(self.window)[1]['quote_display']['unit_price'],before_price[0])
        self.warnings.assert_not_called()

    def test_cancel_does_not_reprice_or_modify(self):
        target=self.prepare();before=deepcopy(target)
        self.window.recalculate_draft_attachment=self.respond
        self.start(cancel=True)
        self.assertEqual(target,before);self.assertEqual(self.calls,[])

    def test_later_failure_keeps_all_original_costs_and_can_retry(self):
        target=self.prepare();before=deepcopy(target)
        def respond(item,source,success,failed):
            if self.calls:QTimer.singleShot(0,lambda:failed('离线测试失败'))
            else:self.respond(item,source,success,failed)
        self.window.recalculate_draft_attachment=respond
        self.start();self.assertEqual(target,before);self.warnings.assert_called_once()
        self.calls=[];self.window.recalculate_draft_attachment=self.respond
        self.start();self.assertEqual(len(self.calls),2);self.assertEqual(pending_rows(target),[])

    def test_readonly_cannot_recover(self):
        target=self.prepare();before=deepcopy(target)
        self.window._quote_scheme_read_only=True
        self.window.recalculate_draft_attachment=self.respond
        recover_selected(self.window)
        self.assertEqual(target,before);self.assertEqual(self.calls,[])

    def test_changed_draft_during_recovery_drops_stale_result(self):
        target=self.prepare()
        def respond(item,source,success,failed):
            target['name']='用户新名称'
            self.respond(item,source,success,failed)
        self.window.recalculate_draft_attachment=respond
        self.start()
        self.assertEqual(target['name'],'用户新名称')
        self.assertTrue(pending_rows(target));self.assertEqual(len(self.calls),1)

    def test_missing_or_conflicting_reference_is_never_guessed(self):
        target=self.prepare();row=target['attachments'][0]
        self.assertEqual(suggested_dimension(self.window.draft_items,target,row,'分段板高度'),50)
        other=deepcopy(self.donor);other['attachments'][0]['manual_inputs']['分段板高度']=70
        self.assertIsNone(suggested_dimension([self.donor,other],target,row,'分段板高度'))
        other['ganged_cabinets'][0]['width_mm']=900
        self.assertIsNone(suggested_dimension([other],target,row,'分段板高度'))
        self.assertIsNone(suggested_dimension([],target,row,'分段板高度'))

    def test_recovery_button_is_only_available_for_pending_editable_row(self):
        self.prepare();button=self.window.scheme2_cost_recover
        self.assertTrue(button.isVisible());self.assertTrue(button.isEnabled())
        self.window.summary_table.selectRow(0);app.processEvents();self.assertFalse(button.isVisible())
        self.window.summary_table.selectRow(1);self.window._quote_scheme_read_only=True
        self.window.refresh_summary();self.assertFalse(button.isEnabled())

    def test_cost_freight_follows_recovered_weight_without_changing_sale_freight(self):
        from freight_state import AUTO_FREIGHT_BASIS
        from quick_discount_rules import quick_freight_fee
        target=self.prepare()
        target.update(freight_mode='AUTO',freight_basis=AUTO_FREIGHT_BASIS)
        target['formula']['corrected_material_weight_kg']=20
        self.window.refresh_summary()
        before=ui._row_values(target)[15:17];sale_freight=quick_freight_fee(target)
        def respond(item,source,success,failed):
            self.respond(item,source,lambda cost:success({**cost,'weight_kg':2}),failed)
        self.window.recalculate_draft_attachment=respond
        self.start()
        self.assertEqual(target['freight_fee'],24)
        self.assertEqual(quick_freight_fee(target),sale_freight)
        self.assertEqual(ui._row_values(target)[15:17],before)
        self.window.refresh_summary();self.assertEqual(ui._row_values(target)[15:17],before)

    def test_twenty_cabinet_dimension_fields_scroll_and_keep_confirmation_visible(self):
        self.prepare()
        fields=[f'柜体{i+1} · 分段板高度' for i in range(20)]
        dialog=dimension_dialog(self.window,fields,dict.fromkeys(fields,50))
        self.addCleanup(dialog.close)
        dialog.show();app.processEvents()
        scroll=dialog.findChild(QScrollArea,'scheme2RecoveryDimensionScroll')
        self.assertIsNotNone(scroll)
        self.assertGreater(scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(dialog.confirm_button.isVisible())
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual(len(dialog.fields),20)


if __name__=='__main__':unittest.main(verbosity=2)
