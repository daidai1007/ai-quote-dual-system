"""Focused typography contract for the two-page scheme-2 UI."""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import v3_launcher  # noqa: E402


app = QApplication.instance() or QApplication([])
namespace = v3_launcher.load_v3_namespace()
namespace["AttachmentDialog"].load_catalog = lambda self, url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()


def pixel_size(widget, expected):
    actual = widget.font().pixelSize()
    assert actual == expected, (widget.objectName(), actual, expected)


option_page = window.stack.widget(1)
pixel_size(option_page.findChild(QLabel, "scheme2SectionTitle"), 17)
pixel_size(option_page.findChild(QLabel, "scheme2OptionGroupTitle"), 14)
pixel_size(option_page.findChild(QLabel, "scheme2OptionLabel"), 13)
pixel_size(window.product_combo, 14)

cost_page = window.stack.widget(3)
pixel_size(cost_page.findChild(QLabel, "scheme2PageTitle"), 17)
pixel_size(cost_page.findChild(QLabel, "scheme2SidebarTitle"), 14)
pixel_size(cost_page.findChild(QLabel, "scheme2FieldLabel"), 13)
pixel_size(window.scheme2_cost_controls["carbon_price"], 14)
pixel_size(window.summary_table, 13)
tabular_tag = QFont.Tag.fromString("tnum")
assert window.quote_spec_edit.font().featureValue(tabular_tag) == 1
assert window.scheme2_cost_controls["carbon_price"].font().featureValue(tabular_tag) == 1
assert window.summary_table.font().featureValue(tabular_tag) == 1

buttons = [window._scheme2_import_button, *window.scheme2_cost_action_buttons]
for button in buttons:
    pixel_size(button, 13)
    assert button.height() == 28, (button.text(), button.size())
assert all(button.height() == 28 for button in window.nav_buttons)

assert 'font-family:"Microsoft YaHei UI","Segoe UI"' in window.styleSheet()
assert "QHeaderView::section { background:#2563EB; color:#FFFFFF;" in window.styleSheet()
assert "padding:7px 8px; font-size:13px; font-weight:600;" in window.styleSheet()
print("scheme2 typography contract passed")
