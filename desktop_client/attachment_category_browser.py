"""Pure hierarchy rules for the attachment category browser."""

from __future__ import annotations

from collections.abc import Iterable
import re

from ganged_cabinet_rules import parse_ganged_specification


CATEGORY_KEYS = ("category_level1", "category_level2", "category_level3")
LEVEL1_ORDER = (
    "侧板",
    "安装板",
    "安装附件",
    "底座",
    "灯开关",
    "资料盒",
    "风机",
    "滤网",
    "门变形",
    "并柜件",
)
# Business categories that must remain at the end of the first-level browser.
# Categories imported later still sort before this suffix, so the requested
# positions do not drift when a workbook adds another category.
LEVEL1_TRAILING_ORDER = (
    "配置变形",
    "控制柜附件",
    "其他附件",
)
UNGROUPED_LEVEL1 = "未分类"
DIRECT_ITEMS_LABEL = "本级附件"
DIRECT_SELECTION_LEVEL1 = frozenset({"风机", "滤网", "门变形", "配置变形", "其他附件"})
FIXED_BASE_CATEGORY = "底座"
FIXED_BASE_SUBCATEGORY = "固定底座"
DEFAULT_FIXED_BASE = "fixed_base"
DEFAULT_INSTALLATION_BOARD = "installation_board"
QUICK_FIXED_COLUMN = "fixed_column"
QUICK_THREE_ROW_INSTALLATION_BEAM = "three_row_installation_beam"
DEFAULT_LIGHT_SWITCH = "light_switch"
DEFAULT_A3_FOLDER = "a3_folder"
DEFAULT_A4_FOLDER = "a4_folder"
DEFAULT_DOOR_LIMITER = "door_limiter"
DEFAULT_JP_SIDE_PANEL = "jp_side_panel"
DEFAULT_DOOR_REINFORCEMENT = "door_reinforcement"
DEFAULT_GROUND_WIRE = "ground_wire"
DEFAULT_COPPER_BUSBAR = "copper_busbar"
QUICK_GANGED_CONNECTOR = "ganged_connector"
QUICK_JK_INSTALLATION_BOARD = "jk_installation_board"
QUICK_INNER_DOOR = "inner_door"
QUICK_RAIN_COVER = "rain_cover"
QUICK_VENTILATION_HOOD = "ventilation_hood"
QUICK_GANGED_FILL_INSTALLATION_BOARD = "ganged_fill_installation_board"
DOOR_TRANSFORMATION_RULE_PREFIX = "door_transformation:"
DOOR_TRANSFORMATION_NAMES = (
    "JS、JP后背板改为单开门",
    "JS、JP后背板改为双开门",
    "JS、JP单开门改为双开门",
    "JA、JE单开门改为双开门",
)
ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES = ("侧板", "门变形", "风机滤网")
GANGED_FIXED_BASE_MATCH_KEY = "ganged_fixed_base_match"
GANGED_FIXED_BASE_INDEX_KEY = "ganged_fixed_base_index"
ATTACHMENT_SELECTION_SOURCE_KEY = "selection_source"
AUTOMATIC_SELECTION_SOURCE = "automatic"
MANUAL_SELECTION_SOURCE = "manual"
DOOR_COUNT_DEFAULT_QUANTITIES = {
    (1, 0): 1,
    (2, 0): 2,
    (0, 1): 2,
    (0, 2): 4,
    (1, 1): 3,
}


def attachment_selection_source(item: dict) -> str:
    """Return the persisted operator/system origin for one selected row."""

    value = str((item or {}).get(ATTACHMENT_SELECTION_SOURCE_KEY) or "").strip().lower()
    return value if value in {AUTOMATIC_SELECTION_SOURCE, MANUAL_SELECTION_SOURCE} else ""


def with_attachment_selection_source(item: dict, source: str) -> dict:
    """Copy an attachment snapshot and attach a validated selection origin."""

    normalized = str(source or "").strip().lower()
    if normalized not in {AUTOMATIC_SELECTION_SOURCE, MANUAL_SELECTION_SOURCE}:
        raise ValueError(f"unsupported attachment selection source: {source}")
    selected = dict(item)
    selected[ATTACHMENT_SELECTION_SOURCE_KEY] = normalized
    return selected


