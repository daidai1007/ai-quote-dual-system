"""JC selections remain one database product with two explicit configurations."""
from copy import deepcopy
import re

LABELS = {'STANDARD': 'JC 标配型', 'LUXURY': 'JC 豪华型'}


def profile_of(value):
    text = str(value or '').strip().upper()
    if any(word in text for word in ('LUXURY', 'DELUXE', '豪华')):
        return 'LUXURY'
    if any(word in text for word in ('STANDARD', '标配')):
        return 'STANDARD'
    match = re.fullmatch(r'JC\d+-([12])', text)
    return {'1': 'STANDARD', '2': 'LUXURY'}.get(match[1]) if match else None


def item_profile(item):
    for key in ('jc_profile_code', 'variant_code', 'scheme2_selected_product_name',
                'product_family', 'variant_name', 'model_code'):
        if profile := profile_of(item.get(key)):
            return profile
    return None


def is_jc(item):
    return any(str(item.get(key) or '').upper().startswith('JC') for key in
               ('product_code', 'product_family', 'scheme2_selected_product_code'))


def expand_catalog(window):
    catalog, combo = window.product_catalog, window.product_combo
    base = catalog.get('JC')
    index = combo.findData('JC')
    if not isinstance(base, dict) or index < 0:
        return
    selected = combo.currentData()
    blocked = combo.blockSignals(True)
    try:
        combo.removeItem(index)
        for offset, (profile, label) in enumerate(LABELS.items()):
            entry = deepcopy(base)
            code = next(iter((base.get('codes') or {}).values()), 'JC_EXP')
            entry.update(jc_profile_code=profile, name=label)
            entry['codes'] = {**entry.get('codes', {}), profile: code}
            entry['models'] = [row for row in entry.get('models', [])
                               if profile_of(row.get('model_code')) in (None, profile)]
            catalog[label] = entry
            combo.insertItem(index + offset, label, label)
        retained = getattr(window, '_persistent_product_selection', None) or selected
        target = combo.findData(retained)
        if target >= 0:
            combo.setCurrentIndex(target)
        elif retained == 'JC':
            combo.setCurrentIndex(int(combo.property('schemePlaceholderIndex') or 0))
            window._persistent_product_selection = None
    finally:
        combo.blockSignals(blocked)


def select_item_profile(window, item):
    if not is_jc(item):
        return
    profile = item_profile(item)
    combo = window.product_combo
    index = combo.findData(LABELS.get(profile)) if profile else -1
    if index < 0:
        index = int(combo.property('schemePlaceholderIndex') or 0)
        window._persistent_product_selection = None
    else:
        window._persistent_product_selection = LABELS[profile]
    combo.setCurrentIndex(index)
    if not profile and getattr(window, 'risk_label', None) is not None:
        window.risk_label.setText('JC 产品请明确选择标配型或豪华型后再报价。')


def install_jc_profiles(namespace):
    cls = namespace['MainWindow']
    if getattr(cls, '_jc_profiles_installed', False):
        return
    cls._jc_profiles_installed = True
    catalog_loaded, variant_code, variant_name = cls.product_catalog_loaded, cls.selected_variant_code, cls.selected_variant_name
    load_draft, apply_drawing = cls.load_draft_item, cls._apply_confirmed_drawing_to_quote

    def loaded(window, result):
        retained = getattr(window, '_persistent_product_selection', None) or window.product_combo.currentData()
        value = catalog_loaded(window, result)
        expand_catalog(window)
        if retained in LABELS.values():
            window.product_combo.setCurrentIndex(window.product_combo.findData(retained))
        return value

    def selected_variant(window):
        entry = window.product_catalog.get(window.product_combo.currentData(), {})
        return entry.get('jc_profile_code') or variant_code(window)

    def selected_name(window):
        entry = window.product_catalog.get(window.product_combo.currentData(), {})
        profile = entry.get('jc_profile_code')
        return (LABELS[profile][3:] + ' ' if profile else '') + variant_name(window)

    def restore(window, item):
        adjusted = item
        if is_jc(item):
            adjusted = {**item, 'product_family': LABELS.get(item_profile(item), 'JC')}
        result = load_draft(window, adjusted)
        select_item_profile(window, item)
        return result

    def drawing(window, item):
        select_item_profile(window, item)
        result = apply_drawing(window, item)
        select_item_profile(window, item)
        return result

    cls.product_catalog_loaded, cls.selected_variant_code, cls.selected_variant_name = loaded, selected_variant, selected_name
    cls.load_draft_item, cls._apply_confirmed_drawing_to_quote = restore, drawing
