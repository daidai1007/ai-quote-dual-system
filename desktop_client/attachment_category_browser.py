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
DEFAULT_FIXED_BASE = "fixed_base"
DEFAULT_LIGHT_SWITCH = "light_switch"
DEFAULT_A4_FOLDER = "a4_folder"
DEFAULT_DOOR_LIMITER = "door_limiter"
DEFAULT_JP_SIDE_PANEL = "jp_side_panel"
DEFAULT_DOOR_REINFORCEMENT = "door_reinforcement"
DEFAULT_GROUND_WIRE = "ground_wire"
DOOR_LIMITER_DEFAULT_QUANTITIES = {
    (1, 0): 1,
    (2, 0): 2,
    (0, 1): 2,
    (0, 2): 4,
    (1, 1): 3,
}


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


def _unique_match(items: Iterable[dict], predicate) -> dict | None:
    matches = [item for item in items if predicate(item)]
    return matches[0] if len(matches) == 1 else None


def match_default_light_switch(items: Iterable[dict]) -> dict | None:
    return _unique_match(items, lambda item: category_value(item, 0) == "灯开关")


def match_default_a4_folder(items: Iterable[dict]) -> dict | None:
    def is_a4(item: dict) -> bool:
        text = " ".join(str(item.get(key) or "") for key in ("item_name", "model_code", "variant"))
        return category_value(item, 0) == "文件夹" and "A4" in text.upper()

    return _unique_match(items, is_a4)


def match_default_door_limiter(items: Iterable[dict]) -> dict | None:
    return _unique_match(items, lambda item: category_value(item, 0) == "门限位器")


def door_limiter_default_quantity(single_door_count, double_door_count) -> int | None:
    """Return the approved limiter quantity for one valid door-count pair.

    ``0/0`` and every other unsupported pair intentionally return ``None``;
    callers must not invent a default for an invalid door configuration.
    """

    try:
        counts = int(single_door_count), int(double_door_count)
    except (TypeError, ValueError):
        return None
    return DOOR_LIMITER_DEFAULT_QUANTITIES.get(counts)


def match_default_door_reinforcement(items: Iterable[dict]) -> dict | None:
    return _unique_match(items, lambda item: category_value(item, 0) == "门加强筋")


def match_default_ground_wire(items: Iterable[dict]) -> dict | None:
    def is_red_green_wire(item: dict) -> bool:
        text = " ".join(
            [
                category_value(item, 1),
                str(item.get("item_name") or ""),
                str(item.get("model_code") or ""),
                str(item.get("variant") or ""),
            ]
        )
        return category_value(item, 0) == "接地线" and "红绿线" in text

    return _unique_match(items, is_red_green_wire)


def is_jp_product(value) -> bool:
    code = str(value or "").strip().upper()
    return code == "JP" or code.startswith("JP_")


def match_jp_side_panel(
    items: Iterable[dict],
    height_mm: float,
    depth_mm: float,
) -> dict | None:
    target_height = float(height_mm)
    target_depth = float(depth_mm)

    def matches(item: dict) -> bool:
        if category_value(item, 0) != "侧板":
            return False
        height = _number(item.get("height_mm"))
        depth = _number(item.get("depth_mm"))
        return (
            height is not None
            and depth is not None
            and abs(height - target_height) <= 0.0001
            and abs(depth - target_depth) <= 0.0001
        )

    return _unique_match(items, matches)


def default_rule_for_item(item: dict) -> str | None:
    """Map catalogue or collected selection data to its default rule group."""

    category = category_value(item, 0)
    name = str(item.get("item_name") or "").strip()
    model = str(item.get("model_code") or "").strip().upper()
    if category == "底座" or "底座" in name:
        return DEFAULT_FIXED_BASE
    if category == "灯开关" or "开关" in name:
        return DEFAULT_LIGHT_SWITCH
    if category == "文件夹" or "资料盒" in name:
        return DEFAULT_A4_FOLDER
    if category == "门限位器" or "门限位器" in name:
        return DEFAULT_DOOR_LIMITER
    if category == "门加强筋" or "门加强筋" in name:
        return DEFAULT_DOOR_REINFORCEMENT
    if category == "接地线" or "接地线" in name:
        return DEFAULT_GROUND_WIRE
    if category == "侧板" or name == "侧板" or model.startswith("JP68"):
        return DEFAULT_JP_SIDE_PANEL
    return None


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
