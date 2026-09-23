"""Focused recovery contract for a valid JP template after stale calculator state."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLineEdit  # noqa: E402
import layout_refresh  # noqa: E402


class BrokenCalculator:
    def calculate(self, *_args):
        return None


class FreshCalculator:
    def load_template(self, payload):
        assert payload == {"template": "JP_DOUBLE"}

    def calculate(self, code, width, height, depth, single, double):
        assert (code, width, height, depth, single, double) == (
            "JP_DOUBLE", 1250.0, 2000.0, 400.0, 0, 1
        )
        return 166.52682759, 10.25


app = QApplication.instance() or QApplication([])
window = SimpleNamespace(
    formula_calculator=BrokenCalculator(),
    weight_edit=QLineEdit(), area_edit=QLineEdit(),
    width_spin=QDoubleSpinBox(), height_spin=QDoubleSpinBox(), depth_spin=QDoubleSpinBox(),
    door_counts=lambda: (0, 1),
)
for spin, value in ((window.width_spin, 1250), (window.height_spin, 2000), (window.depth_spin, 400)):
    spin.setRange(0, 5000)
    spin.setValue(value)

assert layout_refresh._ensure_formula_outputs(
    window, "JP_DOUBLE", {"template": "JP_DOUBLE"}, FreshCalculator
)
assert window.weight_edit.text() == "166.5" and window.area_edit.text() == "10.2"
assert isinstance(window.formula_calculator, FreshCalculator)
print("JP formula template recovery contract passed")
