"""Pure hierarchy rules for the attachment category browser."""

from __future__ import annotations

from collections.abc import Iterable


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
