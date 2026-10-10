"""Shared V2 attachment integration for source MainWindow and recovered V3 classes.

The existing catalogue browser and ganged workflow retain their layout/rules.
Single-cabinet and ganged V2 selections share server previews and immutable quote rows.
"""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QTableWidgetItem, QVBoxLayout, QHeaderView, QInputDialog, QWidget
from shiboken6 import isValid
from material_prices import material_unit_price

from attachment_category_browser import (
    match_attachment_size,
    match_installation_board_for_product,
    match_named_quick_attachment_size,
    parse_base_specification,
    size_match_attachment_name,
)

PREVIEW_DELAY_MS = 350
EXTRA_HEADERS = ("快速金额", "公式状态", "公式单位成本", "公式金额", "人工尺寸")
COST_KEYS = ("error", "rule_id", "rule_version", "rule_materials", "rule_source_row", "formulas", "calculation_notes", "weight_kg", "material_cost", "spray_area_m2", "spray_cost", "auxiliary_cost", "auxiliary_list", "labor_cost", "attachment_selection_id", "quote_line_id", "environment", "pending_manual_dimensions", "pending_manual_error")


def attachment_image_match_key(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def attachment_model_suffix(value, category):
    """Return the comparable fan/filter model suffix, including its variant."""
    normalized = attachment_image_match_key(value)
    prefix = "ka" if str(category).strip() == "风机" else "fu-?" if str(category).strip() == "滤网" else ""
    if not prefix:
        return ""
    match = re.search(rf"({prefix}[0-9a-z/-]+(?:\([^()]+\))?)$", normalized)
    return match.group(1) if match else ""


def _catalog_model_suffixes(item, category):
    return {
        suffix for suffix in (
            attachment_model_suffix(item.get(field), category)
            for field in ("item_name", "model_code", "category_level2", "category_level3")
        ) if suffix
    }


def _visible_quote_dimensions(window):
    """Prefer the dimensions currently typed in the visible option field."""
    for name in ("quote_spec_edit", "model_edit"):
        control = getattr(window, name, None)
        text = control.text().strip() if control is not None and hasattr(control, "text") else ""
        parsed = parse_base_specification(text)
        if parsed is not None:
            return tuple(float(value) for value in parsed[:3])
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*[xX×＊*]\s*"
            r"(\d+(?:\.\d+)?)\s*[xX×＊*]\s*(\d+(?:\.\d+)?)\s*",
            text,
        )
        if match:
            width, depth, height = (float(value) for value in match.groups())
            if min(width, height, depth) > 0:
                return width, height, depth
    controls = [getattr(window, name, None) for name in ("width_spin", "height_spin", "depth_spin")]
    try:
        return tuple(float(control.value()) for control in controls)
    except (AttributeError, TypeError, ValueError):
        return None


def missing_manual_dimensions(row):
    manual = row.get("manual_inputs") if isinstance(row, dict) else None
    manual = manual if isinstance(manual, dict) else {}
    missing = []
    for parameter in row.get("required_parameters", []) if isinstance(row, dict) else []:
        if not isinstance(parameter, dict) or parameter.get("source") != "MANUAL":
            continue
        name = str(parameter.get("name") or "").strip()
        try:
            valid = float(manual.get(name)) > 0
        except (TypeError, ValueError):
            valid = False
        if name and not valid:
            missing.append(name)
    return missing


def provisionalize_manual_dimension_result(result):
    """Make only missing-manual-dimension rows addable at zero UI amount."""
    if not isinstance(result, dict) or result.get("attachment_contract") != 2:
        return result
    rendered = copy.deepcopy(result)
    pending_quick = 0.0
    has_pending = False
    has_blocking_error = False
    for row in rendered.get("attachments", []):
        missing = missing_manual_dimensions(row)
        manual_error = row.get("status") == "ERROR" and missing and str(row.get("error") or "").startswith("人工尺寸")
        if manual_error:
            has_pending = True
            pending_quick += float(row.get("quick_amount") or 0)
            row["pending_manual_dimensions"] = missing
            row["pending_manual_error"] = str(row.get("error") or "")
            row["quick_amount"] = 0.0
            row["formula_amount"] = 0.0
            row["formula_unit_cost"] = 0.0
            row["status"] = "PENDING_MANUAL"
            row["status_text"] = "待补充尺寸：" + "、".join(missing)
        elif row.get("status") == "ERROR":
            has_blocking_error = True
    if not has_pending:
        return rendered
    quick = dict(rendered.get("quick_quote") or {})
    quick["attachment_fee"] = max(0.0, float(quick.get("attachment_fee") or 0) - pending_quick)
    if quick.get("total_cost") is not None:
        quick["total_cost"] = float(quick["total_cost"]) - pending_quick
    rendered["quick_quote"] = quick
    formula = dict(rendered.get("formula_cost") or {})
    formula["attachment_fee"] = (
        sum(float(row.get("formula_amount") or 0) for row in rendered.get("attachments", []))
        if not has_blocking_error else None
    )
    if not has_blocking_error and formula.get("total_cost") is None:
        formula["total_cost"] = sum(float(formula.get(key) or 0) for key in (
            "material_cost", "auxiliary_cost", "labor_cost", "spray_cost", "management_fee",
        )) + float(formula.get("attachment_fee") or 0)
    rendered["formula_cost"] = formula
    pending_names = {
        str(row.get("item_name") or "") for row in rendered.get("attachments", [])
        if row.get("status") == "PENDING_MANUAL"
    }
    rendered["risk_flags"] = [
        risk for risk in rendered.get("risk_flags", [])
        if not (
            isinstance(risk, dict)
            and risk.get("code") == "attachment_error"
            and any(name and str(risk.get("message") or "").startswith(name + "：") for name in pending_names)
        )
    ]
    return rendered


def match_catalog_attachment(selection, catalog, target_dimensions=None, product_code="", base_height_mm=None):
    """Resolve a price-free scheme selection against the live V2 catalogue."""
    wanted_name = attachment_image_match_key(selection.get("item_name") or selection.get("name"))
    wanted_category = attachment_image_match_key(
        selection.get("category_level1") or selection.get("attachment_category")
    )
    category = str(selection.get("category_level1") or selection.get("attachment_category") or "").strip()
    name = str(selection.get("item_name") or selection.get("name") or "").strip()
    if category in {"配置变形", "其他附件"}:
        name_matches = [
            item for item in catalog if isinstance(item, dict)
            and attachment_image_match_key(item.get("category_level1")) == wanted_category
            and attachment_image_match_key(item.get("item_name")) == wanted_name
        ]
        if len(name_matches) == 1:
            return name_matches[0]
    ground_wire_aliases = {
        "接地线-黄绿线": ("黄绿线", "红绿线"),
        "接地线-编织带": ("编织带",),
    }
    if name in ground_wire_aliases:
        aliases = tuple(attachment_image_match_key(value) for value in ground_wire_aliases[name])
        ground_wire_matches = []
        for item in catalog:
            if not isinstance(item, dict):
                continue
            identity = " ".join(
                str(item.get(field) or "")
                for field in ("category_level1", "category_level2", "category_level3", "item_name", "model_code", "variant")
            )
            normalized_identity = attachment_image_match_key(identity)
            if "接地线" in normalized_identity and any(alias in normalized_identity for alias in aliases):
                ground_wire_matches.append(item)
        if len(ground_wire_matches) == 1:
            return ground_wire_matches[0]
    if category in {"风机", "滤网"}:
        wanted_suffix = attachment_model_suffix(name, category)
        if wanted_suffix:
            suffix_candidates = [
                item for item in catalog if isinstance(item, dict)
                and wanted_suffix in _catalog_model_suffixes(item, category)
            ]
            same_category = [
                item for item in suffix_candidates
                if attachment_image_match_key(item.get("category_level1")) == wanted_category
            ]
            if len(same_category) == 1:
                return same_category[0]
            if len(suffix_candidates) == 1:
                return suffix_candidates[0]
    candidates = [
        item for item in catalog if isinstance(item, dict)
        and attachment_image_match_key(item.get("item_name")) == wanted_name
    ]
    category_matches = [
        item for item in candidates
        if attachment_image_match_key(item.get("category_level1")) == wanted_category
    ]
    wanted_model = str(selection.get("model_code") or selection.get("specification") or "").strip().upper()
    if wanted_model and not (target_dimensions is not None and installation_board(selection)):
        exact_models = [
            item for item in (category_matches or candidates)
            if str(item.get("model_code") or "").strip().upper() == wanted_model
        ]
        if len(exact_models) == 1:
            return exact_models[0]
    light_switch_key = attachment_image_match_key("照明灯/行程开关")
    if wanted_name == light_switch_key or wanted_category == light_switch_key:
        light_switch_matches = category_matches or candidates
        default_220v = [
            item for item in light_switch_matches
            if str(item.get("model_code") or "").strip().upper() == "220V"
        ]
        if len(default_220v) == 1:
            return default_220v[0]
    all_category_matches = [
        item for item in catalog if isinstance(item, dict)
        and attachment_image_match_key(item.get("category_level1")) == wanted_category
    ]
    sized_candidates = (
        [item for item in all_category_matches if size_match_attachment_name(item) == "侧板"]
        if category == "侧板" else category_matches or candidates
    )
    if sized_candidates and target_dimensions is not None:
        target = tuple(target_dimensions)
        if category == "底座" and base_height_mm is not None and len(target) >= 3:
            target = (target[0], float(base_height_mm), target[2])
        matched = None
        if category == "侧板":
            matched = match_attachment_size(sized_candidates, sized_candidates[0], target)
        elif category == "安装板" and name in {"安装板", "JK安装板"}:
            matched = match_installation_board_for_product(
                catalog, sized_candidates[0], target, product_code
            )
        elif category == "安装附件" and name == "固定立柱":
            matched = match_named_quick_attachment_size(
                catalog, category, "固定立柱", name, target
            )
        elif category == "安装附件" and name == "三排安装梁":
            matched = match_named_quick_attachment_size(
                catalog, category, "三排纵梁", name, target
            )
        elif category in {"控制箱附件", "控制柜附件"} and name in {
            "JK安装板", "内门", "防雨顶", "通风顶罩",
        }:
            matched = match_named_quick_attachment_size(
                catalog, category, name, name, target
            )
        elif size_match_attachment_name(sized_candidates[0]) is not None:
            matched = match_attachment_size(sized_candidates, sized_candidates[0], target)
        if matched is not None:
            return matched
    if len(category_matches) == 1:
        return category_matches[0]
    if len(candidates) == 1:
        return candidates[0]
    if wanted_name == wanted_category:
        category_items = [
            item for item in catalog if isinstance(item, dict)
            and attachment_image_match_key(item.get("category_level1")) == wanted_category
        ]
        if len(category_items) == 1:
            return category_items[0]
    return None


