"""Manufacturing expense is four percent of the displayed quoted unit price."""
import math
from quick_discount_rules import money_product, missing_management_costs, apply_management_fee, MANUFACTURING_COST_BASIS

MANUFACTURING_RATE = 0.04
MANUFACTURING_BASIS = MANUFACTURING_COST_BASIS


def manufacturing_unit_cost(quoted_unit_price):
    if isinstance(quoted_unit_price, bool) or quoted_unit_price in (None, ''):
        raise ValueError('制造成本需要有效的单台／单套报价')
    value = float(quoted_unit_price)
    if not math.isfinite(value) or value < 0:
        raise ValueError('制造成本需要有效的非负报价')
    return money_product(value, MANUFACTURING_RATE)


def manufacturing_cost_snapshot(formula, quoted_unit_price, freight_fee, *, include_in_management=False):
    """Confirmed policy: manufacturing 4%, management 5%, both of quote."""
    if include_in_management is not False:
        raise ValueError('制造成本不计入管理费基数')
    if missing_management_costs(formula):
        raise ValueError('原始生产成本尚未完整')
    manufacturing = manufacturing_unit_cost(quoted_unit_price)
    return apply_management_fee({**formula, 'manufacturing_cost': manufacturing, 'manufacturing_cost_basis': MANUFACTURING_BASIS,
            'manufacturing_quote_unit_price': float(quoted_unit_price), 'manufacturing_in_management': include_in_management,
            },freight_fee)


def has_manufacturing_cost(item):
    return (item.get('manufacturing_cost_basis')==MANUFACTURING_BASIS
            or (item.get('formula') or {}).get('manufacturing_cost_basis')==MANUFACTURING_BASIS)
