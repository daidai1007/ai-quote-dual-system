"""Independent attachment rows: their own inputs, never the option-page cabinet."""
from copy import deepcopy
from uuid import uuid4
import math

from quick_discount_rules import PRICING_BASIS, apply_management_fee
from attachment_cost_allocation import with_cost_allocation

ITEM_TYPE = 'standalone_attachment'


def is_standalone(item):
    return isinstance(item, dict) and item.get('item_type') == ITEM_TYPE


def ready(item):
    rows = item.get('attachments') or []
    if len(rows) != 1:
        return False
    row = rows[0]
    return (row.get('status') in ('FIXED', 'CALCULATED', 'QUICK_ONLY')
            and not row.get('pending_manual_dimensions')
            and all(isinstance(row.get(key), (int, float)) and not isinstance(row[key], bool)
                    and math.isfinite(row[key]) and row[key] >= 0
                    for key in ('formula_amount', 'quick_amount')))


def new_item(selection, settings=None):
    row = deepcopy(selection)
    row.update(quantity=1, attachment_price_sign=1, standalone_attachment=True,
               status='PENDING_MANUAL', pending_manual_dimensions=['读取附件规格'])
    # Names-only entry intentionally drops prior cabinet dimensions and quantities.
    row = {key: value for key, value in row.items() if key in (
        'item_name', 'name', 'category_level1', 'category_level2', 'category_level3',
        'attachment_category', 'custom', 'quantity', 'attachment_price_sign',
        'standalone_attachment', 'status', 'pending_manual_dimensions')}
    row['standalone_cost_settings'] = deepcopy(settings or {})
    return {'item_type': ITEM_TYPE, 'attachment_contract': 'standalone_v1',
            'product_code': ITEM_TYPE.upper(), 'scheme2_selected_product_code': ITEM_TYPE.upper(),
            'scheme2_selected_product_name': '独立附件', 'name': row.get('item_name') or row.get('name'),
            'quantity': 1, 'unit': '件', 'quick_discount': 1.0, 'pricing_basis': PRICING_BASIS,
            'freight_fee': 0, 'freight_mode': 'AUTO', 'freight_basis': 'self_made_weight_v1',
            'standalone_id': str(uuid4()), 'attachments': [row], 'specification': '待完善',
            'standalone_reprice_token': str(uuid4()),
            'scheme2_cost_settings': deepcopy(settings or {}),
            'formula': {}, 'quick': {}}


def update_item(item, row):
    item['attachments'] = [deepcopy(row)]
    item['unit'] = row.get('unit') or '件'
    own = row.get('standalone_environment') or row.get('environment') or {}
    item['material_code'] = row.get('standalone_material_code') or ''
    dimensions = ' × '.join(str(own[key]).removesuffix('.0') for key in ('width_mm', 'depth_mm', 'height_mm')
                            if own.get(key) is not None)
    if not dimensions:
        dimensions = '；'.join(f'{name}={value:g} mm' for name, value in (row.get('manual_inputs') or {}).items()
                              if isinstance(value, (int, float)) and any(axis in name for axis in ('宽度','高度','深度')))
    item['specification'] = row.get('model_code') or dimensions or ('—' if ready(item) else '待完善')
    item['standalone_error'] = row.get('error') or ''
    item.pop('quote_display', None)
    item.pop('cost_detail_rows', None)
    if ready(item):
        formula = apply_management_fee({'material_cost': 0, 'auxiliary_cost': 0, 'labor_cost': 0,
                                       'spray_cost': 0, 'attachment_fee': row['formula_amount']}, item.get('freight_fee', 0))
        item['formula'] = with_cost_allocation(formula, [row])
        item['formula_base'] = deepcopy(item['formula'])
        item['quick'] = {'base_price': 0, 'attachment_fee': row['quick_amount'], 'total_cost': row['quick_amount']}
    else:
        item['formula'] = {}
        item['quick'] = {}


def request(window, sources, succeeded, failed):
    """Read-only API call; contains attachment-owned fields and no cabinet values."""
    worker_class = window._standalone_worker_class
    payload = {'attachments': deepcopy(sources)}
    url = window.base_url().split('/api/', 1)[0].rstrip('/') + '/api/attachments/preview-standalone'
    worker = worker_class(url, payload, window)
    active = getattr(window, '_scheme2_attachment_reprice_workers', set())
    window._scheme2_attachment_reprice_workers = active
    active.add(worker)
    worker.succeeded.connect(lambda body: succeeded(body.get('attachments') or []))
    worker.failed.connect(failed)
    def finished():
        active.discard(worker)
        worker.deleteLater()
    worker.finished.connect(finished)
    worker.start()


def reprice(window, item, source, succeeded, failed):
    source = {**deepcopy(source), 'standalone_cost_settings': deepcopy(item.get('scheme2_cost_settings') or {})}
    request(window, [source], lambda rows: succeeded(rows[0]) if rows else failed('附件服务未返回计算结果'), failed)


def refresh_costs(window, item):
    token = item['standalone_reprice_token'] = str(uuid4())
    source = deepcopy(item['attachments'][0])
    item['attachments'][0].update(status='PENDING_MANUAL', pending_manual_dimensions=['重新计算'])
    def current():
        return (item.get('standalone_reprice_token') == token
                and any(row is item for row in window.draft_items))
    def loaded(row):
        if current():
            update_item(item, row)
            window.refresh_summary()
    def failed(message):
        if current():
            item['standalone_error'] = str(message)
            item['attachments'][0]['pending_manual_dimensions'] = ['重新读取附件规格']
            window.refresh_summary()
    reprice(window, item, source, loaded, failed)
    window.refresh_summary()
