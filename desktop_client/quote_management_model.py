"""Quote document snapshots. Reuse the current selective-discount calculation."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math

from quick_discount_rules import PRICING_BASIS, money, money_sum

SCHEMA = 1
MAX_VERSIONS = 50


def decimal_input(text, places=2, maximum=None):
    try:
        value = Decimal(str(text).strip().replace(',', ''))
    except (InvalidOperation, ValueError):
        raise ValueError('请输入有效数字。') from None
    if not value.is_finite() or value < 0 or value.as_tuple().exponent < -places:
        raise ValueError(f'请输入非负数字，最多{places}位小数。')
    if maximum is not None and value > maximum:
        raise ValueError(f'数字不能超过{maximum}。')
    return float(value)


def original_discounts(items):
    for item in items:
        value = item.get('quick_discount', 1)
        if not math.isfinite(float(value)):
            raise ValueError('原有折扣无效，请返回成本计算核对。')
        item.setdefault('quote_original_discount', float(value))


def set_unit_price(item, value):
    """Reverse the same affine price rule used by the original quote sheet.

    Keep the full factor precision: rounding the factor to four decimals can
    silently change a two-decimal unit price. Only the editor display rounds it.
    """
    import scheme2_ui as ui
    from quick_discount_rules import quick_order_line_breakdown
    target = decimal_input(value)
    quantity = max(1, int(item.get('quantity') or 1))
    freight = max(0, float(item.get('freight_fee', item.get('freight', 0)) or 0))
    quick, _ = ui._quote_with_popup_attachment_fee(ui._quick(item), item.get('attachments') or [], ui._popup_quick_amount)
    args = (quick, item.get('attachments') or [])
    zero = quick_order_line_breakdown(*args, 0, quantity, 1, freight)['equivalent_unit_total']
    full = quick_order_line_breakdown(*args, 1, quantity, 1, freight)['equivalent_unit_total']
    fixed = money_sum((zero, ui._material_difference_amount(item)))
    discountable = money_sum((full, -zero))
    if target < fixed:
        raise ValueError(f'折后单价不能低于原价附件、运费及材料差价合计 ¥{fixed:,.2f}。')
    if discountable <= 0:
        if money(ui._row_values(item)[15]) == target:
            return
        raise ValueError('本行没有可调整金额，请返回成本计算核对。')
    factor = (Decimal(str(target)) - Decimal(str(fixed))) / Decimal(str(discountable))
    if not 0 <= factor <= 10:
        raise ValueError('反算折扣超出0–10范围，请核对单价。')
    original_discounts([item])
    item['quick_discount'] = float(factor)
    item['pricing_basis'] = PRICING_BASIS
    item.pop('quote_display', None)
    if money(ui._row_values(item)[15]) != target:
        raise ValueError('单价无法按当前报价精确计算，请核对。')


def set_factor(item, value):
    factor = decimal_input(value, 4, 10)
    original_discounts([item])
    item['quick_discount'] = factor
    item['pricing_basis'] = PRICING_BASIS
    item.pop('quote_display', None)


def attachment_unit_price(item, index, value):
    import scheme2_ui as ui
    from quick_discount_rules import quick_discount_category, money_product
    row = item['attachments'][index]
    if not quick_discount_category(row):
        raise ValueError('不参与折扣的附件保持原价，不能在调价页修改。')
    value = decimal_input(value)
    quantity = float(row.get('quantity') or 1)
    sign = -1 if float(row.get('attachment_price_sign') or 1) == -1 else 1
    old = ui._popup_quick_amount(row)
    amount = money_product(value, quantity, sign)
    row.update(quick_amount=amount, quick_amount_override=amount,
               custom_amount_edited=True, unit_price_override=value)
    quick = item.get('quick') or {}
    quick['attachment_fee'] = money_sum((quick.get('attachment_fee', 0), -old, amount))
    quick['total_cost'] = money_sum((quick.get('total_cost', 0), -old, amount))
    item['quick'] = quick
    item.pop('quote_display', None)
    item.pop('cost_detail_rows', None)


def make_version(items, company, number, reason='', operator='', quote_date='', order_nature='UNCLASSIFIED'):
    import scheme2_ui as ui
    frozen = deepcopy(items)
    original_discounts(frozen)
    from quote_order_nature import normalize
    return dict(version=number, items=frozen, company=str(company), reason=str(reason), order_nature=normalize(order_nature),
                operator=str(operator), quote_date=str(quote_date),
                updated_at=datetime.now().isoformat(timespec='seconds'),
                amount=money_sum(ui._row_values(item)[16] for item in frozen), sealed=False)


def restore_state(value):
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        return dict(schema=SCHEMA, versions=[], current=0)
    versions = value.get('versions')
    if not isinstance(versions, list) or len(versions) > MAX_VERSIONS:
        raise ValueError('报价版本记录无效。')
    for index, version in enumerate(versions, 1):
        if not isinstance(version, dict) or version.get('version') != index or not isinstance(version.get('items'), list):
            raise ValueError('报价版本记录不连续或明细无效。')
    return deepcopy(value)


def sync_latest(state, items, company, operator='', quote_date='', order_nature='UNCLASSIFIED'):
    if not items:
        return state
    original_discounts(items)
    versions = state.setdefault('versions', [])
    number = len(versions) or 1
    prior = versions[-1] if versions else {}
    entry = make_version(items, company, number, prior.get('reason', '首次报价'), operator, quote_date, order_nature)
    entry['sealed'] = bool(prior.get('sealed'))
    if prior.get('revision_draft'):
        entry['revision_draft'] = True
    if versions and not prior.get('sealed'):
        versions[-1] = entry
    elif not versions:
        versions.append(entry)
    state.update(schema=SCHEMA, current=len(versions))
    return state


def append_version(state, items, company, reason, operator='', quote_date='', order_nature=None):
    if not reason.strip():
        raise ValueError('请填写调价原因。')
    if len(state['versions']) >= MAX_VERSIONS:
        raise ValueError('报价版本超过50份，请新建报价方案。')
    if order_nature is None:
        order_nature = (state['versions'][-1] if state['versions'] else {}).get('order_nature')
    entry = make_version(items, company, len(state['versions']) + 1, reason, operator, quote_date, order_nature)
    state['versions'].append(entry)
    state['current'] = entry['version']
    return entry
