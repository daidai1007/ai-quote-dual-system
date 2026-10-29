import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanLedgerInput,ledgerDocuments,ledgerRecordKey} from '../api/contract_ledger_data.mjs';
import {ledgerFixture} from './helpers/contract_ledger_fixtures.mjs';

test('Nuoyue groups full contract numbers and retains ledger names, source serials and row ordering',()=>{
 const source=ledgerFixture(),docs=ledgerDocuments(cleanLedgerInput(source));
 assert.equal(docs.length,2);assert.equal(docs[0].quote.items.length,2);assert.equal(docs[0].quote.total,650.3);
 assert.deepEqual(docs[0].quote.items.map(r=>r.number),[1,2]);assert.deepEqual(docs[0].source_records.map(r=>r.serial),['001','002']);
 assert.equal(docs[0].quote.items[0].name,source.records[0].name);assert.equal(docs[1].quote.total,99.99);
 assert.equal(docs[0].contract_no,'SYNTHETIC-001');
});
test('Fangyuan selected serials with different old contract numbers form one independently numbered contract',()=>{
 const data=ledgerFixture('FANGYUAN');data.fields.contract_no='';
 assert.equal(ledgerDocuments(cleanLedgerInput(data),{requireFields:false}).length,1);
 assert.throws(()=>ledgerDocuments(cleanLedgerInput(data)),/填写方圆/);
 data.fields.contract_no='SYNTHETIC-MERGE-NEW';const [doc]=ledgerDocuments(cleanLedgerInput(data));
 assert.equal(doc.quote.total,650.3);assert.equal(doc.contract_no,'SYNTHETIC-MERGE-NEW');
 assert.equal(new Set(doc.source_records.map(r=>r.contract_no)).size,2);
});
test('manual remark, explicit empty remark and original ledger remark remain separate',()=>{
 const data=ledgerFixture(),original=structuredClone(data.records);
 data.remarks[data.records[0].record_id]='人工确认\n第二行备注';data.remarks[data.records[1].record_id]='';
 const doc=ledgerDocuments(cleanLedgerInput(data))[0];assert.equal(doc.quote.items[0].remark,'人工确认\n第二行备注');assert.equal(doc.quote.items[1].remark,'');
 assert.deepEqual(data.records,original);assert.equal(doc.quote.total,650.3);
});
test('empty contract groups, tampered source positions, duplicate record IDs and cross-customer sheets are rejected',()=>{
 const data=ledgerFixture();data.records[0].contract_no='';assert.throws(()=>cleanLedgerInput(data),/合同号/);
 const other=ledgerFixture();other.records[0].source_row=50;assert.throws(()=>cleanLedgerInput(other),/定位/);
 const repeated=ledgerFixture();repeated.records.push(repeated.records[0]);assert.throws(()=>cleanLedgerInput(repeated),/定位/);
 const wrong=ledgerFixture();wrong.records[0].sheet='方圆接手2026';assert.throws(()=>cleanLedgerInput(wrong),/工作表/);
});
test('ledger import cannot impersonate a quote source, owner, buyer or role',()=>{
 for(const injection of [{scheme_no:'BJ-20261029-000001'},{owner_user_id:'other'},{source_kind:'QUOTE'},{order_nature:'INTERNAL'}])
  assert.throws(()=>cleanLedgerInput({...ledgerFixture(),...injection}),/字段无效/);
 const data=ledgerFixture();data.fields.buyer_name='其他客户';assert.throws(()=>cleanLedgerInput(data),/人员权限/);
});
test('decimal arithmetic checks the imported subtotal without silently changing a price or dropping zero',()=>{
 const data=ledgerFixture();data.records[0].total='349.99';assert.throws(()=>cleanLedgerInput(data),/小计不一致/);
 const free=ledgerFixture();Object.assign(free.records[0],{unit_price:'0',total:'0'});assert.equal(ledgerDocuments(cleanLedgerInput(free))[0].quote.total,300.3);
 const missing=ledgerFixture();missing.records[0].unit_price='';assert.throws(()=>cleanLedgerInput(missing),/有效数值/);
 const fractional=ledgerFixture();Object.assign(fractional.records[0],{quantity:'0.125',unit_price:'0.05',total:'0.01'});
 assert.equal(ledgerDocuments(cleanLedgerInput(fractional))[0].quote.total,300.31);
});
test('signing date conflicts require a confirmed date, and invalid calendar dates fail',()=>{
 const data=ledgerFixture();data.records[1].source_date='2026-10-28';assert.throws(()=>ledgerDocuments(cleanLedgerInput(data)),/签订日期/);
 data.document_fields=[{contract_no:'SYNTHETIC-001',sign_date:'2026-10-29'}];assert.equal(ledgerDocuments(cleanLedgerInput(data))[0].sign_date,'2026-10-29');
 data.document_fields[0].sign_date='2026-02-30';assert.throws(()=>cleanLedgerInput(data),/日期/);
});
test('duplicate serials at different original rows retain different source identities',()=>{
 const data=ledgerFixture();data.records[1].serial=data.records[0].serial;
 const doc=ledgerDocuments(cleanLedgerInput(data))[0];assert.equal(doc.source_records.length,2);
 assert.notEqual(doc.source_records[0].record_id,doc.source_records[1].record_id);
 assert.notEqual(ledgerRecordKey(data.source.sha256,'诺玥科技',2),ledgerRecordKey(data.source.sha256,'诺玥科技',3));
});
