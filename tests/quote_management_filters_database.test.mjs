// Fresh loopback-only PostgreSQL and synthetic quotations; no app settings.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('quotation filters combine, preserve ownership and include whole Shanghai dates',{timeout:180000},async t=>{
 const pg=await startLocalPostgres();
 try{
  pg.query('CREATE SCHEMA calc;');
  pg.query(await readFile(new URL('../database/migrations/quote_scheme_center_v1.sql',import.meta.url),'utf8'));
  const q=value=>"'"+String(value).replaceAll("'","''")+"'";
  // The cluster uses UTC: filtering must not depend on the database session zone.
  const service=createQuoteSchemeService({runPsql:async sql=>pg.query("SET TIME ZONE 'UTC';\n"+sql),sqlUnicodeText:q,sqlNumber:value=>String(Number(value))});
  const owner={userId:'filters-owner',role:'USER'},other={userId:'filters-other',role:'USER'};
  const make=async({person=owner,name='测试创建人',company='筛选客户',product='JQ',time='2026-10-21T16:00:00Z',quoted=true}={})=>{
   const snapshot={company,scheme_summary:{company,product_summary:product,quoted_amount:100},draft_items:[]};
   const created=await service.create(person,{operator_name:name,snapshot});
   if(quoted)await service.exportResult(person,created.scheme_no,{operator_name:name,kind:'XLSX',succeeded:true,expected_version:1,snapshot});
   pg.query(`UPDATE calc.quote_scheme SET updated_at=${q(time)}::timestamptz WHERE scheme_no=${q(created.scheme_no)};`);
   return created.scheme_no;
  };
  const start=await make(),end=await make({time:'2026-10-22T15:59:59.999999Z'});
  await make({time:'2026-10-21T15:59:59.999999Z'});await make({time:'2026-10-22T16:00:00Z'});
  await make({person:other});await make({company:'其他客户'});await make({product:'JE'});
  await make({name:'其他创建人'});await make({quoted:false});
  const combined={status:'QUOTED',company:'筛选客户',product:'JQ',creator:'测试创建人',updated_from:'2026-10-22',updated_to:'2026-10-22'};
  await t.test('all independent conditions AND together and dates include both day boundaries',async()=>{
   const result=await service.list(owner,combined);
   assert.equal(result.total,2);assert.deepEqual(result.items.map(row=>row.scheme_no),[end,start]);
   assert.equal((await service.list(owner,{...combined,scheme_no:start})).total,1);
   assert.equal((await service.list(other,{...combined,scheme_no:start})).total,0);
   assert.equal((await service.list(owner,{...combined,company:'does-not-match'})).total,0);
   assert.equal((await service.list(owner,{...combined,product:'does-not-match'})).total,0);
   assert.equal((await service.list(owner,{...combined,creator:'does-not-match'})).total,0);
  });
  await t.test('one-sided dates, status selection and literal wildcard queries remain supported',async()=>{
   const {updated_from,updated_to,...base}=combined;
   assert.equal((await service.list(owner,{...base,updated_from})).total,3);
   assert.equal((await service.list(owner,{...base,updated_to})).total,3);
   assert.equal((await service.list(owner,{...base,status:'DRAFT'})).total,1);
   const literal=await make({company:'100%_literal'});
   assert.deepEqual((await service.list(owner,{company:'%_'})).items.map(row=>row.scheme_no),[literal]);
  });
  await t.test('invalid and reversed dates are rejected before executing SQL',async()=>{
   for(const dates of [{updated_from:'2026-02-30'},{updated_to:'0000-01-01'},{updated_to:'not-a-date'},{updated_to:'2026-13-01'},
     {updated_from:'2026-10-23',updated_to:'2026-10-22'},{updated_from:"2026-10-22'; DROP TABLE calc.quote_scheme;--"}])
    await assert.rejects(()=>service.list(owner,dates),{statusCode:400});
   assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_scheme;')),10);
  });
 }finally{await pg.close();}
});
