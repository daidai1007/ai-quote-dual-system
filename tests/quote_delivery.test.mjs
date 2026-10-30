import test from 'node:test';
import assert from 'node:assert/strict';
import ExcelJS from '@excel.js/exceljs';
import {deliveryDocument,deliveryWorkbook} from '../api/quote_delivery_document.mjs';

const snapshot={company:'本机示例客户 <A>',document:{quote_date:'2026-10-23',order_nature:'INTERNAL'},
  quote_management:{current:3,versions:[{version:1,items:[{private:'old'}]}]},
  drawing_path:'PRIVATE_PATH',scheme_summary:{quoted_amount:999},
  draft_items:[{formula:{material_cost:123456},quote_line_id:'PRIVATE_ID',quote_display:{name:'示例柜',specification:'400×300×200',quantity:2,unit:'台',unit_price:175,total:350,remark:'示例备注'}}]};

test('gross and net margins retain frozen values, and old snapshots have no invented net margin',()=>{
 const old=deliveryDocument(snapshot,'BJ-20261023-000001',3);
 assert.equal(old.cost_snapshot.items[0].columns[old.cost_snapshot.headers.indexOf('净利率')],null);
 assert.equal(old.cost_snapshot.items[0].columns[old.cost_snapshot.headers.indexOf('制造成本')],null);
 const current=structuredClone(snapshot);
 current.draft_items[0].quote_cost_display={schema:1,values:{毛利率:'50.00%',净利率:'40.00%',制造成本:'7.00',管理费用:'8.75',报价运费:'20.00',运费:'7.00'}};
 const doc=deliveryDocument(current,'BJ-20261023-000001',3);
 for(const [key,value] of Object.entries({毛利率:'50.00%',净利率:'40.00%',制造成本:'7.00',管理费用:'8.75',报价运费:'20.00',运费:'7.00'}))
  assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf(key)],value);
});

test('received fixed/discounted categories use the frozen version and an allowlist',()=>{
 const data=structuredClone(snapshot);
 data.draft_items[0].quote_cost_display={schema:1,values:{面价:'325.00',固定报价:'25.00',折扣面价:'150.00'},
  price_breakdown:{schema:1,basis:'per_unit_set_v1',private:'PRIVATE_BREAKDOWN',
   fixed:{total:25,rows:[{category:'运费',original:25,discount:1,amount:25,secret:'PRIVATE_ROW'}]},
   discounted:{total:150,rows:[{category:'柜体',original:300,discount:.5,amount:150}]}}};
 const doc=deliveryDocument(data,'BJ-20261023-000001',1);
 assert.equal(doc.cost_snapshot.items[0].price_breakdown.total,175);
 assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf('固定报价')],'25.00');
 assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf('折扣面价')],'150.00');
 assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf('面价')],'325.00','Older clients retain their existing wire field');
 assert.equal(JSON.stringify(doc).includes('PRIVATE_'),false);
 data.draft_items[0].quick={base_price:99999};
 assert.equal(deliveryDocument(data,'BJ-20261023-000001',1).cost_snapshot.items[0].price_breakdown.total,175);
 data.draft_items[0].quote_cost_display.price_breakdown.fixed.rows[0].amount=99;
 assert.equal(deliveryDocument(data,'BJ-20261023-000001',1).cost_snapshot.items[0].price_breakdown,null);
 assert.equal(deliveryDocument(snapshot,'BJ-20261023-000001',1).cost_snapshot.items[0].price_breakdown,null);
});

test('delivery preserves formal face and same-version costs, without history or source IDs',()=>{
 const d=deliveryDocument(snapshot,'BJ-20261023-000001',2);
 assert.equal(d.total,350);assert.equal(d.quote_version,3);assert.equal(d.source_version_no,2);assert.equal(d.order_nature,'INTERNAL');
 assert.equal(d.items[0].unit_price,175);assert.equal(d.items[0].total,350);
 const text=JSON.stringify(d);for(const value of ['PRIVATE_ID','PRIVATE_PATH','versions','attachments'])assert.ok(!text.includes(value),value);
 assert.equal(d.cost_snapshot.items[0].columns[d.cost_snapshot.headers.indexOf('材料成本')],123456);
 assert.equal(d.cost_snapshot.items[0].columns[d.cost_snapshot.headers.indexOf('管理费用')],null);
 assert.equal(snapshot.scheme_summary.quoted_amount,999);
});
test('delivery rejects unclassified formal face and inconsistent prices without zero-fill',()=>{
 assert.throws(()=>deliveryDocument({...snapshot,document:{order_nature:'UNCLASSIFIED'}},'BJ-20261023-000001',1));
 const broken=structuredClone(snapshot);broken.draft_items[0].quote_display.total=351;
 assert.throws(()=>deliveryDocument(broken,'BJ-20261023-000001',1),/不一致/);
 delete broken.draft_items[0].quote_display.unit_price;
 assert.throws(()=>deliveryDocument(broken,'BJ-20261023-000001',1),/未确定/);
});
test('real recipient Excel uses fixed version, nature and amount and has no cost sheet',async()=>{
 const d=deliveryDocument(snapshot,'BJ-20261023-000001',2);
 const book=new ExcelJS.Workbook();await book.xlsx.load(await deliveryWorkbook(d));
 assert.deepEqual(book.worksheets.map(s=>s.name),['报价单']);const sheet=book.worksheets[0];
 for(const [cell,value] of [['B2',d.scheme_no],['E2','V3'],['B3','内部'],['E3',350],['B4',snapshot.company],['F10',175],['G10',350],['G11',350]])assert.equal(sheet.getCell(cell).value,value,cell);
 assert.equal(sheet.getCell('H10').value,'示例备注');
});
