import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import ExcelJS from '@excel.js/exceljs';
import {TAX_COST_BASIS,withTaxCostForItem} from '../tax_cost.mjs';
import {MANUFACTURING_COST_BASIS,manufacturingFormulaForItem,applyManagementFee,PRICING_BASIS} from '../quick_discount_rules.mjs';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {contractQuote} from '../api/contract_quote.mjs';
import {deliveryDocument} from '../api/quote_delivery_document.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
function source(quantity=1){
 const item={name:'合成税费测试柜',product_code:'JP',quantity,quick_discount:1,formula_discount:1,freight_fee:100,
  material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,specification:'800*600*1800',attachments:[],
  manufacturing_cost_basis:MANUFACTURING_COST_BASIS,tax_cost_basis:TAX_COST_BASIS,pricing_basis:PRICING_BASIS,
  quick:{base_price:900,total_cost:900,attachment_fee:0},formula:{material_cost:600,auxiliary_cost:0,labor_cost:0,spray_cost:0,attachment_fee:0}};
 item.formula=withTaxCostForItem(item,manufacturingFormulaForItem(item));
 item.quote_display={name:item.name,specification:item.specification,unit:'台',quantity,discount:1,unit_price:1000,total:1000*quantity,
  attachment_face_price:0,material_difference:0,quick_base_price:900,quick_attachment_fee:0,quick_total_cost:900,attachment_source:'popup_v1',attachments:[],remark:''};
 return item;
}
test('tax45 enters unit835 exactly once; gross excludes tax and management stays50',()=>{
 const item=source();assert.equal(item.formula.tax_cost_base,300);assert.equal(item.formula.tax_cost,45);
 assert.equal(item.formula.total_cost,735);assert.equal(item.formula.management_fee,50);
 assert.deepEqual(withTaxCostForItem(item),item.formula);assert.deepEqual(applyManagementFee(item.formula,100),item.formula);
 const before=item.formula.tax_cost;
 item.formula.labor_cost=200;item.formula=withTaxCostForItem(item,manufacturingFormulaForItem(item));
 assert.equal(item.formula.tax_cost,before,'labor is not a tax deduction');assert.equal(item.formula.total_cost,935);
 const cents={...source(3),freight_fee:0,quick:{base_price:.1,total_cost:.1,attachment_fee:0},
  formula:{material_cost:0,auxiliary_cost:0,labor_cost:0,spray_cost:0,attachment_fee:0}};
 cents.formula=withTaxCostForItem(cents,manufacturingFormulaForItem(cents));
 assert.equal(cents.formula.tax_cost,.02);assert.equal(cents.formula.tax_cost*3,.06,'round the unit expense before order quantity');
});
test('tax uses classified displayed material/auxiliary/attachment/spray columns',async()=>{
 const data=JSON.parse(await fs.readFile(new URL('./fixtures/formula_attachment_allocation.json',import.meta.url),'utf8'));
 const item={...source(),freight_fee:8,quick:{base_price:500,total_cost:613,attachment_fee:113},attachments:data.attachments,formula:data.formula};
 const formula=withTaxCostForItem(item,manufacturingFormulaForItem(item));
 assert.equal(formula.tax_cost_base,428);assert.equal(formula.tax_cost,64.2);
 assert.equal(formula.tax_cost_inputs.attachment_fee,12);assert.equal(formula.tax_cost_inputs.material_cost,135);
 assert.equal(formula.total_cost,342.09);
});
test('negative base is an explicit error; zero base is a valid zero expense',()=>{
 const item=source();item.quick_discount=.5;
 assert.throws(()=>withTaxCostForItem(item),error=>error.code==='NEGATIVE_BASE'&&error.statusCode===422&&/请核对/.test(error.message));
 item.quick.base_price=600;item.quick_discount=1;
 assert.equal(withTaxCostForItem(item).tax_cost,0);
});
test('API validates tax and recipient/contract keep the same frozen expense',async()=>{
 const item=source(2),service=createAttachmentService({runPsql:async()=>{throw Error('synthetic legacy row needs no SQL');}});
 const hydrated=await service.hydrateDocument({items:[item]});
 assert.equal(hydrated.items[0].formula.tax_cost,45);assert.equal(hydrated.items[0].formula.total_cost,735);
 await assert.rejects(service.hydrateDocument({items:[{...item,formula:{...item.formula,tax_cost:0}}]}),/税费.*不一致/);
 assert.equal(contractQuote({draft_items:[item]},'FORMULA').total,1670);
 const doc=deliveryDocument({draft_items:[item],document:{order_nature:'EXTERNAL'}},'LOCAL-TAX',1);
 assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf('税费')],45);
 const old=structuredClone(item);delete old.tax_cost_basis;old.formula={material_cost:600};
 assert.deepEqual(withTaxCostForItem(old),old.formula);
});
test('actual workbook records tax90 for two units, quick2000, formula1670 and no adjustment',async()=>{
 const base=path.join(root,'.codex-tmp');await fs.mkdir(base,{recursive:true});
 const folder=await fs.mkdtemp(path.join(base,'tax-cost-'));
 try{
  const input=path.join(folder,'input.json'),output=path.join(folder,'output.xlsx');
  await fs.writeFile(input,JSON.stringify({quote_id:'LOCAL-TAX',company_name:'合成测试客户',order_nature:'EXTERNAL',quotation_detail_layout:'vertical_v1',items:[source(2)]}));
  execFileSync(process.execPath,['export_dual_quote_workbook.mjs',input,output],{cwd:root,windowsHide:true,stdio:'pipe'});
  const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);
  assert.equal(book.getWorksheet('报价').getCell('G11').value,2000);
  assert.equal(book.getWorksheet('成本').getCell('F11').value,835);
  assert.equal(book.getWorksheet('成本').getCell('G11').value,1670);
  const taxes=[],adjustments=[];book.getWorksheet('成本明细').eachRow(row=>{if(row.getCell(4).value==='税费')taxes.push(row);if(row.getCell(4).value==='汇总调整')adjustments.push(row);});
  assert.equal(taxes.length,1);assert.equal(taxes[0].getCell(13).value,90);assert.equal(adjustments.length,0);
 }finally{assert(path.resolve(folder).startsWith(path.resolve(base)+path.sep));await fs.rm(folder,{recursive:true,force:true});}
});