def match_quote_attachment(window, selection, catalog):
    """Apply the retained quick-size rules immediately before quote pricing."""
    dimensions = _visible_quote_dimensions(window)
    product_getter = getattr(window, "selected_product_code", None)
    product_code = product_getter() if callable(product_getter) else ""
    return match_catalog_attachment(
        selection,
        catalog,
        target_dimensions=dimensions,
        product_code=product_code,
        base_height_mm=base_height(window),
    )

def merge_cost(source, cost, automatic_base_height=None):
    # Old popups froze a pending dimension placeholder as a price override.
    # Do not let that automatic zero hide a successful database repricing.
    if (source.get("pending_manual_dimensions") and source.get("quick_amount_override") == 0
            and not source.get("custom_amount_edited")):
        source = {key: value for key, value in source.items() if key != "quick_amount_override"}
    merged = {**{key: value for key, value in source.items() if key not in COST_KEYS}, **cost}
    # Older V2 APIs return the catalogue amount for sized attachments. Apply
    # the selected size price to all approved families; newer APIs derive it.
    sized = not source.get("custom") and (size_match_attachment_name(source) or size_match_attachment_name(cost))
    if sized and cost.get("status") != "PENDING_MANUAL" and (source.get("size_match_ratio") is not None or cost.get("size_match_ratio") is not None):
        source_price = source.get("unit_price_override")
        automatic_price = None
        if source.get("size_match_original_price") is not None and source.get("size_match_ratio") is not None:
            automatic_price = round(float(source["size_match_original_price"]) * float(source["size_match_ratio"]), 6)
        manual_price = source_price is not None and automatic_price is not None and abs(float(source_price) - automatic_price) > 0.000001
        if source.get("quick_amount_override") is not None:
            merged["quick_amount"] = source["quick_amount_override"]
            if source.get("unit_price_override") is not None:
                merged["unit_price_override"] = source["unit_price_override"]
        elif source_price is not None and (manual_price or cost.get("size_match_ratio") is None):
            merged["unit_price_override"] = source_price
            amount = Decimal(str(source["unit_price_override"])) * Decimal(str(merged.get("quantity", 1))) * price_sign(merged)
            merged["quick_amount"] = float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        elif cost.get("size_match_exact") is True:
            merged.pop("unit_price_override", None)
    if automatic_base_height is not None and uses_base_height(merged):
        manual = copy.deepcopy(merged.get("manual_inputs") or {})
        # Keep the automatically derived base height in the immutable quote
        # row only for attachments whose formula actually uses it.  Adding
        # this parameter to unrelated rows (lamps, fans, etc.) would differ
        # from their server snapshots and block confirmation.
        manual["底座高度"] = automatic_base_height
        merged["manual_inputs"] = manual
    return merged

def price_sign(source):
    return -1 if source.get("attachment_price_sign") == -1 else 1

def installation_board(source):
    identity = " ".join(str(source.get(key) or "") for key in ("category_level1", "category_level2", "category_level3", "item_name", "model_code"))
    return "安装板" in identity and "安装板单发" not in identity

def needs_installation_board_resolution(window):
    dimensions = _visible_quote_dimensions(window)
    if not dimensions:
        return False
    return any(
        not row.get("custom") and installation_board(row)
        and any(row.get("size_match_target_" + key + "_mm") != dimensions[index]
                for index, key in enumerate(("width", "height")))
        for row in getattr(window, "attachments", []) if isinstance(row, dict)
    )

def resolve_installation_board(source, matched, version):
    # Catalogue identity/dimensions and generated prices must be refreshed,
    # not overwritten by an old selected model or a previous size ratio.
    resolved = {**{key: value for key, value in source.items() if key not in COST_KEYS},
                **copy.deepcopy(matched), "catalog_version": version}
    for key in ("quantity", "attachment_price_sign", "manual_inputs"):
        if key in source:
            resolved[key] = copy.deepcopy(source[key])
    for key in ("quick_amount", "quick_amount_override", "unit_price_override"):
        resolved.pop(key, None)
    if source.get("quick_amount_override") is not None:
        for key in ("quick_amount", "quick_amount_override", "unit_price_override"):
            if key in source:
                resolved[key] = source[key]
    elif matched.get("unit_price_override") is not None:
        resolved["unit_price_override"] = matched["unit_price_override"]
    return resolved

def ganged(window):
    control = getattr(window, "ganged_count_spin", None)
    if control is None:
        control = getattr(window, "ganged_cabinet_count_spin", None)
    try:
        from layout_refresh import _ganged_count
        return _ganged_count(window) > 1
    except (ImportError, AttributeError, TypeError):
        return bool(control and control.value() > 1)


def _is_fixed_base_selection(item):
    """Return whether a scheme attachment represents the fixed-base choice."""
    category = str(
        item.get("category_level1") or item.get("attachment_category") or ""
    ).strip()
    identity = " ".join(
        str(item.get(key) or "")
        for key in ("category_level2", "category_level3", "item_name", "name")
    )
    return category == "底座" and "固定底座" in identity


def expand_ganged_fixed_bases_for_quote(window, rows, catalog, version=None):
    """Replace the logical fixed-base choice with one priced row per child.

    The scheme picker records only whether a base is selected.  Its concrete
    price row must therefore be resolved here, where the complete live
    catalogue and every ganged child dimension are both available.
    """
    cabinets = [
        dict(row) for row in getattr(window, "ganged_cabinets", [])
        if isinstance(row, dict)
    ]
    sources = [dict(item) for item in rows if isinstance(item, dict)]
    fixed_sources = [item for item in sources if _is_fixed_base_selection(item)]
    if len(cabinets) <= 1 or not fixed_sources:
        return sources, []

    try:
        from ganged_cabinet_rules import subcabinet_specification
    except ImportError:
        subcabinet_specification = lambda row: ""

    source = fixed_sources[0]
    product_getter = getattr(window, "selected_product_code", None)
    product_code = product_getter() if callable(product_getter) else ""
    expanded = []
    missing = []
    inserted = False
    for item in sources:
        if not _is_fixed_base_selection(item):
            expanded.append(item)
            continue
        if inserted:
            continue
        inserted = True
        for index, cabinet in enumerate(cabinets):
            try:
                width = float(cabinet["width_mm"])
                height = float(cabinet["height_mm"])
                depth = float(cabinet["depth_mm"])
                base = float(cabinet["base_height_mm"])
            except (KeyError, TypeError, ValueError):
                missing.append(f"柜体{index + 1}固定底座尺寸")
                continue
            matched = match_catalog_attachment(
                source,
                catalog,
                target_dimensions=(width, height, depth),
                product_code=product_code,
                base_height_mm=base,
            )
            if matched is None:
                missing.append(f"柜体{index + 1}固定底座")
                continue
            resolved = {**source, **copy.deepcopy(matched)}
            resolved.update({
                "attachment_price_id": matched.get("attachment_price_id"),
                "catalog_version": version,
                "quantity": 1,
                "ganged_fixed_base_match": True,
                "ganged_fixed_base_index": index,
                "ganged_cabinet_index": index,
                "ganged_fixed_base_split_count": len(cabinets),
                "ganged_fixed_base_specification": subcabinet_specification(cabinet),
            })
            expanded.append(resolved)
    return expanded, missing


