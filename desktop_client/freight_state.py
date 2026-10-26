"""Per-set self-made weight freight; manual and legacy amounts remain explicit."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def money(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value < 0:
            return Decimal('0.00')
        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0.00')


def billable_weight(result):
    """Only the accepted server material result, including all ganged children."""
    if not isinstance(result, dict):
        return None
    children = result.get('ganged_cabinet_results')
    if children:
        values = [billable_weight(child) for child in children]
        return sum(values, Decimal(0)) if all(v is not None for v in values) else None
    raw = (result.get('formula_cost') or {}).get('corrected_material_weight_kg')
    try:
        value = Decimal(str(raw))
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


AUTO_FREIGHT_BASIS = 'self_made_weight_v1'
JP_AUXILIARY_WEIGHT_BASIS = 'jp_auxiliary_frame_weight_v1'


def _finite(value, default=Decimal(0)):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else default
    except (InvalidOperation, ValueError, TypeError):
        return default


def self_made_weight(item):
    """One set: cabinet billable + JP BOM frame + completed attachment weights.

    Child counts, order quantity and cabinet waste are already represented by
    the accepted cabinet/attachment results; never apply them a second time.
    """
    if not isinstance(item, dict):
        return Decimal(0)
    formula = item.get('formula')
    if not isinstance(formula, dict): formula = item.get('formula_cost')
    if not isinstance(formula, dict): formula = {}
    cabinet = _finite(formula.get('corrected_material_weight_kg'))
    if formula.get('corrected_material_weight_kg') is None and item.get('ganged_cabinet_results'):
        cabinet = billable_weight(item) or Decimal(0)
    total = max(Decimal(0), cabinet) + jp_auxiliary_weight(item)
    for row in item.get('attachments') or []:
        if (not isinstance(row, dict) or row.get('status') in ('ERROR', 'PENDING_MANUAL')
                or row.get('pending_manual_dimensions')):
            continue
        weight, quantity = _finite(row.get('weight_kg')), _finite(row.get('quantity', 1), None)
        if weight < 0 or quantity is None:
            continue
        sign = -1 if quantity < 0 or _finite(row.get('attachment_price_sign', 1), Decimal(1)) == -1 else 1
        total += weight * abs(quantity) * sign
    return max(Decimal(0), total)


def jp_auxiliary_weight(item):
    """Accepted JP BOM weight already includes its 1.2; no extra multipliers."""
    if not isinstance(item, dict): return Decimal(0)
    formula = item.get('formula') or item.get('formula_cost') or {}
    if not isinstance(formula, dict): return Decimal(0)
    if formula.get('cabinet_auxiliary_weight_basis') == JP_AUXILIARY_WEIGHT_BASIS:
        return max(Decimal(0), _finite(formula.get('cabinet_auxiliary_self_made_weight_kg')))
    children = formula.get('ganged_cabinet_costs')
    if not isinstance(children, list) or not children:
        children = item.get('ganged_cabinet_results')
    return sum((jp_auxiliary_weight(child) for child in children or [] if isinstance(child, dict)), Decimal(0))


def automatic_item_freight(item):
    return isinstance(item, dict) and item.get('freight_mode') == 'AUTO' and item.get('freight_basis') == AUTO_FREIGHT_BASIS


def sync_item_freight(item):
    """Only explicitly opted-in editable rows follow weight; legacy quotes stay put."""
    if not automatic_item_freight(item):
        return False
    value = float(money(self_made_weight(item)))
    if item.get('freight_fee') != value:
        item['freight_fee'] = value
        if 'freight' in item:
            item['freight'] = value
        item.pop('cost_detail_rows', None)
        item.pop('quote_display', None)
        return True
    return False


@dataclass
class FreightState:
    mode: str = 'AUTO'
    weight: Decimal | None = None
    value: Decimal = Decimal('0.00')

    def update_weight(self, weight):
        self.weight = weight
        if self.mode == 'AUTO':
            self.value = money(weight)

    def manual(self, value):
        self.mode, self.value = 'MANUAL', money(value)

    def automatic(self):
        self.mode = 'AUTO'
        self.update_weight(self.weight)

    def reset(self):
        self.mode, self.weight, self.value = 'AUTO', None, Decimal('0.00')
