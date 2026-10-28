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
            cwd=fixture.ROOT,capture_output=True,text=True,encoding='utf-8',check=True).stdout
        current=(fixture.ROOT/'desktop_client/scheme2_ui.py').read_text(encoding='utf-8')
        def definitions(text):
            lines=text.splitlines(keepends=True)
            return {n.name:''.join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(text).body
                    if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        old,new=definitions(baseline),definitions(current)
        self.assertEqual(old,new)
        self.assertNotIn('cost_vertical_view',current)
        for name in ('run_client_tests.ps1','run_quote_management_checks.py'):
            self.assertNotIn('verify_cost_vertical_view.py',(fixture.ROOT/'tests'/name).read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