def _is_door_selection(item, door_name):
    if item.get("custom"):
        return False
    category = str(item.get("category_level1") or item.get("attachment_category") or "").strip()
    name = re.sub(r"^柜体\s*\d+\s*[｜:：]\s*", "", str(item.get("item_name") or item.get("name") or "")).strip()
    return category in {"控制箱附件", "控制柜附件"} and (
        name == door_name or str(item.get("category_level2") or "").strip() == door_name
    )


def _ganged_door_keys(door_name):
    kind = {"内门": "inner_door", "玻璃门": "glass_door"}[door_name]
    return f"ganged_{kind}_match", f"ganged_{kind}_specification"


def _needs_ganged_door_resolution(window, door_name):
    """An existing first-child ID is not a complete ganged door selection."""
    cabinets = getattr(window, "ganged_cabinets", [])
    if len(cabinets) <= 1:
        return False
    doors = [item for item in getattr(window, "attachments", [])
             if isinstance(item, dict) and _is_door_selection(item, door_name)]
    if not doors:
        return False
    if len(doors) != len(cabinets):
        return True
    from ganged_cabinet_rules import subcabinet_specification
    match_key, specification_key = _ganged_door_keys(door_name)
    try:
        for index, cabinet in enumerate(cabinets):
            matches = [row for row in doors if row.get("ganged_cabinet_index") == index]
            if len(matches) != 1:
                return True
            row = matches[0]
            if (not row.get(match_key)
                    or _catalogue_id(row.get("attachment_price_id")) is None
                    or row.get(specification_key) != subcabinet_specification(cabinet)):
                return True
    except (KeyError, TypeError, ValueError):
        return True
    return False


def needs_ganged_inner_door_resolution(window):
    return _needs_ganged_door_resolution(window, "内门")


def needs_ganged_glass_door_resolution(window):
    return _needs_ganged_door_resolution(window, "玻璃门")


def needs_ganged_door_resolution(window):
    return needs_ganged_inner_door_resolution(window) or needs_ganged_glass_door_resolution(window)


def _expand_ganged_doors_for_quote(window, rows, catalog, version, door_name):
    """Resolve one door per child without changing its existing size rule."""
    cabinets = [row for row in getattr(window, "ganged_cabinets", []) if isinstance(row, dict)]
    sources = [copy.deepcopy(row) for row in rows if isinstance(row, dict)]
    doors = [row for row in sources if _is_door_selection(row, door_name)]
    if len(cabinets) <= 1 or not doors:
        return sources, []
    from ganged_cabinet_rules import subcabinet_specification
    match_key, specification_key = _ganged_door_keys(door_name)
    # Treat the picker choice as logical selection, not a pinned catalogue model.
    choice = {**doors[0], "item_name": door_name, "model_code": "", "specification": ""}
    expanded, missing = [], []
    inserted = False
    for source in sources:
        if not _is_door_selection(source, door_name):
            expanded.append(source)
            continue
        if inserted:
            continue
        inserted = True
        for index, cabinet in enumerate(cabinets):
            try:
                dimensions = tuple(float(cabinet[key]) for key in ("width_mm", "height_mm", "depth_mm"))
                if not all(value > 0 for value in dimensions):
                    raise ValueError("invalid child dimensions")
                specification = subcabinet_specification(cabinet)
            except (KeyError, TypeError, ValueError):
                missing.append(f"柜体{index + 1}{door_name}尺寸")
                continue
            matched = match_catalog_attachment(choice, catalog, target_dimensions=dimensions)
            if matched is None or _catalogue_id(matched.get("attachment_price_id")) is None:
                missing.append(f"柜体{index + 1}{door_name}")
                continue
            previous = next((row for row in doors if row.get("ganged_cabinet_index") == index), None)
            unchanged = previous is not None and (
                previous.get("attachment_price_id") == matched.get("attachment_price_id")
                and previous.get(specification_key) == specification
            )
            resolved = {**choice, **copy.deepcopy(matched)}
            # Preserve local edits only when this child's matched size is unchanged.
            if unchanged:
                resolved.update(previous)
            else:
                for key in ("unit_price_override", "custom_amount_edited", "quick_amount",
                            "formula_amount", "formula_unit_cost", *COST_KEYS):
                    resolved.pop(key, None)
                if "unit_price_override" in matched:
                    resolved["unit_price_override"] = matched["unit_price_override"]
            resolved.update({
                "item_name": door_name, "catalog_version": version,
                "quantity": previous.get("quantity", 1) if previous else 1,
                match_key: True, "ganged_cabinet_index": index,
                specification_key: specification,
            })
            expanded.append(resolved)
    return expanded, missing


def expand_ganged_inner_doors_for_quote(window, rows, catalog, version=None):
    return _expand_ganged_doors_for_quote(window, rows, catalog, version, "内门")


def expand_ganged_glass_doors_for_quote(window, rows, catalog, version=None):
    return _expand_ganged_doors_for_quote(window, rows, catalog, version, "玻璃门")


def base_height(window):
    """Return the base height already entered in the visible cabinet specification."""
    rows = [dict(row) for row in getattr(window, "ganged_cabinets", []) if isinstance(row, dict)]
    if len(rows) > 1:
        values = [row.get("base_height_mm") for row in rows]
        if values and all(value not in (None, "") for value in values):
            return float(values[0])
    for name in ("quote_spec_edit", "model_edit"):
        control = getattr(window, name, None)
        text = control.text().strip() if control is not None and hasattr(control, "text") else ""
        parsed = parse_base_specification(text)
        if parsed is not None:
            return float(parsed[3])
    return None

def environment(window, attachments):
    ganged_rows = [dict(row) for row in getattr(window, "ganged_cabinets", []) if isinstance(row, dict)]
    if len(ganged_rows) <= 1:
        ganged_rows = []
    child_inputs = []
    if ganged_rows:
        product_key = getattr(getattr(window, "product_combo", None), "currentData", lambda: None)() or ""
        codes = (getattr(window, "product_catalog", {}).get(product_key, {}) or {}).get("codes") or {}
        fallback_code = window.selected_product_code()
        for row in ganged_rows:
            wanted = "SINGLE" if int(row.get("single_door_count") or 0) > 0 else "DOUBLE"
            code = next((codes.get(key) for key in (wanted, "DEFAULT", "SINGLE", "DOUBLE") if codes.get(key)), fallback_code)
            child_inputs.append({**row, "product_code": code})
    return {"quote_id": "PREVIEW", "product_code": window.selected_product_code(), "model_code": window.model_edit.text().strip() if hasattr(window, "model_edit") else "",
            "material_code": window.material_combo.currentData(),
            "width_mm": window.width_spin.value(), "height_mm": window.height_spin.value(), "depth_mm": window.depth_spin.value(),
            "coating_type": window.coating_combo.currentData(), "quote_date": window.quote_date.date().toString("yyyy-MM-dd"),
            "attachments": attachments, "attachment_contract": 2,
            "ganged_cabinet_count": len(ganged_rows) if ganged_rows else 1, "ganged_cabinets": ganged_rows,
            "ganged_cabinet_inputs": child_inputs}

def uses_base_height(item):
    identity = " ".join(str(item.get(key) or "") for key in ("category_level1", "category_level2", "item_name"))
    if "底座" in identity:
        return True
    if any(parameter.get("name") == "底座高度" for parameter in item.get("required_parameters", [])):
        return True
    formulas = [item.get("formulas")]
    formulas.extend(rule.get("formulas") for rule in item.get("rules", []) if isinstance(rule, dict))
    return any("底座高度" in json.dumps(value, ensure_ascii=False) for value in formulas if value)

