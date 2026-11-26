"""User-defined quote expense; classified cost columns are its deduction base."""
import math
from attachment_cost_allocation import with_cost_allocation
from quick_discount_rules import money, money_sum, money_product, MANAGEMENT_COST_KEYS, MANUFACTURING_COST_BASIS

TAX_COST_BASIS = 'quoted_less_display_costs_15pct_v1'
DEDUCTION_KEYS = ('material_cost', 'auxiliary_cost', 'attachment_fee', 'spray_cost')


class TaxCostError(ValueError):
    def __init__(self, message, code='MISSING_COSTS'):
        super().__init__(message)
        self.code = code


def has_tax_cost(item):
    return item.get('tax_cost_basis') == TAX_COST_BASIS or (item.get('formula') or {}).get('tax_cost_basis') == TAX_COST_BASIS


def with_tax_cost(formula, attachments, quoted_unit_price, cost_freight):
    result = with_cost_allocation(formula, attachments)
    allocation = result.get('cost_allocation')
    if allocation and not allocation.get('complete'):
        raise TaxCostError('税费所需附件成本分项尚未完整，请重新计算')
    costs = allocation['totals'] if allocation else result
    inputs = {'quoted_unit_price': quoted_unit_price, **{key: costs.get(key) for key in DEDUCTION_KEYS}, 'freight_fee': cost_freight}
    try:
        valid = all(value not in (None, '') and not isinstance(value, bool) and math.isfinite(float(value)) for value in inputs.values())
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise TaxCostError('税费计算所需报价或成本尚未完整，请重新计算')
    deductions = money_sum([*(inputs[key] for key in DEDUCTION_KEYS), cost_freight])
    base = money_sum((quoted_unit_price, -deductions))
    result.update(tax_cost=money_product(base, .15), tax_cost_basis=TAX_COST_BASIS,
                  tax_cost_base=base, tax_cost_rate=.15, tax_cost_inputs={key: money(value) for key, value in inputs.items()})
    result.pop('tax_cost_error', None)
    result.pop('tax_cost_error_code', None)
    if base < 0:
        result['tax_cost_notice'] = f'税费基数为 {base:.2f} 元，按原公式计算税费 {result["tax_cost"]:.2f} 元；报价和折扣未调整。'
    else:
        result.pop('tax_cost_notice', None)
    manufacturing = result.get('manufacturing_cost') if result.get('manufacturing_cost_basis') == MANUFACTURING_COST_BASIS else 0
    result['total_cost'] = money_sum([*(result[key] for key in MANAGEMENT_COST_KEYS), manufacturing, result['management_fee'], result['tax_cost']])
    return with_cost_allocation(result, attachments)