def is_automatic_attachment_selection(item: dict) -> bool:
    return attachment_selection_source(item) == AUTOMATIC_SELECTION_SOURCE


def is_manual_attachment_selection(item: dict) -> bool:
    return attachment_selection_source(item) == MANUAL_SELECTION_SOURCE
# Backward-compatible public name used by the existing client contracts.
DOOR_LIMITER_DEFAULT_QUANTITIES = DOOR_COUNT_DEFAULT_QUANTITIES
SIZE_MATCH_METADATA_KEYS = (
    "size_match_target_width_mm",
    "size_match_target_height_mm",
    "size_match_target_depth_mm",
    "size_match_width_mm",
    "size_match_height_mm",
    "size_match_depth_mm",
    "size_match_target_perimeter",
    "size_match_perimeter",
    "size_match_ratio",
    "size_match_exact",
    "size_match_original_price",
    "size_match_warning",
)


def parse_base_specification(text: str) -> tuple[float, float, float, float] | None:
    """Parse ``W*D*(H+base)`` as width, cabinet height, depth, base height.

    A base is intentionally requested only when both brackets and a plus sign
    are present.  Plain ``W*D*H`` specifications therefore never trigger an
    automatic base selection.
    """

    value = str(text or "").strip()
    ganged = parse_ganged_specification(value)
    if ganged is not None and ganged.get("base_height_mm") is not None:
        first = ganged["rows"][0]
        return (
            float(first["width_mm"]),
            float(first["height_mm"]),
            float(first["depth_mm"]),
            float(first["base_height_mm"]),
        )
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
    matches = [
        item for item in items
        if category_value(item, 0) in {"灯开关", "照明灯/行程开关"}
    ]
    default_220v = [
        item for item in matches
        if str(item.get("model_code") or "").strip().upper() == "220V"
    ]
    return default_220v[0] if len(default_220v) == 1 else (matches[0] if len(matches) == 1 else None)


def match_default_a4_folder(items: Iterable[dict]) -> dict | None:
    return match_quick_attachment_identity(items, "资料盒", "", "A4资料盒")


def match_default_a3_folder(items: Iterable[dict]) -> dict | None:
    return match_quick_attachment_identity(items, "资料盒", "", "A3资料盒")


def match_quick_attachment_identity(
    items: Iterable[dict],
    category_level1: str,
    category_level2: str,
    item_name: str,
) -> dict | None:
    """Return one exact catalogue identity used by a first-level quick action.

    These operator-facing shortcuts deliberately use the effective catalogue
    names rather than broad substrings.  In particular, the catalogue calls
    the requested three-row installation beam ``三排安装梁`` under the
    ``三排纵梁`` branch.
    """

    return _unique_match(
        items,
        lambda item: (
            category_value(item, 0) == category_level1
            and category_value(item, 1) == category_level2
            and str(item.get("item_name") or "").strip() == item_name
        ),
    )


def match_quick_attachment_source(
    items: Iterable[dict],
    category_level1: str,
    category_level2: str,
    item_name: str,
) -> dict | None:
    """Return a deterministic source row when an exact identity has sizes."""

    matches = [
        item for item in items
        if category_value(item, 0) == category_level1
        and category_value(item, 1) == category_level2
        and str(item.get("item_name") or "").strip() == item_name
    ]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: (
            _number(item.get("attachment_price_id")) is None,
            _number(item.get("attachment_price_id")) or float("inf"),
            _natural_text_key(item.get("model_code")),
        ),
    )[0]


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
    return DOOR_COUNT_DEFAULT_QUANTITIES.get(counts)


def door_reinforcement_default_quantity(single_door_count, double_door_count) -> int | None:
    """Door reinforcement follows the approved door-limiter quantity matrix."""

    return door_limiter_default_quantity(single_door_count, double_door_count)


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


def match_default_copper_busbar(items: Iterable[dict]) -> dict | None:
    """Return the sole active catalogue candidate in the copper-busbar category."""

    return _unique_match(
        items,
        lambda item: category_value(item, 0) == "铜排",
    )


