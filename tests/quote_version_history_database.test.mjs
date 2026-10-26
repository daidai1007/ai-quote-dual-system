// Disposable loopback database only; no production connection or customer data.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

const literal=value=>value==null?'NULL':`'${String(value).replaceAll("'","''")}'`;
const owner={userId:'local-history-owner',displayName:'本机历史测试人员',role:'USER'};
const other={userId:'local-history-other',displayName:'其他合成人员',role:'USER'};
const entry=version=>({version,company:'合成历史测试客户',items:[{name:'合成柜',product_code:'JE_SINGLE',quantity:2,quoted_total:version*2}],
  amount:version*2,operator:'本机历史测试人员',reason:`第${version}轮`,quote_date:'2026-10-26',updated_at:'2026-10-26T10:00:00',sealed:true,confirmed:true,order_nature:'EXTERNAL'});
const snapshot=versions=>({company:'合成历史测试客户',document:{order_nature:'EXTERNAL'},
  draft_items:structuredClone(versions.at(-1).items),quote_management:{schema:1,current:versions.length,versions:structuredClone(versions)},
  scheme_summary:{company:'合成历史测试客户',product_summary:'JE',quoted_amount:versions.at(-1).amount}});

test('all saved price versions and formal revisions survive real SQL without schema changes',{timeout:180000},async t=>{
  const pg=await startLocalPostgres();
  try{
    pg.query('CREATE SCHEMA calc;');
    pg.query(await readFile(new URL('../database/migrations/quote_scheme_center_v1.sql',import.meta.url),'utf8'));
    const service=createQuoteSchemeService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:literal,sqlNumber:value=>String(Number(value))});
    const created=await service.create(owner,{operator_name:owner.displayName,snapshot:snapshot([entry(1)])});
    const no=created.scheme_no;let lock=created.lock_version;const versions=[];
    await t.test('six formal exports preserve every previous immutable version',async()=>{
      for(let version=1;version<=6;version++){
        if(version>1){const result=await service.revision(owner,no,lock,owner.displayName);lock=result.lock_version;}
        versions.push(entry(version));
        const result=await service.exportResult(owner,no,{kind:'XLSX',succeeded:true,expected_version:lock,
          operator_name:owner.displayName,snapshot:snapshot(versions)});
        lock=result.lock_version;
        const restored=await service.get(owner,no);
        assert.deepEqual(restored.snapshot.quote_management.versions,versions);
      }
      const frozen=JSON.parse(pg.query(`SELECT json_agg(v ORDER BY v.version_no) FROM calc.quote_scheme_version v JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${literal(no)};`));
      assert.equal(frozen.length,6);
      for(let i=0;i<6;i++)assert.deepEqual(frozen[i].snapshot_payload.quote_management.versions,versions.slice(0,i+1));
    });
    await t.test('121 saved prices round-trip and list displays V121 rather than formal counter',async()=>{
      lock=(await service.revision(owner,no,lock,owner.displayName)).lock_version;
      for(let number=7;number<=121;number++)versions.push(entry(number));
      const saved=await service.save(owner,no,{expected_version:lock,operator_name:owner.displayName,snapshot:snapshot(versions)});
      lock=saved.lock_version;
      assert.deepEqual((await service.get(owner,no)).snapshot.quote_management.versions,versions);
      const list=await service.list(owner,{scheme_no:no});
      assert.equal(list.items[0].quote_version,121);assert.equal(list.items[0].version_no,7);
    });
    await t.test('old version export logs without replacing latest 121 versions; foreign writes stay blocked',async()=>{
      const before=(await service.get(owner,no)).snapshot;
      const historic={...snapshot(versions),draft_items:structuredClone(versions[50].items)};
      await service.exportResult(owner,no,{kind:'XLSX',succeeded:true,expected_version:lock,operator_name:owner.displayName,
        historical_quote_version:51,snapshot:historic});
      assert.deepEqual((await service.get(owner,no)).snapshot,before);
      // The most recent confirmed price remains exportable as history while
      // the current workspace is a revision; it cannot finalize that workspace.
      await service.exportResult(owner,no,{kind:'XLSX',succeeded:true,expected_version:lock,operator_name:owner.displayName,
        historical_quote_version:121,snapshot:snapshot(versions)});
      assert.equal((await service.get(owner,no)).status,'REVISING');
      const forged=snapshot(versions);forged.draft_items[0].quantity=99;
      await assert.rejects(()=>service.exportResult(owner,no,{kind:'XLSX',succeeded:true,expected_version:lock,
        operator_name:owner.displayName,historical_quote_version:121,snapshot:forged}),{statusCode:409});
      await assert.rejects(()=>service.save(other,no,{expected_version:lock,operator_name:other.displayName,snapshot:snapshot(versions)}),{statusCode:409});
      assert.equal((await service.get(other,no)).found,false);
      assert.deepEqual((await service.get(owner,no)).snapshot,before);
    });
    await t.test('old or stale clients cannot truncate, rewrite or remove confirmed history',async()=>{
      const before=(await service.get(owner,no)).snapshot;
      for(const mode of ['truncate','rewrite','remove-marker']){
        const changed=structuredClone(before);
        if(mode==='truncate')changed.quote_management.versions=changed.quote_management.versions.slice(-2);
        if(mode==='rewrite')changed.quote_management.versions[1].amount=999;
        if(mode==='remove-marker')delete changed.quote_management.versions[1].confirmed;
        await assert.rejects(()=>service.save(owner,no,{expected_version:lock,operator_name:owner.displayName,snapshot:changed}),{statusCode:409});
        await assert.rejects(()=>service.exportResult(owner,no,{kind:'XLSX',succeeded:true,expected_version:lock,
          operator_name:owner.displayName,snapshot:changed}),{statusCode:409});
        assert.deepEqual((await service.get(owner,no)).snapshot,before);
      }
    });
  }finally{await pg.close();}
});
