"""Pure rules that keep quote remarks aligned with door-count selections."""

from __future__ import annotations

import re


DOOR_PHRASE_PATTERN = re.compile(
    r"前(?:单|双)开门后(?:背板|单开门|双开门)|前后(?:单|双)开门|前(?:单|双)开门"
)
DOOR_PHRASES_BY_COUNTS = {
    (1, 0): "前单开门",
    (0, 1): "前双开门",
    (2, 0): "前后单开门",
    (0, 2): "前后双开门",
    (1, 1): "前单开门后双开门",
}


def door_phrase_for_item(item: dict) -> str:
    """Return the customer-facing door phrase for the current door counts."""

    has_counts = all(
        key in item and item.get(key) not in (None, "")
        for key in ("single_door_count", "double_door_count")
    )
    if has_counts:
        try:
            counts = (
                int(item.get("single_door_count")),
                int(item.get("double_door_count")),
            )
        except (TypeError, ValueError):
            counts = None
        if counts in DOOR_PHRASES_BY_COUNTS:
            return DOOR_PHRASES_BY_COUNTS[counts]

    variant = str(item.get("variant_name") or item.get("variant_code") or "").strip()
    if "双" in variant.upper() or str(item.get("variant_code") or "").upper() == "DOUBLE":
        return "前双开门"
    if "单" in variant.upper() or str(item.get("variant_code") or "").upper() == "SINGLE":
        return "前单开门"
    return ""


def replace_door_configuration_phrase(remark: str, item: dict) -> str:
    """Replace only the door phrase, preserving all other operator wording."""

    text = str(remark or "")
    expected = door_phrase_for_item(item)
    if not expected or not DOOR_PHRASE_PATTERN.search(text):
        return text
    return DOOR_PHRASE_PATTERN.sub(expected, text, count=1)
