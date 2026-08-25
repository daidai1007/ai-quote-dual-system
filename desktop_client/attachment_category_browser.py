"""Pure hierarchy rules for the attachment category browser."""

from __future__ import annotations

from collections.abc import Iterable
import re


CATEGORY_KEYS = ("category_level1", "category_level2", "category_level3")
LEVEL1_ORDER = (
    "底座",
    "侧板",
    "三排纵梁",
    "安装板",
    "灯开关",
    "文件夹",
    "风机滤网",
    "门限位器",
    "门加强筋",
    "配置变形",
    "内门",
    "玻璃门",
    "安装条",
    "防雨顶",
    "接地线",
    "孔承板",
    "控制柜附件",
)
UNGROUPED_LEVEL1 = "未分类"
DIRECT_ITEMS_LABEL = "本级附件"
FIXED_BASE_CATEGORY = "底座"
FIXED_BASE_SUBCATEGORY = "固定底座"


def parse_base_specification(text: str) -> tuple[float, float, float, float] | None:
    """Parse ``W*D*(H+base)`` as width, cabinet height, depth, base height.

    A base is intentionally requested only when both brackets and a plus sign
    are present.  Plain ``W*D*H`` specifications therefore never trigger an
    automatic base selection.
    """

    value = str(text or "").strip()
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*[xX×＊*]\s*"
        r"(\d+(?:\.\d+)?)\s*[xX×＊*]\s*"
        r"[（(]\s*(\d+(?:\.\d+)?)\s*[+＋]\s*"
        r"(\d+(?:\.\d+)?)\s*[）)]\s*",
        value,
    )
    if not match:
        return None
    width, depth, height, base_height = (float(part) for part in match.groups())
    if min(width, height, depth, base_height) <= 0:
        return None
    return width, height, depth, base_height


def _number(value) -> float | None:
    try:
        return float(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def is_base_selection(item: dict) -> bool:
    """Return whether an existing attachment selection is any kind of base."""

    if category_value(item, 0) == FIXED_BASE_CATEGORY:
        return True
    return "底座" in str(item.get("item_name") or "")


def match_fixed_base(
    items: Iterable[dict],
    width_mm: float,
    depth_mm: float,
    base_height_mm: float,
) -> dict | None:
    """Find the unique fixed base matching cabinet width/depth and base height."""

    target = (float(width_mm), float(base_height_mm), float(depth_mm))
    matches: list[dict] = []
    for item in items:
        if category_value(item, 0) != FIXED_BASE_CATEGORY:
            continue
        if category_value(item, 1) != FIXED_BASE_SUBCATEGORY:
            continue
        dimensions = tuple(_number(item.get(key)) for key in ("width_mm", "height_mm", "depth_mm"))
        if all(
            actual is not None and abs(actual - expected) <= 0.0001
            for actual, expected in zip(dimensions, target)
        ):
            matches.append(item)
    if len(matches) != 1:
        return None
    return matches[0]


def category_value(item: dict, level: int) -> str:
    value = str(item.get(CATEGORY_KEYS[level]) or "").strip()
    if level == 0 and not value:
        return UNGROUPED_LEVEL1
    return value


def category_path(item: dict) -> tuple[str, str, str]:
    return tuple(category_value(item, level) for level in range(len(CATEGORY_KEYS)))


def matches_selection(item: dict, selection: Iterable[str]) -> bool:
    path = category_path(item)
    return all(path[level] == value for level, value in enumerate(selection))


def items_for_selection(items: Iterable[dict], selection: Iterable[str]) -> list[dict]:
    chosen = tuple(selection)
    return [item for item in items if matches_selection(item, chosen)]


def _level1_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, LEVEL1_ORDER.index(value))
    except ValueError:
        return (1, value.casefold())


def category_options(items: Iterable[dict], selection: Iterable[str]) -> list[dict]:
    """Return the next category cards, or an empty list at a leaf node.

    A mixture of categorized and direct items gets one ``本级附件`` card so
    no price row becomes unreachable when a category is only partly refined.
    """

    chosen = tuple(selection)
    level = len(chosen)
    if level >= len(CATEGORY_KEYS):
        return []
    eligible = items_for_selection(items, chosen)
    groups: dict[str, int] = {}
    for item in eligible:
        value = category_value(item, level)
        groups[value] = groups.get(value, 0) + 1
    nonblank = [value for value in groups if value]
    if not nonblank:
        return []
    if level == 0:
        ordered = sorted(nonblank, key=_level1_sort_key)
    else:
        ordered = sorted(nonblank, key=str.casefold)
    options = [
        {"value": value, "label": value, "count": groups[value]}
        for value in ordered
    ]
    if "" in groups:
        options.append({"value": "", "label": DIRECT_ITEMS_LABEL, "count": groups[""]})
    return options


def valid_selection_prefix(items: Iterable[dict], selection: Iterable[str]) -> list[str]:
    """Keep the longest still-valid prefix after a catalogue reload."""

    result: list[str] = []
    materialized = list(items)
    for value in selection:
        options = category_options(materialized, result)
        if value not in {option["value"] for option in options}:
            break
        result.append(value)
    return result
