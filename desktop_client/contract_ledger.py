"""Read customer ledgers without Excel automation, calculation, or source writes.

Only the selected customer's business sheets are retained. Saved drafts contain
selected rows, their origin and original remarks; never a copy of the workbook.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
import re
from typing import Any
import zipfile
from xml.etree import ElementTree as ET

CUSTOMERS = {
    'NUOYUE': {'name': '杭州诺玥科技有限公司', 'sheet': '诺玥科技', 'group_by': 'contract_no'},
    'FANGYUAN': {'name': '杭州方圆塑机股份有限公司', 'sheet_prefix': '方圆接手', 'group_by': 'record'},
}
LIMITS = dict(file_bytes=64*1024*1024, xml_bytes=256*1024*1024, sheets=80,
              rows=200000, records=50000, selected=2000, contract_rows=500)
MONEY = Decimal('0.01')
ALIASES = {
    'serial': ('序号',), 'name': ('名称', '产品名称'),
    'specification': ('规格型号（W*H*D）', '规格型号(W*H*D)', '规格型号', '尺寸', '型号'),
    'quantity': ('数量',), 'unit': ('单位',),
    'unit_price': ('含税单价（元）', '含税单价(元)', '含税单价', '单价'),
    'total': ('小计（元）', '小计(元)', '小计', '含税总价', '金额'),
    'remark': ('备注',), 'contract_no': ('钉钉合同号', '京能合同号'),
    'source_date': ('签合同日期', '下单日期'), 'delivery_date': ('交期', '计划交期'),
}


class LedgerError(ValueError):
    pass


def header_text(value):
    return re.sub(r'\s+', '', str(value or '')).replace('（', '(').replace('）', ')').casefold()


def column_name(index):
    result = ''
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(65+remainder)+result
        index -= 1
    return result


def decimal_text(value, places=6):
    if value is None or value == '' or isinstance(value, bool):
        raise LedgerError('数值缺失')
    try:
        number = Decimal(str(value).strip().replace(',', ''))
    except InvalidOperation:
        raise LedgerError('数值格式无效') from None
    if not number.is_finite() or abs(number) >= Decimal('1000000000000'):
        raise LedgerError('数值超出支持范围')
    if number == 0:
        return '0'
    normalized = format(number.normalize(), 'f')
    if '.' in normalized and len(normalized.split('.')[1]) > places:
        # Excel doubles may carry a binary tail beyond the visible precision.
        rounded = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if abs(number-rounded) > Decimal('0.000000001'):
            raise LedgerError('数值精度超出支持范围')
        normalized = format(rounded.normalize(), 'f')
    return normalized


def identifier(value, number_format=''):
    if value is None or value == '':
        return ''
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        text = decimal_text(value, 6)
        if re.fullmatch(r'0+', number_format) and '.' not in text:
            return text.zfill(len(number_format))
        return text
    return str(value).strip().replace('\r\n', '\n')


def date_text(value):
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value or '').strip()
    if not text:
        return ''
    match = re.fullmatch(r'(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?(?:[ T].*)?', text)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return ''


def find_header(get_values, row_count, customer_key):
    required = ('serial', 'name', 'specification', 'quantity', 'unit', 'unit_price', 'total', 'remark')
    if customer_key == 'NUOYUE':
        required += ('contract_no',)
    for row in range(min(20, row_count)):
        values = [header_text(v) for v in get_values(row)]
        mapping = {}
        for field, aliases in ALIASES.items():
            choices = aliases
            if field == 'contract_no' and customer_key == 'FANGYUAN':
                choices = ('京能合同号', '钉钉合同号')
            for alias in choices:
                indices = [i for i, v in enumerate(values) if v == header_text(alias)]
                if indices:
                    mapping[field] = indices[0]
                    break
        if all(field in mapping for field in required):
            remark_indices = [i for i, v in enumerate(values) if v == header_text('备注')]
            after_amount = [i for i in remark_indices if i > mapping['total']]
            mapping['remark'] = min(after_amount or remark_indices)
            warnings = ['存在同名备注列，读取产品明细旁的 '+column_name(mapping['remark'])+' 列备注。'] if len(remark_indices)>1 else []
            return row, mapping, warnings
    raise LedgerError('未找到完整台账表头，请核对序号、名称、规格、数量、单位、含税单价、小计和备注列。')


def record_key(file_hash, sheet, row):
    return sha256((file_hash+'|'+sheet+'|'+str(row)).encode('utf-8')).hexdigest()


def _record(file_hash, sheet, excel_row, mapping, values, formats):
    get = lambda key: values[mapping[key]] if key in mapping and mapping[key] < len(values) else ''
    serial = identifier(get('serial'), formats.get(mapping['serial'], ''))
    if not serial or not re.search(r'\d', serial):
        return None
    if not any(get(key) not in ('', None) for key in ('name', 'specification', 'quantity', 'unit_price', 'total')):
        return None
    row = dict(record_id=record_key(file_hash, sheet, excel_row), sheet=sheet, source_row=excel_row,
               serial=serial, contract_no=identifier(get('contract_no'), formats.get(mapping.get('contract_no'), '')),
               source_date=date_text(get('source_date')), delivery_date=date_text(get('delivery_date')),
               name=str(get('name') or '').strip(), specification=str(get('specification') or '').strip(),
               unit=str(get('unit') or '').strip(), remark=str(get('remark') or '').replace('\r\n','\n'), issues=[])
    if any(get(key)=='[Excel公式错误]' for key in mapping):
        row['issues'].append('台账含 Excel 公式错误，请核对后重新读取')
    for field, places in [('quantity',4),('unit_price',6),('total',2)]:
        try:
            row[field] = decimal_text(get(field), places)
        except LedgerError as error:
            row[field] = ''
            row['issues'].append({'quantity':'数量','unit_price':'含税单价','total':'小计'}[field]+'：'+str(error))
    if not row['name']:
        row['issues'].append('产品名称缺失')
    if not row['unit']:
        row['issues'].append('单位缺失')
    if row['quantity'] and Decimal(row['quantity']) <= 0:
        row['issues'].append('数量必须大于 0')
    if any(row[k] and Decimal(row[k]) < 0 for k in ('unit_price','total')):
        row['issues'].append('单价和小计不能为负数')
    if all(row[k] for k in ('quantity','unit_price','total')):
        expected=(Decimal(row['quantity'])*Decimal(row['unit_price'])).quantize(MONEY,rounding=ROUND_HALF_UP)
        if expected != Decimal(row['total']).quantize(MONEY,rounding=ROUND_HALF_UP):
            row['issues'].append('数量×单价与台账小计不一致，请核对')
    return row


def _sheet_matches(name, customer_key):
    item = CUSTOMERS[customer_key]
    text = str(name).strip()
    return text == item.get('sheet') or bool(item.get('sheet_prefix') and
        re.fullmatch(re.escape(item['sheet_prefix'])+r'\d{4}', text))


def read_ledger(path, customer_key):
    """Return typed normalized records, never save or recalculate the workbook."""
    if customer_key not in CUSTOMERS:
        raise LedgerError('请选择支持的客户')
    path = Path(path)
    if path.suffix.lower() not in ('.xls','.xlsx') or path.name.startswith('~$'):
        raise LedgerError('请选择 Excel 台账文件（XLS 或 XLSX）')
    if not path.is_file() or not 0 < path.stat().st_size <= LIMITS['file_bytes']:
        raise LedgerError('台账不存在、为空或超过 64MB')
    original_stat = path.stat()
    data = path.read_bytes()
    digest = sha256(data).hexdigest()
    result = dict(schema=1,customer_key=customer_key,customer_name=CUSTOMERS[customer_key]['name'],
                  source=dict(filename=path.name,sha256=digest,size_bytes=len(data)),sheets=[],records=[])
    if data[:8] == bytes.fromhex('d0cf11e0a1b11ae1'):
        try:
            import xlrd
        except ImportError:
            raise LedgerError('缺少 Excel 台账读取组件，请使用包含台账合同功能的客户端版本。') from None
        book = xlrd.open_workbook(file_contents=data,on_demand=True,formatting_info=True)
        try:
            if book.nsheets > LIMITS['sheets']:
                raise LedgerError('台账工作表过多，请选择对应客户的台账')
            for index, name in enumerate(book.sheet_names()):
                if not _sheet_matches(name, customer_key):
                    continue
                sheet=book.sheet_by_index(index)
                if sheet.nrows>LIMITS['rows']:
                    raise LedgerError('工作表超过本次可读取的行数限制')
                header,mapping,warnings=find_header(sheet.row_values,sheet.nrows,customer_key)
                count=0
                for r in range(header+1,sheet.nrows):
                    if sheet.cell_value(r,mapping['serial']) in ('',None):
                        continue
                    values=[];formats={}
                    for c in range(max(mapping.values())+1):
                        cell=sheet.cell(r,c);value=cell.value
                        if cell.ctype==xlrd.XL_CELL_ERROR:
                            value='[Excel公式错误]'
                        if cell.ctype==xlrd.XL_CELL_BOOLEAN and c in [mapping[k] for k in ('quantity','unit_price','total')]:
                            value='[数值格式无效]'
                        if cell.ctype==xlrd.XL_CELL_DATE:
                            try:value=xlrd.xldate_as_datetime(value,book.datemode)
                            except (ValueError,OverflowError):value=''
                        values.append(value)
                        formats[c]=book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                    row=_record(digest,name,r+1,mapping,values,formats)
                    if row is not None:result['records'].append(row);count+=1
                result['sheets'].append(dict(name=name,header_row=header+1,record_count=count,
                    columns={k:column_name(v) for k,v in mapping.items()},warnings=warnings))
                book.unload_sheet(index)
        finally:
            book.release_resources()
    elif data[:2] == b'PK':
        _read_xlsx(data,digest,customer_key,result)
    else:
        raise LedgerError('文件内容不是支持的 Excel 台账')
    if len(result['records']) > LIMITS['records']:
        raise LedgerError('有效记录过多，请按客户和时期拆分台账')
    if not result['sheets']:
        raise LedgerError('未找到所选客户的工作表，请核对台账文件')
    if not result['records']:
        raise LedgerError('所选客户的工作表中没有可用序号记录')
    if customer_key=='NUOYUE':
        for row in result['records']:
            if not row['contract_no']:
                row['issues'].append('钉钉合同号缺失，不能合并到空合同号中')
    serials=Counter((r['sheet'],r['serial']) for r in result['records'])
    result['duplicate_serial_records']=sum(serials[(r['sheet'],r['serial'])]>1 for r in result['records'])
    after=path.stat()
    if after.st_size!=original_stat.st_size or after.st_mtime_ns!=original_stat.st_mtime_ns:
        raise LedgerError('台账在读取期间发生变化，请保存文件后重新读取')
    return result


def _read_xlsx(data,digest,customer_key,result):
    from io import BytesIO
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    def parse(raw):
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise LedgerError('台账 XML 声明不支持')
        return ET.fromstring(raw)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        entries=archive.infolist()
        if len(entries)>3000 or sum(e.file_size for e in entries)>LIMITS['xml_bytes']:
            raise LedgerError('台账解压后内容过大')
        names=set(archive.namelist())
        required={'xl/workbook.xml','xl/_rels/workbook.xml.rels'}
        if not required <= names:raise LedgerError('工作簿结构不完整')
        strings=[]
        if 'xl/sharedStrings.xml' in names:
            strings=[''.join(t.text or '' for t in n.findall('.//s:t',ns)) for n in parse(archive.read('xl/sharedStrings.xml')).findall('s:si',ns)]
        book=parse(archive.read('xl/workbook.xml'))
        links={n.attrib['Id']:n.attrib.get('Target','') for n in parse(archive.read('xl/_rels/workbook.xml.rels'))
               if n.attrib.get('TargetMode')!='External'}
        epoch=date(1904,1,1) if (book.find('s:workbookPr',ns) is not None and book.find('s:workbookPr',ns).attrib.get('date1904') in ('1','true')) else date(1899,12,30)
        sheets=book.findall('s:sheets/s:sheet',ns)
        if len(sheets)>LIMITS['sheets']:raise LedgerError('台账工作表过多')
        for sheet in sheets:
            name=sheet.attrib.get('name','')
            if not _sheet_matches(name,customer_key):continue
            target=links.get(sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'),'')
            part=target.lstrip('/') if target.startswith('/') else 'xl/'+target.removeprefix('./')
            if '..' in part.split('/') or part not in names:raise LedgerError('工作表路径无效')
            rows={}
            for node in parse(archive.read(part)).findall('s:sheetData/s:row',ns):
                row_no=int(node.attrib.get('r','0'))
                if not 1<=row_no<=LIMITS['rows']:raise LedgerError('工作表行号超出限制')
                values={}
                for cell in node.findall('s:c',ns):
                    address=re.fullmatch(r'([A-Z]{1,3})\d+',cell.attrib.get('r',''))
                    if not address:continue
                    c=0
                    for ch in address[1]:c=c*26+ord(ch)-64
                    value=cell.findtext('s:v',default='',namespaces=ns);kind=cell.attrib.get('t')
                    if kind=='s':value=strings[int(value)]
                    elif kind=='inlineStr':value=''.join(cell.find('s:is',ns).itertext())
                    elif kind=='e':value='[Excel公式错误]'
                    elif kind=='b':value=bool(int(value or '0'))
                    elif kind not in ('str','d','b') and value!='':
                        try:value=Decimal(value)
                        except InvalidOperation:pass
                    values[c-1]=value
                rows[row_no-1]=values
            row_count=max(rows,default=-1)+1
            get_values=lambda r:[rows.get(r,{}).get(c,'') for c in range(max(rows.get(r,{}),default=-1)+1)]
            header,mapping,warnings=find_header(get_values,row_count,customer_key)
            count=0
            for r,raw in sorted(rows.items()):
                if r<=header:continue
                values=get_values(r)
                for field in ('source_date','delivery_date'):
                    if field in mapping and mapping[field]<len(values) and isinstance(values[mapping[field]],Decimal):
                        try:values[mapping[field]]=epoch+timedelta(days=float(values[mapping[field]]))
                        except (ValueError,OverflowError):values[mapping[field]]=''
                row=_record(digest,name,r+1,mapping,values,{})
                if row is not None:result['records'].append(row);count+=1
            result['sheets'].append(dict(name=name,header_row=header+1,record_count=count,
                columns={k:column_name(v) for k,v in mapping.items()},warnings=warnings))


def contract_groups(imported, sheet=None):
    records=[r for r in imported['records'] if sheet is None or r['sheet']==sheet]
    if imported['customer_key']=='FANGYUAN':
        return [dict(key=r['record_id'],number=r['serial'],records=[r],issues=r['issues']) for r in records]
    grouped={}
    for row in records:
        key=row['contract_no'] or 'missing:'+row['record_id']
        group=grouped.setdefault(key,dict(key=key,number=row['contract_no'],records=[],issues=[]))
        group['records'].append(row)
        group['issues'].extend(row['issues'])
    return list(grouped.values())


def selected_payload(imported, selected_keys, remarks=None, fields=None, document_fields=None, sheet=None):
    selected=set(selected_keys)
    groups=[g for g in contract_groups(imported,sheet) if g['key'] in selected]
    if not groups or len(groups)!=len(selected):raise LedgerError('请选择有效的台账记录')
    rows=[row for group in groups for row in group['records']]
    if len(rows)>LIMITS['selected']:raise LedgerError('本次选择记录过多，请分批生成')
    if any(g['issues'] for g in groups):raise LedgerError('所选记录存在缺失或金额差异，请先核对台账')
    if imported['customer_key']=='NUOYUE' and any(len(g['records'])>LIMITS['contract_rows'] for g in groups):
        raise LedgerError('单份合同超过 500 行，请核对合同号分组')
    if imported['customer_key']=='FANGYUAN' and len(rows)>LIMITS['contract_rows']:
        raise LedgerError('单份合同超过 500 行，请分批选择')
    row_ids={r['record_id'] for r in rows}
    clean_remarks={key:value for key,value in (remarks or {}).items() if key in row_ids}
    return dict(schema=1,customer_key=imported['customer_key'],source=imported['source'],
        records=[{key:value for key,value in row.items() if key!='issues'} for row in rows],
        remarks=clean_remarks,fields=fields or {},document_fields=document_fields or [])


def reopen_import(payload):
    if payload.get('schema')!=1 or payload.get('customer_key') not in CUSTOMERS:
        raise LedgerError('台账合同草稿格式不支持')
    records=[{**row,'issues':[]} for row in payload.get('records',[])]
    sheets=list(dict.fromkeys(r['sheet'] for r in records))
    return dict(schema=1,customer_key=payload['customer_key'],customer_name=CUSTOMERS[payload['customer_key']]['name'],
                source=payload['source'],records=records,sheets=[dict(name=s,header_row=0,record_count=sum(r['sheet']==s for r in records),columns={},warnings=[]) for s in sheets],
                duplicate_serial_records=0)
