"""Display profit ratios without changing quotation or cost ledgers."""
import math
from quick_discount_rules import money_sum, money_product

PRODUCTION_KEYS = ('material_cost', 'auxiliary_cost', 'labor_cost', 'attachment_fee', 'spray_cost')
GROSS_MARGIN_BASIS = 'production_plus_cost_freight_v1'
GROSS_TOOLTIP = '毛利率＝（报价总价－生产成本总额－成本运费总额）÷报价总价；生产成本含材料、辅材、制造、人工、附件和喷涂，毛利率另扣成本运费，不扣管理费和税费。'
NET_TOOLTIP = '净利率＝（报价总价－生产成本总额－管理费总额－税费总额－运费总额）÷报价总价；按本程序已记录费用计算。'


def production_total(formula, quantity=1):
    # Use the original ledger. Classified attachment components must not be
    # added to this ledger again through cost_allocation.totals.
    values = [formula.get(key) for key in PRODUCTION_KEYS]
    if formula.get('manufacturing_cost_basis')=='quoted_unit_4pct_v1':
        values.append(formula.get('manufacturing_cost'))
    try:
        if any(value in (None, '') or not math.isfinite(float(value)) for value in values):
            return None
        return money_product(money_sum(values), quantity)
    except (TypeError, ValueError, OverflowError):
        return None


def rate(revenue, cost):
    try:
        if cost is None or not math.isfinite(float(revenue)) or not math.isfinite(float(cost)) or revenue <= 0:
            return None
        return (revenue - cost) / revenue
    except (TypeError, ValueError):
        return None


def percentage(value):
    return '—' if value is None else f'{value:.2%}'
