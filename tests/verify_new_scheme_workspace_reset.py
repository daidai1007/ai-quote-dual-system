"""New scheme clears every workspace, without writes or stale async results."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import verify_drawing_workflow as base
from PySide6.QtCore import QObject, QRect, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QMessageBox
import quote_scheme_center as centre
import scheme2_ui as ui
from quote_request_context import stamp_quote_response


class PendingWorker(QObject):
    succeeded = Signal(object, object)
    failed = Signal(object, str)
    progress = Signal(dict)
    finished = Signal()

    def __init__(self, *_args):
        super().__init__(_args[-1])
        self.interrupted = False

    def start(self):
        pass

    def isRunning(self):
        return True

    def requestInterruption(self):
        self.interrupted = True


class PendingQuoteWorker(PendingWorker):
    succeeded = Signal(dict)
    failed = Signal(str)


class NewSchemeReset(unittest.TestCase):
    def setUp(self):
        screen = Mock(wraps=base.app.primaryScreen())
        screen.availableGeometry.return_value = QRect(0, 0, 4096, 2160)
        screen_patch = patch.object(base.ns['MainWindow'], 'screen', return_value=screen)
        screen_patch.start()
        self.addCleanup(screen_patch.stop)
        base.DrawingWorkflowTests.setUp(self)
        expected_scale = os.environ.get('QT_SCALE_FACTOR')
        if expected_scale:
            self.assertAlmostEqual(self.w.devicePixelRatioF(), float(expected_scale), places=2)

    def tearDown(self):
        self.w._quote_scheme_save_timer.stop()
        self.w._quote_scheme_id = ''
        self.w._scheme2_dirty = False
        base.DrawingWorkflowTests.tearDown(self)

    def new(self, answer=QMessageBox.StandardButton.Yes):
        with patch.object(QMessageBox, 'question', return_value=answer):
            centre._new_scheme(self.w)
        base.app.processEvents()

    def seed(self, failed=True):
        w = self.w
        w._quote_scheme_id = 'BJ-OLD-SAVED'
        w._quote_scheme_status = 'QUOTED'
        w.scheme2_name_edit.setText('上一方案产品')
        w.quote_spec_edit.setText('(800+800)*600*(2000+100)')
        w.quantity_spin.setValue(7)
        for name, text in (('product_combo', 'JP'), ('material_combo', '碳钢板 (SECC)'),
                           ('coating_combo', '橘纹'), ('scheme2_color_combo', 'RAL7035 浅灰'),
                           ('scheme2_company', '上一方案公司')):
            combo = getattr(w, name)
            with QSignalBlocker(combo):
                if combo.findText(text) < 0:
                    combo.addItem(text, text)
                combo.setCurrentText(text)
        w.attachments = [dict(custom=True, item_name='人工附件', quantity=2,
                              formula_amount=20, quick_amount=100)]
        w._scheme2_attachments_manual = True
        ui._refresh_scheme2_attachment_summary(w)
        ui._mark_manual(w, 'dimensions')
        ui._mark_manual(w, 'material')
        ui._mark_ai(w, 'color')
        old = dict(name='旧柜', product_code='JP', quantity=1, specification='800*600*2000',
                   formula=dict(material_cost=100, auxiliary_cost=10, labor_cost=20, spray_cost=30),
                   quick=dict(base_price=500, total_cost=500), attachments=deepcopy(w.attachments))
        w.draft_items = [old]
        w._scheme2_edit_item = old
        w._scheme2_detail_item = old
        w._scheme2_deleted = (0, deepcopy(old))
        w._scheme2_active_settings = {'carbon_price': 999}
        w.scheme2_cost_undo.show()
        w.scheme2_undo_timer.start(5000)
        w._scheme2_drawing_pages = [dict(key='old-page', item={'name': '旧识图'}, visited=True)]
        w._scheme2_drawing_page_index = 0
        w.recognized_documents = [{'name': '旧图纸'}]
        w.recognized_drawings = [{'name': '旧柜', 'verified': True}]
        w._draft_drawing_refs = {id(old): ({'old': True}, None)}
        w._quote_drawing = w.active_drawing = {'name': '旧图纸'}
        w.current_result = {'quote_id': 'old-result'}
        w._attachment_v2_line_id = 'old-line'
        w._v2_confirmation_inputs = [{'old': True}]
        w._scheme2_add_started_at = 0
        ui._set_add_progress(w, 5, '旧失败' if failed else '已完成', failed=failed)
        controller = w._scheme2_document_controller
        controller.begin('generate')
        controller.set_stage(3, '服务端预检')
        if failed:
            controller.fail(json.dumps(dict(message='旧附件失败', issues=[dict(line_number=1,
                attachment_name='旧附件', reason='旧错误')]), ensure_ascii=False))
        else:
            controller.set_stage(4, '显示报价单')
            controller.end()
        centre._apply_read_only(w, True)
        w.refresh_summary()
        w._quote_scheme_save_timer.stop()
        return old

    def assert_empty(self):
        w = self.w
        self.assertEqual(w.draft_items, [])
        self.assertEqual(w.summary_table.rowCount(), 0)
        self.assertEqual(w._scheme2_drawing_pages, [])
        self.assertEqual(w.recognized_documents, [])
        self.assertEqual(w.recognized_drawings, [])
        self.assertEqual(w._draft_drawing_refs, {})
        self.assertEqual(w.attachments, [])
        self.assertIsNone(w.current_result)
        self.assertIsNone(w._scheme2_edit_item)
        self.assertIsNone(w._scheme2_deleted)
        self.assertIsNone(w._scheme2_detail_item)
        self.assertIsNone(w._attachment_v2_line_id)
        self.assertEqual(w._v2_confirmation_inputs, [])
        self.assertEqual(w.scheme2_name_edit.text(), '')
        self.assertEqual(w.quote_spec_edit.text(), '')
        for name in ('product_combo', 'material_combo', 'coating_combo', 'scheme2_color_combo',
                     'scheme2_company', 'company_combo'):
            self.assertEqual(getattr(w, name).currentText(), '', name)
        self.assertEqual(w.quantity_spin.value(), 1)
        self.assertEqual(w.cabinet_body_thickness_spin.value(), 1.5)
        self.assertFalse(w.scheme2_manual_fields)
        for badge in w.scheme2_provenance_labels.values():
            self.assertEqual(badge.text(), '待识别')
            self.assertEqual(badge.parentWidget().property('provenanceState'), 'pending')
        self.assertEqual(w.scheme2_attachment_status.text(), '未选择附件')
        self.assertEqual(w.scheme2_completion.text(), '已完成 0 / 0')
        self.assertEqual(w.quote_drawing_preview.counter.text(), '0 / 0')
        self.assertFalse(w.quote_drawing_preview.canvas.isEnabled())
        self.assertFalse(w.quote_drawing_preview.canvas.scene().items())
        self.assertEqual(w.scheme2_order_number.text(), '')
        self.assertEqual(w._quote_scheme_id, '')
        self.assertFalse(w._quote_scheme_read_only)
        self.assertFalse(w._scheme2_document_busy)
        self.assertFalse(w._scheme2_dirty)
        self.assertFalse(w.quote_calculation_in_progress)
        self.assertEqual(w.scheme2_add_button.text(), '加入报价清单')
        self.assertTrue(w.scheme2_add_button.isEnabled())
        self.assertTrue(w.scheme2_name_edit.isEnabled())
        self.assertTrue(w.summary_table.isEnabled())
        self.assertEqual(w.scheme2_quote_preview.editTriggers(), QAbstractItemView.EditTrigger.DoubleClicked)
        self.assertFalse(w.scheme2_cost_generate.isEnabled())
        self.assertFalse(w.scheme2_quote_export.isEnabled())
        self.assertTrue(w.scheme2_add_progress.isHidden())
        self.assertEqual(w.scheme2_add_progress.format(), '')
        self.assertEqual(w.scheme2_add_progress.toolTip(), '')
        self.assertEqual(w.scheme2_add_progress.property('failureReason'), '')
        self.assertTrue(w.scheme2_cost_undo.isHidden())
        self.assertEqual(w.scheme2_detail_table.rowCount(), 0)
        self.assertEqual(w.scheme2_detail_meta.text(), '')
        controller = w._scheme2_document_controller
        self.assertEqual((controller.reason, controller.issues), ('', []))
        for host, bar, locate in controller.widgets.values():
            self.assertTrue(host.isHidden())
            self.assertTrue(locate.isHidden())
            self.assertEqual(bar.format(), '')
            self.assertEqual(bar.toolTip(), '')
        for name in ('_scheme2_add_elapsed_timer', '_scheme2_recognition_elapsed_timer',
                     '_formula_template_debounce_timer', '_history_price_timer',
                     '_quote_scheme_save_timer', 'scheme2_undo_timer'):
            self.assertFalse(getattr(w, name).isActive(), name)

    def test_success_and_failure_reset_all_pages_and_repeated_new(self):
        for failed in (True, False):
            with self.subTest(failed=failed):
                old = self.seed(failed)
                old_copy = deepcopy(old)
                catalog_counts = [getattr(self.w, key).count() for key in (
                    'product_combo', 'material_combo', 'coating_combo', 'scheme2_color_combo')]
                defaults = deepcopy(self.w.scheme2_defaults)
                self.new()
                self.assertEqual(self.w.stack.currentIndex(), ui.OPTION_ROUTE)
                for route in (ui.COST_ROUTE, ui.QUOTE_ROUTE, ui.OPTION_ROUTE):
                    self.w.show_section(route)
                    self.w.resize(1400 if route == ui.QUOTE_ROUTE else 1050, 800)
                    base.app.processEvents()
                    self.assert_empty()
                self.assertEqual(old, old_copy)  # No mutation/deletion of saved contents.
                self.assertEqual(self.w.scheme2_defaults, defaults)
                self.assertEqual([getattr(self.w, key).count() for key in (
                    'product_combo', 'material_combo', 'coating_combo', 'scheme2_color_combo')], catalog_counts)
                self.new()
                self.assert_empty()
        artifacts = os.environ.get('AI_QUOTE_UI_ARTIFACT_DIR')
        if artifacts:
            Path(artifacts).mkdir(parents=True, exist_ok=True)
            self.w.resize(1553, 980)
            base.app.processEvents()
            QTest.qWait(60)
            self.assertTrue(self.w.grab().save(str(Path(artifacts) / 'new-scheme-empty.png')))

    def test_cancel_new_preserves_existing_workspace_and_progress(self):
        old = self.seed()
        payload = deepcopy(ui._order_workspace_payload(self.w))
        progress = self.w.scheme2_add_progress.property('failureReason')
        trace = self.w._scheme2_document_controller.trace
        self.new(QMessageBox.StandardButton.No)
        self.assertEqual(ui._order_workspace_payload(self.w), payload)
        self.assertIs(self.w.draft_items[0], old)
        self.assertEqual(self.w.scheme2_add_progress.property('failureReason'), progress)
        self.assertEqual(self.w._scheme2_document_controller.trace, trace)
        self.assertEqual(self.w._quote_scheme_id, 'BJ-OLD-SAVED')

    def test_unsaved_selection_also_requires_confirmation(self):
        self.w.quote_spec_edit.setText('800*600*1800')
        self.w.width_spin.setValue(800)
        self.w.depth_spin.setValue(600)
        self.w.height_spin.setValue(1800)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as question:
            centre._new_scheme(self.w)
        question.assert_called_once()
        self.assertEqual(self.w.quote_spec_edit.text(), '800*600*1800')

    def test_preview_queued_before_new_never_starts_a_request(self):
        controller = self.w._scheme2_document_controller
        controller.generate()
        with patch.object(base.ns['ApiWorker'], 'start') as start:
            self.new()
            start.assert_not_called()
        self.assert_empty()

    def test_old_preview_success_or_error_cannot_navigate_or_revive_progress(self):
        for success in (True, False):
            with self.subTest(success=success):
                self.seed()
                controller = self.w._scheme2_document_controller
                controller.validate = lambda _items: []
                workers = []
                with patch.object(base.ns['ApiWorker'], 'start', lambda worker: workers.append(worker)):
                    controller.generate()
                    base.app.processEvents()
                worker = workers[-1]
                self.new()
                if success:
                    worker.succeeded.emit({'valid': True, 'persisted': False})
                else:
                    worker.failed.emit('上一方案的预检失败')
                base.app.processEvents()
                self.assertEqual(self.w.stack.currentIndex(), ui.OPTION_ROUTE)
                self.assert_empty()

    def test_old_recognition_same_source_key_cannot_update_new_scheme(self):
        entry = dict(key='same-file#page=1', source_path='same-file.png', page_index=0, page_count=1)
        self.w._scheme2_drawing_pages = [entry]
        with patch.object(ui, '_Scheme2PageRecognitionWorker', PendingWorker):
            ui._recognize_scheme2_page(self.w, entry)
        worker = self.w._scheme2_page_worker
        self.new()
        fresh_entry = deepcopy(entry)
        self.w._scheme2_drawing_pages = [fresh_entry]
        worker.succeeded.emit(entry['key'], {'name': '旧任务识别结果'})
        worker.failed.emit(entry['key'], '旧任务识别失败')
        self.assertNotIn('item', fresh_entry)
        self.assertNotIn('error', fresh_entry)
        self.assertTrue(worker.interrupted)
        worker.finished.emit()
        self.w._scheme2_drawing_pages = []
        self.assert_empty()

    def test_pending_open_scheme_is_ignored_after_new(self):
        callbacks = []
        with patch.object(centre, '_run', side_effect=lambda *args: callbacks.append(args)):
            centre._open_scheme(self.w, 'BJ-OLD')
        self.new()
        callbacks[0][4]({'scheme_no': 'BJ-OLD', 'snapshot': {'draft_items': [{'name': '旧方案'}]}})
        callbacks[0][5]('旧方案打开失败')
        self.assert_empty()
        self.assertTrue(self.w.quote_scheme_save_status.isHidden())

    def test_inflight_quote_is_retired_and_late_signals_cannot_restore_old_state(self):
        self.seed()
        worker = PendingQuoteWorker(self.w)
        self.w.worker = worker
        worker.succeeded.connect(self.w.show_result)
        worker.failed.connect(self.w.show_error)
        worker.progress.connect(lambda event: ui._set_add_progress(self.w, 5, '旧报价完成'))
        self.w.quote_calculation_in_progress = True
        self.w._scheme2_add_after_calculate = True
        self.new()
        worker.succeeded.emit(base.response())
        worker.failed.emit('旧报价失败')
        worker.progress.emit({'stage': 'snapshot'})
        self.assertTrue(worker.interrupted)
        self.assertIn(worker, self.w._scheme2_paused_quote_workers)
        self.assert_empty()
        worker.finished.emit()
        self.assertNotIn(worker, self.w._scheme2_paused_quote_workers)

    def test_render_cache_ink_and_late_render_cleared(self):
        preview = self.w.quote_drawing_preview
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        preview.canvas.set_image(image, [])
        preview.canvas.setEnabled(True)
        preview.document_key, preview.path, preview.page_count = 'old', 'old.png', 1
        preview.annotations['old'] = [{'text': '旧标记'}]
        preview.pages['old'] = 1
        preview.rotations['old'] = 90
        preview.cache['old'] = image
        serial = preview.serial
        self.new()
        preview.ready(serial, image, 1, 'image', 3600)
        for mapping in (preview.annotations, preview.pages, preview.rotations, preview.cache):
            self.assertFalse(mapping)
        self.assert_empty()

    def test_active_export_or_scheme_save_is_not_interrupted(self):
        self.seed()
        controller = self.w._scheme2_document_controller
        controller.begin('export')
        self.new()
        self.assertEqual(self.w._quote_scheme_id, 'BJ-OLD-SAVED')
        self.assertTrue(controller.busy)
        controller.end()
        busy = PendingWorker(self.w)
        self.w._quote_scheme_create_worker = busy
        self.new()
        self.assertEqual(self.w._quote_scheme_id, 'BJ-OLD-SAVED')
        self.assertFalse(busy.interrupted)
        self.w._quote_scheme_create_worker = None

    def test_fresh_quote_can_be_added_after_reset_without_replacing_old_row(self):
        self.seed()
        self.new()
        for name, text, data in (('product_combo', 'JP', 'JP'),
                                 ('material_combo', '碳钢板 (SECC)', 'SECC'),
                                 ('coating_combo', '橘纹', '橘纹')):
            combo = getattr(self.w, name)
            with QSignalBlocker(combo):
                if combo.findData(data) < 0:
                    combo.addItem(text, data)
                combo.setCurrentIndex(combo.findData(data))
        self.w.quote_spec_edit.setText('800*600*1800')
        self.w.scheme2_name_edit.setText('全新报价')
        self.w.width_spin.setValue(800)
        self.w.depth_spin.setValue(600)
        self.w.height_spin.setValue(1800)
        def calculate():
            worker = base.ns['ApiWorker']('https://offline.invalid/api/quotes/calculate-dual',
                                         {'quote_id': 'fresh-after-new'}, self.w)
            self.w.show_result(stamp_quote_response(worker, dict(base.response(), quote_id='fresh-after-new')))
        self.w.calculate = calculate
        with patch.object(centre, '_ensure_created'):
            ui._calculate_and_add(self.w)
            base.pump(lambda: bool(self.w.draft_items) or not self.w._scheme2_add_after_calculate)
            base.app.processEvents()
        self.assertEqual(len(self.w.draft_items), 1, self.w.risk_label.text())
        self.assertEqual(self.w.draft_items[0]['name'], '全新报价')
        self.assertIsNone(self.w._scheme2_edit_item)
        self.assertEqual(self.w.scheme2_add_progress.property('stepLabel'), '已完成')
        self.assertFalse(self.w._scheme2_add_elapsed_timer.isActive())


if __name__ == '__main__':
    unittest.main()
