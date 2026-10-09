"""Material-specific sidebar prices shared by all quote request paths."""

STAINLESS_DEFAULT_PRICES = {"SUS304": 16.0, "SUS316": 32.4}
MATERIAL_PRICE_KEYS = {
    "SUS304": "stainless_304_price",
    "SUS316": "stainless_316_price",
}


def material_unit_price(settings, material_code):
    settings = settings or {}
    code = str(material_code or "").strip().upper()
    key = MATERIAL_PRICE_KEYS.get(code)
    if key:
        return float(settings.get(key, settings.get("stainless_price", STAINLESS_DEFAULT_PRICES[code])))
    return float(settings.get("carbon_price", 4.2))


def migrate_material_prices(settings, material_code="", defaults=None):
    """Preserve a legacy shared price only for the row's actual steel grade."""
    existing = dict(settings or {})
    result = {**(defaults or {}), **existing}
    for code, key in MATERIAL_PRICE_KEYS.items():
        if key not in existing:
            if code == str(material_code or "").strip().upper() and "stainless_price" in existing:
                result[key] = existing["stainless_price"]
            else:
                result.setdefault(key, STAINLESS_DEFAULT_PRICES[code])
    return result
