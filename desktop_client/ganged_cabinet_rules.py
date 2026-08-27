"""Pure parsing and state rules for horizontally ganged cabinets."""

from __future__ import annotations

from collections.abc import Iterable
import re


_NUMBER = r"\d+(?:\.\d+)?"
_DIMENSION_SEPARATOR = r"[×xX*/]"
_GANGED_SPECIFICATION = re.compile(
    rf"\s*[（(]\s*(?P<widths>{_NUMBER}(?:\s*\+\s*{_NUMBER})+)\s*[）)]"
    rf"\s*{_DIMENSION_SEPARATOR}\s*(?P<depth>{_NUMBER})"
    rf"\s*{_DIMENSION_SEPARATOR}\s*"
    rf"(?:"
    rf"(?P<height>{_NUMBER})"
    rf"|[（(]\s*(?P<cabinet_height>{_NUMBER})\s*\+\s*(?P<base_height>{_NUMBER})\s*[）)]"
    rf")\s*"
)


def parse_ganged_specification(text: str) -> dict | None:
    """Parse a horizontally ganged specification using common separators.

    Dimension separators may be ``×``, ``x``, ``X``, ``*`` or ``/``.
    Additions deliberately use only the ASCII ``+``.  Depth and cabinet height
    are scalar values shared by every split cabinet.
    """

    source = str(text or "").strip()
    match = _GANGED_SPECIFICATION.fullmatch(source)
    if match is None:
        return None
    widths = [float(value.strip()) for value in match.group("widths").split("+")]
    depth = float(match.group("depth"))
    height = float(match.group("height") or match.group("cabinet_height"))
    base_height = (
        float(match.group("base_height"))
        if match.group("base_height") is not None
        else None
    )
    if len(widths) < 2 or min([*widths, depth, height]) <= 0:
        return None
    if base_height is not None and base_height <= 0:
        return None
    rows = [
        {
            "width_mm": width,
            "depth_mm": depth,
            "height_mm": height,
            "base_height_mm": base_height,
        }
        for width in widths
    ]
    return {
        "specification": source,
        "split_count": len(rows),
        "widths_mm": widths,
        "depth_mm": depth,
        "height_mm": height,
        "base_height_mm": base_height,
        "rows": rows,
    }


def ganged_split_count(value, fallback: int = 1) -> int:
    """Return a persisted split count without interpreting arbitrary models."""

    if isinstance(value, dict):
        direct = value.get("ganged_cabinet_count")
        rows = value.get("ganged_cabinets")
        if direct in (None, "") and isinstance(rows, list):
            direct = len(rows)
    else:
        direct = value
    try:
        count = int(direct)
    except (TypeError, ValueError):
        count = int(fallback)
    return count if count > 1 else 1


def cascade_door_counts(
    rows: Iterable[dict],
    changed_index: int,
    single_count: int,
    double_count: int,
) -> list[dict]:
    """Apply one edited door pair to that row and every following row."""

    output = [dict(row) for row in rows]
    start = max(int(changed_index), 0)
    for index in range(start, len(output)):
        output[index]["single_door_count"] = int(single_count)
        output[index]["double_door_count"] = int(double_count)
    return output


def subcabinet_specification(row: dict) -> str:
    """Return the operator-facing W×D×H expression for one split row."""

    def number(value) -> str:
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else f"{numeric:g}"

    height = number(row.get("height_mm"))
    base = row.get("base_height_mm")
    height_expression = (
        f"（{height}+{number(base)}）" if base not in (None, "") else height
    )
    return (
        f"{number(row.get('width_mm'))}×{number(row.get('depth_mm'))}×"
        f"{height_expression}"
    )
