"""Actual multipage DOCX/XLSX conversion, totals and repeat headers; fake data."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from contract_management import preview_office
from pypdf import PdfReader

class OfficePreview(unittest.TestCase):
    def test_multi_page_files(self):
        directory=ROOT/'test-output/contracts-office-preview';directory.mkdir(parents=True,exist_ok=True)
        script="""
import fs from 'node:fs/promises';
import {wordTemplate,excelTemplate,sampleQuote,sampleValues,mapped} from './tests/helpers/contract_fixtures.mjs';
import {inspectContractTemplate,renderContractTemplate} from './api/contract_document.mjs';
import {upperRmb} from './api/contract_quote.mjs';
const items=Array.from({length:120},(_,i)=>({...sampleQuote.items[i%2],number:i+1,name:'LOCAL-PRODUCT-'+(i+1)}));
const values={...sampleValues,total_amount:39018,total_upper:upperRmb(39018)};
for(const [format,make]of [['docx',wordTemplate],['xlsx',excelTemplate]]){
 const before=make();await fs.writeFile('test-output/contracts-office-preview/artificial.'+format,renderContractTemplate(before,format,mapped(inspectContractTemplate(before,format),format),values,items));
}
"""
        subprocess.run([shutil.which('node'),'--input-type=module','-e',script],cwd=ROOT,check=True,capture_output=True,timeout=30)
        poppler=ROOT.parent/'AIQuoteDualSystem/runtime/poppler/bin/pdftoppm.exe'
        for format in ('docx','xlsx'):
            with self.subTest(format=format):
                result=preview_office(directory/('artificial.'+format),directory/format,str(poppler))
                pdf=PdfReader(result['pdf']);self.assertGreater(len(pdf.pages),1)
                texts=[p.extract_text() for p in pdf.pages];whole=''.join(texts).replace(',','').replace(' ','').replace('\n','')
                self.assertIn('39018',whole);self.assertIn('LOCAL-PRODUCT-120'.replace('-',''),whole.replace('-',''))
                self.assertEqual(len(result['pages']),len(pdf.pages))
                if format=='docx':
                    self.assertIn('产品',texts[1]);self.assertIn('人工模板页眉',texts[-1].replace(' ',''))
                print(format,len(pdf.pages),'pages; total 39018 verified',flush=True)

if __name__=='__main__':unittest.main(verbosity=2)