def match_quick_ganged_connector(items: Iterable[dict]) -> dict | None:
    """Return the exact active catalogue row used by the ganged quick action."""

    return match_quick_attachment_identity(items, "并柜件", "", "并柜件")


def match_quick_ganged_fill_installation_board(items: Iterable[dict]) -> dict | None:
    """Return the single generic fill-board row used only by ganged quotes."""

    return match_quick_attachment_identity(items, "配置变形", "", "填充安装板")


def is_jp_product(value) -> bool:
    code = str(value or "").strip().upper()
    return code == "JP" or code.startswith("JP_")


def _product_family(value) -> str:
    code = str(value or "").strip().upper()
    for family in ("JS", "JP", "JA", "JE"):
        if code == family or code.startswith(f"{family}_"):
            return family
    return code


def _compact_attachment_name(value) -> str:
    return re.sub(r"[\s,，]+", "、", str(value or "").strip()).strip("、")


def door_transformation_rule_for_item(item: dict) -> str | None:
    """Return a stable default-rule key for the four approved door changes."""

    name = _compact_attachment_name(item.get("item_name"))
    known = {_compact_attachment_name(value) for value in DOOR_TRANSFORMATION_NAMES}
    if category_value(item, 0) == "门变形" and name in known:
        return f"{DOOR_TRANSFORMATION_RULE_PREFIX}{name}"
    return None


def door_transformation_default_names(
    product_code,
    single_door_count,
    double_door_count,
) -> tuple[str, ...]:
    """Map product family and door counts to manually priced transform rows."""

    try:
        counts = int(single_door_count), int(double_door_count)
    except (TypeError, ValueError):
        return ()
    family = _product_family(product_code)
    if family in {"JS", "JP"}:
        return {
            (1, 0): (),
            (2, 0): ("JS、JP后背板改为单开门",),
            (0, 1): ("JS、JP单开门改为双开门",),
            (0, 2): (
                "JS、JP单开门改为双开门",
                "JS、JP后背板改为双开门",
            ),
            (1, 1): ("JS、JP后背板改为双开门",),
        }.get(counts, ())
    if family in {"JA", "JE"} and counts == (0, 1):
        return ("JA、JE单开门改为双开门",)
    return ()


def match_door_transformation_defaults(
    items: Iterable[dict],
    product_code,
    single_door_count,
    double_door_count,
) -> dict[str, dict]:
    """Select one deterministic catalogue row for every required transform."""

    wanted = tuple(
        _compact_attachment_name(name)
        for name in door_transformation_default_names(
            product_code, single_door_count, double_door_count
        )
    )
    matches: dict[str, dict] = {}
    ordered = sorted(
        (item for item in items if isinstance(item, dict)),
        key=lambda item: (
            _number(item.get("attachment_price_id")) is None,
            _number(item.get("attachment_price_id")) or float("inf"),
            _natural_text_key(item.get("model_code")),
        ),
    )
    for wanted_name in wanted:
        candidate = next(
            (
                item for item in ordered
                if category_value(item, 0) == "门变形"
                and _compact_attachment_name(item.get("item_name")) == wanted_name
            ),
            None,
        )
        if candidate is not None:
            matches[f"{DOOR_TRANSFORMATION_RULE_PREFIX}{wanted_name}"] = candidate
    return matches


def attachment_uses_cabinet_quantity(item: dict) -> bool:
    """Whether an attachment's chosen quantity is specified per cabinet."""

    values = [category_value(item, level) for level in range(3)]
    combined = " ".join(
        [*values, str(item.get("attachment_category") or ""), str(item.get("item_name") or "")]
    )
    if "风机" in combined or "滤网" in combined:
        return False
    return not any(category in combined for category in ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES)


