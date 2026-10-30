"""Real Qt restoration regression, bounded in a child process against hangs.

Only the transport is offline. Table filling, signals, read-only guards,
workspace restoration, navigation and print/export snapshot preparation run
through the current source and installed V3 core.
"""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse


if __name__ == '__main__' and '--worker' not in sys.argv:
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--worker'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, timeout=45,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit('FAIL: scheme restoration exceeded 45s; possible UI refresh recursion')
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    raise SystemExit(result.returncode)

from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView
import verify_quote_scheme_reference_ui as reference_ui

APP, centre, scheme2_ui = reference_ui.APP, reference_ui.centre, reference_ui.scheme2_ui


def frozen_items():
    items = []
    for index, code in enumerate(('JQ_EXP', 'JE_DOUBLE', 'JP_SINGLE')):
        attachment = dict(item_name='安装板', category_level1='安装板',
                          specification='600*400', quantity=2,
                          formula_amount=25, quick_amount=40)
        item = dict(
            product_code=code, product_name=code, name=f'历史产品{index + 1}',
            specification='1000*480*1060', material_code='SECC', quantity=index + 2,
            quick_discount=0.75, freight_fee=70, attachments=[attachment],
            final_remark=f'历史备注{index + 1}',
            quick=dict(base_price=1000 + index * 100, attachment_fee=40,
                       total_cost=1040 + index * 100),
            formula=dict(material_cost=600, auxiliary_cost=20, labor_cost=30,
                         spray_cost=40, attachment_fee=25, total_cost=715),
        )
        # Freeze a normal current-algorithm result, not a new pricing rule.
        scheme2_ui._recalculate_item_management(item)
        items.append(item)
    return items


