"""Keep support-plate manufacturing costs independent of sales model choices."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math

from attachment_category_browser import SUPPORT_PLATE_DEFAULT_MODELS
from material_prices import material_unit_price
from quick_discount_rules import money_product

COST_SNAPSHOT = "support_plate_cost_snapshot"
MODEL_ONLY = "support_plate_model_only"
COST_FIELDS = (
    "formula_amount", "formula_unit_cost", "weight_kg", "material_cost", "spray_area_m2",
    "spray_cost", "auxiliary_cost", "auxiliary_list", "labor_cost", "rule_id", "rule_version",
    "rule_materials", "rule_source_row", "formulas", "calculation_notes", "required_parameters",
    "status", "status_text", "cost_method",
)


def is_support_plate(row):
    return (not row.get("custom") and row.get("category_level1") == "控制柜附件"
            and row.get("item_name") in SUPPORT_PLATE_DEFAULT_MODELS)


def _normalized(value):
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    if value is None or isinstance(value, bool):
        return value
    try:
        number = Decimal(str(value))
        if number.is_finite():
            return str(number.normalize())
    except (InvalidOperation, ValueError):
        pass
    return value


def cost_context(item, row, defaults=None):
    """Inputs to manufacturing cost; deliberately exclude model and sale price."""
    settings = item.get("scheme2_cost_settings") or defaults or {}
    environment = row.get("environment") or {}
    context = {key: item.get(key) if item.get(key) is not None else environment.get(key) for key in (
        "product_code", "material_code", "width_mm", "height_mm", "depth_mm", "coating_type",
        "cabinet_body_thickness_mm", "quote_date", "ganged_cabinets", "ganged_cabinet_inputs",
    )}
    context.update(
        item_name=row.get("item_name"), quantity=row.get("quantity", 1),
        manual_inputs=deepcopy(row.get("manual_inputs") or {}),
        child_index=row.get("ganged_cabinet_index", row.get("ganged_fixed_base_index")),
        price_sign=row.get("attachment_price_sign", 1),
        waste_factor=settings.get("waste_factor", item.get("waste_factor")),
        material_price=material_unit_price(settings, item.get("material_code")),
        galvanized_price=settings.get("galvanized_price"),
        surface_price=settings.get("surface_price"),
    )
    return _normalized(context)


def _calculated_context(item, row, defaults):
    context = cost_context(item, row, defaults)
    environment = row.get("environment") or {}
    # On first opening a legacy order, use its actual calculation inputs,
    # not newer sidebar settings, to decide whether a full reprice is needed.
    for key in ("product_code", "material_code", "width_mm", "height_mm", "depth_mm", "coating_type",
                "cabinet_body_thickness_mm", "quote_date", "waste_factor"):
        if environment.get(key) is not None:
            context[key] = _normalized(environment[key])
    if environment.get("material_unit_price") is not None:
        context["material_price"] = _normalized(environment["material_unit_price"])
    return context


def cost_ready(row):
    if not is_support_plate(row) or row.get("status") in ("ERROR", "PENDING_MANUAL", "QUICK_ONLY"):
        return False
    if row.get("pending_manual_dimensions") or row.get("error"):
        return False
    try:
        values = [float((row.get("manual_inputs") or {}).get(key))
                  for key in ("孔承板高度", "孔承板宽度")]
        amount = float(row["formula_amount"])
        return all(math.isfinite(value) and value > 0 for value in values) and math.isfinite(amount) and amount >= 0
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def remember_cost(row, item, defaults=None):
    result = deepcopy(row)
    result.pop(MODEL_ONLY, None)
    result.pop(COST_SNAPSHOT, None)
    if cost_ready(result):
        result[COST_SNAPSHOT] = {
            "context": _calculated_context(item, result, defaults),
            "fields": {key: deepcopy(result[key]) for key in COST_FIELDS if key in result},
        }
    return result


def prepare_model_change(row, item, defaults=None):
    result = deepcopy(row)
    if is_support_plate(result):
        # Legacy completed rows acquire a baseline once; an existing baseline
        # must not be silently moved to changed dimensions/material settings.
        if COST_SNAPSHOT not in result:
            result = remember_cost(result, item, defaults)
        result[MODEL_ONLY] = True
    return result


def reusable_cost(row, item, defaults=None):
    snapshot = row.get(COST_SNAPSHOT)
    return (cost_ready(row) and isinstance(snapshot, dict)
            and snapshot.get("context") == cost_context(item, row, defaults)
            and isinstance(snapshot.get("fields"), dict))


def model_price_result(source, catalog, item, defaults=None, version=None):
    """A catalogue lookup changes the sales fields, never confirmed cost fields."""
    if not source.get(MODEL_ONLY) or not reusable_cost(source, item, defaults):
        return None
    if (not is_support_plate(catalog) or catalog.get("item_name") != source.get("item_name")
            or str(catalog.get("model_code") or "").strip().upper()
            != str(source.get("model_code") or "").strip().upper()):
        raise ValueError("承板型号与目录返回结果不一致")
    try:
        price = float(catalog.get("price", catalog.get("face_price")))
        if not math.isfinite(price) or price < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError("承板型号的目录价格无效") from None
    result = deepcopy(source)
    for key in ("attachment_price_id", "model_code", "unit", "color", "source_file", "source_sheet", "source_row_no"):
        if key in catalog:
            result[key] = deepcopy(catalog[key])
    for key in ("unit_price_override", "quick_amount_override", MODEL_ONLY):
        result.pop(key, None)
    result.update(catalog_version=version, price=price, face_price=price, matched_price=price,
                  catalogue_face_price=price, quick_face_price=price, custom_amount_edited=False)
    if not result.get("status"):
        result.update(status="CALCULATED", status_text="已计算")
    result["quick_amount"] = result["catalogue_quick_amount"] = money_product(
        price, result.get("quantity", 1), result.get("attachment_price_sign", 1))
    return result


def merge_snapshot_cost(source, calculated, item, defaults=None):
    """Keep the same manufacturing snapshot across explicit server-line repair."""
    if not is_support_plate(source):
        return calculated
    if (not reusable_cost(source, item, defaults)
            or cost_context(item, calculated, defaults) != source[COST_SNAPSHOT]["context"]):
        return remember_cost(calculated, item, defaults)
    result = deepcopy(calculated)
    for key in COST_FIELDS:
        result.pop(key, None)
    result.update(deepcopy(source[COST_SNAPSHOT]["fields"]))
    result[COST_SNAPSHOT] = deepcopy(source[COST_SNAPSHOT])
    result.pop(MODEL_ONLY, None)
    return result
