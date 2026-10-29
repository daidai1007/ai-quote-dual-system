from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop_client'))
from contract_ledger import read_ledger,contract_groups,selected_payload,reopen_import,LedgerError,decimal_text
from contract_ledger_test_data import write_ledger

class LedgerReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ledger-reader-');self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)

    def test_xls_nuoyue_groups_and_immutable_original_and_reopen(self):
        path=write_ledger(self.folder/'synthetic.xls');before=sha256(path.read_bytes()).hexdigest();stat=path.stat()
        data=read_ledger(path,'NUOYUE');self.assertEqual(len(data['records']),3);self.assertEqual(len(data['sheets']),1)
        self.assertEqual(data['records'][0]['serial'],'001');self.assertEqual(data['records'][0]['remark'],' 原备注 1\n第二行 ')
        groups=contract_groups(data);self.assertEqual([len(g['records']) for g in groups],[2,1]);self.assertFalse(groups[0]['issues'])
        id=data['records'][0]['record_id'];payload=selected_payload(data,[groups[0]['key']],{id:'修改后的备注'})
        self.assertEqual(len(payload['records']),2);self.assertEqual(payload['records'][0]['remark'],' 原备注 1\n第二行 ')
        self.assertEqual(payload['remarks'][id],'修改后的备注');self.assertEqual(sha256(path.read_bytes()).hexdigest(),before);self.assertEqual(path.stat().st_mtime_ns,stat.st_mtime_ns)
        path.unlink();restored=reopen_import(payload);self.assertEqual(len(restored['records']),2);self.assertEqual(restored['source']['sha256'],before)

    def test_fangyuan_row2_header_and_detail_remark_column(self):
        data=read_ledger(write_ledger(self.folder/'synthetic.xls','FANGYUAN'),'FANGYUAN')
        self.assertEqual(data['sheets'][0]['header_row'],2);self.assertEqual(data['sheets'][0]['columns']['remark'],'N')
        self.assertTrue(data['sheets'][0]['warnings']);self.assertEqual(data['records'][0]['remark'],'产品备注1')
        groups=contract_groups(data);payload=selected_payload(data,[groups[0]['key'],groups[2]['key']]);self.assertEqual([r['serial'] for r in payload['records']],['001','003'])

    def test_invalid_amount_blocked_and_duplicate_serials_kept(self):
        data=read_ledger(write_ledger(self.folder/'synthetic.xls',bad=True),'NUOYUE');groups=contract_groups(data)
        self.assertTrue(groups[0]['issues'])
        with self.assertRaises(LedgerError):selected_payload(data,[groups[0]['key']])
        duplicate=deepcopy(data);duplicate['records'][2]['serial']=duplicate['records'][0]['serial']
        self.assertNotEqual(duplicate['records'][2]['record_id'],duplicate['records'][0]['record_id'])
        self.assertEqual(decimal_text(0),'0')
        with self.assertRaises(LedgerError):decimal_text(True)

    def test_xlsx_cached_formula_and_missing_cache(self):
        header=['序号','客户名称','签合同日期','钉钉合同号','名称','柜型','规格型号（W*H*D）','柜体颜色','数量','单位','含税单价（元）','小计（元）','交期','备注']
        def make(path,cache):
            from xml.sax.saxutils import escape
            def row(n,values):
                cells=[]
                for i,value in enumerate(values):
                    column=chr(65+i);cells.append(f'<c r="{column}{n}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                return f'<row r="{n}">'+''.join(cells)+'</row>'
            source=row(1,header)+row(2,['1','','2026-10-29','SYNTHETIC','合成产品','','800*600*1800','',2,'台',175,350,'','缓存备注'])
            source=source.replace('<c r="L2" t="inlineStr"><is><t>350</t></is></c>',f'<c r="L2"><f>I2*K2</f>{"<v>350</v>" if cache else ""}</c>')
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="诺玥科技" sheetId="1" r:id="rId1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+source+'</sheetData></worksheet>')
        path=self.folder/'synthetic.xlsx';make(path,True);self.assertFalse(read_ledger(path,'NUOYUE')['records'][0]['issues'])
        make(path,False);self.assertTrue(read_ledger(path,'NUOYUE')['records'][0]['issues'])

if __name__=='__main__':unittest.main(verbosity=2)
