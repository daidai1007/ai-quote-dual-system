"""Offline cost-detail XLSX snapshots using the portable client's standard library.

This is a display export, not another pricing engine. Every value and its
precision come from the current table; formula descriptions remain literal text.
"""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import re
import tempfile
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CONTENT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NUMERIC_COLUMNS = frozenset((4, 6, 7, 8, 9))
INVALID_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def _node(parent, tag, **attributes):
    return ET.SubElement(parent, f'{{{MAIN}}}{tag}', {key: str(value) for key, value in attributes.items()})


def _xml(root):
    payload = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    # OPC requires its content-type/relationship elements in the default
    # namespace. Local serialization avoids modifying ElementTree's global map.
    namespace = root.tag[1:].split('}', 1)[0].encode('utf-8')
    prefix = re.search(rb'xmlns:([^= ]+)="' + re.escape(namespace) + rb'"', payload)
    if prefix:
        marker = prefix.group(1)
        payload = payload.replace(b'xmlns:' + marker + b'=', b'xmlns=', 1)
        payload = payload.replace(b'<' + marker + b':', b'<').replace(b'</' + marker + b':', b'</')
    return payload


def _column(index):
    result = ''
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def _numeric(text):
    if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', text):
        return None
    try:
        value = Decimal(text.replace(',', ''))
    except InvalidOperation:
        return None
    return (value, len(text.partition('.')[2])) if value.is_finite() else None


