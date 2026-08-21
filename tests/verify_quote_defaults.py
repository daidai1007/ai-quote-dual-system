"""Regression checks for new-item material and coating defaults."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from quote_defaults import (  # noqa: E402
    DEFAULT_COATING_TYPE,
    DEFAULT_MATERIAL_CODE,
    apply_default_quote_inputs,
    restore_combo_selection,
)


class FakeCombo:
    def __init__(self, values):
        self.values = list(values)
        self.index = 0 if self.values else -1

    def findData(self, value):
        try:
            return self.values.index(value)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.index = index

    def currentData(self):
        return self.values[self.index] if self.index >= 0 else None

    def count(self):
        return len(self.values)


class FakeWindow:
    material_combo = FakeCombo(["SUS304", "SECC", "SUS316"])
    coating_combo = FakeCombo(["平光", "橘纹", "皱纹"])


window = FakeWindow()
apply_default_quote_inputs(window)
assert window.material_combo.currentData() == DEFAULT_MATERIAL_CODE
assert window.coating_combo.currentData() == DEFAULT_COATING_TYPE

material = FakeCombo(["SECC", "SUS304"])
restore_combo_selection(material, "SUS304", DEFAULT_MATERIAL_CODE)
assert material.currentData() == "SUS304", "valid user selection must be preserved"

coating = FakeCombo(["平光", "橘纹"])
restore_combo_selection(coating, "已停用喷塑", DEFAULT_COATING_TYPE)
assert coating.currentData() == "橘纹", "invalid selection must fall back to 橘纹"

print("QUOTE_DEFAULTS=PASS")
