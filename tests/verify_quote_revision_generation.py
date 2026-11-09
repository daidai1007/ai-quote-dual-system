"""Explicit revision generation, saved acknowledgements and immutable history.

Real Qt controllers with synthetic records; every transport is offline.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

import verify_quote_export_customer as fixture
from verify_quote_document_progress import app, wait, ui, QTimer, QFileDialog
import quote_scheme_center as schemes
import quote_management_model as model


class RevisionGeneration(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ExportCustomer()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.w = self.h.window
        self.m = self.w.quote_management
        self.c = self.h.controller
        self.w._scheme2_loading_order = False
        self.w._quote_scheme_loading = True
        self.m.generated()
        self.m.state['versions'][-1]['sealed'] = True
        original = schemes._snapshot(self.w)
        self.h.server.update(status='REVISING', version_no=2, snapshot=deepcopy(original), lock_version=8)
        schemes._apply_opened_scheme(self.w, deepcopy(self.h.server), ui.COST_ROUTE)
        self.w._quote_scheme_loading = False
        self.w._quote_scheme_save_timer.stop()
        self.original = deepcopy(self.m.state['versions'][0])
        self.saves = []
        self.held = []
        self.hold = False
        self.error = None
        self.reply = None
        prior = schemes.QuoteSchemeWorker.start
        def start(worker):
            if worker.method != 'PUT': return prior(worker)
            worker.test_running = True
            self.saves.append(deepcopy(worker.payload))
            def respond():
                worker.test_running = False
                if self.error:
                    worker.failed.emit(self.error)
                elif self.reply is not None:
                    worker.succeeded.emit(self.reply)
                else:
                    self.assertEqual(worker.payload['expected_version'], self.h.server['lock_version'])
                    old = (self.h.server['snapshot'].get('quote_management') or {}).get('versions') or []
                    new = worker.payload['snapshot']['quote_management']['versions']
                    for version in old:
                        if version.get('confirmed'):
                            candidate = next(v for v in new if v['version'] == version['version'])
                            self.assertEqual({k: v for k, v in version.items() if k != 'sealed'},
                                             {k: v for k, v in candidate.items() if k != 'sealed'})
                    self.h.server.update(snapshot=deepcopy(worker.payload['snapshot']),
                                         lock_version=self.h.server['lock_version']+1)
                    worker.succeeded.emit(dict(saved=True, lock_version=self.h.server['lock_version']))
                worker.finished.emit()
            if self.hold: self.held.append(respond)
            else: QTimer.singleShot(1, respond)
        p = patch.object(schemes.QuoteSchemeWorker, 'start', start)
        p.start(); self.addCleanup(p.stop)

    def edit(self, price=502):
        model.set_unit_price(self.w.draft_items[0], str(price))
        self.w.refresh_summary()
        self.w._quote_scheme_save_timer.stop()

    def generate(self):
        self.w.show_section(ui.COST_ROUTE)
        self.c.generate()
        wait(lambda: not self.c.busy)
        self.w._quote_scheme_save_timer.stop()

    def reopen(self):
        schemes._apply_opened_scheme(self.w, deepcopy(self.h.server), ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop()

    def assert_saved_revision(self, count=2):
        self.assertEqual(self.c.state, 'success', self.c.reason)
        self.assertEqual(self.w._quote_scheme_status, 'REVISING')
        self.assertEqual(self.h.server['status'], 'REVISING')
        versions = self.h.server['snapshot']['quote_management']['versions']
        self.assertEqual(len(versions), count)
        self.assertEqual(versions[0], self.original)
        self.assertTrue(versions[-1]['confirmed'])
        self.assertNotIn('pending_confirmation', versions[-1])
        self.assertNotIn('revision_draft', versions[-1])
        self.assertEqual(self.w._quote_scheme_version, self.h.server['lock_version'])

    def test_revision_generation_confirms_reserved_v2_then_direct_export(self):
        self.edit()
        self.assertFalse(schemes._prepare_export(self.w))
        self.generate()
        self.assert_saved_revision()
        self.assertEqual(self.w.stack.currentIndex(), ui.QUOTE_ROUTE)
        self.assertEqual(ui._row_values(self.m.state['versions'][-1]['items'][0])[15], 502)
        self.assertEqual(len(self.saves), 1)
        self.reopen()
        self.assertEqual(self.m.history.rowCount(), 2)
        self.h.export()
        self.assertTrue(self.h.path.exists())
        for sheet in ('成本', '报价'):
            self.assertEqual(fixture.workbook_cell(self.h.path, sheet, 'B4'), self.w.scheme2_company.currentText())
        self.assertEqual(float(fixture.workbook_cell(self.h.path, '报价', 'F11')), 502)
        self.assertEqual(float(fixture.workbook_cell(self.h.path, '报价', 'G11')), 1004)
        self.assertEqual(self.w._quote_scheme_status, 'QUOTED')
        self.assertEqual(len(self.m.state['versions']), 2)
        self.assertEqual(self.m.state['versions'][0], self.original)

    def test_repeat_generation_is_idempotent_and_changed_confirmed_content_appends(self):
        self.edit(); self.generate(); self.assert_saved_revision()
        v2 = deepcopy(self.m.state['versions'][1])
        self.generate(); self.assert_saved_revision()
        self.assertEqual(self.m.state['versions'][1], v2)
        self.reopen(); self.generate(); self.assert_saved_revision()
        self.edit(503); self.generate(); self.assert_saved_revision(3)
        self.assertEqual(self.m.state['versions'][1], v2)
        self.generate(); self.assert_saved_revision(3)

    def test_unchanged_reserved_revision_is_confirmed_in_place(self):
        self.generate(); self.assert_saved_revision()
        self.generate(); self.assert_saved_revision()

    def test_cancelled_export_keeps_saved_revision_and_revising_status(self):
        self.edit(); self.generate()
        saved = deepcopy(self.m.state)
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.c.export()
        wait(lambda: not self.c.busy)
        self.assertEqual(self.w._quote_scheme_status, 'REVISING')
        self.assertEqual(self.m.state, saved)
        self.assertFalse(self.h.posts())
        self.generate(); self.assert_saved_revision()

    def test_failed_save_keeps_edits_blocks_export_and_retries_same_v2(self):
        self.edit(); self.error = '409：版本冲突，请重新打开'
        self.generate()
        self.assertEqual(self.c.state, 'failed')
        self.assertIn('版本冲突', self.c.reason)
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15], 502)
        self.assertEqual(self.m.state['versions'][0], self.original)
        self.assertTrue(self.m.state['versions'][-1]['pending_confirmation'])
        self.assertFalse(schemes._prepare_export(self.w))
        self.error = None
        self.generate(); self.assert_saved_revision()
        self.assertEqual(len(self.m.state['versions']), 2)

    def test_invalid_save_ack_cannot_report_generation_success(self):
        self.edit(); self.reply = dict(saved=False, conflict=True)
        self.generate()
        self.assertEqual(self.c.state, 'failed')
        self.assertIn('未确认保存', self.c.reason)
        self.assertFalse(schemes._prepare_export(self.w))
        self.reply = dict(saved=True, lock_version=8)
        self.generate()
        self.assertEqual(self.c.state, 'failed')

    def test_generation_waits_for_ack_and_ignores_double_click(self):
        self.edit(); self.hold = True
        self.c.generate(); wait(lambda: bool(self.held))
        self.assertTrue(self.c.busy)
        self.assertFalse(self.w.scheme2_cost_generate.isEnabled())
        self.assertFalse(schemes._prepare_export(self.w))
        self.c.generate(); self.c.export()
        self.assertEqual(len(self.saves), 1)
        self.hold = False; self.held.pop(0)()
        wait(lambda: not self.c.busy)
        self.assert_saved_revision()
        self.assertIsNone(self.w._quote_scheme_save_worker)

    def test_generation_drains_inflight_autosave_with_next_lock(self):
        self.edit(); self.hold = True
        self.m.save(); wait(lambda: bool(self.held))
        self.c.generate()
        wait(lambda: self.c.step == 4)
        self.assertEqual(len(self.saves), 1)
        self.hold = False; self.held.pop(0)()
        wait(lambda: not self.c.busy)
        self.assert_saved_revision()
        self.assertEqual([p['expected_version'] for p in self.saves], [8, 9])

    def test_preview_failure_creates_no_confirmation_or_put(self):
        self.edit()
        self.h.response_error = {'error': '合成预检失败'}
        self.generate()
        self.assertEqual(self.c.state, 'failed')
        self.assertFalse(self.saves)
        self.assertTrue(self.m.state['versions'][-1]['pending_confirmation'])
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15], 502)

    def test_late_failed_ack_after_progress_reset_rolls_back_confirmation(self):
        self.edit(); self.hold = True
        self.c.generate(); wait(lambda: bool(self.held))
        self.c.reset(); self.error = '合成网络中断'
        self.held.pop(0)(); app.processEvents()
        self.assertEqual(self.c.state, 'idle')
        self.assertTrue(self.m.state['versions'][-1]['pending_confirmation'])
        self.assertFalse(schemes._prepare_export(self.w))

    def test_company_change_during_save_requires_fresh_generation(self):
        self.edit(); self.hold = True
        self.c.generate(); wait(lambda: bool(self.held))
        self.w.scheme2_company.setEditText('合成的另一个客户')
        self.hold = False; self.held.pop(0)()
        wait(lambda: not self.c.busy)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.c.state, 'failed')
        self.assertFalse(schemes._prepare_export(self.w))
        self.generate(); self.assert_saved_revision(3)

    def test_read_only_or_foreign_operator_does_not_confirm_revision(self):
        self.edit()
        for attribute in ('_quote_scheme_read_only', '_name_scope_foreign'):
            with self.subTest(attribute=attribute):
                setattr(self.w, attribute, True)
                self.generate()
                self.assertEqual(self.c.state, 'failed')
                self.assertFalse(self.saves)
                self.assertEqual(self.m.state['versions'][0], self.original)
                setattr(self.w, attribute, False)

    def test_failed_later_generation_preserves_confirmed_v2_and_retries_v3(self):
        self.edit(); self.generate()
        confirmed = deepcopy(self.m.state)
        self.edit(503); self.error = '合成网络错误'
        self.generate()
        self.assertEqual(self.c.state, 'failed')
        self.assertEqual(self.m.state, confirmed)
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15], 503)
        self.assertFalse(schemes._prepare_export(self.w))
        self.error = None; self.generate(); self.assert_saved_revision(3)
        self.assertEqual(self.m.state['versions'][:2], confirmed['versions'])

    def test_manual_adjustment_after_generation_still_retains_another_version(self):
        import quote_management as management
        from PySide6.QtWidgets import QDialog
        self.edit(); self.generate()
        confirmed = deepcopy(self.m.state['versions'])
        def adjust(dialog):
            dialog.grid.item(0, 2).setText('503')
            dialog.reason.setPlainText('合成人工调价')
            return QDialog.DialogCode.Accepted
        with patch.object(management.AdjustQuoteDialog, 'exec', adjust):
            self.m.adjust()
            wait(lambda: not self.w._quote_scheme_workers)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.m.state['versions'][:2], confirmed)
        self.assertEqual(len(self.m.state['versions']), 3)
        self.assertEqual(self.m.state['versions'][-1]['reason'], '合成人工调价')
        self.generate(); self.assert_saved_revision(3)

    def test_old_save_ack_does_not_navigate_or_change_another_workspace(self):
        self.edit(); self.hold = True
        self.c.generate(); wait(lambda: bool(self.held))
        self.c.reset()
        self.w._quote_scheme_id = 'BJ-20261028-999999'
        self.w._scheme2_workspace_epoch = getattr(self.w, '_scheme2_workspace_epoch', 0)+1
        self.w._qm_state = model.restore_state(None)
        self.w.draft_items = []
        self.w._quote_scheme_version = 100
        self.held.pop(0)(); app.processEvents()
        self.assertEqual(self.c.state, 'idle')
        self.assertEqual(self.m.state['versions'], [])
        self.assertEqual(self.w._quote_scheme_version, 100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
