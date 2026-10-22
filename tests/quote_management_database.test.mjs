// Disposable loopback cluster, synthetic quote data; never use service settings.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('historical quote export preserves latest draft, lock and frozen document', {timeout:180000}, async t=>{
  const pg=await startLocalPostgres();
  try {
    pg.query('CREATE SCHEMA calc;');
    pg.query(await readFile(new URL('../database/migrations/quote_scheme_center_v1.sql',import.meta.url),'utf8'));
    const literal=v=>v==null?'NULL':`'${String(v).replaceAll("'","''")}'`;
    const service=createQuoteSchemeService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:literal,sqlNumber:v=>String(Number(v))});
    const owner={userId:'qm-local-owner',displayName:'本机测试人员',role:'USER'};
    const other={userId:'qm-local-other',displayName:'其他人员',role:'USER'};
    const oldItems=[{name:'历史测试柜',quantity:3,quoted_total:3204}];
    const newItems=[{name:'最新测试柜',quantity:3,quoted_total:3300.03}];
    const snapshot={company:'新客户',draft_items:newItems,
      scheme_summary:{company:'新客户',product_summary:'JQ',quoted_amount:3300.03},
      quote_management:{schema:1,current:2,versions:[
        {version:1,company:'原客户',items:oldItems}, {version:2,company:'新客户',items:newItems}]}};
    const created=await service.create(owner,{snapshot,operator_name:'本机测试人员'});
    const no=created.scheme_no, before=await service.get(owner,no);
    assert.equal(before.quote_management_historical_export,true);
    const listed=await service.list(owner,{search:'新客户'});
    assert.equal(listed.total,1); assert.equal(listed.items[0].quote_version,2);
    assert.equal((await service.list(other,{search:'新客户'})).total,0);
    assert.equal((await service.list(owner,{search:'JQ'})).total,1);
    const payload={kind:'XLSX',succeeded:true,expected_version:1,historical_quote_version:1,
      operator_name:'本机测试人员',snapshot:{company:'原客户',draft_items:oldItems,
        document:{export_registration_id:'local-history-only'},
        scheme_summary:{company:'原客户',product_summary:'JQ',quoted_amount:3204}}};
    await t.test('history export logs success without finalizing latest',async()=>{
      const result=await service.exportResult(owner,no,payload);
      assert.deepEqual(result,{recorded:true,formal_success:true,historical:true,status:'DRAFT',lock_version:1});
      assert.deepEqual(await service.get(owner,no),before);
      assert.equal(Number(pg.query(`SELECT count(*) FROM calc.quote_scheme_version;`)),0);
      assert.equal(Number(pg.query(`SELECT count(*) FROM calc.quote_scheme_export;`)),1);
    });
    await t.test('wrong owner, stale lock, current version and forged contents fail',async()=>{
      await assert.rejects(()=>service.exportResult(other,no,payload),e=>e.statusCode===409);
      for(const altered of [
        {...payload,expected_version:2}, {...payload,historical_quote_version:2},
        {...payload,snapshot:{...payload.snapshot,company:'伪造客户'}},
        {...payload,snapshot:{...payload.snapshot,draft_items:[{name:'伪造金额',quantity:1,quoted_total:1}]}},
      ]) await assert.rejects(()=>service.exportResult(owner,no,altered),e=>e.statusCode===409);
      await assert.rejects(()=>service.exportResult(owner,no,{...payload,historical_quote_version:0}),e=>e.statusCode===400);
      assert.deepEqual(await service.get(owner,no),before);
      assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_scheme_export;')),1);
    });
    await t.test('ordinary final export and later historical export remain separate',async()=>{
      await service.exportResult(owner,no,{kind:'XLSX',succeeded:true,expected_version:1,operator_name:'本机测试人员',snapshot:before.snapshot});
      const official=await service.get(owner,no);
      assert.equal(official.status,'QUOTED'); assert.equal(official.lock_version,2);
      await service.exportResult(owner,no,{...payload,expected_version:2});
      assert.deepEqual(await service.get(owner,no),official);
    });
  } finally { await pg.close(); }
});