def selected_input(item, automatic_base_height=None):
    manual_inputs = copy.deepcopy(item.get("manual_inputs") or {})
    # Compatibility for the currently deployed V2 API, where 底座高度 was
    # classified as MANUAL.  The value still comes exclusively from the
    # visible cabinet specification; users never enter it in the attachment row.
    if automatic_base_height is not None and uses_base_height(item):
        manual_inputs["底座高度"] = automatic_base_height
    selected = {"attachment_price_id": item.get("attachment_price_id"), "quantity": item.get("quantity", 1),
                "attachment_price_sign": item.get("attachment_price_sign", 1), "manual_inputs": manual_inputs}
    if item.get("unit_price_override") is not None:
        selected["unit_price_override"] = item.get("unit_price_override")
    ganged_index = item.get("ganged_cabinet_index", item.get("ganged_fixed_base_index"))
    if ganged_index is not None:
        selected["ganged_cabinet_index"] = int(ganged_index)
    return selected


def confirmation_inputs(rows):
    """Freeze exactly the fields compared by the server snapshot guard."""

    frozen = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("custom") is True:
            continue
        selected = selected_input(row)
        selected.pop("unit_price_override", None)
        frozen.append(copy.deepcopy(selected))
    return frozen


def restore_confirmation_inputs(rows, frozen):
    """Restore server-compared fields after the legacy saver copies a row."""

    snapshots = [copy.deepcopy(row) for row in frozen or [] if isinstance(row, dict)]
    output = []
    cursor = 0
    for source in rows or []:
        row = copy.deepcopy(source) if isinstance(source, dict) else source
        if not isinstance(row, dict) or row.get("custom") is True:
            output.append(row)
            continue
        if cursor >= len(snapshots):
            output.append(row)
            continue
        snapshot = snapshots[cursor]
        cursor += 1
        row["attachment_price_id"] = snapshot.get("attachment_price_id")
        row["quantity"] = snapshot.get("quantity", 1)
        row["attachment_price_sign"] = snapshot.get("attachment_price_sign", 1)
        row["manual_inputs"] = copy.deepcopy(snapshot.get("manual_inputs") or {})
        if "ganged_cabinet_index" in snapshot:
            row["ganged_cabinet_index"] = int(snapshot["ganged_cabinet_index"])
        else:
            row.pop("ganged_cabinet_index", None)
            row.pop("ganged_fixed_base_index", None)
        output.append(row)
    return output


def confirmation_attachments_for_item(item):
    """Return the immutable catalogue selections used by quote confirmation.

    Priced attachment rows are later decorated for display (for example with
    final cabinet quantities and compatibility fields).  Those presentation
    rows must never be used as the confirmation contract because the service
    compares them with the exact inputs frozen when the quote line was priced.
    Quote-local custom rows are intentionally appended from the live item: they
    are not part of the catalogue snapshot and are validated separately.
    """

    rows = item.get("attachments") if isinstance(item, dict) else None
    rows = rows if isinstance(rows, list) else []
    frozen = item.get("attachment_confirmation_inputs") if isinstance(item, dict) else None
    if not isinstance(frozen, list):
        return copy.deepcopy(rows)
    catalog = [
        copy.deepcopy(row) for row in frozen
        if isinstance(row, dict) and row.get("custom") is not True
    ]
    custom = [
        copy.deepcopy(row) for row in rows
        if isinstance(row, dict) and row.get("custom") is True
    ]
    return catalog + custom


def _catalogue_id(value):
    """Match the API's positive JavaScript safe-integer catalogue IDs."""

    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        return None
    number = int(text)
    return number if number <= 9007199254740991 else None


def validate_confirmation_attachments(item, line_number):
    """Fail locally with a row name; never manufacture an ID or custom flag."""

    rows = item.get("attachments") or []
    if not isinstance(rows, list):
        raise ValueError(f"第{line_number}行报价的附件数据无效，请重新计算并加入报价单。")
    named_rows = [(index, row) for index, row in enumerate(rows, 1)
                  if not isinstance(row, dict) or row.get("custom") is not True]
    frozen = item.get("attachment_confirmation_inputs")

    def fail(index, row, reason):
        name = (row.get("item_name") or row.get("name") or row.get("model_code")) if isinstance(row, dict) else None
        label = name or f"附件{index}"
        cabinet = item.get("name") or item.get("model_code") or item.get("product_code") or "未命名"
        raise ValueError(f"第{line_number}行报价（{cabinet}）的“{label}”：{reason}。请重新计算该柜并重新加入报价单。")

    if isinstance(frozen, list):
        catalog = [row for row in frozen if not isinstance(row, dict) or row.get("custom") is not True]
        if len(named_rows) != len(catalog):
            index, row = next(((i, r) for i, r in named_rows
                               if not isinstance(r, dict) or _catalogue_id(r.get("attachment_price_id")) is None),
                              named_rows[-1] if named_rows else (1, {}))
            fail(index, row, "附件清单与计算快照不一致，或临时附件标记已丢失")
        for (index, row), snapshot in zip(named_rows, catalog):
            if not isinstance(snapshot, dict) or _catalogue_id(snapshot.get("attachment_price_id")) is None:
                fail(index, row, "计算快照缺少有效的附件价格库 ID")
            if not isinstance(row, dict):
                fail(index, row, "附件数据无效")
            # A legacy presentation row may have lost its ID; a valid frozen
            # server input can restore it. A different real ID is a new choice.
            visible_id = _catalogue_id(row.get("attachment_price_id"))
            if row.get("attachment_price_id") is not None and visible_id != _catalogue_id(snapshot.get("attachment_price_id")):
                fail(index, row, "所选附件与计算快照不一致")
    else:
        for index, row in named_rows:
            if not isinstance(row, dict) or _catalogue_id(row.get("attachment_price_id")) is None:
                fail(index, row, "缺少有效的附件价格库 ID（attachment_price_id），且没有可恢复的计算快照")


def confirmation_payload(payload, *, validate=False):
    """Freeze V2 attachment inputs without mutating the visible draft."""

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return payload
    output = copy.deepcopy(payload)
    for line_number, item in enumerate(output["items"], 1):
        if not isinstance(item, dict) or item.get("attachment_contract") != 2:
            continue
        if validate:
            validate_confirmation_attachments(item, line_number)
        item["attachments"] = confirmation_attachments_for_item(item)
    return output

