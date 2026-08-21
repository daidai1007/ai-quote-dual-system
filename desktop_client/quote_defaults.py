"""Stable default selections for a new quotation item."""

from __future__ import annotations


DEFAULT_MATERIAL_CODE = "SECC"
DEFAULT_COATING_TYPE = "橘纹"


def restore_combo_selection(combo, selected, default):
    """Restore a valid selection, otherwise choose the named default."""
    for candidate in (selected, default):
        if candidate is None:
            continue
        index = combo.findData(candidate)
        if index >= 0:
            combo.setCurrentIndex(index)
            return combo.currentData()
    if combo.count():
        combo.setCurrentIndex(0)
        return combo.currentData()
    return None


def apply_default_quote_inputs(window) -> None:
    """Apply defaults only when starting or explicitly resetting an item."""
    restore_combo_selection(window.material_combo, None, DEFAULT_MATERIAL_CODE)
    restore_combo_selection(window.coating_combo, None, DEFAULT_COATING_TYPE)
