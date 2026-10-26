"""Customer configuration wording from saved quote fields, never price defaults.

Attachment counts describe one cabinet (or an explicitly identified ganged
child/shared set). Order quantity is deliberately absent from this formatter.
Missing requirements are omitted; free-form manual remarks remain the caller's
responsibility. The module performs no catalogue lookup or price calculation.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from ganged_cabinet_rules import DOOR_POSITION_COUNTS

CONFIG_FIELDS = (
    'drawing_number', 'material_number', 'body_thickness_mm', 'door_thickness_mm', 'surface_treatment',
    'texture', 'side_panel_removable', 'rear_panel_removable', 'processing_requirements',
    'excluded_items', 'special_requirements', 'protection_rating', 'packaging_requirements',
    'installation_plate_delivery', 'front_door', 'rear_structure', 'base_color',
)
MATERIAL_NAMES = {'SUS304':'不锈钢304', 'SUS316':'不锈钢316', 'SECC':'SECC'}
DOOR_NAMES = {'SINGLE':'单开门', 'DOUBLE':'双开门', 'PANEL':'背板'}
NUMBER = r'\d+(?:\.\d+)?'


def text(value):
    return str(value).strip() if value is not None else ''


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def numeric(value):
    value = number(value)
    return format(value.normalize(), 'f') if value is not None else ''


def thickness(value):
    parsed = number(value)
    return numeric(parsed) if parsed is not None and 0 < parsed <= 20 else ''


def first(row, *keys):
    return next((row[key] for key in keys if row.get(key) not in (None, '')), '')


def joined(values, separator='，'):
    return separator.join(text(v).strip('，。；; ') for v in values if text(v).strip('，。；; '))


def source_configuration(source=None, reviewed_text=''):
    """Copy only explicit source metadata before the native add/reset runs."""
    source = source if isinstance(source, dict) else {}
    config = {key:deepcopy(source[key]) for key in CONFIG_FIELDS if key in source}
    saved = source.get('quote_configuration')
    if isinstance(saved, dict):
        config.update(deepcopy(saved))
    raw = text(reviewed_text) or text(source.get('reviewed_remark'))
    return {'quote_configuration':config, 'quote_remark_source':raw}


def _configuration(item):
    raw = text(item.get('quote_remark_source'))
    fields = {}
    patterns = {
        'drawing_number': r'(?:图号|图纸编号)\s*[:：]\s*([^，,；;。\n]+)',
        'material_number': r'(?:物料号|客户物料号|物料编号)\s*[:：]\s*([^，,；;。\n]+)',
        'body_thickness_mm': rf'柜体(?:厚度|料厚|厚)?\s*[:：]?\s*({NUMBER})(?:\s*mm)?',
        'door_thickness_mm': rf'门板(?:厚度|料厚|厚)?\s*[:：]?\s*({NUMBER})(?:\s*mm)?',
        'base_color': r'底座颜色\s*[:：]\s*([^，,；;。\n]+)',
        'side_panel_removable': r'侧板\s*(不可拆(?:卸)?|可拆(?:卸)?)',
        'rear_panel_removable': r'(?:后背板|背板)\s*(不可拆(?:卸)?|可拆(?:卸)?)',
        'front_door': r'前\s*(双开门|单开门|玻璃门|网孔门)',
        'rear_structure': r'后\s*(双开门|单开门|背板|网孔门)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, raw, re.I)
        if match:
            fields[key] = match.group(1).strip()
    # Keep each explicit machining/delivery clause, not the entire OCR page or
    # unrelated commercial terms. No guessed IP rating, color or thickness.
    processing, excluded, special = [], [], []
    for clause in re.split(r'[。；;\n]+', raw):
        for match in re.finditer(r'按图([^。；;\n]+)', clause):
            if re.search(r'开孔|丝印|焊接|加强', match.group(1)):
                processing.append(re.split(r'[，,]\s*(?:不含|不配|防护等级|IP\d|包装|交期|报价|质保|付款)', match.group(1), maxsplit=1)[0].strip())
        for match in re.finditer(r'(?:^|[，,])\s*(?:不含|不配)([^，,；;。\n]+)', clause):
            entry=re.split(r'但(?:配|含)', match.group(1), maxsplit=1)[0].strip()
            if not re.search(r'税|运费|报价|交期|质保|付款',entry):
                excluded.append(entry)
        for match in re.finditer(r'(?:^|[，,])\s*无(风机滤网|风机|滤网|安装板)(?=$|[，,])', clause):
            excluded.append(match.group(1))
        for part in re.split('[，,]', clause):
            part = part.strip()
            if not part.startswith(('不含','不配')) and re.search(r'防护等级|\bIP\d{2}\b|包装|木箱|木托|安装板(?:先发|单发)|随柜发货|分开发货', part, re.I):
                special.append(part)
    if processing: fields['processing_requirements'] = joined(processing, '；')
    if excluded: fields['excluded_items'] = excluded
    if special: fields['special_requirements'] = special
    for key in CONFIG_FIELDS:
        if key in item and item[key] not in (None, ''):
            fields[key] = item[key]
    if isinstance(item.get('quote_configuration'), dict):
        fields.update({key:value for key,value in item['quote_configuration'].items() if value not in (None, '')})
    return fields


def _parts(item):
    return [row for row in (item.get('formula') or {}).get('cabinet_material_part_details', [])
            if isinstance(row, dict) and number(row.get('internal_quantity')) is not None
            and number(row['internal_quantity']) > 0]


def _part_value(item, pattern, field):
    values = {text(row.get(field)) for row in _parts(item)
              if re.search(pattern, text(row.get('part_name'))) and row.get(field) not in (None, '')}
    return next(iter(values)) if len(values) == 1 else ''


def _doors(item, fields):
    position = item.get('door_position')
    counts = (number(item.get('single_door_count')), number(item.get('double_door_count')))
    choice = (position.get('front'),position.get('rear')) if isinstance(position, dict) else None
    if choice in DOOR_POSITION_COUNTS and (None in counts or DOOR_POSITION_COUNTS[choice] == counts):
        return f'前{DOOR_NAMES[choice[0]]}，后{DOOR_NAMES[choice[1]]}'
    choices = [pair for pair, value in DOOR_POSITION_COUNTS.items() if value == counts]
    # Old 1/1 counts cannot distinguish front-single/rear-double from the
    # reverse. Do not invent an orientation in a customer document.
    if len(choices) == 1:
        front, rear = choices[0]
        return f'前{DOOR_NAMES[front]}，后{DOOR_NAMES[rear]}'
    return joined(('前'+text(fields['front_door']) if fields.get('front_door') else '',
                   '后'+text(fields['rear_structure']) if fields.get('rear_structure') else ''))


def _scope(item, row):
    children = item.get('ganged_cabinets') or []
    index = row.get('ganged_cabinet_index', row.get('ganged_fixed_base_index'))
    parsed = number(index)
    if parsed is not None and parsed >= 0 and parsed == parsed.to_integral_value():
        return f'（柜体{int(parsed)+1}，单台）'
    if len(children) < 2 and (number(item.get('ganged_cabinet_count')) or 1) < 2:
        return ''
    # An unallocated shared row is stored per complete set. Dividing it by the
    # child count would manufacture a per-cabinet allocation that is not saved.
    return '（每组）'


def _category(row):
    name = text(first(row,'item_name','name'))
    if '安装板' in name and '安装板单发' not in name: return 'plate'
    if '底座' in name: return 'base'
    if '门限位器' in name or name == '限位器': return 'limiter'
    if '锁' in name: return 'lock'
    if '照明灯' in name or '柜内灯' in name: return 'light'
    if any(word in name for word in ('行程开关','灯开关','门开关','限位开关')): return 'switch'
    if '接地' in name: return 'ground'
    if any(word in name for word in ('文件夹','资料盒')): return 'folder'
    if '风机' in name: return 'fan'
    if '滤网' in name or '过滤网' in name: return 'filter'
    if '纵梁' in name or '三排安装梁' in name: return 'beam'
    return 'other'


def _label(row, kind):
    name = re.sub(r'^柜体\s*\d+\s*[｜:：]\s*','',text(first(row,'item_name','name')))
    model = text(row.get('model_code'))
    spec = text(first(row,'specification','matched_specification'))
    brand = text(row.get('brand'))
    voltage = text(row.get('voltage'))
    if kind == 'plate':
        plate_thickness = thickness(first(row,'sheet_thickness_mm','thickness_mm'))
        material = text(first(row,'material_name','material_code'))
        material = MATERIAL_NAMES.get(material, material)
        if plate_thickness and plate_thickness+'mm' not in name.replace(' ',''):
            name = plate_thickness+'mm'+material+name
        elif material and material not in name:
            name = material+name
    elif kind == 'base':
        height = first(row,'base_height_mm') or (row.get('manual_inputs') or {}).get('底座高度')
        # Only base catalogue rows interpret their own height as base height.
        height = height or row.get('height_mm')
        name = (numeric(height)+'mm高' if number(height) is not None and number(height)>0 else '')+text(row.get('color'))+name
    elif kind == 'folder':
        match = re.search(r'A[34]', joined((name,model,spec)), re.I)
        name = (match.group(0).upper() if match else spec if spec and spec not in name else '')+'文件夹'
    elif kind == 'beam':
        name = name.replace('三排安装梁','三排纵梁')
    elif kind in ('fan','filter'):
        noun = '风机' if kind == 'fan' else '滤网'
        detail = name.replace('过滤网','').replace(noun,'').strip(' -：:')
        name = detail+noun
    if kind not in ('plate','base','folder'):
        prefix = []
        for detail in (brand,voltage,model):
            if detail and detail not in name and not any(detail in other for other in prefix):
                prefix.append(detail)
        name = ''.join(prefix)+name
    # User-edited specifications matter; catalogue dimensions that exist only
    # in numeric size-match metadata are not silently substituted as specs.
    if spec and spec not in name and spec != model and kind not in ('base','folder'):
        name += f'（{spec}）'
    if not name: name = model or spec
    return name


def build_configuration_remark(item):
    fields = _configuration(item)
    product = text(first(item,'scheme2_selected_product_name','scheme2_selected_product_code','product_family','product_code'))
    product = re.sub(r'_(?:SINGLE|DOUBLE|DEFAULT)$','',product,flags=re.I)
    if re.fullmatch('[A-Z]{2}',product):
        product += '箱' if product in ('JA','JE','JK') else '柜'
    children = [row for row in item.get('ganged_cabinets',[]) if isinstance(row,dict)]
    count = number(item.get('ganged_cabinet_count')) or len(children)
    if count > 1:
        widths = [numeric(row.get('width_mm'))+'mm' for row in children if number(row.get('width_mm'))]
        product += f'（{numeric(count)}并柜'+('，宽'+ '＋'.join(widths) if widths else '')+'）'
    code=text(item.get('material_code'))
    material = MATERIAL_NAMES[code] if code in ('SUS304','SUS316') else text(item.get('scheme2_selected_material')) or MATERIAL_NAMES.get(code,code)
    surface = text(item.get('scheme2_selected_surface') or item.get('coating_type'))
    texture = text(fields.get('texture'))
    if not texture:
        match = re.search(r'橘纹|桔纹|细砂纹|砂纹|平光|哑光',surface)
        texture = match.group(0) if match else ''
    finish = text(fields.get('surface_treatment'))
    if not finish:
        if surface in ('不喷塑','不喷涂','无'):
            finish = surface
        elif surface in ('橘纹','桔纹','平光') or '喷塑' in surface:
            finish = '喷塑'
        else:
            finish = surface.replace(texture,'').strip() if texture else surface
    color = text(item.get('display_color'))
    if finish in ('不喷塑','不喷涂','无'):
        color = texture = ''
    header = [joined([text(fields.get('drawing_number')),text(fields.get('material_number'))], '/'), product,
              material, finish+color+(texture if texture not in finish else '')]
    body = thickness(item.get('cabinet_body_thickness_mm') or fields.get('body_thickness_mm'))
    door = thickness(fields.get('door_thickness_mm') or _part_value(item,r'^(?:前门|后门|门板|单开门|双开门)(?:板)?$', 'sheet_thickness_mm'))
    if body: header.append('柜体'+body+'mm')
    if door: header.append('门板'+door+'mm')
    rows = [(row,_category(row)) for row in item.get('attachments',[]) if isinstance(row,dict)]
    fragments = {key:[] for key in ('plate','base','lock','light','switch','limiter','ground','folder','fan','filter','beam','other')}
    default_units = {'plate':'块','base':'件','lock':'件','light':'套','switch':'套','limiter':'件',
                     'ground':'根','folder':'个','fan':'只','filter':'只','beam':'根','other':'件'}
    for row,kind in rows:
        quantity = number(row.get('quantity'))
        if quantity is None or quantity == 0: continue
        signed = quantity * (-1 if row.get('attachment_price_sign') == -1 and quantity > 0 else 1)
        effective_row = row
        if kind == 'base' and fields.get('base_color') and not row.get('color'):
            effective_row = {**row,'color':fields['base_color']}
        label = _label(effective_row,kind)
        if not label: continue
        if kind == 'plate' and not first(row,'sheet_thickness_mm','thickness_mm'):
            plate_thickness = thickness(_part_value(item,r'^安装板$', 'sheet_thickness_mm'))
            material = _part_value(item,r'^安装板$', 'material_code')
            if plate_thickness and not re.search(r'\d+(?:\.\d+)?\s*mm',label):
                label = plate_thickness+'mm'+MATERIAL_NAMES.get(material,material)+label
        unit = text(row.get('unit')) or default_units[kind]
        # The requested output units for these pieces describe the physical
        # pieces directly; lock/limiter units remain exactly as saved.
        if kind in ('plate','base','ground','folder','fan','filter','beam'): unit=default_units[kind]
        location = text(first(row,'position','installation_position','distribution'))
        if location: location='（'+location+'）'
        phrase = ('扣减' if signed < 0 else '配')+label+numeric(abs(signed))+unit+location+_scope(item,row)
        fragments[kind].append(phrase)
    header.extend(fragments['plate'])
    structure = []
    if len(children)>1:
        for index,child in enumerate(children):
            doors = _doors(child,{})
            if doors: structure.append(f'柜体{index+1}：'+doors)
    else:
        structure.append(_doors(item,fields))
    for key,label in (('side_panel_removable','侧板'),('rear_panel_removable','后背板')):
        value = fields.get(key)
        if isinstance(value,bool): value='可拆' if value else '不可拆'
        if text(value): structure.append(label+text(value))
    structure_text = joined(structure)
    if fragments['base']: structure_text=joined((structure_text,joined(fragments['base'])), '；')
    accessories = joined(phrase for kind in ('lock','light','switch','limiter','ground','folder','fan','filter','beam','other') for phrase in fragments[kind])
    processing = text(fields.get('processing_requirements'))
    if processing and not processing.startswith('按图'): processing='按图'+processing
    excluded = fields.get('excluded_items') or []
    if isinstance(excluded,str): excluded=[excluded]
    exclusions = ('不含'+joined(excluded,'、')) if excluded else ''
    specials=[]
    for key in ('protection_rating','packaging_requirements','installation_plate_delivery','special_requirements'):
        value=fields.get(key)
        for phrase in value if isinstance(value,list) else [value]:
            if text(phrase) and text(phrase) not in specials: specials.append(text(phrase))
    tail=joined((processing,exclusions,*specials),'；')
    result=joined((joined(header),structure_text,accessories,tail),'。')
    return result+'。' if result else ''