def final_attachment_quantity(
    item: dict,
    cabinet_quantity,
    ganged_cabinet_count=1,
) -> float:
    """Return the quote-line quantity without mutating the manual selection."""

    quantity = _number(item.get("quantity"))
    quantity = 1.0 if quantity is None else quantity
    cabinets = _number(cabinet_quantity)
    cabinets = 1.0 if cabinets is None else cabinets
    split_count = _number(ganged_cabinet_count)
    split_count = 1.0 if split_count is None else split_count
    # In a ganged quote the selected quantity already describes one complete
    # ganged set.  System-matched door limiters/reinforcements persist the sum
    # of the child-cabinet door matrix in that selected quantity, and fixed
    # bases already have one separate row per child.  Do not multiply any row
    # by the split count a second time.
    if split_count > 1:
        return quantity * cabinets
    if not attachment_uses_cabinet_quantity(item):
        return quantity
    return quantity * cabinets


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

    door_rule = door_transformation_rule_for_item(item)
    if door_rule is not None:
        return door_rule
    category = category_value(item, 0)
    subcategory = category_value(item, 1)
    name = str(item.get("item_name") or "").strip()
    model = str(item.get("model_code") or "").strip().upper()
    if category == "配置变形" and subcategory == "" and name == "填充安装板":
        return QUICK_GANGED_FILL_INSTALLATION_BOARD
    if category == "控制箱附件" and subcategory == "JK安装板" and name == "JK安装板":
        return QUICK_JK_INSTALLATION_BOARD
    if category in {"控制箱附件", "控制柜附件"} and subcategory == "内门" and name == "内门":
        return QUICK_INNER_DOOR
    if category in {"控制箱附件", "控制柜附件"} and subcategory == "防雨顶" and name == "防雨顶":
        return QUICK_RAIN_COVER
    if category == "控制柜附件" and subcategory == "通风顶罩" and name == "通风顶罩":
        return QUICK_VENTILATION_HOOD
    if category == "底座" or "底座" in name:
        return DEFAULT_FIXED_BASE
    if size_match_attachment_name(item) in {"安装板", "JK安装板"}:
        return DEFAULT_INSTALLATION_BOARD
    if category == "灯开关" or "开关" in name:
        return DEFAULT_LIGHT_SWITCH
    if category in {UNGROUPED_LEVEL1, "资料盒", "文件夹"} and name == "A3资料盒":
        return DEFAULT_A3_FOLDER
    if category in {UNGROUPED_LEVEL1, "资料盒", "文件夹"} and name == "A4资料盒":
        return DEFAULT_A4_FOLDER
    if category == "安装附件" and category_value(item, 1) == "固定立柱" and name == "固定立柱":
        return QUICK_FIXED_COLUMN
    if category == "安装附件" and category_value(item, 1) == "三排纵梁" and name == "三排安装梁":
        return QUICK_THREE_ROW_INSTALLATION_BEAM
    if category == "门限位器" or "门限位器" in name:
        return DEFAULT_DOOR_LIMITER
    if category == "门加强筋" or "门加强筋" in name:
        return DEFAULT_DOOR_REINFORCEMENT
    if category == "接地线" or "接地线" in name:
        return DEFAULT_GROUND_WIRE
    if category == "铜排" or name == "铜排":
        return DEFAULT_COPPER_BUSBAR
    if category == "并柜件" and name == "并柜件":
        return QUICK_GANGED_CONNECTOR
    if category == "侧板" or name == "侧板" or model.startswith("JP68"):
        return DEFAULT_JP_SIDE_PANEL
    return None


def size_match_attachment_name(item: dict) -> str | None:
    """Return the approved size-match attachment name for one catalogue row."""

    text = " ".join(
        str(item.get(key) or "").strip()
        for key in (
            "category_level1", "category_level2", "category_level3",
            "item_name", "model_code",
        )
    )
    compact = re.sub(r"\s+", "", text)
    if "安装板单发" in compact or "JK安装板单发" in compact:
        return None
    # Match the more specific names before their containing generic names.
    for name in (
        "固定底座", "活动底座", "通风顶罩", "玻璃门", "防雨顶",
        "三排安装梁", "固定立柱", "分段板", "JK安装板", "内门", "侧板", "安装板",
    ):
        if name in compact:
            return name
    return None


