"""Client-only freight policy; never substitutes an estimated material weight."""
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
