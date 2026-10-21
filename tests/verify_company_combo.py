from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402

core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
app.setFont(QFont("Microsoft YaHei UI", 10))
settings_dir = tempfile.TemporaryDirectory()
settings_path = str(Path(settings_dir.name) / "company-settings.ini")
scheme2_ui._company_settings = lambda: QSettings(settings_path, QSettings.Format.IniFormat)
window = namespace["MainWindow"]()
window.resize(1366, 820)
window.show()
window.show_section(scheme2_ui.COST_ROUTE)
app.processEvents()
assert not window.scheme2_cost_page.isAncestorOf(window.scheme2_company)
assert not hasattr(window, "scheme2_cost_company_field")
assert all(label.text() != "客户" for label in window.scheme2_cost_page.findChildren(QLabel))
# Building the cost controls must not create, locate, or depend on a buyer selector.
cost_only_window = QWidget()
cost_sidebar = scheme2_ui._cost_sidebar(cost_only_window)
assert not hasattr(cost_only_window, "scheme2_company")
cost_sidebar.deleteLater()
cost_only_window.deleteLater()
window.show_section(scheme2_ui.QUOTE_ROUTE)
company = window.scheme2_company
company.clear()
company.addItem("绵阳市鑫瑞电气设备制造有限公司")
company.setCurrentIndex(0)
app.processEvents()

assert window.scheme2_cost_sidebar.width() == scheme2_ui.COST_SIDEBAR_WIDTH == 130
assert not window.scheme2_cost_sidebar.isAncestorOf(company)
assert window.scheme2_quote_company_field.isAncestorOf(company)
assert window.scheme2_quote_page.isAncestorOf(company)
assert company.height() == scheme2_ui.COMPANY_COMBO_HEIGHT == 56
assert company.view().objectName() == "scheme2CompanyDropdown"
assert company.view().minimumWidth() >= 320
assert company.view().wordWrap()
assert company.view().sizeHintForRow(0) >= 40
assert company.isEditable() and not company.lineEdit().isReadOnly()
assert company.lineEdit().focusPolicy() == Qt.FocusPolicy.StrongFocus
assert not company.lineEdit().testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
assert company.currentText() == "绵阳市鑫瑞电气设备制造有限公司"
assert company.toolTip() == company.currentText()

custom_company = "四川测试电气设备制造有限公司"
company.setEditText(custom_company)
company.lineEdit().editingFinished.emit()
assert custom_company in scheme2_ui._saved_custom_companies()
assert company.findText(custom_company, Qt.MatchFlag.MatchExactly) >= 0
scheme2_ui._sync_export_company(window)
assert window.company_combo.currentText() == custom_company
assert window.scheme2_quote_preview.item(3, 1).text() == custom_company

output = ROOT / "outputs" / "scheme2-ui-qa"
output.mkdir(parents=True, exist_ok=True)
window.scheme2_quote_company_field.grab().save(str(output / "company-combo.png"))
window.show_section(scheme2_ui.COST_ROUTE)
app.processEvents()
window.scheme2_cost_page.grab().save(str(output / "cost-page-no-company.png"))
window.close()
app.processEvents()
second_window = namespace["MainWindow"]()
second_company = second_window.scheme2_company
assert second_company.findText(custom_company, Qt.MatchFlag.MatchExactly) >= 0
second_window.close()
app.processEvents()
settings_dir.cleanup()
print("quote-only company selector and independent cost-page contracts passed")