def installation_board_catalogue_name(item: dict) -> str | None:
    """Return the installation-board branch for a valid catalogue row.

    Automatic installation-board matching is intentionally restricted to the
    catalogue hierarchy whose first-level category is ``安装板``.  This keeps
    a same-named record under another business category from being selected.
    """

    if category_value(item, 0) != "安装板":
        return None
    name = size_match_attachment_name(item)
    return name if name in {"安装板", "JK安装板"} else None


def size_match_group_key(item: dict) -> tuple[str, str, str, str] | None:
    """Keep nearest-size selection inside one attachment name/category path."""

    name = size_match_attachment_name(item)
    if name is None:
        return None
    return name, *category_path(item)


def target_dimension_tuple(dimensions) -> tuple[float, float, float] | None:
    """Validate the recognized/manual W/H/D target used for size matching."""

    if not isinstance(dimensions, (list, tuple)) or len(dimensions) < 3:
        return None
    values = tuple(_number(value) for value in dimensions[:3])
    if any(value is None or value <= 0 for value in values):
        return None
    return values  # type: ignore[return-value]


def completed_size_dimensions(
    item: dict,
    target_dimensions,
) -> tuple[float, float, float] | None:
    """Fill missing catalogue W/H/D only for the matching calculation."""

    target = target_dimension_tuple(target_dimensions)
    if target is None:
        return None
    values = []
    for index, key in enumerate(("width_mm", "height_mm", "depth_mm")):
        candidate = _number(item.get(key))
        values.append(target[index] if candidate is None else candidate)
    return tuple(values)


def _natural_text_key(value) -> tuple:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(value or ""))
    )


def _matching_candidates(items: Iterable[dict], source: dict) -> list[dict]:
    group = size_match_group_key(source)
    if group is None:
        return []
    candidates = [item for item in items if size_match_group_key(item) == group]
    # A manually selected price scheme/variant remains authoritative while its
    # physical size is replaced by the nearest row from that same scheme.
    for key in ("variant", "price_source"):
        wanted = str(source.get(key) or "").strip()
        if not wanted:
            continue
        restricted = [item for item in candidates if str(item.get(key) or "").strip() == wanted]
        if restricted:
            candidates = restricted
    return candidates