def install_attachment_v2(namespace):
    window_class, dialog_class, worker_class = (namespace.get(n) for n in ("MainWindow", "AttachmentDialog", "ApiWorker"))
    if not window_class or not dialog_class or not worker_class or getattr(window_class, "_attachment_v2_installed", False):
        return
    window_class._attachment_v2_installed = True
    export = window_class.export_workbook
    def export_v2(window, output_path, payload):
        # The Excel endpoint hydrates the same server snapshot as confirmation.
        # Validate inside the export worker so existing error dialogs handle it.
        return export(window, output_path, confirmation_payload(payload, validate=True))
    window_class.export_workbook = export_v2
    originals = {name: getattr(dialog_class, name) for name in ("__init__", "load_catalog", "rebuild_table", "collect_attachments", "accept_selection")}
    same_choice = dialog_class._same_catalog_choice
    @classmethod
    def same_choice_v2(cls, selected, catalog_item):
        if selected.get("catalog_version") or catalog_item.get("catalog_version") or catalog_item.get("data_version"):
            return selected.get("attachment_price_id") is not None and str(selected["attachment_price_id"]) == str(catalog_item.get("attachment_price_id"))
        return same_choice(selected, catalog_item)
    dialog_class._same_catalog_choice = same_choice_v2

    def checked(dialog):
        rows = []
        for row in range(dialog.table.rowCount()):
            cell = dialog.table.item(row, dialog.COL_CHECK)
            if cell and cell.checkState() == Qt.CheckState.Checked:
                rows.append((row, cell, cell.data(Qt.ItemDataRole.UserRole) or {}))
        return rows

    def collect(dialog, show_errors=True):
        result = originals["collect_attachments"](dialog, show_errors=show_errors)
        if result is not None and getattr(dialog, "_v2_mode", False):
            for index, (item, (_, _, source)) in enumerate(zip(result, checked(dialog))):
                result[index] = item = {**copy.deepcopy(source), **item}
                item.pop("rules", None)
            decorate(dialog)
        return result

    def decorate(dialog):
        if not getattr(dialog, "_v2_mode", False):
            return
        table = dialog.table
        first = dialog.COL_QUANTITY + 1
        table.blockSignals(True)
        try:
            table.setColumnCount(first + len(EXTRA_HEADERS))
            table.setHorizontalHeaderItem(dialog.COL_PRICE, QTableWidgetItem("面价（元）"))
            table.setHorizontalHeaderItem(dialog.COL_SCHEME, QTableWidgetItem("单位"))
            table.setHorizontalHeaderItem(dialog.COL_NAME, QTableWidgetItem("一级分类 / 名称"))
            table.horizontalHeader().setSectionResizeMode(dialog.COL_NAME, QHeaderView.ResizeMode.Interactive)
            table.horizontalHeader().resizeSection(dialog.COL_NAME, 250)
            table.verticalHeader().setMinimumSectionSize(64)
            table.verticalHeader().setDefaultSectionSize(64)
            dialog.catalog_hint.setText("面价按Excel原值；金额＝选择数量×单价×加减符号。双击人工尺寸填写参数。")
            for i, name in enumerate(EXTRA_HEADERS):
                table.setHorizontalHeaderItem(first + i, QTableWidgetItem(name))
                table.horizontalHeader().setSectionResizeMode(first + i, QHeaderView.ResizeMode.ResizeToContents)
            for row in range(table.rowCount()):
                price = table.item(row, dialog.COL_PRICE)
                if price:
                    price.setFlags(price.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cell = table.item(row, dialog.COL_CHECK)
                source = dict(cell.data(Qt.ItemDataRole.UserRole) or {}) if cell else {}
                name_item = table.item(row, dialog.COL_NAME)
                if source and name_item:
                    name_cell = table.cellWidget(row, dialog.COL_NAME)
                    if name_cell is None or name_cell.objectName() != "attachmentCategoryNameCell":
                        name_cell = QWidget(table)
                        name_cell.setObjectName("attachmentCategoryNameCell")
                        name_cell.setMinimumHeight(60)
                        name_layout = QVBoxLayout(name_cell)
                        name_layout.setContentsMargins(6, 3, 6, 3)
                        name_layout.setSpacing(1)
                        category_label = QLabel(name_cell)
                        category_label.setObjectName("attachmentPrimaryCategoryCell")
                        category_label.setStyleSheet("color:#5c6b78;font-size:9pt;")
                        item_label = QLabel(name_cell)
                        item_label.setObjectName("attachmentItemNameCell")
                        item_label.setStyleSheet("color:#173f67;font-weight:600;")
                        name_layout.addWidget(category_label)
                        name_layout.addWidget(item_label)
                        table.setCellWidget(row, dialog.COL_NAME, name_cell)
                    category_label = name_cell.findChild(QLabel, "attachmentPrimaryCategoryCell")
                    item_label = name_cell.findChild(QLabel, "attachmentItemNameCell")
                    category = str(source.get("category_level1") or "未分类").strip() or "未分类"
                    # The catalogue row already owns the primary category.  Some
                    # historical ``display_name`` values contain the category
                    # path as an extra line, which made the custom two-line cell
                    # render three overlapping labels.  Keep the table contract
                    # explicit: one category line and one item-name line.
                    name = " ".join(
                        str(source.get("item_name") or name_item.text() or "未命名附件").split()
                    )
                    name_item.setText("")
                    category_label.setText(f"一级分类：{category}")
                    item_label.setText(f"名称：{name}")
                    name_cell.setAccessibleName(f"一级分类：{category}，名称：{name}")
                    table.setRowHeight(row, max(64, table.rowHeight(row)))
                scheme = table.item(row, dialog.COL_SCHEME)
                if scheme:
                    scheme.setText(source.get("unit") or "")
                face = source.get("face_price", source.get("price", source.get("matched_price")))
                if price and face is not None:
                    price.setText(str(abs(float(face)) * price_sign(source)))
                    price.setToolTip("Excel面价；仅安装板可双击切换加价/扣减")
                source.setdefault("selection_key", str(uuid4()))
                if cell:
                    cell.setData(Qt.ItemDataRole.UserRole, source)
                for i in range(len(EXTRA_HEADERS)):
                    if table.item(row, first + i) is None:
                        value = QTableWidgetItem("—")
                        value.setFlags(value.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row, first + i, value)
        finally:
            table.blockSignals(False)

    def rebuild(dialog):
        result = originals["rebuild_table"](dialog)
        decorate(dialog)
        if hasattr(dialog, "_v2_timer"):
            dialog._v2_timer.start()
        return result

    def load(dialog, api_url):
        parent = dialog.parentWidget()
        dialog._v2_mode = parent is not None and all(hasattr(parent, key) for key in ("material_combo", "width_spin", "height_spin", "depth_spin", "coating_combo", "quote_date"))
        if not dialog._v2_mode:
            return originals["load_catalog"](dialog, api_url)
        dialog.catalog_hint.setText("正在读取附件面价及成本规则…")
        generation = getattr(dialog, "_v2_catalog_generation", 0) + 1
        dialog._v2_catalog_generation = generation
        url = api_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/catalog?v=2"
        worker = worker_class(url, {}, parent, method="GET")
        dialog._v2_catalog_worker = worker
        def loaded(body):
            if not isValid(dialog) or dialog._v2_catalog_generation != generation:
                return
            dialog.catalog = [
                dict(
                    x,
                    catalog_version=body["data_version"],
                    display_name=dialog.display_name(x),
                )
                for x in body.get("items", [])
            ]
            if parent is not None:
                parent._attachment_catalog_cache = [
                    copy.deepcopy(item) for item in dialog.catalog
                ]
            add_button = getattr(dialog, "add_attachment_catalog_button", None)
            if add_button is not None:
                write_supported = body.get("catalog_write_supported") is True
                add_button.setEnabled(write_supported)
                add_button.setToolTip(
                    "新增到当前启用的附件目录；未配置成本规则时作为仅快速报价附件"
                    if write_supported
                    else "当前线上服务尚未启用V2附件新增接口"
                )
            dialog.catalog_hint.setText(f"已读取 {len(dialog.catalog)} 项附件；面价固定，公式成本随当前产品环境计算。")
            prepare = getattr(dialog, "prepare_fixed_base_quick_match", None)
            if callable(prepare):
                spec = getattr(dialog, "_specification_text", None)
                dialog.base_quick_match_specification = spec() if callable(spec) else ""
                prepare()
            dialog.rebuild_table()
            dialog.refresh_category_browser()
        worker.succeeded.connect(loaded)
        worker.failed.connect(lambda message: dialog.catalog_hint.setText(f"附件读取失败：{message}；可点击重新读取价格库重试") if isValid(dialog) else None)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def preview(dialog):
        if not getattr(dialog, "_v2_mode", False):
            return
        selected = dialog.collect_attachments(show_errors=False)
        if selected is None:
            return
        automatic_base = base_height(dialog.parentWidget())
        payload = environment(dialog.parentWidget(), [selected_input(x, automatic_base) for x in selected])
        signature = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        dialog._v2_signature = signature
        old = getattr(dialog, "_v2_preview_worker", None)
        if old and old.isRunning():
            dialog._v2_timer.start()
            return
        if not selected:
            dialog._v2_ready = True
            return
        dialog._v2_ready = False
        url = dialog.api_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/preview"
        worker = worker_class(url, payload, dialog.parentWidget())
        dialog._v2_preview_worker = worker
        def loaded(body):
            if not isValid(dialog):
                return
            latest = dialog.collect_attachments(show_errors=False)
            if latest is None or json.dumps(environment(dialog.parentWidget(), [selected_input(x, automatic_base) for x in latest]), sort_keys=True, ensure_ascii=False) != signature:
                dialog._v2_timer.start()
                return
            dialog.table.blockSignals(True)
            try:
                for (row, cell, source), cost in zip(checked(dialog), body.get("attachments", [])):
                    source = merge_cost(source, cost, automatic_base)
                    cell.setData(Qt.ItemDataRole.UserRole, source)
                    manual = [p["name"] for p in cost.get("required_parameters", []) if p["source"] == "MANUAL" and not (p["name"] == "底座高度" and automatic_base is not None)]
                    values = [source.get("quick_amount"), cost.get("status_text"), cost.get("formula_unit_cost"), cost.get("formula_amount"), "、".join(manual) or "无需填写"]
                    for i, value in enumerate(values):
                        item = dialog.table.item(row, dialog.COL_QUANTITY + 1 + i)
                        if item:
                            item.setText("—" if value is None else (f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)))
                            item.setToolTip((cost.get("error") or "") + "\n辅材清单：\n" + cost.get("auxiliary_list", ""))
                dialog._v2_ready = not body.get("errors")
                dialog.selection_hint.setText("成本已更新；双击人工尺寸列填写参数" if dialog._v2_ready else "请补充人工尺寸或处理公式错误；双击人工尺寸列填写")
            finally:
                dialog.table.blockSignals(False)
            decorate(dialog)
        worker.succeeded.connect(loaded)
        worker.failed.connect(lambda message: dialog.selection_hint.setText(f"附件计算失败：{message}") if isValid(dialog) else None)
        def finished():
            if isValid(dialog) and getattr(dialog, "_v2_preview_worker", None) is worker:
                dialog._v2_preview_worker = None
            worker.deleteLater()
        worker.finished.connect(finished)
        worker.start()

    def edit_parameters(dialog, row, column):
        if not getattr(dialog, "_v2_mode", False):
            return
        source_cell = dialog.table.item(row, dialog.COL_CHECK)
        source = dict(source_cell.data(Qt.ItemDataRole.UserRole) or {})
        if column == dialog.COL_PRICE and installation_board(source):
            choice, accepted = QInputDialog.getItem(dialog, "安装板加减", "面价固定，选择金额方向", ["加价", "扣减"], 0 if price_sign(source) > 0 else 1, False)
            if accepted:
                source["attachment_price_sign"] = -1 if choice == "扣减" else 1
                if hasattr(dialog, "installation_board_sign"):
                    dialog.installation_board_sign = source["attachment_price_sign"]
                    for _, cell, item in checked(dialog):
                        if installation_board(item):
                            cell.setData(Qt.ItemDataRole.UserRole, {**item, "attachment_price_sign": source["attachment_price_sign"]})
                source_cell.setData(Qt.ItemDataRole.UserRole, source)
                decorate(dialog)
                dialog._v2_ready = False
                dialog._v2_timer.start()
            return
        if column != dialog.COL_QUANTITY + len(EXTRA_HEADERS):
            return
        automatic_base = base_height(dialog.parentWidget())
        parameters = [p for p in source.get("required_parameters", []) if p["source"] == "MANUAL" and not (p["name"] == "底座高度" and automatic_base is not None)]
        if not parameters:
            return
        editor = QDialog(dialog)
        editor.setWindowTitle(f"{source.get('item_name', '附件')} · 人工尺寸（mm）")
        layout, form, fields = QVBoxLayout(editor), QFormLayout(), {}
        for parameter in parameters:
            name = parameter["name"]
            fields[name] = QLineEdit(str((source.get("manual_inputs") or {}).get(name, "")))
            fields[name].setPlaceholderText("必填，不自动使用产品尺寸")
            form.addRow(name, fields[name])
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(editor.accept)
        buttons.rejected.connect(editor.reject)
        layout.addWidget(buttons)
        if editor.exec() == QDialog.DialogCode.Accepted:
            source["manual_inputs"] = {name: field.text().strip() for name, field in fields.items()}
            # V3's legacy itemChanged handler rematches dimensions. Metadata edits
            # must not trigger that handler and discard this selection's inputs.
            blocked = dialog.table.blockSignals(True)
            try:
                source_cell.setData(Qt.ItemDataRole.UserRole, source)
            finally:
                dialog.table.blockSignals(blocked)
            dialog._v2_ready = False
            dialog._v2_timer.start()

    def init(dialog, *args, **kwargs):
        originals["__init__"](dialog, *args, **kwargs)
        if not getattr(dialog, "_v2_mode", False):
            return
        decorate(dialog)
        add_button = getattr(dialog, "add_attachment_catalog_button", None)
        if add_button is not None:
            add_button.setEnabled(False)
            add_button.setToolTip("正在检查V2附件新增接口…")
        dialog._v2_ready = False
        dialog._v2_timer = QTimer(dialog)
        dialog._v2_timer.setSingleShot(True)
        dialog._v2_timer.setInterval(PREVIEW_DELAY_MS)
        dialog._v2_timer.timeout.connect(lambda: preview(dialog))
        def changed(*_):
            dialog._v2_ready = False
            dialog._v2_timer.start()
        dialog.table.itemChanged.connect(changed)
        dialog.table.cellDoubleClicked.connect(lambda row, column: edit_parameters(dialog, row, column))
        dialog._v2_timer.start()

    def accept(dialog):
        if getattr(dialog, "_v2_mode", False) and not getattr(dialog, "_v2_ready", False) and checked(dialog):
            QMessageBox.information(dialog, "附件成本未完成", "请等待计算完成，并填写提示的人工尺寸或处理错误。")
            return
        return originals["accept_selection"](dialog)

    def attachment_selection_changed(dialog):
        """Recalculate both attachment prices after a card-level toggle."""

        if not getattr(dialog, "_v2_mode", False) or not hasattr(dialog, "_v2_timer"):
            return
        dialog._v2_ready = False
        dialog._v2_timer.start()

    dialog_class.__init__, dialog_class.load_catalog, dialog_class.rebuild_table = init, load, rebuild
    dialog_class.collect_attachments, dialog_class.accept_selection = collect, accept
    dialog_class.attachment_selection_changed = attachment_selection_changed
    item_changed = getattr(dialog_class, "table_item_changed", None)
    if item_changed is not None:
        def item_changed_v2(dialog, item):
            remembered = [(row, source.get("attachment_price_id"), source.get("selection_key"), {key: copy.deepcopy(source[key]) for key in ("manual_inputs", "selection_key") if key in source}) for row, _, source in checked(dialog)] if getattr(dialog, "_v2_mode", False) else []
            result = item_changed(dialog, item)
            blocked = dialog.table.blockSignals(True)
            try:
                for row, cell, source in checked(dialog):
                    candidates = [entry for entry in remembered if entry[1] == source.get("attachment_price_id")]
                    match = next((entry for entry in candidates if entry[2] and entry[2] == source.get("selection_key")), None)
                    match = match or next((entry for entry in candidates if entry[0] == row), None)
                    if match is None and len(candidates) == 1:
                        match = candidates[0]
                    if match:
                        cell.setData(Qt.ItemDataRole.UserRole, {**source, **match[3]})
            finally:
                dialog.table.blockSignals(blocked)
            return result
        dialog_class.table_item_changed = item_changed_v2
    refresh_browser = dialog_class.refresh_category_browser
    def refresh_browser_v2(dialog, *args, **kwargs):
        result = refresh_browser(dialog, *args, **kwargs)
        if getattr(dialog, "_v2_mode", False) and hasattr(dialog, "_v2_timer"):
            decorate(dialog)
            dialog._v2_ready = False
            dialog._v2_timer.start()
        return result
    dialog_class.refresh_category_browser = refresh_browser_v2

    def resolve_attachments_for_quote(window, succeeded, failed):
        rows = [dict(item) for item in getattr(window, "attachments", []) if isinstance(item, dict)]
        pending = [item for item in rows if not item.get("custom") and item.get("attachment_price_id") is None]
        needs_ganged_base_catalog = (
            ganged(window) and any(_is_fixed_base_selection(item) for item in rows)
        )
        if not pending and not needs_ganged_base_catalog and not needs_ganged_door_resolution(window) and not needs_installation_board_resolution(window):
            succeeded()
            return
        active = getattr(window, "_scheme2_attachment_catalog_worker", None)
        if active is not None and active.isRunning():
            failed("附件价格库正在读取，请稍后重试")
            return
        base_url = str(window.base_url() or "")
        url = base_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/catalog?v=2"
        worker = worker_class(url, {}, window, method="GET")
        window._scheme2_attachment_catalog_worker = worker

        def loaded(body):
            if not isValid(window):
                return
            catalog = [dict(item) for item in body.get("items", []) if isinstance(item, dict)]
            version = body.get("data_version")
            window._attachment_catalog_cache = [copy.deepcopy(item) for item in catalog]
            source_rows, fixed_base_missing = expand_ganged_fixed_bases_for_quote(
                window, rows, catalog, version
            )
            source_rows, inner_door_missing = expand_ganged_inner_doors_for_quote(
                window, source_rows, catalog, version
            )
            source_rows, glass_door_missing = expand_ganged_glass_doors_for_quote(
                window, source_rows, catalog, version
            )
            resolved = []
            missing = list(fixed_base_missing) + inner_door_missing + glass_door_missing
            for source in source_rows:
                if source.get("custom"):
                    resolved.append(source)
                    continue
                if source.get("attachment_price_id") is not None and not installation_board(source):
                    resolved.append(source)
                    continue
                match = match_quote_attachment(window, source, catalog)
                if match is None:
                    missing.append(str(source.get("item_name") or source.get("name") or "未命名附件"))
                    continue
                if installation_board(source):
                    resolved.append(resolve_installation_board(source, match, version))
                    continue
                resolved.append({
                    **copy.deepcopy(match),
                    **source,
                    "attachment_price_id": match.get("attachment_price_id"),
                    "catalog_version": version,
                })
            if missing:
                failed("价格库中未找到唯一匹配项：" + "、".join(missing))
                return
            window.attachments = resolved
            window._attachment_v2_line_id = None
            window.current_result = None
            window.update_attachment_view()
            succeeded()

        worker.succeeded.connect(loaded)
        worker.failed.connect(lambda message: failed(f"附件价格库读取失败：{message}") if isValid(window) else None)

        def finished():
            if isValid(window) and getattr(window, "_scheme2_attachment_catalog_worker", None) is worker:
                window._scheme2_attachment_catalog_worker = None
            worker.deleteLater()

        worker.finished.connect(finished)
        worker.start()

    window_class.resolve_attachments_for_quote = resolve_attachments_for_quote

    def recalculate_draft_attachment(window, quote_item, attachment, succeeded, failed):
        # Temporary attachments use only this quotation's manual amounts.
        # Never resolve them into catalogue records or send them to preview.
        if attachment.get("custom") is True:
            succeeded(copy.deepcopy(attachment))
            return
        if _catalogue_id(attachment.get("attachment_price_id")) is None:
            base_url = str(window.base_url() or "")
            url = base_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/catalog?v=2"
            worker = worker_class(url, {}, window, method="GET")
            active = getattr(window, "_scheme2_attachment_model_workers", set())
            active.add(worker)
            window._scheme2_attachment_model_workers = active

            def catalog_loaded(body):
                catalog = [dict(item) for item in body.get("items", []) if isinstance(item, dict)]
                match = match_catalog_attachment(
                    attachment,
                    catalog,
                    target_dimensions=(
                        quote_item.get("width_mm"), quote_item.get("height_mm"), quote_item.get("depth_mm")
                    ),
                    product_code=str(quote_item.get("product_code") or ""),
                )
                if match is None:
                    label = attachment.get("model_code") or attachment.get("item_name") or attachment.get("name") or "未命名附件"
                    failed(f"价格库中未找到唯一匹配项：{label}")
                    return
                if _catalogue_id(match.get("attachment_price_id")) is None:
                    label = attachment.get("item_name") or attachment.get("name") or attachment.get("model_code") or "未命名附件"
                    failed(f"附件“{label}”的价格库 ID 无效，请更新附件目录后重试。")
                    return
                resolved = {
                    **copy.deepcopy(match),
                    **attachment,
                    "attachment_price_id": match.get("attachment_price_id"),
                    "catalog_version": body.get("data_version"),
                }
                if installation_board(attachment):
                    resolved = resolve_installation_board(attachment, match, body.get("data_version"))
                recalculate_draft_attachment(window, quote_item, resolved, succeeded, failed)

            worker.succeeded.connect(catalog_loaded)
            worker.failed.connect(lambda message: failed(f"附件价格库读取失败：{message}"))

            def catalog_finished():
                getattr(window, "_scheme2_attachment_model_workers", set()).discard(worker)
                worker.deleteLater()

            worker.finished.connect(catalog_finished)
            worker.start()
            return
        settings = quote_item.get("scheme2_cost_settings") or getattr(window, "scheme2_defaults", {})
        payload = {
            "quote_id": "PREVIEW",
            "product_code": quote_item.get("product_code"),
            "model_code": quote_item.get("model_code") or quote_item.get("name") or "",
            "material_code": quote_item.get("material_code"),
            "width_mm": quote_item.get("width_mm"),
            "height_mm": quote_item.get("height_mm"),
            "depth_mm": quote_item.get("depth_mm"),
            "coating_type": quote_item.get("coating_type"),
            "quote_date": quote_item.get("quote_date") or QDate.currentDate().toString("yyyy-MM-dd"),
            "cabinet_body_thickness_mm": quote_item.get("cabinet_body_thickness_mm"),
            "waste_factor": settings.get("waste_factor", quote_item.get("waste_factor")),
            "galvanized_sheet_unit_price_override": settings.get("galvanized_price"),
            "material_unit_price_override": material_unit_price(settings, quote_item.get("material_code")),
            "carbon_steel_unit_price_override": settings.get("carbon_price"),
            "surface_treatment_unit_price_override": settings.get("surface_price"),
            "attachments": [selected_input(attachment)],
            "attachment_contract": 2,
        }
        # Reprice against this saved order, never the currently visible product.
        # A per-child selection cannot be previewed without its child context.
        child_index = attachment.get("ganged_cabinet_index", attachment.get("ganged_fixed_base_index"))
        if child_index is not None:
            environment = attachment.get("environment") or {}
            children = copy.deepcopy(quote_item.get("ganged_cabinets") or environment.get("ganged_cabinets") or [])
            child_inputs = copy.deepcopy(quote_item.get("ganged_cabinet_inputs") or children)
            if not 0 <= int(child_index) < len(children) or int(child_index) >= len(child_inputs):
                failed(f"第 {int(child_index) + 1} 个子柜尺寸缺失，请重新计算该产品。")
                return
            payload.update(ganged_cabinet_count=len(children), ganged_cabinets=children,
                           ganged_cabinet_inputs=child_inputs)
        url = str(window.base_url() or "").split("/api/", 1)[0].rstrip("/") + "/api/attachments/preview"
        worker = worker_class(url, payload, window)
        active = getattr(window, "_scheme2_attachment_reprice_workers", set())
        active.add(worker)
        window._scheme2_attachment_reprice_workers = active

        def loaded(body):
            rows = body.get("attachments", []) if isinstance(body, dict) else []
            if not rows:
                failed("附件数据库未返回计算结果")
                return
            calculated = merge_cost(attachment, rows[0])
            if calculated.get("status") == "ERROR":
                failed(str(calculated.get("error") or "附件金额计算失败"))
                return
            succeeded(calculated)

        worker.succeeded.connect(loaded)
        worker.failed.connect(failed)

        def finished():
            getattr(window, "_scheme2_attachment_reprice_workers", set()).discard(worker)
            worker.deleteLater()

        worker.finished.connect(finished)
        worker.start()

    window_class.recalculate_draft_attachment = recalculate_draft_attachment

    # ApiWorker handles ordinary requests. The existing ganged worker keeps its
    # child-cabinet flow and commits one aggregate V2 attachment snapshot.
    worker_init = worker_class.__init__
    def init_worker(worker, url, payload, parent=None, *args, **kwargs):
        endpoint = str(url)
        if endpoint.endswith(("/api/quotes/confirm", "/api/quotes/confirm-check")):
            payload = confirmation_payload(payload)
        all_attachments = list(payload.get("attachments", []))
        request_attachments = [row for row in all_attachments if not row.get("custom")]
        if parent is not None:
            parent._v2_custom_attachments = [copy.deepcopy(row) for row in all_attachments if row.get("custom")]
        if str(url).endswith("/api/quotes/calculate-dual") and parent is not None and not ganged(parent) and (payload.get("attachment_contract") == 2 or all_attachments):
            automatic_base = base_height(parent)
            payload = {**payload, "attachment_contract": 2, "attachments": [selected_input(x, automatic_base) for x in request_attachments]}
            parent._v2_request_quote_id = payload.get("quote_id")
            parent._v2_request_environment = json.dumps(environment(parent, payload["attachments"]), sort_keys=True)
        elif str(url).endswith("/api/quotes/calculate-dual") and parent is not None:
            parent._v2_request_environment = None
        worker_init(worker, url, payload, parent, *args, **kwargs)
    worker_class.__init__ = init_worker

    show = window_class.show_result
    def show_result(window, result, *args, **kwargs):
        result = provisionalize_manual_dimension_result(result)
        if getattr(window, "_v2_request_environment", None) and result.get("attachment_contract") != 2:
            window.current_result = None
            window._attachment_v2_line_id = None
            window.risk_label.setText("当前API尚未返回附件V2结果，请更新API后重新计算。")
            return
        if result.get("attachment_contract") == 2 and getattr(window, "_v2_request_environment", None):
            automatic_base = base_height(window)
            latest = json.dumps(environment(window, [selected_input(x, automatic_base) for x in window.attachments if not x.get("custom")]), sort_keys=True)
            if latest != window._v2_request_environment or result.get("quote_id") != window._v2_request_quote_id:
                return
        previous = getattr(window, "current_result", None)
        original_rows = getattr(window, "attachments", [])
        if result.get("attachment_contract") == 2:
            priced_rows = [row for row in original_rows if not row.get("custom")]
            server_rows = result.get("attachments", [])
            merged_rows = [merge_cost(priced_rows[i] if i < len(priced_rows) else {}, row, base_height(window))
                           for i, row in enumerate(server_rows)]
            delta = sum(float(row.get("quick_amount") or 0) - float(server.get("quick_amount") or 0)
                        for row, server in zip(merged_rows, server_rows))
            if delta:
                result = copy.deepcopy(result)
                quick = result.get("quick_quote", result.get("quick"))
                if isinstance(quick, dict):
                    for key in ("attachment_fee", "total_cost"):
                        if quick.get(key) is not None:
                            quick[key] = round(float(quick[key]) + delta, 2)
                result["attachments"] = merged_rows
        window._v2_render_rows = result.get("attachments") if result.get("attachment_contract") == 2 else None
        try:
            rendered = show(window, result, *args, **kwargs)
        finally:
            window._v2_render_rows = None
        if result.get("attachment_contract") == 2 and getattr(window, "current_result", None) is not previous:
            automatic_base = base_height(window)
            priced_rows = [row for row in original_rows if not row.get("custom")]
            window.attachments = [merge_cost(priced_rows[i] if i < len(priced_rows) else {}, row, automatic_base) for i, row in enumerate(result.get("attachments", []))]
            window.attachments.extend(copy.deepcopy(getattr(window, "_v2_custom_attachments", [])))
            window._attachment_v2_line_id = result.get("quote_line_id")
            window._v2_confirmation_inputs = confirmation_inputs(result.get("attachments", []))
            window.update_attachment_view()
            window.refresh_discounted_totals()
        elif result.get("attachment_contract") == 2:
            window.attachments = original_rows
        return rendered
    window_class.show_result = show_result

    refresh = window_class.refresh_discounted_totals
    def refresh_v2(window):
        pending = getattr(window, "_v2_render_rows", None)
        if pending is not None:
            rows = window.attachments
            window.attachments, window._v2_render_rows = pending, None
            try:
                return refresh_v2(window)
            finally:
                window.attachments, window._v2_render_rows = rows, pending
        errors = [row for row in getattr(window, "attachments", []) if row.get("status") == "ERROR"]
        if errors and getattr(window, "current_result", None):
            window.current_result["formula"]["total_cost"] = None
            window.current_result["formula"]["attachment_fee"] = None
            for label in window.formula_labels.values():
                label.setText("—")
            window.formula_labels["attachment"].setText("附件成本错误")
            from quick_discount_rules import quick_discount_breakdown
            quick = window.current_result["quick"]
            value = quick_discount_breakdown(quick, window.attachments, window.quick_discount.value())["discounted_total"] if quick.get("total_cost") is not None else None
            window.quick_labels["total"].setText("—" if value is None else f"{value + window.freight_spin.value():,.2f}")
            window.quick_labels["attachment"].setText(str(quick.get("attachment_fee", "—")))
            return
        return refresh(window)
    window_class.refresh_discounted_totals = refresh_v2

    open_dialog = window_class.open_attachment_dialog
    def open_dialog_v2(window, *args, **kwargs):
        automatic_base = base_height(window)
        before = json.dumps([selected_input(x, automatic_base) for x in window.attachments], sort_keys=True)
        result = open_dialog(window, *args, **kwargs)
        if before != json.dumps([selected_input(x, automatic_base) for x in window.attachments], sort_keys=True):
            window._attachment_v2_line_id = None
            window.current_result = None
            for labels in (window.formula_labels, window.quick_labels):
                labels["total"].setText("—")
            window.risk_label.setText("附件选择已变化，请重新计算整柜报价。")
        return result
    window_class.open_attachment_dialog = open_dialog_v2

    add = window_class.add_current_to_summary
    def add_to_summary(window, *args, **kwargs):
        before = len(window.draft_items)
        line_id = getattr(window, "_attachment_v2_line_id", None)
        frozen_inputs = copy.deepcopy(getattr(window, "_v2_confirmation_inputs", []))
        source_attachments = copy.deepcopy(window.attachments)
        quote_date = window.quote_date.date().toString("yyyy-MM-dd")
        result = add(window, *args, **kwargs)
        if line_id and len(window.draft_items) == before + 1:
            item = window.draft_items[-1]
            item["attachments"] = restore_confirmation_inputs(
                source_attachments, frozen_inputs
            )
            item["attachment_confirmation_inputs"] = copy.deepcopy(frozen_inputs)
            item.update(attachment_contract=2, quote_line_id=line_id, quote_date=quote_date)
        return result
    window_class.add_current_to_summary = add_to_summary
    load_item, reset, update = window_class.load_draft_item, window_class.reset_current_cabinet, window_class.update_attachment_view
    def load_item_v2(window, item):
        window._attachment_v2_restoring = True
        try:
            if item.get("attachment_contract") == 2 and item.get("quote_date"):
                window.quote_date.setDate(QDate.fromString(item["quote_date"], "yyyy-MM-dd"))
            result = load_item(window, item)
            window._attachment_v2_line_id = item.get("quote_line_id")
            frozen = item.get("attachment_confirmation_inputs")
            window._v2_confirmation_inputs = copy.deepcopy(frozen) if isinstance(frozen, list) else confirmation_inputs(item.get("attachments", []))
            return result
        finally:
            window._attachment_v2_restoring = False
    def reset_v2(window, *args, **kwargs):
        window._attachment_v2_line_id = None
        window._v2_confirmation_inputs = []
        return reset(window, *args, **kwargs)
    def update_v2(window):
        result = update(window)
        for i, item in enumerate(getattr(window, "attachments", [])):
            cell = window.attachment_list.item(i)
            if cell and item.get("status"):
                cell.setText(cell.text() + f" · 快速 {item.get('quick_amount', '—')} · 公式 {item.get('formula_amount') if item.get('formula_amount') is not None else item.get('status_text', '—')}")
                cell.setToolTip("辅材清单：\n" + str(item.get("auxiliary_list") or ""))
        return result
    window_class.load_draft_item, window_class.reset_current_cabinet, window_class.update_attachment_view = load_item_v2, reset_v2, update_v2

    window_init = window_class.__init__
    def init_window(window, *args, **kwargs):
        window_init(window, *args, **kwargs)
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.setInterval(PREVIEW_DELAY_MS)
        window._v2_environment_timer = timer
        def changed(*_):
            if getattr(window, "_attachment_v2_restoring", False) or not any(row.get("catalog_version") for row in getattr(window, "attachments", [])):
                return
            window._attachment_v2_line_id = None
            window.current_result = None
            window.risk_label.setText("附件环境已变化，正在重新计算成本；整柜报价请重新计算。")
            for labels in (window.formula_labels, window.quick_labels):
                labels["total"].setText("—")
            timer.start()
        def recalculate():
            rows = getattr(window, "attachments", [])
            if not any(row.get("catalog_version") for row in rows):
                return
            old = getattr(window, "_v2_environment_worker", None)
            if old and old.isRunning():
                timer.start()
                return
            automatic_base = base_height(window)
            payload = environment(window, [selected_input(x, automatic_base) for x in rows])
            signature = json.dumps(payload, sort_keys=True)
            worker = worker_class(window.base_url() + "/api/attachments/preview", payload, window)
            window._v2_environment_worker = worker
            def received(body):
                if not isValid(window):
                    return
                now = environment(window, [selected_input(x, base_height(window)) for x in window.attachments])
                if json.dumps(now, sort_keys=True) != signature:
                    return
                window.attachments = [merge_cost(rows[i], cost, base_height(window)) for i, cost in enumerate(body.get("attachments", []))]
                window.update_attachment_view()
                window.risk_label.setText("；".join(x.get("error", "") for x in body.get("errors", [])) or "附件成本已更新；请重新计算整柜报价。")
            worker.succeeded.connect(received)
            worker.failed.connect(lambda text: window.risk_label.setText(f"附件重新计算失败：{text}") if isValid(window) else None)
            def finished():
                if isValid(window) and getattr(window, "_v2_environment_worker", None) is worker:
                    window._v2_environment_worker = None
                worker.deleteLater()
            worker.finished.connect(finished)
            worker.start()
        timer.timeout.connect(recalculate)
        for name, signal in (("product_combo", "currentIndexChanged"), ("variant_combo", "currentIndexChanged"), ("single_door_combo", "currentIndexChanged"), ("double_door_combo", "currentIndexChanged"), ("material_combo", "currentIndexChanged"), ("coating_combo", "currentIndexChanged"), ("width_spin", "valueChanged"), ("height_spin", "valueChanged"), ("depth_spin", "valueChanged"), ("quote_date", "dateChanged"), ("model_edit", "textChanged")):
            control = getattr(window, name, None)
            if control is not None:
                getattr(control, signal).connect(changed)
    window_class.__init__ = init_window