def write_cost_detail_xlsx(output_path, snapshot):
    """Write all displayed rows atomically, without touching any order state."""
    headers, rows = snapshot['headers'], snapshot['rows']
    numeric_columns = frozenset(snapshot.get('numeric_columns', NUMERIC_COLUMNS))
    if len(headers) != 11 or not rows or any(len(row) != len(headers) for row in rows):
        raise ValueError('成本明细表不完整，无法导出。')
    output = Path(output_path)
    if output.suffix.lower() != '.xlsx':
        raise ValueError('请选择 .xlsx 格式保存成本明细。')
    strings = [snapshot['title'], snapshot['meta'], *headers, *(text for row in rows for text in row)]
    if any(len(text) > 32767 or INVALID_XML.search(text) for text in strings):
        raise ValueError('明细文本过长或含有 Excel 不支持的字符，请检查后重试。')

    styles = ET.Element(f'{{{MAIN}}}styleSheet')
    formats = _node(styles, 'numFmts', count=5)
    for places in range(5):
        _node(formats, 'numFmt', numFmtId=164 + places,
              formatCode='#,##0' + ('.' + '0' * places if places else ''))
    fonts = _node(styles, 'fonts', count=4)
    for size, bold, color in ((10, False, '1F3A6A'), (14, True, '1F3A6A'),
                              (10, True, 'FFFFFF'), (10, True, '1F3A6A')):
        font = _node(fonts, 'font')
        _node(font, 'sz', val=size)
        _node(font, 'name', val='Microsoft YaHei')
        _node(font, 'color', rgb='FF' + color)
        if bold:
            _node(font, 'b')
    fills = _node(styles, 'fills', count=6)
    for pattern, color in (('none', None), ('gray125', None), ('solid', '2563EB'),
                           ('solid', 'FFFFFF'), ('solid', 'F6F7F9'), ('solid', 'E6F1FB')):
        fill = _node(_node(fills, 'fill'), 'patternFill', patternType=pattern)
        if color:
            _node(fill, 'fgColor', rgb='FF' + color)
            _node(fill, 'bgColor', indexed=64)
    borders = _node(styles, 'borders', count=2)
    for color in (None, 'D7DCE3'):
        border = _node(borders, 'border')
        for edge in ('left', 'right', 'top', 'bottom', 'diagonal'):
            side = _node(border, edge, **({'style': 'thin'} if color and edge != 'diagonal' else {}))
            if color and edge != 'diagonal':
                _node(side, 'color', rgb='FF' + color)
    _node(_node(styles, 'cellStyleXfs', count=1), 'xf', numFmtId=0, fontId=0, fillId=0, borderId=0)
    xfs = _node(styles, 'cellXfs')
    style_ids = {}

    def style(font=0, fill=3, border=1, align='left', places=None):
        key = font, fill, border, align, places
        if key not in style_ids:
            style_ids[key] = len(style_ids)
            xf = _node(xfs, 'xf', numFmtId=164 + places if places is not None else 0,
                       fontId=font, fillId=fill, borderId=border, xfId=0,
                       applyAlignment=1, applyNumberFormat=1)
            _node(xf, 'alignment', horizontal=align, vertical='center', wrapText=1)
        return style_ids[key]

    style(border=0)  # Normal style must occupy index zero.
    _node(_node(styles, 'cellStyles', count=1), 'cellStyle', name='Normal', xfId=0, builtinId=0)
    sheet = ET.Element(f'{{{MAIN}}}worksheet')
    last_column = _column(len(headers))
    last_row = len(rows) + 3
    _node(_node(sheet, 'sheetPr'), 'pageSetUpPr', fitToPage=1)
    _node(sheet, 'dimension', ref=f'A1:{last_column}{last_row}')
    view = _node(_node(sheet, 'sheetViews'), 'sheetView', workbookViewId=0, showGridLines=0)
    _node(view, 'pane', xSplit=3, ySplit=3, topLeftCell='D4', activePane='bottomRight', state='frozen')
    _node(view, 'selection', pane='bottomRight', activeCell='D4', sqref='D4')
    _node(sheet, 'sheetFormatPr', defaultRowHeight=34.5)
    columns = _node(sheet, 'cols')
    widths = snapshot['widths']
    for index, width in enumerate(widths, 1):
        _node(columns, 'col', min=index, max=index, width=width, customWidth=1)
    data = _node(sheet, 'sheetData')

    def cell(row, column, text, style_id, numeric=None):
        c = _node(row, 'c', r=f'{_column(column)}{row.get("r")}', s=style_id,
                  t='n' if numeric is not None else 'inlineStr')
        if numeric is not None:
            _node(c, 'v').text = format(numeric, 'f')
        else:
            value = _node(_node(c, 'is'), 't')
            value.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            value.text = text

    cell(_node(data, 'row', r=1, ht=26, customHeight=1), 1, snapshot['title'], style(font=1, border=0))
    meta_height = max(24, 15 * (1 + len(snapshot['meta']) // max(1, int(sum(widths) / 2))))
    cell(_node(data, 'row', r=2, ht=meta_height, customHeight=1), 1, snapshot['meta'], style(border=0))
    header_row = _node(data, 'row', r=3, ht=42, customHeight=1)
    for index, text in enumerate(headers, 1):
        cell(header_row, index, text, style(font=2, fill=2, align='center'))
    for row_index, values in enumerate(rows, 4):
        lines = 1
        for text, width in zip(values, widths):
            wrapped = 0
            for line in text.split('\n'):
                units = sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in line)
                wrapped += max(1, (units + max(1, int(width) - 2) - 1) // max(1, int(width) - 2))
            lines = max(lines, wrapped)
        row = _node(data, 'row', r=row_index, ht=min(409, max(34.5, lines * 15 + 8)), customHeight=1)
        total = row_index == last_row
        for column, text in enumerate(values):
            number = _numeric(text) if column in numeric_columns else None
            style_id = style(font=3 if total else 0, fill=5 if total else 4 if row_index % 2 else 3,
                             align='right' if column in numeric_columns else 'center'
                             if column == snapshot.get('unit_column', 5) else 'left',
                             places=min(number[1], 4) if number else None)
            cell(row, column + 1, text, style_id, number[0] if number else None)
    merges = _node(sheet, 'mergeCells', count=2)
    for row_index in (1, 2):
        _node(merges, 'mergeCell', ref=f'A{row_index}:{last_column}{row_index}')
    _node(sheet, 'pageMargins', left=.25, right=.25, top=.4, bottom=.4, header=.2, footer=.2)
    _node(sheet, 'pageSetup', paperSize=9, orientation='landscape', fitToWidth=1, fitToHeight=0)
    xfs.set('count', str(len(style_ids)))

    workbook = ET.Element(f'{{{MAIN}}}workbook')
    _node(_node(workbook, 'bookViews'), 'workbookView', activeTab=0)
    _node(_node(workbook, 'sheets'), 'sheet', name='成本明细', sheetId=1).set(f'{{{REL}}}id', 'rId1')
    names = _node(workbook, 'definedNames')
    _node(names, 'definedName', name='_xlnm.Print_Titles', localSheetId=0).text = "'成本明细'!$1:$3"
    _node(names, 'definedName', name='_xlnm.Print_Area', localSheetId=0).text = f"'成本明细'!$A$1:${last_column}${last_row}"
    types = ET.Element(f'{{{CONTENT}}}Types')
    for extension, content_type in (('rels', 'application/vnd.openxmlformats-package.relationships+xml'), ('xml', 'application/xml')):
        ET.SubElement(types, f'{{{CONTENT}}}Default', Extension=extension, ContentType=content_type)
    for name, part_type in (('workbook.xml', 'sheet.main'), ('styles.xml', 'styles'), ('worksheets/sheet1.xml', 'worksheet')):
        ET.SubElement(types, f'{{{CONTENT}}}Override', PartName='/xl/' + name,
                      ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.' + part_type + '+xml')

    def relationships(entries):
        root = ET.Element(f'{{{PACKAGE_REL}}}Relationships')
        for index, kind, target in entries:
            ET.SubElement(root, f'{{{PACKAGE_REL}}}Relationship', Id=index, Type=REL + '/' + kind, Target=target)
        return _xml(root)

    parts = {'[Content_Types].xml': _xml(types),
             '_rels/.rels': relationships([('rId1', 'officeDocument', 'xl/workbook.xml')]),
             'xl/workbook.xml': _xml(workbook), 'xl/styles.xml': _xml(styles),
             'xl/_rels/workbook.xml.rels': relationships([('rId1', 'worksheet', 'worksheets/sheet1.xml'),
                                                        ('rId2', 'styles', 'styles.xml')]),
             'xl/worksheets/sheet1.xml': _xml(sheet)}
    handle, temporary = tempfile.mkstemp(prefix='.cost-detail-', suffix='.xlsx.part', dir=output.parent)
    os.close(handle)
    try:
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED) as package:
            for name, content in parts.items():
                package.writestr(name, content)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output