def match_installation_board_size(
    items: Iterable[dict],
    source: dict,
    target_dimensions,
    *,
    required_name: str | None = None,
) -> dict | None:
    """Match installation boards by cabinet W/H and scale price by perimeter.

    Installation boards are mounted on the cabinet face, so cabinet depth is
    deliberately excluded from both the nearest-size choice and the price
    ratio. Catalogue rows without a usable width and height are not eligible;
    otherwise missing data could be mistaken for an exact match.
    """

    target = None
    if isinstance(target_dimensions, (list, tuple)) and len(target_dimensions) >= 2:
        target_width = _number(target_dimensions[0])
        target_height = _number(target_dimensions[1])
        target_depth = (
            _number(target_dimensions[2])
            if len(target_dimensions) >= 3 else None
        )
        if target_depth is not None and target_depth <= 0:
            target_depth = None
        if (
            target_width is not None and target_width > 0
            and target_height is not None and target_height > 0
        ):
            # Depth is retained only as diagnostic metadata. It is neither a
            # prerequisite nor an input to installation-board selection or
            # perimeter price scaling.
            target = (target_width, target_height, target_depth)
    catalogue = list(items)
    if required_name:
        candidates = [
            item for item in catalogue
            if installation_board_catalogue_name(item) == required_name
        ]
        if installation_board_catalogue_name(source) == required_name:
            grouped = _matching_candidates(candidates, source)
            if grouped:
                candidates = grouped
    else:
        source_name = installation_board_catalogue_name(source)
        if source_name is not None:
            candidates = _matching_candidates(
                [
                    item for item in catalogue
                    if installation_board_catalogue_name(item) == source_name
                ],
                source,
            )
        elif size_match_attachment_name(source) in {"安装板", "JK安装板"}:
            # Explicit quick actions can live under a business category such
            # as 控制箱附件. Keep them in their exact category path while
            # reusing this same W/H perimeter matcher and price scaling.
            candidates = _matching_candidates(catalogue, source)
        else:
            candidates = []
    if target is None or not candidates:
        return None
    target_width, target_height, target_depth = target
    target_perimeter = 2.0 * (target_width + target_height)

    eligible: list[tuple[dict, float, float]] = []
    for item in candidates:
        width = _number(item.get("width_mm"))
        height = _number(item.get("height_mm"))
        if width is None or width <= 0 or height is None or height <= 0:
            continue
        eligible.append((item, width, height))
    if not eligible:
        return None

    def choice_key(candidate: tuple[dict, float, float]):
        item, width, height = candidate
        squared_distance = (
            (width - target_width) ** 2
            + (height - target_height) ** 2
        )
        perimeter = 2.0 * (width + height)
        price_id = _number(item.get("attachment_price_id"))
        return (
            squared_distance,
            abs(perimeter - target_perimeter),
            width,
            height,
            _natural_text_key(item.get("model_code")),
            _natural_text_key(item.get("variant")),
            _natural_text_key(item.get("price_source")),
            float("inf") if price_id is None else price_id,
        )

    matched, matched_width, matched_height = min(eligible, key=choice_key)
    matched_perimeter = 2.0 * (matched_width + matched_height)
    if matched_perimeter <= 0:
        return None
    exact = (
        abs(matched_width - target_width) <= 0.0001
        and abs(matched_height - target_height) <= 0.0001
    )
    ratio = 1.0 if exact else target_perimeter / matched_perimeter
    selected = dict(matched)
    matched_depth = _number(matched.get("depth_mm"))
    original_price = _number(matched.get("price"))
    selected.update({
        "size_match_target_width_mm": target_width,
        "size_match_target_height_mm": target_height,
        "size_match_target_depth_mm": target_depth,
        "size_match_width_mm": matched_width,
        "size_match_height_mm": matched_height,
        "size_match_depth_mm": target_depth if matched_depth is None else matched_depth,
        "size_match_target_perimeter": target_perimeter,
        "size_match_perimeter": matched_perimeter,
        "size_match_ratio": ratio,
        "size_match_exact": exact,
    })
    if original_price is None:
        selected["size_match_warning"] = "原价格不是安全的单一数值，未执行周长比例折价"
        return selected
    selected["matched_price"] = original_price
    selected["size_match_original_price"] = original_price
    scaled_price = original_price if exact else round(original_price * ratio, 6)
    if exact:
        selected.pop("unit_price_override", None)
    else:
        selected["unit_price_override"] = scaled_price
    selected.pop("size_match_warning", None)
    return selected


def installation_board_match_name_for_product(product_code) -> str:
    """Return the only installation-board catalogue allowed for a product."""

    code = str(product_code or "").strip().upper()
    return "JK安装板" if code == "JK" or code.startswith("JK_") else "安装板"


def match_installation_board_for_product(
    items: Iterable[dict],
    source: dict,
    target_dimensions,
    product_code,
) -> dict | None:
    """Apply product-family routing before the W/H installation-board match."""

    return match_installation_board_size(
        items,
        source,
        target_dimensions,
        required_name=installation_board_match_name_for_product(product_code),
    )


