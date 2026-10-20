"""Local-only prototype checks; intentionally not a production API migration."""
import os
from pathlib import Path
import sys
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from preview_quote_scheme_lifecycle import LifecyclePreview,LABELS,TERMINAL,ARCHIVE_FILTER,QTest


class LifecycleVisualPreview(unittest.TestCase):
    def setUp(self):
        self.preview = LifecyclePreview()
        self.addCleanup(self.preview.close)
        self.window = self.preview.window

    def test_seven_business_states_and_archive_tags_share_status_column(self):
        table = self.window.quote_scheme_table
        self.assertEqual(len(LABELS),7)
        self.assertNotIn('ARCHIVED',LABELS)
        self.assertEqual({row['status'] for row in self.preview.rows},set(LABELS))
        self.assertEqual(table.horizontalHeaderItem(3).text(),'状态')
        self.assertNotIn('归档',[table.horizontalHeaderItem(i).text() for i in range(table.columnCount())])
        self.assertEqual(table.horizontalHeaderItem(5).text(),'版本')
        self.assertEqual(table.horizontalHeaderItem(7).text(),'审核人')
        self.assertEqual(table.item(0,7).text(),'—')  # Never invent an approval record.
        self.assertEqual(table.item(0,3).text(),'已完成')
        self.assertEqual(table.item(7,3).text(),'已完成 · 已归档')

    def test_archive_filter_and_reset_do_not_change_business_status(self):
        original = [r['status'] for r in self.preview.rows]
        self.window.quote_scheme_status_filter.setCurrentIndex(
            self.window.quote_scheme_status_filter.findData(ARCHIVE_FILTER))
        self.assertEqual(self.window.quote_scheme_table.rowCount(),2)
        self.window.quote_scheme_status_filter.setCurrentIndex(5)  # Completed.
        self.assertEqual(self.window.quote_scheme_table.rowCount(),2)
        self.preview.reset_filters()
        self.assertEqual(self.window.quote_scheme_table.rowCount(),9)
        self.assertEqual([r['status'] for r in self.preview.rows],original)

    def test_confirmation_requires_number_and_valid_date_and_locks_version(self):
        row = self.preview.rows[1]
        dialog = self.preview.contract_dialog(row)
        self.assertTrue(dialog.final_version.isReadOnly())
        dialog.accept_button.click()
        self.assertEqual(row['status'],'WAIT_CONTRACT')
        dialog.contract_number.setText('HT-TEST-01')
        dialog.contract_date.setText('2026-99-99')
        dialog.accept_button.click()
        self.assertEqual(row['status'],'WAIT_CONTRACT')
        dialog.contract_date.setText('2026-10-20')
        dialog.accept_button.click()
        self.assertEqual(row['status'],'COMPLETED')
        self.assertEqual(row['contract_no'],'HT-TEST-01')
        self.assertEqual(row['version_no'],2)
        self.assertFalse(row['archived'])

    def test_cancel_leaves_record_unchanged_and_completed_contract_is_read_only(self):
        row = self.preview.rows[1]
        dialog = self.preview.contract_dialog(row)
        dialog.contract_number.setText('UNSAVED')
        dialog.reject()
        self.assertEqual(row['status'],'WAIT_CONTRACT')
        self.assertEqual(row['contract_no'],'')
        completed = self.preview.contract_dialog(self.preview.rows[0],readonly=True)
        self.assertTrue(completed.contract_number.isReadOnly())
        self.assertFalse(completed.contract_date.isEnabled())
        self.assertEqual(completed.accept_button.text(),'关闭')

    def test_archive_and_restore_only_change_archive_marker(self):
        row = self.preview.rows[0]
        self.preview.act(row,'归档')
        self.preview.dialogs[-1].accept_button.click()
        self.assertTrue(row['archived'])
        self.assertEqual(row['status'],'COMPLETED')
        self.preview.act(row,'取消归档')
        self.preview.dialogs[-1].accept_button.click()
        self.assertFalse(row['archived'])
        self.assertEqual(row['status'],'COMPLETED')
        for r in self.preview.rows:
            actions = {label for label,_ in self.preview.actions(r).actions}
            if r['status'] not in TERMINAL:
                self.assertNotIn('归档',actions)

    def test_completed_has_no_revision_action_and_pending_contract_has_confirmation(self):
        completed = {label for label,_ in self.preview.actions(self.preview.rows[0]).actions}
        pending = {label for label,_ in self.preview.actions(self.preview.rows[1]).actions}
        self.assertNotIn('修订',completed)
        self.assertNotIn('作废',completed)
        self.assertIn('合同',completed)
        self.assertIn('确认合同',pending)

    def test_readable_identifiers_and_actions_fit_at_desktop_widths(self):
        for width in (1280,1553,1920):
            self.window.resize(width,980)
            QTest.qWait(60)
            table = self.window.quote_scheme_table
            self.assertGreaterEqual(table.columnWidth(0),table.fontMetrics().horizontalAdvance('BJ-20261020-000009')+24)
            self.assertGreaterEqual(table.columnWidth(8),table.fontMetrics().horizontalAdvance('2026-10-20 10:36')+24)
            for row in range(table.rowCount()):
                actions = table.cellWidget(row,9)
                self.assertLessEqual(actions.more.geometry().right(),actions.width())
            if width>=1553:
                self.assertLessEqual(sum(table.columnWidth(i) for i in range(10)),table.viewport().width())


if __name__=='__main__': unittest.main(verbosity=2)
