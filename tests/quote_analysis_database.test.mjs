import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {createQuoteAnalysisService} from '../api/quote_analysis_service.mjs';

const q=value=>value==null?'NULL':`'${String(value).replaceAll("'","''")}'`;
const owner={userId:'owner',displayName:'测试人员',departmentId:'dept',role:'USER'};
const other={userId:'other',displayName:'其他人员',departmentId:'other-dept',role:'USER'};
test('real PostgreSQL analytics, permissions, frozen amounts, outcome audit and deduplication',{timeout:180000},async t=>{
  const pg=await startLocalPostgres();
  try {
    pg.query('CREATE SCHEMA calc; CREATE TABLE calc.ordering_company(company_code text PRIMARY KEY,company_name text); INSERT INTO calc.ordering_company VALUES (\'customer-a\',\'本机示例客户 A\'),(\'customer-b\',\'本机示例客户 B\');');
    pg.query(await readFile(new URL('../database/migrations/quote_scheme_center_v1.sql',import.meta.url),'utf8'));
    const deps={runPsql:async sql=>pg.query(sql),sqlUnicodeText:q,sqlNumber:v=>String(Number(v))};
    const schemes=createQuoteSchemeService(deps),analysis=createQuoteAnalysisService(deps);
    const snapshot={company:'本机示例客户 A',scheme_summary:{company:'本机示例客户 A',product_summary:'JP',quoted_amount:200.20},
      document:{quote_date:'2026-10-21',order_nature:'EXTERNAL'},analysis_customer:{customer_code:'customer-a'},draft_items:[{product_code:'JP',quantity:2,
        formula:{material_cost:10,auxiliary_cost:2,labor_cost:3,attachment_fee:4,spray_cost:5,management_fee:1},
        quote_display:{total:200.20,discount:.85,quantity:2}}]};
    const create=async(p=owner,payload=snapshot)=>{
      const s=await schemes.create(p,{snapshot:structuredClone(payload),operator_name:'测试'});
      await schemes.exportResult(p,s.scheme_no,{expected_version:1,operator_name:'测试',kind:'XLSX',succeeded:true,snapshot:structuredClone(payload)});
      return s.scheme_no;
    };
    const no=await create(),hidden=await create(other);
    await t.test('overview works before migration without inventing outcomes',async()=>{
      const data=await analysis.analyze(owner,{});
      assert.equal(data.outcomes_available,false);
      assert.equal(data.summary.quoted,1);
      assert.equal(data.summary.amount,'200.20');
      assert.equal(data.details.length,1);
      assert.equal(data.discount.sample,0);
    });
    const migration=await readFile(new URL('../database/migrations/quote_analysis_v1.sql',import.meta.url),'utf8');
    pg.query(migration);pg.query(migration);
    const resultInput={scheme_no:no,version_no:1,customer_code:'customer-a',product_code:'JP',opportunity_key:'LOCAL-OPPORTUNITY',
      result:'WON',result_date:'2026-10-21',expected_revision:0,operator_name:'登记测试'};
    await t.test('registration ignores forged price/discount and retains quote unchanged',async()=>{
      const before=pg.query(`SELECT row_to_json(s) FROM calc.quote_scheme s WHERE scheme_no=${q(no)};`);
      await analysis.recordOutcome(owner,{...resultInput,discount:.01,quote_method:'FORMULA'});
      const data=await analysis.analyze(owner,{});
      assert.equal(data.discount.sample,1);
      assert.equal(data.discount.records[0].discount,'0.850000');
      assert.equal(data.discount.records[0].quote_method,'QUICK');
      assert.equal(data.costs.material_cost,'20.00');
      assert.equal(before,pg.query(`SELECT row_to_json(s) FROM calc.quote_scheme s WHERE scheme_no=${q(no)};`));
      assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_analysis_outcome_audit;')),1);
      await assert.rejects(analysis.recordOutcome(owner,resultInput),{statusCode:409});
      await analysis.recordOutcome(owner,{...resultInput,result:'LOST',expected_revision:1});
      await assert.rejects(analysis.recordOutcome(owner,{...resultInput,result:'WON',expected_revision:1}),{statusCode:409});
      assert.equal((await analysis.analyze(owner,{})).discount.sample,1);
      assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_analysis_outcome_audit;')),2);
      await analysis.recordOutcome(owner,{...resultInput,result:'PENDING',expected_revision:2});
      assert.equal((await analysis.analyze(owner,{})).discount.sample,0);
    });
    await t.test('other users cannot read or overwrite outcomes; share grants read only',async()=>{
      await assert.rejects(analysis.recordOutcome(other,resultInput),{statusCode:409});
      const data=await analysis.analyze(other,{});
      assert.equal(data.details[0].scheme_no,hidden);
      assert.equal(data.outcome_records.length,0);
      pg.query(`INSERT INTO calc.quote_scheme_share(scheme_id,grantee_user_id,granted_by_user_id) SELECT scheme_id,'other','owner' FROM calc.quote_scheme WHERE scheme_no=${q(no)};`);
      const shared=await analysis.analyze(other,{});
      assert.equal(shared.details.length,2);
      await assert.rejects(analysis.recordOutcome(other,{...resultInput,expected_revision:3}),{statusCode:409});
    });
    await t.test('revision drafts do not replace formal prices and renamed customers retain stable ID',async()=>{
      await schemes.revision(owner,no,2,'测试');
      pg.query(`UPDATE calc.quote_scheme_snapshot snap SET snapshot_payload=jsonb_set(snapshot_payload,'{scheme_summary,quoted_amount}','999999'::jsonb) FROM calc.quote_scheme s WHERE snap.scheme_id=s.scheme_id AND s.scheme_no=${q(no)}; UPDATE calc.ordering_company SET company_name='本机更名客户 A' WHERE company_code='customer-a';`);
      const data=await analysis.analyze(owner,{customer:'customer-a'});
      assert.equal(data.summary.amount,'200.20');
      assert.equal(data.details[0].customer_name,'本机更名客户 A');
      assert.equal(data.details[0].formal_version,1);
      await assert.rejects(analysis.recordOutcome(owner,{...resultInput,version_no:2,expected_revision:3}),{statusCode:409});
    });
    await t.test('legacy codes filter by configuration type while registration and frozen snapshots keep original keys',async()=>{
      const payload=structuredClone(snapshot);
      payload.company='本机示例客户 B';
      payload.analysis_customer={customer_code:'customer-b'};
      payload.scheme_summary={company:payload.company,product_summary:'JP_SINGLE;JP_DOUBLE;JQ_EXP;JP_WIDE_EXP',quoted_amount:156.30};
      payload.draft_items=[['JP_SINGLE',60.10,.85],['JP_DOUBLE',40.20,.9],['JQ_EXP',50.50,.9],['JP_WIDE_EXP',5.50,.8]]
        .map(([product_code,total,discount])=>({product_code,quantity:1,quote_display:{total,discount,quantity:1}}));
      const legacy=await create(owner,payload);
      const frozenSql=`SELECT v.snapshot_payload::text FROM calc.quote_scheme_version v JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${q(legacy)};`;
      const before=pg.query(frozenSql);
      const data=await analysis.analyze(owner,{customer:'customer-b',product:'JP'});
      assert.equal(data.product_filter_mode,'family-v1');
      assert.equal(data.summary.quoted,1);
      assert.equal(data.summary.amount,'100.30');
      assert.equal(data.details[0].analysis_amount,'100.30');
      assert.deepEqual(data.details[0].products.map(p=>p.product_code),['JP_SINGLE','JP_DOUBLE','JQ_EXP','JP_WIDE_EXP']);
      assert.equal((await analysis.analyze(owner,{customer:'customer-b',product:'JQ'})).summary.amount,'50.50');
      assert.equal((await analysis.analyze(owner,{customer:'customer-b',product:'JP WIDE'})).summary.amount,'5.50');
      assert.equal((await analysis.analyze(owner,{customer:'customer-b',product:'JC'})).summary.quoted,0);
      const registration={scheme_no:legacy,version_no:1,customer_code:'customer-b',product_code:'JP_SINGLE',
        opportunity_key:'LOCAL-LEGACY-TYPE',result:'WON',result_date:'2026-10-21',expected_revision:0,operator_name:'本机测试'};
      await analysis.recordOutcome(owner,registration);
      const decided=await analysis.analyze(owner,{customer:'customer-b',product:'JP'});
      assert.equal(decided.discount.sample,1);
      assert.equal(decided.discount.records[0].product_code,'JP_SINGLE');
      assert.equal(decided.discount.records[0].discount,'0.850000');
      await assert.rejects(analysis.recordOutcome(owner,registration),{statusCode:409});
      await assert.rejects(analysis.recordOutcome(owner,{...registration,product_code:'JP'}),{statusCode:400});
      assert.equal(pg.query(frozenSql),before);
    });
    await t.test('saved formula-attachment allocation feeds category analytics without changing old cost ledger',async()=>{
      const payload=structuredClone(snapshot);payload.draft_items[0].product_code='JA_SINGLE';
      payload.draft_items[0].formula.cost_allocation={schema:1,basis:'formula_attachments_v1',complete:true,
        totals:{material_cost:12,auxiliary_cost:3,labor_cost:4,attachment_fee:0,spray_cost:5,management_fee:1}};
      const number=await create(owner,payload);
      const data=await analysis.analyze(owner,{product:'JA'});
      assert.equal(data.costs.material_cost,'24.00');assert.equal(data.costs.attachment_fee,'0.00');
      assert.equal(data.costs.labor_cost,'8.00');
      assert.equal(pg.query(`SELECT snapshot_payload#>>'{draft_items,0,formula,material_cost}' FROM calc.quote_scheme_version v JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${q(number)};`),'10');
    });
  } finally {await pg.close();}
});
