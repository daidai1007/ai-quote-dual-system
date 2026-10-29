"""Artificial ledgers only. No customer orders or original workbooks copied."""
from pathlib import Path
import xlwt

def write_ledger(path,customer='NUOYUE',bad=False):
    book=xlwt.Workbook();sheet=book.add_sheet('诺玥科技' if customer=='NUOYUE' else '方圆接手2025')
    ny=customer=='NUOYUE';header_row=0 if ny else 1
    header=['序号','客户名称','签合同日期','钉钉合同号','名称','柜型','规格型号（W*H*D）','柜体颜色','数量','单位','含税单价（元）','小计（元）','交期','备注'] if ny else ['序号','客户名称','下单日期','客户订单号','京能合同号','名称','柜型','规格型号（W*H*D）','柜体颜色','数量','单位','含税单价（元）','小计（元）','备注','','','','','','','备注']
    for c,v in enumerate(header):sheet.write(header_row,c,v)
    for i,(quantity,price,total) in enumerate(((2,175,350),(3,100.1,300.3),(1,99.99,99.99))):
        number='SYNTHETIC-001' if i<2 else 'SYNTHETIC-002'
        values=[i+1,'本机合成客户','2026-10-29',number,'本机合成产品'+str(i+1),'','800*600*1800','',quantity,'台',price,total,'',' 原备注 '+str(i+1)+'\n第二行 '] if ny else [i+1,'本机合成客户','2026-09-01','SRC-'+str(i+1),number,'本机合成产品'+str(i+1),'','800*600*1800','',quantity,'台',price,total,'产品备注'+str(i+1),'','','','','','','另一备注禁止读取']
        if bad and i==1:values[11 if ny else 12]='待确认'
        for c,v in enumerate(values):sheet.write(header_row+i+1,c,v,xlwt.easyxf(num_format_str='000') if c==0 else xlwt.Style.default_style)
    sheet.write(5000,0,'',xlwt.easyxf('pattern: pattern solid, fore_colour white;'))
    book.add_sheet('无关订单表').write(0,0,'不读取本表')
    book.save(str(path));return Path(path)
