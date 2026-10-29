import {createHash} from 'node:crypto';
import {unzipSync,zipSync,strFromU8,strToU8} from 'fflate';
import {excelTemplate,wordTemplate} from './contract_fixtures.mjs';
import {ledgerRecordKey} from '../../api/contract_ledger_data.mjs';
export function ledgerFixture(customer='NUOYUE'){
 const hash=createHash('sha256').update('synthetic contract ledger, no user data').digest('hex');
 const sheet=customer==='NUOYUE'?'诺玥科技':'方圆接手2026';
 const row=(r,serial,contract,name,quantity,price,total)=>({record_id:ledgerRecordKey(hash,sheet,r),sheet,source_row:r,serial,
  contract_no:contract,source_date:'2026-10-29',delivery_date:'',name,specification:'800*600*1800',quantity,
  unit:'台',unit_price:price,total,remark:'本机合成原备注 '+serial});
 return {schema:1,customer_key:customer,source:{filename:'synthetic-ledger.xls',sha256:hash,size_bytes:1234},
  records:[row(2,'001','SYNTHETIC-001','本机合成产品甲','2','175','350'),row(3,'002',customer==='NUOYUE'?'SYNTHETIC-001':'SYNTHETIC-002','本机合成产品乙','3','100.10','300.30'),
    ...(customer==='NUOYUE'?[row(4,'003','SYNTHETIC-002','本机合成产品丙','1','99.99','99.99')]:[])],
  remarks:{},fields:customer==='NUOYUE'?{}:{contract_no:'SYNTHETIC-MERGED',sign_date:'2026-10-29'},document_fields:[],template_version_id:1};
}
export function ledgerExcelTemplate(){
 const files=unzipSync(excelTemplate());let sheet=strFromU8(files['xl/worksheets/sheet1.xml']);
 const cell=(address,text)=>`<c r="${address}" s="1" t="inlineStr"><is><t xml:space="preserve">${text}</t></is></c>`;
 sheet=sheet.replace(/<c r="G10"[\s\S]*?<\/c>/,cell('G10','{{total_amount}}'))
  .replace(/(<row r="8"[^>]*>)([\s\S]*?)(<\/row>)/,(_m,a,b,c)=>a+b+cell('H8','备注')+c)
  .replace(/(<row r="9"[^>]*>)([\s\S]*?)(<\/row>)/,(_m,a,b,c)=>a+b+cell('H9','{{item.remark}}')+c)
  .replace('</cols>','<col min="8" max="8" width="26" customWidth="1"/></cols>')
  .replace('A1:G13','A1:H13');
 files['xl/worksheets/sheet1.xml']=strToU8(sheet);
 files['xl/workbook.xml']=strToU8(strFromU8(files['xl/workbook.xml']).replace('$A$1:$G$13','$A$1:$H$13'));
 return Buffer.from(zipSync(files));
}
export function ledgerWordTemplate(){
 const files=unzipSync(wordTemplate());
 let index=0;
 files['word/document.xml']=strToU8(strFromU8(files['word/document.xml']).replace(/<w:tr>[\s\S]*?<\/w:tr>/g,row=>row.replace('</w:tr>',`<w:tc><w:p><w:r><w:t>${index++===0?'备注':'{{item.remark}}'}</w:t></w:r></w:p></w:tc></w:tr>`)));
 return Buffer.from(zipSync(files));
}
