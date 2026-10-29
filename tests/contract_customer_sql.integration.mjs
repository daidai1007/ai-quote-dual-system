import assert from 'node:assert/strict';
import test from 'node:test';
import {contractCustomer,contractCustomerNameSql} from '../api/contract_customer.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('real PostgreSQL keeps quotation buyer 无 ahead of older summary and catalogue names', {timeout:90000}, async()=>{
  // Disposable loopback cluster; query only VALUES, never application settings
  // or an existing business database. No migrations or business tables needed.
  const pg=await startLocalPostgres();
  try {
    const cases=[
      [{company:'无',scheme_summary:{company:'旧汇总客户'}},'旧方案客户','无'],
      [{company:'  无  ',scheme_summary:{company:'旧汇总客户'}},'旧方案客户','无'],
      [{company:'本机报价客户',scheme_summary:{company:'无'}},'旧方案客户','本机报价客户'],
      [{company:'',scheme_summary:{company:'无'}},'旧方案客户','无'],
      [{scheme_summary:{company:'本机旧版报价客户'}},'旧方案客户','本机旧版报价客户'],
      [{company:'',scheme_summary:{company:''}},'无','无'],
      [{company:'',scheme_summary:{company:''}},'',null],
    ];
    const quote=value=>"'"+String(value).replaceAll("'","''")+"'";
    const values=cases.map(([snapshot,fallback],i)=>`(${i},${quote(JSON.stringify(snapshot))}::jsonb,${quote(fallback)})`).join(',');
    const expression=contractCustomerNameSql('v.snapshot_payload','v.company_name');
    const result=JSON.parse(pg.query(`SELECT jsonb_agg(jsonb_build_object('name',${expression}) ORDER BY v.id)::text
      FROM(VALUES ${values}) v(id,snapshot_payload,company_name);`));
    assert.deepEqual(result.map(row=>row.name),cases.map(row=>row[2]));
    const buyer=contractCustomer({customer_name:result[0].name,snapshot_customer_name:'旧汇总客户',snapshot_customer_code:'OLD'});
    assert.equal(buyer.customer_name,'无');assert.notEqual(buyer.customer_code,'OLD');
  } finally {await pg.close();}
});
