"""Confirmed product wording rules; no prices, catalogue writes or snapshot edits."""
from decimal import Decimal, InvalidOperation
import re

DASHES = {'-', '－', '—'}
PLATE_QUANTITY_KEYS = ('installation_plate_quantity', 'installation_board_quantity', '安装板数量')
STANDARD_TYPES = {'AE', 'JA', 'JC', 'JE', 'JK', 'JM', 'JP', 'JS', 'PS'}

def value_text(value):
    return '' if value is None else str(value).strip()

def finite(value):
    if isinstance(value, bool): return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError): return None

def product_rule(value):
    original = value_text(value)
    normalized = re.sub(r'(?:_(?:SINGLE|DOUBLE|DEFAULT|EXP))+$', '', original.upper())
    normalized = re.sub(r'^仿威图', '', normalized)
    if normalized in {'PS结构柜','PS柜（PS结构）','PS柜(PS结构)'}: normalized='PS'
    match = re.fullmatch(r'(AE|JA|JC|JE|JK|JM|JP|JS|PS)(?:[_ ]?WIDE|超宽)?(?:箱|柜)?', normalized)
    key = match.group(1) if match else ''
    standard = bool(key)
    if standard:
        wide = bool(re.search(r'WIDE|超宽', normalized))
        label = key + ('超宽柜' if wide else ('箱' if key in {'JA','JK'} and not original.endswith('柜') else '柜'))
        label = '仿威图' + label
    elif re.fullmatch(r'JQ1(?:斜面操作台)?', normalized): key, label = 'JQ1', 'JQ1斜面操作台'
    elif re.fullmatch(r'JQ2(?:琴式操作台)?', normalized): key, label = 'JQ2', 'JQ2琴式操作台'
    else:
        label = original
        if normalized == 'MNS': label = 'MNS柜'
        if normalized == 'FB': label = 'FB非标柜'
    fixed = '侧板不可拆，后背板可拆' if key == 'JS' else '侧板、后背板可拆' if key == 'JP' else ''
    return dict(key=key, label=label, standard=standard or key in {'JQ1','JQ2'}, fixed=fixed)

def installation_state(item, fields, rows, *, standard=False):
    """Only quantity fields can contain a dash; numeric deductions keep their meaning."""
    explicit = False; raw = None
    for source in (fields, item):
        for key in PLATE_QUANTITY_KEYS:
            if key in source:
                explicit, raw = True, source[key]; break
        if explicit: break
    quantities = [row.get('quantity') for row, kind in rows if kind == 'plate']
    dash = value_text(raw) in DASHES if explicit else any(value_text(q) in DASHES for q in quantities)
    positives = [finite(q) for q in quantities if finite(q) is not None and finite(q) > 0]
    issues = []
    if dash:
        if positives: issues.append('安装板数量横线与已配安装板明细冲突，请核对')
        return dict(mode='none', quantity=None, issues=issues)
    parsed = finite(raw) if explicit else None
    if explicit:
        if parsed is None or parsed <= 0:
            issues.append('安装板数量待确认；负数不能自动解释为不含安装板')
            return dict(mode='unknown', quantity=None, issues=issues)
        if positives and sum(positives) != parsed:
            issues.append('安装板数量字段与附件明细不一致，请核对')
        return dict(mode='positive', quantity=parsed, issues=issues)
    if quantities:
        if any(finite(q) is None for q in quantities): issues.append('安装板数量待确认')
        if any(finite(q) is not None and finite(q) < 0 for q in quantities):
            issues.append('安装板含数值扣减，请核对实际供货数量')
        return dict(mode='rows', quantity=None, issues=issues)
    if standard:
        return dict(mode='unknown', quantity=None, issues=['安装板数量待确认'])
    return dict(mode='absent', quantity=None, issues=[])

def structural_review(rule, fields, raw=''):
    issues = []
    def removable(v):
        if isinstance(v, bool): return v
        text = value_text(v)
        return False if '不可拆' in text else True if '可拆' in text else None
    if rule['key'] in {'JS','JP'}:
        expected = {'side_panel_removable':rule['key']=='JP', 'rear_panel_removable':True}
        for key, value in expected.items():
            actual = removable(fields.get(key))
            if actual is not None and actual != value:
                issues.append('侧背板配置与'+rule['key']+'已确认固定结构冲突，请核对')
    if rule['key'] == 'JM' and any(removable(fields.get(k)) is True for k in ('side_panel_removable','rear_panel_removable')):
        issues.append('JM侧背板结构尚待业务确认，请核对当前要求')
    for label in ('柜体','门板'):
        values = set(re.findall(label+r'(?:厚度|料厚|厚)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*mm', raw))
        if len(values)>1: issues.append(label+'存在不同板厚，请核对')
    return list(dict.fromkeys(issues))
