"""Real Qt file dialogs retain their editors through browse/save/cancel.

Run each sequence in a child process so a native access violation is reported
as a test failure instead of terminating the whole client regression suite.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def probe(mode):
    sys.path.insert(0, str(ROOT / "desktop_client"))
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QCompleter, QDialogButtonBox, QFileDialog,
        QLineEdit, QListView, QTreeView, QVBoxLayout, QWidget,
    )
    from dialog_style import install_dialog_style
    from dropdown_style import install_combo_popup_style, style_combo, style_popup

    app = QApplication([])
    install_dialog_style()
    install_combo_popup_style()
    results = []
    with tempfile.TemporaryDirectory(prefix="quote-file-picker-") as folder:
        root = Path(folder)
        (root / "子目录").mkdir()
        existing = root / "已存在的报价.xlsx"
        existing.write_bytes(b"synthetic-file-picker-input")
        for sequence in range(6):
            expected = existing if mode == "open" else root / f"正式报价_{sequence}.xlsx"

            def interact():
                dialog = next(w for w in app.topLevelWidgets()
                              if isinstance(w, QFileDialog) and w.isVisible())
                for _ in range(3):
                    app.processEvents()
                # Both presentation filters are active, but Qt-owned child
                # combo/completer views must retain their original delegates.
                for combo in dialog.findChildren(QComboBox):
                    style_combo(combo)
                    assert not combo.view().property("unifiedComboPopup")
                filename = dialog.findChild(QLineEdit, "fileNameEdit")
                assert filename is not None
                completer = filename.completer()
                if completer is not None:
                    style_popup(completer, completer.popup())
                    assert not completer.popup().property("unifiedComboPopup")
                tree = dialog.findChild(QTreeView, "treeView")
                assert tree is not None
                index = tree.model().index(str(root / "子目录"))
                assert index.isValid()
                tree.setCurrentIndex(index)
                rect = tree.visualRect(index)
                if rect.isValid():
                    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                filename.setFocus()
                filename.setText(str(expected).replace("\\", "/"))
                QTest.keyClick(filename, Qt.Key.Key_End)
                app.processEvents()
                assert dialog.selectedFiles() == [str(expected).replace("\\", "/")]
                if mode == "cancel":
                    dialog.reject()
                else:
                    buttons = dialog.findChild(QDialogButtonBox)
                    role = QDialogButtonBox.StandardButton.Open if mode == "open" else QDialogButtonBox.StandardButton.Save
                    buttons.button(role).click()

            QTimer.singleShot(100, interact)
            picker = QFileDialog.getOpenFileName if mode == "open" else QFileDialog.getSaveFileName
            selected, name_filter = picker(None, "选择台账" if mode == "open" else "导出正式报价单",
                                            str(existing if mode == "open" else root / "初始报价.xlsx"),
                                            "Excel 工作簿 (*.xlsx)")
            if mode == "cancel":
                assert selected == ""
            else:
                assert Path(selected) == expected, selected
                assert "*.xlsx" in name_filter
            results.append(bool(selected))
            app.processEvents()

        # Application-owned inputs and their replaced/completion views still
        # receive the common dropdown style after file dialogs have closed.
        owner = QWidget()
        layout = QVBoxLayout(owner)
        combo = QComboBox(owner)
        combo.addItems(["草稿", "已报价", "合同"])
        layout.addWidget(combo)
        editor = QLineEdit(owner)
        layout.addWidget(editor)
        completer = QCompleter(["JP760260", "JP930060"], editor)
        editor.setCompleter(completer)
        owner.show()
        app.processEvents()
        combo.showPopup()
        app.processEvents()
        assert combo.view().property("unifiedComboPopup")
        combo.hidePopup()
        combo.setView(QListView())
        combo.showPopup()
        app.processEvents()
        assert combo.view().property("unifiedComboPopup")
        combo.hidePopup()
        completer.setCompletionPrefix("JP")
        completer.complete()
        app.processEvents()
        assert completer.popup().property("unifiedComboPopup")
        completer.popup().hide()
        owner.close()
    print(json.dumps({"mode": mode, "completed": len(results), "selected": results,
                      "application_dropdowns_styled": True}), flush=True)


class FileDialogSaveTests(unittest.TestCase):
    def run_probe(self, mode):
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                           PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--probe", mode],
            cwd=ROOT, env=environment, capture_output=True, text=True,
            encoding="utf-8", timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(report["completed"], 6)
        self.assertTrue(report["application_dropdowns_styled"])
        return report

    def test_browse_and_save_repeatedly_with_both_global_styles(self):
        self.assertEqual(self.run_probe("save")["selected"], [True] * 6)

    def test_existing_file_open_with_both_global_styles(self):
        self.assertEqual(self.run_probe("open")["selected"], [True] * 6)

    def test_cancel_then_reopen_does_not_select_or_write_a_file(self):
        self.assertEqual(self.run_probe("cancel")["selected"], [False] * 6)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        probe(sys.argv[2])
    else:
        unittest.main(verbosity=2)
