"""Read saved quotation versions without changing their prices or costs."""
from copy import deepcopy
import math
from quick_discount_rules import money, money_sum, money_product
from profit_metrics import GROSS_MARGIN_BASIS, production_total


def number(value):
    try:
        parsed=float(str(value).replace(',', '').strip())
        return parsed if math.isfinite(parsed) else None
    except (TypeError,ValueError):
        return None


def line_metrics(item):
    import scheme2_ui as ui
    display=item.get('quote_display') or {}
    quantity=number(display.get('quantity',item.get('quantity',1)))
    quantity=max(1,int(quantity)) if quantity is not None else 1
    unit,total=number(display.get('unit_price')),number(display.get('total'))
    if unit is None or total is None:
        quick=item.get('quick') or {}
        if number(quick.get('base_price')) is not None or number(quick.get('total_cost')) is not None:
            values=ui._row_values(deepcopy(item))
            unit,total=values[15],values[16]
        else:
            unit=total=None
    frozen=item.get('quote_cost_display') or {}
    saved=(frozen.get('values') or {}) if frozen.get('schema')==1 else {}
    cost=number(saved.get('成本总价'))
    if cost is None:
        cost_unit=number(saved.get('成本单价'))
        if cost_unit is not None:
            cost=money_product(cost_unit,quantity)
    if cost is None:
        # The recorded formula total excludes freight. Do not run today's
        # management-fee or catalogue rules over a historical cost snapshot.
        formula=item.get('formula') or {}
        cost_unit=number(formula.get('total_cost'))
        if cost_unit is None:
            values=[number(formula.get(key)) for key in
                ('material_cost','auxiliary_cost','labor_cost','attachment_fee','spray_cost','management_fee')]
            if formula.get('manufacturing_cost_basis')=='quoted_unit_4pct_v1':
                values.append(number(formula.get('manufacturing_cost')))
            if formula.get('tax_cost_basis')=='quoted_less_display_costs_15pct_v1':
                values.append(number(formula.get('tax_cost')))
            if all(value is not None for value in values):cost_unit=money_sum(values)
        freight=number(item.get('freight_fee',item.get('freight',0)))
        if cost_unit is not None and freight is not None:
            cost=money_product(money_sum((cost_unit,freight)),quantity)
    margin=(total-cost)/total if total not in (None,0) and cost is not None else None
    margin_cost=cost
    # New snapshots explicitly distinguish production gross and all-in net.
    # Older stored versions retain their original comparison interpretation.
    if '净利率' in saved:
        text=str(saved.get('毛利率') or '').strip()
        margin=number(text[:-1])/100 if text.endswith('%') and number(text[:-1]) is not None else None
        production=[number(saved.get(label)) for label in ('材料成本','辅材成本','人工成本','附件成本','喷涂费用')]
        if saved.get('制造成本') not in (None,'','未记录','—'):
            production.append(number(saved['制造成本']))
        if all(value is not None for value in production):
            margin_cost=money_product(money_sum(production),quantity)
        elif margin is not None and total is not None:
            margin_cost=money_product(total,1-margin)
        else:
            margin_cost=None
    if margin is None and total not in (None,0):
        text=str(saved.get('毛利率') or '').strip()
        if text.endswith('%') and number(text[:-1]) is not None:
            margin=number(text[:-1])/100
    if item.get('gross_margin_basis') == GROSS_MARGIN_BASIS:
        production=[number(saved.get(label)) for label in ('材料成本','辅材成本','人工成本','附件成本','喷涂费用')]
        if saved.get('制造成本') not in (None,'','未记录','—'):
            production.append(number(saved['制造成本']))
        production_amount=money_product(money_sum(production),quantity) if saved and all(v is not None for v in production) else production_total(item.get('formula') or {},quantity)
        freight=number(saved.get('运费',item.get('freight_fee',item.get('freight',0))))
        margin_cost=money_sum((production_amount,money_product(freight,quantity))) if production_amount is not None and freight is not None else None
        margin=(total-margin_cost)/total if total not in (None,0) and margin_cost is not None else None
    return dict(name=str(item.get('name') or item.get('model_code') or '未命名'),quantity=quantity,
                unit=unit,total=total,cost=cost,margin=margin,margin_cost=margin_cost)


