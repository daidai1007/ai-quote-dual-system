"""Focused check for proportional layout and typography scaling."""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402


namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window.show()
app.processEvents()

reference = window._scheme2_scale_reference
base_style = window.styleSheet()
window.resize(round(reference.width() * 1.2), round(reference.height() * 1.2))
app.processEvents()
scheme2_ui._apply_responsive(window)

assert 1.19 <= window._scheme2_scale <= 1.21
assert window.scheme2_nav.width() == round(scheme2_ui.NAV_EXPANDED_WIDTH * window._scheme2_scale)
assert window.scheme2_cost_sidebar.width() == round(scheme2_ui.COST_SIDEBAR_WIDTH * window._scheme2_scale)
assert window.scheme2_company.height() == round(scheme2_ui.COMPANY_COMBO_HEIGHT * window._scheme2_scale)
assert window.summary_table.columnWidth(1) == round(scheme2_ui.COST_COLUMN_WIDTHS[1] * window._scheme2_scale)
assert window.summary_table.columnWidth(19) == round(scheme2_ui.COST_COLUMN_WIDTHS[19] * window._scheme2_scale)
assert window.styleSheet() != base_style
assert "font-size:16px" in window.styleSheet()

window.close()
print("SCHEME2_PROPORTIONAL_SCALE=PASS")
