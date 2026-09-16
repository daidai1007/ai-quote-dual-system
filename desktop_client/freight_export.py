"""Repair freight presentation in a downloaded workbook, without repricing it.

Only existing quote-sheet freight cells and their number formats are changed.
All other ZIP entries, total cells, formulas, images and layout are preserved.
"""
from copy import deepcopy
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from freight_state import money

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def fill_freight_cells(path, amounts):
    """Amounts are existing order-line breakdown totals, in payload item order."""
    path = Path(path)
    with ZipFile(path) as source:
        entries = [(info, source.read(info.filename)) for info in source.infolist()]
    parts = {info.filename: data for info, data in entries}
    strings = []
    if 'xl/sharedStrings.xml' in parts:
        strings = [''.join(node.itertext()) for node in ET.fromstring(parts['xl/sharedStrings.xml'])]
    relations = {node.get('Id'): node.get('Target') for node in
                 ET.fromstring(parts['xl/_rels/workbook.xml.rels'])}
    styles = parts['xl/styles.xml'].decode('utf-8')
    block = re.search(r'<cellXfs\b[^>]*>(.*?)</cellXfs>', styles, re.S)
    if block is None:
        raise ValueError('Excel 缺少单元格格式，无法补齐运费显示')
    xfs = re.findall(r'<xf\b[^>]*?(?:/>|>.*?</xf>)', block.group(1), re.S)
    extra_styles, style_ids = [], {}

    def amount_style(original):
        original = int(original or 0)
        if original not in style_ids:
            xf = xfs[original]
            xf = re.sub(r'\snumFmtId="[^"]*"', '', xf, count=1)
            xf = re.sub(r'\sapplyNumberFormat="[^"]*"', '', xf, count=1)
            xf = xf.replace('<xf', '<xf numFmtId="2" applyNumberFormat="1"', 1)
            style_ids[original] = len(xfs) + len(extra_styles)
            extra_styles.append(xf)
        return style_ids[original]

    def text(cell):
        value = cell.find('m:v', NS)
        if cell.get('t') == 's' and value is not None:
            return strings[int(value.text)]
        if cell.get('t') == 'inlineStr':
            return ''.join(cell.find('m:is', NS).itertext())
        return value.text if value is not None else ''

    changed = {}
    for sheet in ET.fromstring(parts['xl/workbook.xml']).findall('m:sheets/m:sheet', NS):
        values = amounts.get(sheet.get('name'))
        if values is None:
            continue
        target = relations[sheet.get(REL)]
        name = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
        xml = parts[name].decode('utf-8')
        root = ET.fromstring(xml)
        header = next((c for c in root.findall('.//m:sheetData/m:row/m:c', NS)
                       if text(c).strip() == '运费'), None)
        if header is None:
            continue  # Do not introduce a column into an unrelated template.
        column, first_row = re.fullmatch(r'([A-Z]+)(\d+)', header.get('r')).groups()
        for index, amount in enumerate(values, int(first_row) + 1):
            reference = f'{column}{index}'
            row_pattern = rf'(<row\b[^>]*\br="{index}"[^>]*>)(.*?)(</row>)'
            row_match = re.search(row_pattern, xml, re.S)
            if row_match is None:
                raise ValueError(f'Excel 报价行缺失：{reference}')
            body = row_match.group(2)
            cell_pattern = rf'<c\b[^>]*\br="{reference}"[^>]*?(?:/>|>.*?</c>)'
            cell_match = re.search(cell_pattern, body, re.S)
            original = ET.fromstring(cell_match.group()) if cell_match else None
            style = amount_style(original.get('s') if original is not None else header.get('s'))
            replacement = f'<c r="{reference}" s="{style}" t="n"><v>{money(amount):.2f}</v></c>'
            if cell_match:
                body = body[:cell_match.start()] + replacement + body[cell_match.end():]
            else:
                # Excel cells must remain in column order.
                following = next((m for m in re.finditer(r'<c\b[^>]*\br="([A-Z]+)\d+"', body)
                                  if (len(m[1]), m[1]) > (len(column), column)), None)
                at = following.start() if following else len(body)
                body = body[:at] + replacement + body[at:]
            xml = xml[:row_match.start(2)] + body + xml[row_match.end(2):]
        changed[name] = xml.encode('utf-8')
    if not changed:
        return
    updated = block.group().replace('</cellXfs>', ''.join(extra_styles) + '</cellXfs>')
    updated = re.sub(r'count="\d+"', f'count="{len(xfs) + len(extra_styles)}"', updated, count=1)
    changed['xl/styles.xml'] = (styles[:block.start()] + updated + styles[block.end():]).encode('utf-8')
    temporary = path.with_suffix(path.suffix + '.freight.part')
    try:
        with ZipFile(temporary, 'w') as output:
            for info, data in entries:
                output.writestr(info, changed.get(info.filename, data))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install_freight_export(namespace):
    from layout_refresh import _formula_order_line_breakdown, ganged_split_count, quick_order_line_breakdown

    cls = namespace['MainWindow']
    original = cls.export_workbook

    def export_workbook(window, output_path, payload):
        # Freeze the same quote snapshot sent to the existing export endpoint.
        payload = deepcopy(payload)
        amounts = {'公式法报价单': [], '快速报价单': []}
        for item in payload.get('items', []):
            amounts['公式法报价单'].append(_formula_order_line_breakdown(item)['freight_total'])
            amounts['快速报价单'].append(quick_order_line_breakdown(
                item.get('quick', {}), item.get('attachments', []),
                item.get('quick_discount', 1), item.get('quantity') or 1,
                ganged_split_count(item), item.get('freight_fee', item.get('freight', 0)),
            )['freight_total'])
        result = original(window, output_path, payload)
        fill_freight_cells(output_path, amounts)
        return result

    cls.export_workbook = export_workbook
