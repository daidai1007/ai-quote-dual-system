"""Undiscounted surcharge from the two server-produced cabinet cost weights."""
from decimal import Decimal, ROUND_HALF_UP
import math

BASIS = 'cabinet_cost_weight_vs_1_5_v1'
DEFAULT_COEFFICIENT = 10.0


def _finite(value):
    try:
        return value not in (None, '') and not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def coefficient(item):
    state = item.get('scheme2_cost_settings') or {}
    value = item.get('thickness_surcharge_coefficient', state.get('thickness_surcharge_coefficient', DEFAULT_COEFFICIENT))
    if not _finite(value) or float(value) < 0:
        raise ValueError('料厚补价系数必须为有效的非负金额')
    return float(value)


def weight_difference(item):
    if item.get('item_type') == 'standalone_attachment':
        return 0.0
    comparison = (item.get('formula') or {}).get('thickness_comparison') or {}
    if comparison.get('basis') != BASIS:
        return 0.0
    requested = item.get('waste_factor', (item.get('scheme2_cost_settings') or {}).get('waste_factor'))
    def weight(row):
        original = row.get('waste_factor')
        target = requested if requested is not None else original
        left, right = row.get('selected_cost_weight_kg'), row.get('reference_cost_weight_kg')
        if not all(_finite(v) for v in (original, target, left, right)) or float(original) <= 0 or float(target) <= 0:
            raise ValueError('料厚差价的计价重量或废料系数无效，请重新计算')
        value = (Decimal(str(left)) - Decimal(str(right))) * Decimal(str(target)) / Decimal(str(original))
        if value < 0:
            raise ValueError('料厚差价的重量差不能为负数')
        return value.quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP)
    rows = comparison.get('children')
    value = sum((weight(row) for row in rows), Decimal(0)) if isinstance(rows, list) else weight(comparison)
    return float(value)


def amount(item):
    value = weight_difference(item)
    if not value:
        return 0.0
    return float((Decimal(str(value)) * Decimal(str(coefficient(item)))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def explanation(item):
    value = weight_difference(item)
    return f'料厚差价：成本计价重量差 {value:g} kg × 系数 {coefficient(item):g} = {amount(item):,.2f} 元，不参与折扣。'
