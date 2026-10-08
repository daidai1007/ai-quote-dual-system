"""Pure cost-data adjustments shared by the desktop UI."""


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def rescale_material_weight(formula, waste_factor, original_waste_factor):
    """Rescale every waste-dependent material weight from its original snapshot."""
    value = max(0.0, _number(waste_factor))
    original = max(0.01, _number(original_waste_factor, 1.2))
    ratio = value / original

    collections = (
        formula.get("material_details") or [],
        formula.get("cabinet_material_part_details") or [],
    )
    for rows in collections:
        for row in rows:
            if not isinstance(row, dict):
                continue
            base_weight = _number(
                row.setdefault("_scheme2_base_billable_weight", row.get("billable_weight_kg"))
            )
            row["billable_weight_kg"] = base_weight * ratio

    for detail in formula.get("cabinet_material_part_details") or []:
        if isinstance(detail, dict):
            detail["waste_factor"] = value

    base_total = _number(
        formula.setdefault(
            "_scheme2_base_corrected_material_weight_kg",
            formula.get("corrected_material_weight_kg"),
        )
    )
    formula["corrected_material_weight_kg"] = base_total * ratio
    formula["waste_factor"] = value
    formula["requested_waste_factor"] = value
    return ratio
