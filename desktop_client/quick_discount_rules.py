"""Selective discount rules for quick quotations.

Stored database prices and attachment line prices remain unchanged.  Only the
displayed/exported quick-quote total applies the selected factor to the cabinet
body and the approved attachment categories.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping
import math
from decimal import Decimal, ROUND_HALF_UP

PRICING_BASIS = "per_unit_set_v1"
MANAGEMENT_FEE_RATE = 0.06
MANAGEMENT_FEE_BASIS = "pre_management_cost_with_freight_v1"


def money(value=0):
    number = Decimal(str(value if value not in (None, "") else 0))
    if not number.is_finite():
        raise ValueError("金额必须为有效数值")
    return float(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money_sum(values):
    return money(sum((Decimal(str(money(value))) for value in values), Decimal(0)))


def money_product(*values):
    result = Decimal(1)
    for value in values:
        result *= Decimal(str(value))
    return money(result)


def apply_management_fee(quote, freight_fee=0):
    """Six percent of current pre-management costs plus per-cabinet freight.

    total_cost continues to exclude freight itself, avoiding a second addition
    by the existing quotation/quantity rules. Keep unlisted historical costs.
    """
    def finite(value):
        try:
            return value not in (None, "") and math.isfinite(float(value))
        except (TypeError, ValueError):
            return False
    result = dict(quote)
    result.update(management_fee_rate=MANAGEMENT_FEE_RATE, management_fee_basis=MANAGEMENT_FEE_BASIS)
    keys = ("material_cost", "auxiliary_cost", "labor_cost", "attachment_fee", "spray_cost")
    if all(finite(quote.get(key)) for key in keys):
        base = money_sum(quote[key] for key in keys)
    elif finite(quote.get("total_cost")):
        base = money_sum((quote["total_cost"], -float(quote.get("management_fee") or 0)))
    else:
        result.update(management_fee_base=None, management_fee=None, total_cost=None)
        return result
    freight = max(0, float(freight_fee)) if finite(freight_fee) else 0
    result["management_fee_base"] = money_sum((base, freight))
    result["management_fee"] = money_product(result["management_fee_base"], MANAGEMENT_FEE_RATE)
    result["total_cost"] = money_sum((base, result["management_fee"]))
    return result


ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES = ("侧板", "门变形", "风机滤网")
GANGED_FIXED_BASE_MATCH_KEY = "ganged_fixed_base_match"


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _top_level_category(item: Mapping[str, Any] | None) -> str:
    item = item or {}
    for key in ("category_level1", "attachment_category", "category"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def quick_discount_category(item: Mapping[str, Any] | None) -> str | None:
    item = item or {}
    if _top_level_category(item) == "其他附件":
        return None
    candidates = [
        item.get("category_level3"),
        item.get("category_level2"),
        item.get("category_level1"),
        item.get("attachment_category"),
        item.get("category"),
        item.get("item_name"),
        item.get("model_code"),
    ]
    combined = " ".join(str(value).strip() for value in candidates if value)
    if any(str(value).strip() == "填充安装板" for value in candidates if value):
        return None
    if "安装板单发" in combined:
        return None
    if "JK安装板" in combined.upper().replace(" ", ""):
        return "JK安装板"
    for category in (
        "无孔承板", "有孔承板", "通风顶罩", "防雨顶", "分段板",
        "玻璃门", "内门", "底座", "侧板",
    ):
        if category in combined:
            return category
    if "安装板" in combined or "填充板" in combined:
        return "安装板"
    return None


def attachment_excluded_from_discount(item: Mapping[str, Any] | None) -> bool:
    """Return whether an attachment stays at original price in both methods."""

    item = item or {}
    if _top_level_category(item) == "其他附件":
        return True
    candidates = (
        item.get("category_level3"), item.get("category_level2"),
        item.get("category_level1"), item.get("attachment_category"),
        item.get("category"), item.get("item_name"), item.get("model_code"),
    )
    return any(str(value).strip() in ("门安装条", "填充安装板") for value in candidates if value)


def formula_attachment_excluded(item: Mapping[str, Any] | None) -> bool:
    """Return whether an attachment is omitted only from formula quotations.

    门变形 is a closed first-level catalogue in the attachment database.  Use
    that authoritative classification exactly; names and lower-level labels
    are deliberately not fuzzy-matched.
    """

    if (item or {}).get("catalog_version"):
        return item.get("status") == "QUICK_ONLY"
    return _top_level_category(item) == "门变形"


def formula_attachment_line_amount(item):
    if (item or {}).get("custom") is True:
        if item.get("formula_amount") is None:
            raise ValueError("人工新增附件公式成本未完成，不能汇总")
        return float(item["formula_amount"])
    if (item or {}).get("catalog_version"):
        if item.get("status") == "QUICK_ONLY":
            return 0.0
        if item.get("status") == "ERROR" or item.get("formula_amount") is None:
            raise ValueError("附件公式成本未完成，不能汇总")
        return float(item["formula_amount"])
    if (item or {}).get("formula_amount") is not None:
        return float(item["formula_amount"])
    return quick_attachment_line_amount(item)


def effective_formula_attachment_line_amount(item, cabinet_quantity, ganged_cabinet_count=1):
    selected = _number((item or {}).get("quantity"), 1.0)
    return formula_attachment_line_amount(item) * effective_attachment_quantity(item, cabinet_quantity, ganged_cabinet_count) / selected


def quick_attachment_line_amount(item: Mapping[str, Any] | None) -> float:
    item = item or {}
    if item.get("pending_manual_dimensions"):
        return 0.0
    override = item.get("quick_amount_override")
    edited = item.get("custom_amount_edited") is True or (
        "custom_amount_edited" not in item and override not in (None, 0))
    if edited and override is not None:
        return money(override)
    if item.get("quick_amount") is not None:
        return money(item["quick_amount"])
    sign = -1.0 if _number(item.get("attachment_price_sign"), 1.0) == -1.0 else 1.0
    for key in ("total_price", "total_cost", "amount", "subtotal"):
        if item.get(key) is not None:
            try:
                return money_product(abs(float(item[key])), sign)
            except (TypeError, ValueError):
                pass
    unit_price = 0.0
    for key in ("unit_price_override", "matched_price", "unit_price", "price"):
        if item.get(key) is not None:
            try:
                unit_price = float(item[key])
                break
            except (TypeError, ValueError):
                pass
    return money_product(abs(unit_price), _number(item.get("quantity"), 1.0), sign)


def attachment_uses_cabinet_quantity(item: Mapping[str, Any] | None) -> bool:
    item = item or {}
    candidates = [
        item.get("category_level3"), item.get("category_level2"),
        item.get("category_level1"), item.get("attachment_category"),
        item.get("category"), item.get("item_name"), item.get("model_code"),
    ]
    combined = " ".join(str(value).strip() for value in candidates if value)
    if "风机" in combined or "滤网" in combined:
        return False
    return not any(category in combined for category in ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES)


def _manually_quantified_attachment(item: Mapping[str, Any]) -> bool:
    source = str(item.get("selection_source") or "").strip().lower()
    return bool(
        item.get("cost_quantity_manual")
        or item.get("custom")
        or source in {"manual", "quote_local"}
    )


def effective_attachment_quantity(
    item: Mapping[str, Any] | None,
    cabinet_quantity: Any,
    ganged_cabinet_count: Any = 1,
) -> float:
    item = item or {}
    selected = _number(item.get("quantity"), 1.0)
    cabinets = _number(cabinet_quantity, 1.0)
    # Every selected row already belongs to one complete cabinet/ganged set.
    # Only the order quantity expands it; manual selection is not a child multiplier.
    # Attachment rows stored on a quote are per-cabinet values.  The order
    # quantity must therefore scale every ordinary row, including fans,
    # side panels and door transformations.  Those categories used to be
    # treated as already complete-set quantities, which made two identical
    # cabinet lines with quantities 1 and 10 produce different unit prices.
    # Ganged child rows are already expanded by child index; they still use
    # the complete-set quantity branch above.
    return selected * cabinets


def effective_attachment_line_amount(
    item: Mapping[str, Any] | None,
    cabinet_quantity: Any,
    ganged_cabinet_count: Any = 1,
) -> float:
    item = item or {}
    selected = _number(item.get("quantity"), 1.0) or 1.0
    return quick_attachment_line_amount(item) * effective_attachment_quantity(
        item, cabinet_quantity, ganged_cabinet_count
    ) / selected


def quick_discount_breakdown(
    quote: Mapping[str, Any] | None,
    attachments: Iterable[Mapping[str, Any]] | None,
    discount: Any,
) -> dict[str, float]:
    quote = quote or {}
    rows = list(attachments or [])
    raw_total = money(quote.get("total_cost"))
    listed_attachment_total = money_sum(quick_attachment_line_amount(item) for item in rows)
    # The attachment editor is the source of truth for the current draft.
    # Keep the API fee only long enough to recover the cabinet base when an
    # old snapshot still contains a different aggregate attachment fee.
    stored_attachment_fee = (
        _number(quote.get("attachment_fee"))
        if quote.get("attachment_fee") is not None
        else listed_attachment_total
    )
    attachment_fee = listed_attachment_total
    base_price = (
        _number(quote.get("base_price"))
        if quote.get("base_price") is not None
        else raw_total - stored_attachment_fee
    )
    base_price = money(base_price)
    listed_eligible = money_sum(
        quick_attachment_line_amount(item)
        for item in rows
        if quick_discount_category(item)
    )
    eligible_attachment_total = listed_eligible
    original_price_attachment_total = money_sum((attachment_fee, -eligible_attachment_total))
    factor = _number(discount, 1.0)
    discounted_total = money_sum((money_product(money_sum((base_price, eligible_attachment_total)), factor),
                                  original_price_attachment_total))
    return {
        "raw_total": raw_total,
        "base_price": base_price,
        "attachment_fee": attachment_fee,
        "listed_attachment_total": listed_attachment_total,
        "eligible_attachment_total": eligible_attachment_total,
        "original_price_attachment_total": original_price_attachment_total,
        "discount": factor,
        "discounted_total": discounted_total,
    }


def quick_order_line_breakdown(
    quote: Mapping[str, Any] | None,
    attachments: Iterable[Mapping[str, Any]] | None,
    discount: Any,
    cabinet_quantity: Any,
    ganged_cabinet_count: Any = 1,
    freight_fee: Any = 0,
    material_difference: Any = 0,
) -> dict[str, float]:
    rows = list(attachments or [])
    unit = quick_discount_breakdown(quote, rows, discount)
    cabinets = _number(cabinet_quantity, 1.0)
    split_count = _number(ganged_cabinet_count, 1.0)
    eligible_total = sum(
        effective_attachment_line_amount(item, cabinets, split_count)
        for item in rows if quick_discount_category(item)
    )
    original_total = sum(
        effective_attachment_line_amount(item, cabinets, split_count)
        for item in rows if not quick_discount_category(item)
    )
    # There is no second, hidden attachment bucket: all current attachment
    # money comes from the rows displayed in the editor.
    unlisted_difference = 0.0
    original_total += unlisted_difference * cabinets
    factor = _number(discount, 1.0)
    unit_freight = money(max(0.0, _number(freight_fee, 0.0)))
    freight_total = money_product(unit_freight, cabinets)
    unit_total = money_sum((unit["discounted_total"], unit_freight, material_difference))
    line_total = money_product(unit_total, cabinets)
    return {
        **unit,
        "cabinet_quantity": cabinets,
        "ganged_cabinet_count": split_count,
        "eligible_attachment_total": eligible_total,
        "original_price_attachment_total": original_total,
        "unlisted_difference": unlisted_difference,
        "freight_fee": unit_freight,
        "freight_total": freight_total,
        "line_total": line_total,
        "equivalent_unit_total": unit_total,
    }
