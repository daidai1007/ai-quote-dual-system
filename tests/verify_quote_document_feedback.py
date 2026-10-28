"""Real current-client feedback lifecycle; all network/workbooks stay offline."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint

import verify_quote_document_progress as base
import quote_document_progress as progress
from progress_style import PROGRESS_COLORS

app, ui, wait = base.app, base.ui, base.wait
QTest = base.QTest


class DocumentFeedback(unittest.TestCase):
    setUp = base.DocumentProgress.setUp

    def show_cost(self, width=1550):
        self.window._scheme2_dirty = False
        self.window.resize(width, 900 if width > 1100 else 700)
        self.window.show_section(ui.COST_ROUTE)
        self.window.show()
        for _ in range(3):
            app.processEvents()

    def capture(self, name, kind=None):
        if not os.environ.get('FEEDBACK_CAPTURE'):
            return
        app.processEvents()
        folder = Path(os.environ['FEEDBACK_CAPTURE'])
        folder.mkdir(parents=True, exist_ok=True)
        host = self.controller.widgets[kind or self.controller.feedback_kind][0]
        self.assertTrue(host.grab().save(str(folder / f'{name}.png')))

    def test_idle_delay_green_thin_track_and_cancel_restores_layout(self):
        self.show_cost()
        c = self.controller
        for host, _bar, _locate in c.widgets.values():
            self.assertTrue(host.isHidden())
        # The original short table can already be at its minimum height and
        # feedback can occupy the existing action dock. Verify actual fit and
        # non-overlap instead of requiring an unrelated table to shrink.
        cost_page = self.window.scheme2_cost_page
        initial_height = cost_page.height()
        c.begin('generate')
        host, bar, _locate = c.widgets['generate']
        self.assertEqual(c.show_timer.interval(), 300)
        self.assertTrue(host.isHidden())
        QTest.qWait(200)
        self.assertTrue(host.isHidden())
        QTest.qWait(140)
        self.assertTrue(host.isVisible())
        self.assertLessEqual(bar.height(), 4)
        self.assertFalse(bar.isTextVisible())
        self.assertIn(PROGRESS_COLORS['fill'], bar.styleSheet())
        table = self.window.summary_table
        table_bottom = table.mapTo(self.window, QPoint(0, table.height())).y()
        feedback_top = host.mapTo(self.window, QPoint(0, 0)).y()
        self.assertLessEqual(table_bottom, feedback_top)
        self.assertTrue(self.window.rect().contains(host.mapTo(self.window, host.rect().bottomRight())))
        self.capture('running')
        c.end(cancelled=True)
        app.processEvents()
        self.assertTrue(host.isHidden())
        self.assertEqual(cost_page.height(), initial_height)
        self.assertTrue(self.window.scheme2_cost_generate.isEnabled())
        self.assertTrue(self.window.summary_table.isEnabled())
        self.assertFalse(c.timer.isActive())

    def test_fast_generation_skips_track_success_on_quote_page_then_collapses(self):
        self.show_cost()
        c = self.controller
        c.generate()
        self.assertTrue(c.widgets['generate'][0].isHidden())
        wait(lambda: not c.busy)
        self.assertEqual(c.state, 'success')
        self.assertEqual(self.window.stack.currentIndex(), ui.QUOTE_ROUTE)
        self.assertEqual(c.feedback_kind, 'export')
        self.assertTrue(c.widgets['generate'][0].isHidden())
        host, bar, _locate = c.widgets['export']
        self.assertTrue(host.isVisible())
        self.assertTrue(bar.isHidden())
        self.assertTrue(c.feedback['export']['success_icon'].isVisible())
        self.assertEqual(c.feedback['export']['label'].full_text, '✓ 报价单已生成')
        self.assertEqual(c.hide_timer.interval(), 2000)
        self.assertIsNone(c.show_timer)
        QTest.qWait(150)
        self.assertTrue(host.isVisible())
        self.capture('generated')
        shown_height = self.window.scheme2_quote_preview.height()
        QTest.qWait(1950)
        self.assertTrue(host.isHidden())
        self.assertEqual(c.state, 'idle')
        self.assertGreater(self.window.scheme2_quote_preview.height(), shown_height)
        self.assertTrue(self.window.scheme2_quote_export.isEnabled())

    def test_elapsed_is_total_and_phase_durations_are_in_details(self):
        self.show_cost()
        c = self.controller
        with patch.object(progress.time, 'monotonic', return_value=100):
            c.begin('generate')
        with patch.object(progress.time, 'monotonic', return_value=103.2):
            c.set_stage(2, '校验附件')
        with patch.object(progress.time, 'monotonic', return_value=103.9):
            c.refresh()
            self.assertIn('已用时 3.9 秒', c.feedback['generate']['label'].full_text)
            self.assertIn('本阶段：0.7秒', c.widgets['generate'][1].toolTip())
            c.fail('测试错误')
        details = []
        with patch.object(base.QMessageBox, 'exec', lambda box: details.append(box.detailedText()) or 0):
            c.details()
        self.assertIn('累计耗时：3.9秒', details[0])
        self.assertIn('校验清单：3.2秒', details[0])
        self.assertIn('校验附件：0.7秒', details[0])
        old_text = c.widgets['generate'][1].toolTip()
        c.refresh()
        self.assertEqual(c.widgets['generate'][1].toolTip(), old_text, 'completed timing must not keep increasing')

    def test_cancelled_file_selection_hides_immediately_without_requests(self):
        self.window._qm_entry_pending = True
        self.window.show_section(ui.QUOTE_ROUTE)
        self.window.show()
        with patch.object(base.QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.controller.export()
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.controller.state, 'idle')
        self.assertEqual(self.requests, [])
        for host, _bar, _locate in self.controller.widgets.values():
            self.assertTrue(host.isHidden())
        self.assertTrue(self.window.scheme2_quote_export.isEnabled())
        self.assertEqual(self.window.scheme2_quote_export.text(), '导出报价单')
        self.assertIsNone(self.controller.show_timer)
        self.assertIsNone(self.controller.hide_timer)

    def test_failure_persists_shows_recovery_actions_and_retry_succeeds(self):
        self.show_cost(1024)
        self.response_error = dict(message='附件成本存在错误', issues=[dict(
            line_number=1, product_name='JP测试柜', attachment_name='固定底座',
            attachment_price_id=99, reason='底座高度必须是正数')])
        c = self.controller
        c.generate()
        wait(lambda: not c.busy)
        host, bar, locate = c.widgets['generate']
        feedback = c.feedback['generate']
        self.assertEqual(c.state, 'failed')
        self.assertTrue(host.isVisible())
        self.assertTrue(bar.isHidden())
        for button in (feedback['retry'], feedback['details'], locate):
            self.assertTrue(button.isVisible())
            self.assertFalse(button.geometry().intersects(feedback['label'].geometry()))
        self.assertIn('固定底座', feedback['label'].full_text)
        self.capture('failure')
        selected = []
        with patch.object(ui.AttachmentEditor, 'exec', lambda editor: selected.append(editor.table.currentRow()) or 0):
            locate.click()
        self.assertEqual(selected, [0])
        QTest.qWait(2100)
        self.assertTrue(host.isVisible())
        self.assertIsNone(c.hide_timer)
        self.response_error = None
        feedback['retry'].click()
        wait(lambda: not c.busy)
        self.assertEqual(c.state, 'success')
        self.assertEqual(c.reason, '')

    def test_plain_failure_has_details_but_no_attachment_locator(self):
        self.show_cost()
        c = self.controller
        c.begin('generate')
        c.fail('服务连接暂时不可用')
        feedback = c.feedback['generate']
        self.assertTrue(c.widgets['generate'][2].isHidden())
        self.assertTrue(feedback['retry'].isVisible())
        detail_text = []
        with patch.object(base.QMessageBox, 'exec', lambda box: detail_text.append(box.text()) or 0):
            feedback['details'].click()
        self.assertIn('服务连接暂时不可用', detail_text[0])

    def test_old_timer_callbacks_cannot_show_or_hide_new_task(self):
        self.show_cost()
        c = self.controller
        c.begin('generate')
        old_show = c.show_timer
        c.end()
        old_hide = c.hide_timer
        self.window._qm_entry_pending = True
        self.window.show_section(ui.QUOTE_ROUTE)
        c.begin('export')
        host = c.widgets['export'][0]
        old_show.timeout.emit()
        old_hide.timeout.emit()
        self.assertTrue(host.isHidden())
        c.show_timer.timeout.emit()
        self.assertTrue(host.isVisible())
        old_hide.timeout.emit()
        self.assertTrue(host.isVisible())
        c.fail('新任务失败')
        old_hide.timeout.emit()
        self.assertTrue(host.isVisible())
        self.assertEqual(c.state, 'failed')

    def test_reset_clears_feedback_and_pending_callbacks(self):
        c = self.controller
        c.begin('generate')
        old_show = c.show_timer
        c.end()
        old_hide = c.hide_timer
        c.reset()
        old_show.timeout.emit()
        old_hide.timeout.emit()
        self.assertEqual(c.state, 'idle')
        self.assertEqual(c.phase_times, [])
        self.assertIsNone(c.show_timer)
        self.assertIsNone(c.hide_timer)
        for kind, (host, bar, locate) in c.widgets.items():
            self.assertTrue(host.isHidden())
            self.assertTrue(locate.isHidden())
            self.assertEqual(bar.format(), '')
            self.assertEqual(c.feedback[kind]['label'].full_text, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
