"""Focused check for proportional layout and typography scaling."""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402


namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window.show()
app.processEvents()

# The offscreen Qt backend caps the real top-level window to its small virtual
# screen.  Use the current geometry as the 1.2x target so the proportional
# scale contract remains deterministic on development machines and CI.
reference = QSize(round(window.width() / 1.2), round(window.height() / 1.2))
window._scheme2_scale_reference = reference
base_style = window.styleSheet()
page_title = window.stack.widget(3).findChild(QLabel, "scheme2PageTitle")
base_title_size = page_title.font().pixelSize()
scheme2_ui._apply_responsive(window)

assert 1.19 <= window._scheme2_scale <= 1.21
assert window.scheme2_nav.width() == round(scheme2_ui.NAV_EXPANDED_WIDTH * window._scheme2_scale)
assert window.scheme2_cost_sidebar.width() == round(scheme2_ui.COST_SIDEBAR_WIDTH * window._scheme2_scale)
assert window.scheme2_company.height() == round(scheme2_ui.COMPANY_COMBO_HEIGHT * window._scheme2_scale)
assert window.summary_table.columnWidth(1) == round(scheme2_ui.COST_COLUMN_WIDTHS[1] * window._scheme2_scale)
assert window.summary_table.columnWidth(19) == round(scheme2_ui.COST_COLUMN_WIDTHS[19] * window._scheme2_scale)
assert window.scheme2_detail_table.columnWidth(0) == round(scheme2_ui.DETAIL_COLUMN_WIDTHS[0] * window._scheme2_scale)
assert window.scheme2_detail_table.columnWidth(7) == round(scheme2_ui.DETAIL_COLUMN_WIDTHS[7] * window._scheme2_scale)
assert window.scheme2_detail_table.isColumnHidden(3)
assert window.scheme2_detail_table.horizontalHeader().minimumHeight() == round(44 * window._scheme2_scale)
assert window.scheme2_detail_table.verticalHeader().defaultSectionSize() == round(46 * window._scheme2_scale)
assert window.styleSheet() != base_style
assert base_title_size == 18
assert page_title.font().pixelSize() == round(base_title_size * window._scheme2_scale)

window.close()
print("SCHEME2_PROPORTIONAL_SCALE=PASS")
