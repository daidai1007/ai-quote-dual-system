"""Cancellation regression: restore the original table without undoing business rules."""
import ast
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import verify_quote_management as fixture
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

APP,ui=fixture.APP,fixture.ui
OUT=Path(os.environ.get('AI_QUOTE_HORIZONTAL_SCREENSHOT_DIR',str(fixture.ROOT/'outputs'/'cost-horizontal-restore')))

class HorizontalCostRestore(unittest.TestCase):
    setUp=fixture.ManagementTests.setUp
    tearDown=fixture.ManagementTests.tearDown

    def test_original_horizontal_rows_actions_and_original_popups_are_restored(self):
        self.w.show_section(ui.COST_ROUTE);APP.processEvents()
        table=self.w.summary_table
        self.assertTrue(table.isVisible())
        self.assertFalse(hasattr(self.w,'scheme2_cost_vertical'))
        self.assertEqual(table.rowCount(),len(self.w.draft_items)+1)
        self.assertEqual(table.columnCount(),len(ui.HEADERS))
        self.assertEqual(table.item(0,1).text(),self.w.draft_items[0]['name'])
        self.assertEqual(table.item(1,1).text(),self.w.draft_items[1]['name'])
        self.assertEqual(table.item(2,0).text(),'汇总')
        table.selectRow(0);APP.processEvents()
        self.assertTrue(self.w.scheme2_cost_selection_detail.isVisible())
        self.assertEqual([b.text() for b in self.w.scheme2_cost_action_buttons[:3]],['× 删除','↑ 上移','↓ 下移'])
        before=deepcopy(self.w.draft_items)
        with patch.object(ui,'AttachmentEditor') as editor:
            editor.return_value.exec.return_value=QDialog.DialogCode.Accepted
            item=table.item(0,5);table.scrollToItem(item);APP.processEvents()
            QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,pos=table.visualItemRect(item).center())
            self.assertIs(editor.call_args.args[1],self.w.draft_items[0])
        self.assertEqual(self.w.draft_items,before)
        OUT.mkdir(parents=True,exist_ok=True)
        for width,height in ((1510,960),(1280,860),(1024,768)):
            self.w.setMinimumSize(0,0);self.w.resize(width,height);APP.processEvents();QTest.qWait(30)
            table.horizontalScrollBar().setValue(0)
            self.assertTrue(self.w.grab().save(str(OUT/f'horizontal-{width}-{os.environ.get("QT_SCALE_FACTOR","1")}.png')))

    def test_original_layout_functions_and_all_native_dialogs_match_before_transpose(self):
        baseline=subprocess.run(['git','show','97b2a23ad6ca628f4cad3590db89c89accce2683:desktop_client/scheme2_ui.py'],
            cwd=Path(os.environ.get('AI_QUOTE_TEST_GIT_ROOT', str(fixture.ROOT))),
            capture_output=True,text=True,encoding='utf-8',check=True).stdout
        current=(fixture.ROOT/'desktop_client/scheme2_ui.py').read_text(encoding='utf-8')
        def definitions(text):
            lines=text.splitlines(keepends=True)
            return {n.name:''.join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(text).body
                    if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        old,new=definitions(baseline),definitions(current)
        # Approved later work extends these entry points: discard-close guards,
        # confirmed remarks, and standalone attachments. Keep the strict source
        # comparison for every other original layout function and popup.
        evolved = {
            '_refresh_quote_page', '_load_order_workspace', '_finish_discard_close',
            '_discard_close_has_workers', '_defer_discard_close', 'install_scheme2_ui',
            'AttachmentEditor', '_quote_export_items_snapshot', '_apply_cost_control',
            '_build_cost_page', '_edit_selected', '_cost_cell_clicked',
            '_refresh_cost_table', '_SchemeAttachmentDialog', '_quote_item_remark',
            # Approved D dimension review / page-switch entry points.
            '_Scheme2PageRecognitionWorker', '_sync_scheme2_page_navigation',
            '_finish_scheme2_page_recognition', '_confirm_scheme2_recognition',
            '_fail_scheme2_page_recognition', '_activate_scheme2_page',
            '_mark_ai', '_calculate_and_add',
            '_synchronize_active_drawing_confirmation',
            '_row_values', '_GroupedCostHeader',
            '_cost_cell_changed', '_cost_price_components',
            '_recalculate_item_management', '_item_production_total', '_detail_rows', '_show_detail', '_build_detail_page', '_quote_unit_price_changed', '_attachment_summary_product_values', '_finish_add',
        }
        self.assertTrue(set(old).issubset(new), 'An original layout function or popup was removed')
        for name in set(old) - evolved:
            with self.subTest(original_definition=name):
                self.assertEqual(old[name], new[name])
        self.assertTrue(issubclass(ui.AttachmentEditor, QDialog))
        self.assertTrue(issubclass(ui._SchemeAttachmentDialog, QDialog))
        self.assertEqual(self.w.scheme2_cost_add_independent.text(), '＋ 新增独立附件')
        self.assertEqual(self.w.scheme2_cost_add_independent.accessibleName(), '新增独立附件')
        self.assertNotIn('cost_vertical_view',current)
        for name in ('run_client_tests.ps1','run_quote_management_checks.py'):
            self.assertNotIn('verify_cost_vertical_view.py',(fixture.ROOT/'tests'/name).read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