def match_attachment_size(
    items: Iterable[dict],
    source: dict,
    target_dimensions,
) -> dict | None:
    """Select and price one exact/nearest approved attachment size.

    Missing catalogue fields are completed from the corresponding recognized
    or manually entered target field for matching only.  The selected row keeps
    the original database dimensions so later database lookup still identifies
    the source price record correctly.
    """

    if "安装板" in str(size_match_attachment_name(source) or ""):
        return match_installation_board_size(items, source, target_dimensions)

    target = target_dimension_tuple(target_dimensions)
    candidates = _matching_candidates(items, source)
    if target is None or not candidates:
        return None
    target_perimeter = sum(target)

    def choice_key(item: dict):
        completed = completed_size_dimensions(item, target)
        if completed is None:
            return (float("inf"), float("inf"), float("inf"), (), (), (), (), float("inf"))
        perimeter = sum(completed)
        squared_distance = sum((actual - expected) ** 2 for actual, expected in zip(completed, target))
        price_id = _number(item.get("attachment_price_id"))
        # A fixed base's explicitly entered/recognized height is the primary
        # engineering constraint.  Exact W/H/D still wins; otherwise prefer
        # every height-equal row before comparing perimeter proximity.  When
        # no height-equal row exists, all candidates share rank 1 and the
        # normal nearest-perimeter ordering applies unchanged.
        height_rank = 0
        if size_match_attachment_name(source) == "固定底座":
            height_rank = 0 if abs(completed[1] - target[1]) <= 0.0001 else 1
        return (
            height_rank,
            abs(perimeter - target_perimeter),
            squared_distance,
            completed,
            _natural_text_key(item.get("model_code")),
            _natural_text_key(item.get("variant")),
            _natural_text_key(item.get("price_source")),
            float("inf") if price_id is None else price_id,
        )

    matched = min(candidates, key=choice_key)
    completed = completed_size_dimensions(matched, target)
    if completed is None:
        return None
    matched_perimeter = sum(completed)
    if matched_perimeter <= 0:
        return None
    exact = all(abs(actual - expected) <= 0.0001 for actual, expected in zip(completed, target))
    ratio = 1.0 if exact else target_perimeter / matched_perimeter
    selected = dict(matched)
    original_price = _number(matched.get("price"))
    selected.update({
        "size_match_target_width_mm": target[0],
        "size_match_target_height_mm": target[1],
        "size_match_target_depth_mm": target[2],
        "size_match_width_mm": completed[0],
        "size_match_height_mm": completed[1],
        "size_match_depth_mm": completed[2],
        "size_match_target_perimeter": target_perimeter,
        "size_match_perimeter": matched_perimeter,
        "size_match_ratio": ratio,
        "size_match_exact": exact,
    })
    if original_price is None:
        selected["size_match_warning"] = "原价格不是安全的单一数值，未执行比例折价"
        return selected
    selected["matched_price"] = original_price
    selected["size_match_original_price"] = original_price
    scaled_price = original_price if exact else round(original_price * ratio, 6)
    if not exact:
        selected["unit_price_override"] = scaled_price
    else:
        selected.pop("unit_price_override", None)
    selected.pop("size_match_warning", None)
    return selected


def match_named_quick_attachment_size(
    items: Iterable[dict],
    category_level1: str,
    category_level2: str,
    item_name: str,
    target_dimensions,
) -> dict | None:
    """Route an exact quick-action identity through the existing size matcher.

    The source workbook leaves the dimensions of the five three-row beam
    records blank even though their approved model codes encode cabinet depth.
    Supplying that catalogue fact as ``depth_mm`` lets ``match_attachment_size``
    remain the sole nearest-size and price-scaling implementation.
    """

    candidates: list[dict] = []
    for item in items:
        if not (
            category_value(item, 0) == category_level1
            and category_value(item, 1) == category_level2
            and str(item.get("item_name") or "").strip() == item_name
        ):
            continue
        candidate = dict(item)
        if item_name == "三排安装梁":
            model = str(candidate.get("model_code") or "").strip().upper()
            model_match = re.fullmatch(r"JP7602(40|50|60|80|10)", model)
            if model_match is None:
                continue
            candidate["depth_mm"] = {
                "40": 400.0,
                "50": 500.0,
                "60": 600.0,
                "80": 800.0,
                "10": 1000.0,
            }[model_match.group(1)]
        candidates.append(candidate)
    if not candidates:
        return None
    return match_attachment_size(candidates, candidates[0], target_dimensions)


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
        try:
            return (2, LEVEL1_TRAILING_ORDER.index(value))
        except ValueError:
            return (1, value.casefold())


def category_options(items: Iterable[dict], selection: Iterable[str]) -> list[dict]:
    """Return the next category cards, or an empty list at a leaf node.

    A mixture of categorized and direct items gets one ``本级附件`` card so
    no price row becomes unreachable when a category is only partly refined.
    """

    chosen = tuple(selection)
    if len(chosen) == 1 and chosen[0] in DIRECT_SELECTION_LEVEL1:
        return []
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
