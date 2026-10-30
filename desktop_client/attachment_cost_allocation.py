"""Classify saved formula attachments; never alter cabinet pricing inputs."""
from decimal import Decimal
import math
from quick_discount_rules import money,money_sum,money_product,formula_attachment_line_amount

BASIS='formula_attachments_v1'
COST_PARTS=('material_cost','spray_cost','auxiliary_cost','labor_cost')
LABELS=dict(material_cost='材料成本',spray_cost='喷涂费用',auxiliary_cost='辅材成本',labor_cost='人工成本')


def finite(value):
    try:return value not in (None,'') and math.isfinite(float(value))
    except (TypeError,ValueError):return False


def is_formula_cost(row):
    return row.get('formula_cost_edited') is not True and not row.get('custom') and (row.get('cost_method')=='FORMULA' or row.get('status')=='CALCULATED'
        or '公式成本' in str(row.get('calculation_notes') or ''))


def allocate_attachment_costs(formula,rows,*,strict=False):
    rows=[r for r in rows or [] if isinstance(r,dict)]
    if not any(r.get('status')!='QUICK_ONLY' and is_formula_cost(r) for r in rows):return None
    errors=[];lines=[];parts=dict.fromkeys(COST_PARTS,0);fixed=0
    for index,row in enumerate(rows):
        if row.get('status')=='QUICK_ONLY' and row.get('formula_cost_edited') is not True:continue
        try:amount=money(row['formula_amount'] if row.get('formula_amount') is not None else formula_attachment_line_amount(row))
        except (ValueError,TypeError):
            errors.append(f"{row.get('item_name') or '附件'}：成本尚未完成");continue
        quantity=float(row.get('quantity',1)) if finite(row.get('quantity',1)) else 0
        sign=-1 if row.get('attachment_price_sign')==-1 else 1
        signed_quantity=abs(quantity)*(-1 if quantity<0 else sign)
        line=dict(index=index,name=str(row.get('item_name') or row.get('name') or '附件'),
            specification=str(row.get('model_code') or row.get('specification') or ''),unit=str(row.get('unit') or '件'),
            quantity=signed_quantity,amount=amount,method='FORMULA' if is_formula_cost(row) else 'FIXED',components={})
        if line['method']=='FIXED':
            fixed=money_sum((fixed,amount));lines.append(line);continue
        if not quantity or any(not finite(row.get(key)) for key in COST_PARTS):
            errors.append(f"{line['name']}：公式成本缺少材料、喷塑、辅材或人工分项，请重新计算");lines.append(line);continue
        expected=money_product(sum((Decimal(str(row[key])) for key in COST_PARTS),Decimal(0)),signed_quantity)
        if abs(expected-amount)>.001:
            errors.append(f"{line['name']}：公式成本分项与原成本不一致，请重新计算");lines.append(line);continue
        cumulative=Decimal(0);previous=0
        for position,key in enumerate(COST_PARTS):
            cumulative+=Decimal(str(row[key]))
            current=amount if position==len(COST_PARTS)-1 else money_product(cumulative,signed_quantity)
            value=money_sum((current,-previous));previous=current
            line['components'][key]=dict(unit_cost=float(row[key]),amount=value,
                formula=str((row.get('formulas') or {}).get(key) or '已保存公式成本分项'))
            parts[key]=money_sum((parts[key],value))
        lines.append(line)
    total=money_sum((fixed,*parts.values()))
    if not errors and finite(formula.get('attachment_fee')) and abs(total-money(formula['attachment_fee']))>.001:
        errors.append('附件归类合计与原附件成本不一致，请重新计算')
    totals={key:money_sum((formula[key],parts[key])) if finite(formula.get(key)) else None for key in COST_PARTS}
    totals.update(attachment_fee=fixed,management_fee=formula.get('management_fee'))
    if formula.get('tax_cost_basis')=='quoted_less_display_costs_15pct_v1':
        totals['tax_cost']=formula.get('tax_cost')
    if formula.get('manufacturing_cost_basis')=='quoted_unit_4pct_v1':
        totals['manufacturing_cost']=formula.get('manufacturing_cost')
    result=dict(schema=1,basis=BASIS,complete=not errors,totals=totals,attachment_parts=parts,fixed_cost=fixed,
                attachment_total=total,lines=lines,errors=errors)
    if strict and errors:raise ValueError('；'.join(errors))
    return result


def with_cost_allocation(formula,rows,*,strict=False):
    result=dict(formula);result.pop('cost_allocation',None)
    allocation=allocate_attachment_costs(result,rows,strict=strict)
    if allocation is not None:result['cost_allocation']=allocation
    return result


def attachment_detail_rows(allocation):
    result=[]
    for line in allocation['lines']:
        components=line['components'] if line['method']=='FORMULA' else {
            'attachment_fee':dict(unit_cost=line['amount']/line['quantity'] if line['quantity'] else 0,
                                  amount=line['amount'],formula='已保存固定成本')}
        if not components:
            components={'unallocated_attachment':dict(unit_cost=0,amount=line['amount'],formula='成本分项缺失，请重新计算')}
        for key,value in components.items():
            result.append(dict(category=key,type=LABELS.get(key,'附件成本' if key=='attachment_fee' else '待重新计算'),
                name=f"{line['name']}－{LABELS.get(key,'固定成本' if key=='attachment_fee' else '待重新计算')}",
                spec=line['specification'],formula=value['formula'],quantity=line['quantity'],unit=line['unit'],
                unit_price=value['unit_cost'],base_amount=value['amount'],factor=1,
                note='附件公式成本分项' if line['method']=='FORMULA' else '固定成本附件',
                attachment_cost_source=True,_scheme2_version=3))
    return result


def merge_attachment_details(rows,allocation):
    base=[row for row in rows if row.get('category')!='attachment_fee']
    attached=attachment_detail_rows(allocation)
    order=('material_cost','auxiliary_cost','manufacturing_cost','labor_cost','spray_cost','attachment_fee','unallocated_attachment','management_fee','tax_cost')
    return [row for key in order for row in (*base,*attached) if row.get('category')==key]+[
        row for row in base if row.get('category') not in order]
