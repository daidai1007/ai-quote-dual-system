from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh  # noqa: E402


calls = []


def base_parser(text):
    calls.append(text)
    if "+" in str(text):
        return None
    return {"specification": str(text), "dimensions": (800.0, 1800.0, 600.0)}


scope = {"parse_review_specification": base_parser}
exec(
    "def original_add(window):\n"
    "    parsed = parse_review_specification(window.specification)\n"
    "    if parsed is None:\n"
    "        return False\n"
    "    window.saved = parsed\n"
    "    return True\n",
    scope,
)
original_add = scope["original_add"]
window = SimpleNamespace(specification="(800+600)*600*1800", saved=None)
rows = [
    {"width_mm": 800, "depth_mm": 600, "height_mm": 1800},
    {"width_mm": 600, "depth_mm": 600, "height_mm": 1800},
]

assert layout_refresh._add_with_ganged_specification(
    window, original_add, rows, window.specification
)
assert window.saved["specification"] == "800*600*1800"
assert calls == ["800*600*1800"]
assert scope["parse_review_specification"] is base_parser

plain = SimpleNamespace(specification="800*600*1800", saved=None)
assert layout_refresh._add_with_ganged_specification(
    plain, original_add, [rows[0]], plain.specification
)
assert plain.saved["specification"] == "800*600*1800"

print("ganged summary specification validation passed")
