"""Selective discount rules for quick quotations.

Stored database prices and attachment line prices remain unchanged.  Only the
displayed/exported quick-quote total applies the selected factor to the cabinet
body and the approved attachment categories.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


QUICK_DISCOUNT_ATTACHMENT_CATEGORIES = (
    "底座",
    "侧板",
    "安装板",
    "内门",
    "玻璃门",
    "通风顶罩",
    "防雨顶",
    "分段板",
    "JK安装板",
)


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
    for key in ("total_price", "total_cost", "amount", "subtotal"):
        if item.get(key) is not None:
            try:
                return float(item[key])
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
    return unit_price * _number(item.get("quantity"), 1.0)


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