def _identity(item):
    return tuple(str(item.get(key) or '') for key in
        ('name','product_code','product_family','model_code','specification','material_code','width_mm','depth_mm','height_mm'))


def pair_items(left,right,metrics=line_metrics):
    """Prefer quote-line identity; never pair unrelated rows by table index."""
    unused=set(range(len(left)))
    matches={}
    # Match unchanged copies first. Otherwise a modified/reordered copy could
    # consume the row belonging to a later unchanged, identically named item.
    for position,current in enumerate(right):
        current_values=metrics(current)
        match=next((i for i in sorted(unused) if _identity(left[i])==_identity(current)
                    and metrics(left[i])==current_values),None)
        if match is not None:
            matches[position]=match;unused.remove(match)
    for position,current in enumerate(right):
        if position in matches:continue
        line_id=current.get('quote_line_id')
        candidates=[i for i in sorted(unused) if line_id and left[i].get('quote_line_id')==line_id]
        exact=[i for i in candidates if _identity(left[i])==_identity(current)]
        if not candidates:
            candidates=[i for i in sorted(unused) if _identity(left[i])==_identity(current)]
        index=next(iter(exact or candidates),None)
        matches[position]=index
        if index is not None:unused.remove(index)
    pairs=[(None if matches[position] is None else left[matches[position]],current) for position,current in enumerate(right)]
    pairs.extend((left[i],None) for i in sorted(unused))
    return pairs


def aggregate(metrics):
    def complete_sum(key):
        return money_sum(row[key] for row in metrics) if all(row[key] is not None for row in metrics) else None
    total,cost=complete_sum('total'),complete_sum('cost')
    margin_cost=money_sum(row.get('margin_cost',row['cost']) for row in metrics) if all(row.get('margin_cost',row['cost']) is not None for row in metrics) else None
    return dict(name='本版合计',quantity=sum(row['quantity'] for row in metrics),unit=None,total=total,cost=cost,
                margin=(total-margin_cost)/total if total not in (None,0) and margin_cost is not None else None)


def comparison_groups(versions,from_version=None,to_version=None):
    confirmed=[v for v in versions if not v.get('pending_confirmation') and not v.get('revision_draft')]
    confirmed.sort(key=lambda v:v['version'])
    by_number={v['version']:v for v in confirmed}
    if from_version in by_number and to_version in by_number:
        transitions=[(by_number[from_version],by_number[to_version])]
    else:
        transitions=[(confirmed[i-1] if i else None,current) for i,current in enumerate(confirmed)]
    groups=[]
    cache={}
    def metrics(item):
        if item is None:return None
        if id(item) not in cache:cache[id(item)]=line_metrics(item)
        return cache[id(item)]
    for previous,current in transitions:
        left=(previous or {}).get('items') or [];right=current.get('items') or []
        rows=[dict(left=metrics(a),right=metrics(b),summary=False) for a,b in pair_items(left,right,metrics)]
        rows.append(dict(left=aggregate([metrics(item) for item in left]) if previous else None,
                         right=aggregate([metrics(item) for item in right]),summary=True))
        groups.append(dict(previous=(previous or {}).get('version'),current=current['version'],rows=rows))
    return groups


def percentage(value):
    return '未记录' if value is None else f'{money(value*100):.2f}%'


def change_details(left,right,*,initial=False):
    if initial:
        amount='未记录' if right['total'] is None else f"¥ {right['total']:,.2f}"
        return f"首次报价 · 金额 {amount}\n毛利率：{percentage(right['margin'])}"
    old_amount=0 if left is None else left['total']
    new_amount=0 if right is None else right['total']
    prefix='新增产品 · ' if left is None else '移除产品 · ' if right is None else ''
    amount='未记录' if old_amount is None or new_amount is None else f"{money_sum((new_amount,-old_amount)):+,.2f}"
    old_margin=left['margin'] if left else None;new_margin=right['margin'] if right else None
    delta='无法计算变化'
    if old_margin is not None and new_margin is not None:
        delta=f"{money_sum((money(new_margin*100),-money(old_margin*100))):+.2f} 个百分点"
    return f"{prefix}金额：{amount}\n毛利率：{percentage(old_margin) if left else '—'} → {percentage(new_margin) if right else '—'}（{delta}）"