class SchemeRestoreResponsiveness(unittest.TestCase):
    setUp = reference_ui.ReferenceSchemeUI.setUp
    tearDown = reference_ui.ReferenceSchemeUI.tearDown
    wait_loaded = reference_ui.ReferenceSchemeUI.wait_loaded

    def result(self, status):
        snapshot = centre._snapshot(self.window)
        snapshot.update(draft_items=frozen_items(), company='历史买方公司',
                        active_route=3, drawing_pages=[], drawing_page_index=-1)
        snapshot['document'].update(scheme_no='BJ-20261019-000001',
                                    version_no=2, quote_date='2026-10-10')
        return dict(scheme_no='BJ-20261019-000001', status=status,
                    lock_version=7, version_no=2, snapshot=snapshot,
                    created_at='2026-10-10T01:00:00+00:00',
                    updated_at='2026-10-19T01:00:00+00:00')

    def restore(self, status):
        result = self.result(status)
        centre._apply_opened_scheme(self.window, deepcopy(result))
        self.window._quote_scheme_save_timer.stop()
        return result

    def test_background_open_and_repeated_read_only_navigation(self):
        w = self.window
        ticks = []
        heartbeat = QTimer(w)
        heartbeat.setInterval(5)
        heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
        heartbeat.start()
        try:
            for attempt, status in enumerate(('QUOTED', 'ARCHIVED', 'VOID') * 3):
                with self.subTest(status=status):
                    result = self.result(status)
                    # Saved from configuration, quote sheet or scheme centre;
                    # all opens must still finish on the requested cost page.
                    result['snapshot']['active_route'] = (1, 2, 6)[attempt // 3]
                    expected = [scheme2_ui._row_values(item) for item in result['snapshot']['draft_items']]

                    def respond(worker):
                        if worker.method != 'GET' or not urlparse(worker.url).path.endswith(result['scheme_no']):
                            worker.failed.emit('unexpected request in restoration test')
                            return
                        QThread.msleep(10)
                        worker.succeeded.emit(deepcopy(result))

                    with patch.object(centre.QuoteSchemeWorker, 'run', respond):
                        centre._open_scheme(w, result['scheme_no'])
                        self.wait_loaded()
                    self.assertTrue(w._quote_scheme_read_only)
                    self.assertEqual(w.stack.currentIndex(), 3)
                    self.assertEqual(w.scheme2_company.currentText(), '历史买方公司')
                    self.assertEqual(len(w.draft_items), 3)
                    self.assertEqual([scheme2_ui._row_values(item) for item in w.draft_items], expected)
                    for saved,current in zip(result['snapshot']['draft_items'],w.draft_items):
                        self.assertEqual(current['formula'],saved['formula'])
                        self.assertNotIn('manufacturing_cost_basis',current)
                        self.assertNotIn('tax_cost_basis',current)
                    self.assertEqual(w.summary_table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
                    self.assertEqual(w.scheme2_quote_preview.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
                    for route in (2, 3, 2, 3):
                        w.show_section(route)
                        APP.processEvents()
                    previous = len(ticks)
                    QTest.qWait(25)
                    self.assertGreater(len(ticks), previous, 'Qt heartbeat stopped after restoration')
                    self.assertFalse(w._scheme2_refreshing)
                    self.assertFalse(w._scheme2_refreshing_quote)
                    self.assertFalse(w._quote_scheme_save_timer.isActive())
        finally:
            heartbeat.stop()

    def test_read_only_rejects_edit_without_recursive_redraw(self):
        w = self.window
        for status in ('QUOTED', 'ARCHIVED', 'VOID'):
            with self.subTest(status=status):
                self.restore(status)
                original = deepcopy(w.draft_items)
                for column, invalid in ((1, '不允许修改名称'), (4, '999'), (19, '999')):
                    expected = w.summary_table.item(0, column).text()
                    w.summary_table.item(0, column).setText(invalid)
                    self.assertEqual(w.summary_table.item(0, column).text(), expected)
                for column, invalid in ((1, '不允许修改名称'), (5, '99999.00')):
                    expected = w.scheme2_quote_preview.item(10, column).text()
                    w.scheme2_quote_preview.item(10, column).setText(invalid)
                    self.assertEqual(w.scheme2_quote_preview.item(10, column).text(), expected)
                self.assertEqual(w.draft_items, original)

    def test_draft_and_revision_remain_editable_after_read_only_restore(self):
        w = self.window
        for status in ('DRAFT', 'REVISING'):
            with self.subTest(status=status):
                self.restore('QUOTED')
                self.restore(status)
                self.assertFalse(w._quote_scheme_read_only)
                self.assertTrue(w.scheme2_add_button.isEnabled())
                w.summary_table.item(0, 4).setText('7')
                self.assertEqual(w.draft_items[0]['quantity'], 7)
                w.scheme2_quote_preview.item(10, 1).setText('可编辑产品')
                self.assertEqual(w.draft_items[0]['name'], '可编辑产品')
                w._quote_scheme_save_timer.stop()

    def test_restored_price_rows_print_and_export_snapshot_stay_consistent(self):
        w = self.window
        for status in ('QUOTED', 'ARCHIVED', 'VOID'):
            with self.subTest(status=status):
                self.restore(status)
                before = deepcopy(w.draft_items)
                rendered = scheme2_ui._printable_quote_html(w)
                exported = scheme2_ui._quote_export_items_snapshot(w)
                self.assertEqual(w.scheme2_quote_preview.item(3, 1).text(), '历史买方公司')
                self.assertIn('历史买方公司', rendered)
                self.assertEqual(centre._snapshot(w)['company'], '历史买方公司')
                for index, item in enumerate(w.draft_items):
                    values = scheme2_ui._row_values(item)
                    unit, total = scheme2_ui._money(values[15]), scheme2_ui._money(values[16])
                    self.assertEqual(w.summary_table.item(index, 10).text(), unit)
                    self.assertEqual(w.summary_table.item(index, 11).text(), total)
                    self.assertEqual(w.scheme2_quote_preview.item(index + 10, 5).text(), unit)
                    self.assertEqual(w.scheme2_quote_preview.item(index + 10, 6).text(), total)
                    self.assertEqual(exported[index]['quote_display']['unit_price'], values[15])
                    self.assertEqual(exported[index]['quote_display']['total'], values[16])
                    self.assertIn(f'<td>{unit}</td><td>{total}</td>', rendered)
                    self.assertEqual(item['attachments'], before[index]['attachments'])
                self.assertIn('2026-10-10', rendered)
                self.assertEqual(w.draft_items, before)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
