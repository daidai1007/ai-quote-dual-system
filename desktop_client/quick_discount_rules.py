"""Selective discount rules for quick quotations.

Stored database prices and attachment line prices remain unchanged.  Only the
displayed/exported quick-quote total applies the selected factor to the cabinet
body and the approved attachment categories.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES = ("侧板", "门变形", "风机滤网")
GANGED_FIXED_BASE_MATCH_KEY = "ganged_fixed_base_match"


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def quick_discount_category(item: Mapping[str, Any] | None) -> str | None:
    item = item or {}
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
    if "安装板单发" in combined:
        return None
    if "JK安装板" in combined.upper().replace(" ", ""):
        return "JK安装板"
    for category in ("通风顶罩", "防雨顶", "分段板", "玻璃门", "内门", "底座", "侧板"):
        if category in combined:
            return category
    if "安装板" in combined or "填充板" in combined:
        return "安装板"
    return None


def quick_attachment_line_amount(item: Mapping[str, Any] | None) -> float:
    item = item or {}
    sign = -1.0 if _number(item.get("attachment_price_sign"), 1.0) == -1.0 else 1.0
    for key in ("total_price", "total_cost", "amount", "subtotal"):
        if item.get(key) is not None:
            try:
                return abs(float(item[key])) * sign
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
    return abs(unit_price) * _number(item.get("quantity"), 1.0) * sign


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


def effective_attachment_quantity(
    item: Mapping[str, Any] | None,
    cabinet_quantity: Any,
    ganged_cabinet_count: Any = 1,
) -> float:
    item = item or {}
    selected = _number(item.get("quantity"), 1.0)
    cabinets = _number(cabinet_quantity, 1.0)
    split_count = _number(ganged_cabinet_count, 1.0)
    # A selected quantity in a ganged quote is the quantity for one complete
    # ganged set.  Automatic limiter/reinforcement rows already contain the
    # sum required by all child cabinets, while fixed bases are separate rows.
    if split_count > 1:
        return selected * cabinets
    if not attachment_uses_cabinet_quantity(item):
        return selected
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
    raw_total = _number(quote.get("total_cost"))
    listed_attachment_total = sum(quick_attachment_line_amount(item) for item in rows)
    attachment_fee = (
        _number(quote.get("attachment_fee"))
        if quote.get("attachment_fee") is not None
        else listed_attachment_total
    )
    base_price = (
        _number(quote.get("base_price"))
        if quote.get("base_price") is not None
        else raw_total - attachment_fee
    )
    listed_eligible = sum(
        quick_attachment_line_amount(item)
        for item in rows
        if quick_discount_category(item)
    )
    eligible_attachment_total = listed_eligible
    original_price_attachment_total = attachment_fee - eligible_attachment_total
    factor = _number(discount, 1.0)
    discounted_total = (
        (base_price + eligible_attachment_total) * factor
        + original_price_attachment_total
    )
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
    unlisted_difference = unit["attachment_fee"] - unit["listed_attachment_total"]
    original_total += unlisted_difference * cabinets
    factor = _number(discount, 1.0)
    line_total = (unit["base_price"] * cabinets + eligible_total) * factor + original_total
    return {
        **unit,
        "cabinet_quantity": cabinets,
        "ganged_cabinet_count": split_count,
        "eligible_attachment_total": eligible_total,
        "original_price_attachment_total": original_total,
        "unlisted_difference": unlisted_difference,
        "line_total": line_total,
        "equivalent_unit_total": line_total / cabinets if cabinets else line_total,
    }
