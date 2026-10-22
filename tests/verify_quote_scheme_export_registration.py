"""Real Qt export flow with isolated file workers and an offline scheme server.

No client credentials, online schemes, production workbooks or builds are used.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import verify_quote_document_progress as base
from verify_quote_document_progress import app, wait, ui, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
import quote_scheme_center as schemes


class ExportRegistration(unittest.TestCase):
    def setUp(self):
        base.DocumentProgress.setUp(self)
        self.server = dict(scheme_no='BJ-20261019-000003', status='DRAFT', lock_version=7,
                           version_no=1, snapshot={})
        self.scheme_requests = []
        self.registration_error = None
        self.registration_reply = None
        self.lose_reply = False
        self.hold_post = False
        self.held = []
        self.information = []

        def start(worker):
            worker.test_running = True
            self.scheme_requests.append((worker.method, worker.url, copy.deepcopy(worker.payload)))

            def respond():
                worker.test_running = False
                if worker.method == 'GET':
                    if '?' in worker.url:
                        row = {**self.server, 'creator_name':'创建人', 'last_editor_name':'当前人员'}
                        result = dict(items=[row], total=1, page=1, page_size=10)
                    else:
                        result = copy.deepcopy(self.server)
                    worker.succeeded.emit(result)
                elif worker.method == 'POST' and worker.url.endswith('/export-result'):
                    if self.registration_error:
                        worker.failed.emit(self.registration_error)
                    elif self.registration_reply is not None:
                        worker.succeeded.emit(copy.deepcopy(self.registration_reply))
                    else:
                        payload = worker.payload
                        self.assertEqual(payload['expected_version'], self.server['lock_version'])
                        if self.server['status'] in ('DRAFT', 'REVISING'):
                            self.server.update(status='QUOTED', lock_version=self.server['lock_version']+1,
                                               snapshot=copy.deepcopy(payload['snapshot']))
                        if self.lose_reply:
                            worker.failed.emit('请求超时（服务器可能已完成）')
                        else:
                            worker.succeeded.emit(dict(recorded=True, formal_success=True,
                                status=self.server['status'], lock_version=self.server['lock_version']))
                else:
                    self.fail(f'Unexpected network request: {worker.method} {worker.url}')
                worker.finished.emit()

            if self.hold_post and worker.method == 'POST':
                self.held.append(respond)
            else:
                QTimer.singleShot(10, respond)

        for p in (patch.object(schemes.QuoteSchemeWorker, 'start', start),
                  patch.object(schemes.QuoteSchemeWorker, 'isRunning',
                               lambda w: bool(getattr(w, 'test_running', False))),
                  patch.object(QMessageBox, 'information', lambda *args:self.information.append(args[2]))):
            p.start()
            self.addCleanup(p.stop)
        w = self.window
        w._quote_scheme_id = self.server['scheme_no']
        w._quote_scheme_status = 'DRAFT'
        w._quote_scheme_version = 7
        w._quote_scheme_dirty_seq = 3
        w._quote_scheme_saved_seq = 1
        w.quote_scheme_operator_name.setText('当前人员')
        w._qm_entry_pending = True  # Exercise a document opened from a workflow entry.
        w.show_section(ui.QUOTE_ROUTE)
        w._quote_scheme_save_timer.stop()
        self.path = Path(self.folder.name)/'result.xlsx'
        # Cleanup runs before the base window.close; never show modal dialogs
        # or let an offline fixture accidentally start an automatic save.
        self.addCleanup(self.clean_window)

    def clean_window(self):
        self.window._quote_scheme_save_timer.stop()
        self.window._quote_scheme_export_context = None
        self.window._quote_scheme_pending_export = None
        self.window._quote_scheme_registration_busy = False
        self.window._quote_scheme_id = ''
        self.window._quote_scheme_last_save_failed = False
        self.window._scheme2_dirty = False
        self.controller.reset()
        wait(lambda:not self.window._quote_scheme_workers)

    def export(self):
        self.controller.export()
        wait(lambda:not self.controller.busy)
        wait(lambda:not self.window._quote_scheme_workers)

    def posts(self):
        return [p for method, url, p in self.scheme_requests if method=='POST']

    def fail_registration(self):
        self.registration_error = '本机模拟网络故障'
        self.export()
        self.assertEqual(self.controller.state, 'failed')
        self.assertTrue(self.path.is_file())

    def test_missing_operator_cancel_stops_before_file_dialog_and_requests(self):
        self.window.quote_scheme_operator_name.clear()
        with patch.object(QInputDialog, 'getText', return_value=('',False)) as prompt, \
                patch.object(QFileDialog, 'getSaveFileName') as dialog:
            self.controller.export()
        prompt.assert_called_once()
        dialog.assert_not_called()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.scheme_requests, [])
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.window._quote_scheme_export_context)

    def test_blank_operator_is_rejected_even_in_legacy_workspace(self):
        self.window._quote_scheme_id = ''
        self.window.quote_scheme_operator_name.clear()
        with patch.object(QInputDialog, 'getText', return_value=('   ',True)), \
                patch.object(QFileDialog, 'getSaveFileName') as dialog:
            self.controller.export()
        dialog.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_enter_operator_exports_registers_and_refreshes_visible_status(self):
        self.window.quote_scheme_operator_name.clear()
        with patch.object(QInputDialog, 'getText', return_value=('  登记人员  ',True)):
            self.export()
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.posts()[0]['operator_name'], '登记人员')
        self.assertEqual(self.window._quote_scheme_status, 'QUOTED')
        self.assertEqual(self.window._quote_scheme_version, 8)
        self.assertTrue(self.window._quote_scheme_read_only)
        self.assertEqual(self.window._quote_scheme_saved_seq, 3)
        self.assertEqual(self.controller.state, 'success')
        self.assertIn('文件已导出，方案已登记（已报价）', self.controller.feedback['export']['label'].full_text)
        self.assertEqual(self.window.quote_scheme_table.item(0,3).text(), '已报价')
        self.assertTrue(self.window.quote_scheme_registration_retry.isHidden())
        self.assertIsNone(self.window._quote_scheme_pending_export)
        self.assertFalse(any('正式报价单已生成' in value for value in self.information))

    def test_file_success_is_not_registration_success_while_waiting(self):
        self.hold_post = True
        self.controller.export()
        wait(lambda:bool(self.held))
        self.assertTrue(self.path.exists())
        self.assertTrue(self.controller.busy)
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.assertIn('文件已导出，正在登记方案', self.controller.feedback['export']['label'].full_text)
        self.assertEqual(self.window.scheme2_quote_export.text(), '登记中…')
        self.assertFalse(self.window.quote_scheme_registration_retry.isEnabled())
        self.assertIsNone(self.controller.hide_timer)
        self.assertFalse(self.window.scheme2_quote_print.isEnabled())
        self.controller.export()
        schemes._retry_export_registration(self.window)
        self.assertEqual(len(self.posts()), 1)
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.held.pop()()
        wait(lambda:not self.window._quote_scheme_workers)

    def test_failure_retry_uses_frozen_receipt_without_exporting_or_confirming_again(self):
        self.fail_registration()
        before_file = self.path.read_bytes(), self.path.stat().st_mtime_ns
        before_requests = copy.deepcopy(self.requests)
        before_payload = copy.deepcopy(self.posts()[0])
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.assertEqual(self.window.scheme2_quote_export.text(), '重试登记')
        self.assertFalse(self.window.quote_scheme_registration_retry.isHidden())
        self.assertIsNone(self.controller.hide_timer)
        self.window.quote_scheme_operator_name.setText('以后填写的另一人')
        self.registration_error = None
        self.controller.feedback['export']['retry'].click()
        wait(lambda:not self.controller.busy)
        wait(lambda:not self.window._quote_scheme_workers)
        self.assertEqual(self.posts(), [before_payload, before_payload])
        self.assertEqual(self.requests, before_requests)
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before_file)
        self.assertEqual(self.window._quote_scheme_status, 'QUOTED')

    def test_export_button_and_center_retry_share_single_registration_request(self):
        self.fail_registration()
        self.registration_error = None
        self.window.scheme2_quote_export.click()
        self.window.quote_scheme_registration_retry.click()
        wait(lambda:not self.controller.busy)
        wait(lambda:not self.window._quote_scheme_workers)
        self.assertEqual(len(self.posts()), 2)
        self.assertEqual(len(self.requests), 2)  # Original confirm-check/confirm only.

    def test_lost_success_response_is_reconciled_by_unique_server_snapshot_receipt(self):
        self.lose_reply = True
        self.export()
        self.assertEqual(self.server['status'], 'QUOTED')
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.window.quote_scheme_registration_retry.click()
        wait(lambda:not self.controller.busy)
        wait(lambda:not self.window._quote_scheme_workers)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.window._quote_scheme_status, 'QUOTED')
        self.assertEqual(self.window._quote_scheme_version, 8)

    def test_stale_version_does_not_overwrite_other_edits(self):
        self.fail_registration()
        self.registration_error = None
        self.server['lock_version'] = 8
        self.server['snapshot'] = {'draft_items':[{'name':'别人修改的方案'}]}
        saved = copy.deepcopy(self.server)
        self.controller.retry()
        wait(lambda:not self.controller.busy)
        self.assertEqual(self.server, saved)
        self.assertEqual(len(self.posts()), 1)
        self.assertIn('不能覆盖', self.controller.reason)
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.assertTrue(self.path.is_file())

    def test_matching_content_without_our_receipt_is_not_claimed_as_our_success(self):
        self.fail_registration()
        self.server.update(status='QUOTED',lock_version=8,snapshot=copy.deepcopy(self.posts()[0]['snapshot']))
        self.server['snapshot']['document']['export_registration_id'] = 'different-request'
        self.controller.retry()
        wait(lambda:not self.controller.busy)
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.assertEqual(len(self.posts()), 1)

    def test_invalid_acknowledgement_keeps_retry_and_draft(self):
        self.registration_reply = dict(recorded=False, formal_success=True, status='QUOTED', lock_version=8)
        self.export()
        for result in (
                [],
                dict(recorded=True, formal_success=False, status='QUOTED', lock_version=8),
                dict(recorded=True, formal_success=True, status='DRAFT', lock_version=8),
                dict(recorded=True, formal_success=True, status='QUOTED', lock_version=7)):
            self.registration_reply = result
            self.controller.retry()
            wait(lambda:not self.controller.busy)
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.assertIn('未确认', self.controller.reason)
        self.assertIsNotNone(self.window._quote_scheme_pending_export)
        self.assertFalse(self.window.quote_scheme_registration_retry.isHidden())

    def test_save_in_flight_blocks_export_then_pending_save_timer_is_paused(self):
        self.window._quote_scheme_save_worker = SimpleNamespace(isRunning=lambda:True)
        with patch.object(QFileDialog, 'getSaveFileName') as dialog:
            self.controller.export()
        dialog.assert_not_called()
        self.assertEqual(self.requests, [])
        self.window._quote_scheme_save_worker = None
        self.window._quote_scheme_save_timer.start(1)
        self.export()
        self.assertFalse(self.window._quote_scheme_save_timer.isActive())
        self.assertFalse(any(method=='PUT' for method,_,_ in self.scheme_requests))
        self.assertEqual(self.window._quote_scheme_status, 'QUOTED')

    def test_cancel_file_dialog_restores_editability_and_autosave(self):
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.controller.export()
        self.assertEqual(self.controller.state, 'idle')
        self.assertIsNone(self.window._quote_scheme_export_context)
        self.assertIsNone(self.window._quote_scheme_pending_export)
        self.assertFalse(self.window._quote_scheme_read_only)
        self.assertTrue(self.window.scheme2_company.isEnabled())
        self.assertTrue(self.window.scheme2_quote_print.isEnabled())
        self.assertTrue(self.window._quote_scheme_save_timer.isActive())
        self.window._quote_scheme_save_timer.stop()
        self.assertEqual(self.scheme_requests, [])
        self.assertFalse(self.path.exists())

    def test_file_failure_does_not_register_success_or_keep_frozen_workspace(self):
        self.response_error = {'message':'模拟导出预检失败'}
        self.export()
        self.assertIsNone(self.window._quote_scheme_export_context)
        self.assertIsNone(self.window._quote_scheme_pending_export)
        self.assertFalse(self.window._quote_scheme_read_only)
        self.assertEqual(self.window._quote_scheme_status, 'DRAFT')
        self.assertEqual(self.posts(), [])
        self.assertFalse(self.path.exists())

    def test_pending_registration_cannot_be_silently_replaced_or_closed(self):
        self.fail_registration()
        no = self.window._quote_scheme_id
        schemes._new_scheme(self.window)
        schemes._open_scheme(self.window, 'BJ-20261019-000099')
        self.controller.generate()
        self.assertEqual(self.window._quote_scheme_id, no)
        self.assertEqual(len(self.scheme_requests), 1)
        with patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.No) as warning:
            event = QCloseEvent()
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(warning.call_args.args[-1], QMessageBox.StandardButton.No)

    def test_revision_finishes_as_quoted_but_archived_export_retains_historical_status(self):
        self.server['status'] = self.window._quote_scheme_status = 'REVISING'
        self.export()
        self.assertEqual(self.window._quote_scheme_status, 'QUOTED')
        self.server['status'] = self.window._quote_scheme_status = 'ARCHIVED'
        self.export()
        self.assertEqual(self.window._quote_scheme_status, 'ARCHIVED')
        self.assertEqual(self.window._quote_scheme_version, 8)
        self.assertIn('已归档', self.controller.feedback['export']['label'].full_text)

    def test_success_after_old_list_request_queues_a_fresh_list(self):
        self.window._quote_scheme_list_worker = object()
        self.export()
        self.assertTrue(self.window._quote_scheme_reload_after_registration)
        schemes._list_loaded(self.window, dict(items=[dict(self.server,status='DRAFT')],total=1))
        schemes._list_finished(self.window)
        wait(lambda:self.window.quote_scheme_table.item(0,3) is not None
             and self.window.quote_scheme_table.item(0,3).text()=='已报价')
        wait(lambda:not self.window._quote_scheme_workers)
        self.assertFalse(self.window._quote_scheme_reload_after_registration)

    def test_late_open_response_cannot_replace_the_workspace_during_registration(self):
        with patch.object(schemes, '_run') as run:
            schemes._open_scheme(self.window, 'BJ-20261019-000099')
            opened = run.call_args.args[4]
        self.hold_post = True
        self.controller.export()
        wait(lambda:bool(self.held))
        opened(dict(scheme_no='BJ-20261019-000099',snapshot={}))
        self.assertEqual(self.window._quote_scheme_id, 'BJ-20261019-000003')
        self.held.pop()()
        wait(lambda:not self.window._quote_scheme_workers)

    def test_registration_feedback_and_center_recovery_are_visible_without_overlap(self):
        self.window.resize(1280,800)
        self.window.show()
        self.fail_registration()
        app.processEvents()
        feedback = self.controller.feedback['export']
        self.assertTrue(feedback['retry'].isVisible())
        self.assertTrue(feedback['details'].isVisible())
        self.assertFalse(feedback['label'].geometry().intersects(feedback['retry'].geometry()))
        self.assertFalse(feedback['label'].geometry().intersects(feedback['details'].geometry()))
        output = base.ROOT/'outputs'
        output.mkdir(exist_ok=True)
        self.assertTrue(self.window.grab().save(str(output/'export-registration-failed.png')))
        self.window.show_section(schemes.SCHEME_ROUTE)
        wait(lambda:not self.window._quote_scheme_workers)
        self.assertTrue(self.window.quote_scheme_registration_retry.isVisible())
        self.assertTrue(self.window.quote_scheme_operation_status.isVisible())
        self.assertIn('文件已导出，方案登记失败',self.window.quote_scheme_operation_status.text())
        self.assertIn('本机模拟网络故障',self.window.quote_scheme_operation_status.toolTip())
        self.assertTrue(self.window.grab().save(str(output/'scheme-registration-retry.png')))
        self.registration_error = None
        self.window.quote_scheme_registration_retry.click()
        wait(lambda:not self.controller.busy)
        wait(lambda:not self.window._quote_scheme_workers)
        self.window.show_section(ui.QUOTE_ROUTE)
        app.processEvents()
        self.assertTrue(self.window.grab().save(str(output/'export-registration-success.png')))


if __name__ == '__main__':
    unittest.main()
