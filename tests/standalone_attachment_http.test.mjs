// Real HTTP + owned disposable loopback PostgreSQL. Never application settings.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import net from 'node:net';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {PRICING_BASIS,quickOrderLineBreakdown,manufacturingFormulaForItem,MANUFACTURING_COST_BASIS,moneyProduct,QUICK_FREIGHT_BASIS} from '../quick_discount_rules.mjs';
import {TAX_COST_BASIS,withTaxCostForItem} from '../tax_cost.mjs';

test('independent attachment: HTTP preview, confirmation, owned export, no cabinet-history fiction', {timeout:180000},async()=>{
 const pg=await startLocalPostgres();let child;
 try{
  for(const file of ['tests/fixtures/attachment_online_schema_20260911.sql',
    'database/attachment-v2/web/01-prepare.sql','database/attachment-v2/web/02-stage.sql',
    'tests/fixtures/attachment_api_base_stub.sql','database/migrations/cabinet_material_v2.sql',
    'database/migrations/cabinet_spray_v2.sql','database/migrations/cabinet_labor_v1.sql',
    'database/migrations/cabinet_auxiliary_v1.sql','database/migrations/cabinet_auxiliary_v2.sql',
    'database/migrations/cabinet_auxiliary_v3.sql','database/migrations/quote_scheme_center_v1.sql',
    'database/migrations/quote_name_scope_v1.sql'])pg.query(await readFile(new URL('../'+file,import.meta.url),'utf8'));
  const version=pg.query("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
  pg.query(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${version}'); COMMIT;`);
  const listener=net.createServer();listener.listen(0,'127.0.0.1');await once(listener,'listening');
  const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
  const env={...process.env,AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),AI_QUOTE_API_KEY:'standalone-test',
    PSQL_PATH:pg.connection.psql,AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:String(pg.connection.port),
    AI_QUOTE_DB_USER:pg.connection.user,AI_QUOTE_DB_NAME:'postgres'};
  for(const key of ['DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGPASSFILE','PGOPTIONS','PGPASSWORD','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','RENDER','AI_QUOTE_PRINCIPALS_JSON','AI_QUOTE_ATTACHMENT_V2_VERSION','AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED'])delete env[key];
  env.PGSSLMODE='disable';env.PGCONNECT_TIMEOUT='5';
  child=spawn(process.execPath,['api/server.mjs'],{cwd:new URL('../',import.meta.url),env,windowsHide:true,stdio:['ignore','pipe','pipe']});
  let errors='';child.stdout.resume();child.stderr.on('data',chunk=>errors+=chunk.toString());
  const base=`http://127.0.0.1:${port}`;
  for(let n=0;n<100;n++){try{if((await fetch(base+'/health')).ok)break;}catch{}if(child.exitCode!==null)throw Error(errors);await new Promise(resolve=>setTimeout(resolve,50));}
  const request=(route,body,token)=>fetch(base+route,{method:body?'POST':'GET',headers:{'x-ai-quote-key':'standalone-test','Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
  const call=async(...args)=>{const response=await request(...args);return {status:response.status,body:await response.json()};};
  const login=await call('/api/name-login',{name:'独立附件回归甲'});assert.equal(login.status,200,JSON.stringify(login));
  const token=login.body.token;
  const catalog=await call('/api/attachments/catalog?v=2',undefined,token);assert.equal(catalog.status,200);
  const fixed=catalog.body.items.find(row=>row.source_row_no===208);assert.ok(fixed);
  const settings={galvanized_price:4.55,carbon_price:4.2,stainless_304_price:16,stainless_316_price:32.4,surface_price:26};
  const fixedRule=fixed.rules.find(rule=>rule.method==='FIXED');assert.ok(fixedRule);
  const preview=await call('/api/attachments/preview-standalone',{attachments:[{attachment_price_id:fixed.attachment_price_id,quantity:1,standalone_rule_id:fixedRule.rule_id,standalone_cost_settings:settings}]},token);
  assert.equal(preview.status,200,JSON.stringify(preview));const row=preview.body.attachments[0];
  assert.equal(row.status,'FIXED',JSON.stringify(row));assert.equal(row.formula_amount,Number(fixedRule.fixed_cost));assert.equal(row.environment.width_mm,undefined);
  const item={item_type:'standalone_attachment',attachment_contract:'standalone_v1',product_code:'STANDALONE_ATTACHMENT',
    scheme2_selected_product_name:'独立附件',name:row.item_name,specification:'—',quantity:3,unit:row.unit||'件',quick_discount:.85,
    attachments:[row],pricing_basis:PRICING_BASIS,scheme2_cost_settings:settings,freight_fee:0,
    quick:{base_price:0,attachment_fee:row.quick_amount,total_cost:row.quick_amount}};
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:[row],discount:.85,cabinetQuantity:3,freightFee:0});
  item.quote_display={name:item.name,specification:'—',quantity:3,unit:item.unit,discount:.85,
    unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:row.quick_amount,
    material_difference:0,quick_base_price:0,quick_attachment_fee:row.quick_amount,quick_total_cost:row.quick_amount,
    attachment_source:'popup_v1',attachments:[row],remark:'本机测试'};
  const payload={quote_id:'LOCAL-INDEPENDENT-ONLY',company_name:'独立附件测试客户',quote_date:'2026-10-30',order_nature:'EXTERNAL',items:[item]};
  const preflight=await call('/api/quotes/confirm-check',payload,token);assert.equal(preflight.status,200,JSON.stringify(preflight));
  assert.equal(pg.query('SELECT count(*) FROM calc.quote_document;'),'0');
  const confirmed=await call('/api/quotes/confirm',payload,token);assert.equal(confirmed.status,200,JSON.stringify(confirmed));
  assert.equal(confirmed.body.history_items,0);
  assert.equal(pg.query('SELECT count(*) FROM calc.company_quote_history;'),'0');
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,item_type}' FROM calc.quote_document;"),'standalone_attachment');
  const output=await request('/api/quotes/export',payload,token);
  assert.equal(output.status,200,output.status===200?'':await output.text());
  assert((await output.arrayBuffer()).byteLength>1000);
  const manufactured={...item,manufacturing_cost_basis:MANUFACTURING_COST_BASIS,
    formula:{material_cost:0,auxiliary_cost:0,labor_cost:0,spray_cost:0,attachment_fee:row.formula_amount}};
  manufactured.formula=manufacturingFormulaForItem(manufactured);
  assert.equal(manufactured.formula.manufacturing_cost,moneyProduct(line.equivalentUnitTotal,.04));
  assert.equal(manufactured.formula.management_fee,moneyProduct(line.equivalentUnitTotal,.05));
  const newFeesPayload={...payload,quote_id:'LOCAL-INDEPENDENT-NEW-FEES',items:[manufactured]};
  const newChecked=await call('/api/quotes/confirm-check',newFeesPayload,token);
  assert.equal(newChecked.status,200,JSON.stringify(newChecked));
  const newSaved=await call('/api/quotes/confirm',newFeesPayload,token);
  assert.equal(newSaved.status,200,JSON.stringify(newSaved));
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,formula,management_fee_basis}' FROM calc.quote_document WHERE quote_id='LOCAL-INDEPENDENT-NEW-FEES';"),'quoted_unit_5pct_v1');
  const newFile=await request('/api/quotes/export',newFeesPayload,token);
  assert.equal(newFile.status,200,newFile.status===200?'':await newFile.text());
  assert((await newFile.arrayBuffer()).byteLength>1000);
  const invalid=await call('/api/quotes/confirm-check',{...newFeesPayload,quote_id:'LOCAL-INDEPENDENT-BAD-FEES',
    items:[{...manufactured,formula:{...manufactured.formula,management_fee:999}}]},token);
  assert.equal(invalid.status,422,JSON.stringify(invalid));assert.match(invalid.body.message,/5%/);
  const separate={...manufactured,freight_fee:7,quick_freight_fee:20,quick_freight_mode:'MANUAL',quick_freight_basis:QUICK_FREIGHT_BASIS};
  const separateLine=quickOrderLineBreakdown({quote:separate.quick,attachments:separate.attachments,discount:.85,cabinetQuantity:3,freightFee:20});
  separate.quote_display={...separate.quote_display,unit_price:separateLine.equivalentUnitTotal,total:separateLine.lineTotal};
  separate.formula=manufacturingFormulaForItem(separate);
  const separatePayload={...payload,quote_id:'LOCAL-SEPARATE-QUICK-FREIGHT',items:[separate]};
  const separateSaved=await call('/api/quotes/confirm',separatePayload,token);
  assert.equal(separateSaved.status,200,JSON.stringify(separateSaved));
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,freight_fee}' FROM calc.quote_document WHERE quote_id='LOCAL-SEPARATE-QUICK-FREIGHT';"),'7');
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,quick_freight_fee}' FROM calc.quote_document WHERE quote_id='LOCAL-SEPARATE-QUICK-FREIGHT';"),'20');
  const separateOutput=await request('/api/quotes/export',separatePayload,token);
  assert.equal(separateOutput.status,200,separateOutput.status===200?'':await separateOutput.text());
  assert((await separateOutput.arrayBuffer()).byteLength>1000);
  const taxed={...separate,tax_cost_basis:TAX_COST_BASIS};taxed.formula=withTaxCostForItem(taxed);
  const taxedPayload={...payload,quote_id:'LOCAL-EXPLICIT-TAX',items:[taxed]};
  const taxChecked=await call('/api/quotes/confirm-check',taxedPayload,token);
  assert.equal(taxChecked.status,200,JSON.stringify(taxChecked));
  const taxSaved=await call('/api/quotes/confirm',taxedPayload,token);
  assert.equal(taxSaved.status,200,JSON.stringify(taxSaved));
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,formula,tax_cost}' FROM calc.quote_document WHERE quote_id='LOCAL-EXPLICIT-TAX';"),String(taxed.formula.tax_cost));
  const taxFile=await request('/api/quotes/export',taxedPayload,token);
  assert.equal(taxFile.status,200,taxFile.status===200?'':await taxFile.text());
  assert((await taxFile.arrayBuffer()).byteLength>1000);
  const staleTax=await call('/api/quotes/confirm-check',{...taxedPayload,quote_id:'LOCAL-TAX-STALE',items:[{...taxed,formula:{...taxed.formula,tax_cost:999}}]},token);
  assert.equal(staleTax.status,422,JSON.stringify(staleTax));assert.match(staleTax.body.message,/税费.*不一致/);
  const negativeTax=await call('/api/quotes/confirm-check',{...taxedPayload,quote_id:'LOCAL-TAX-NEGATIVE',items:[{...taxed,freight_fee:10000}]},token);
  assert.equal(negativeTax.status,422,JSON.stringify(negativeTax));assert.match(negativeTax.body.message,/税费计算失败/);
  const cabinet={name:'保留柜体',product_code:'JP',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,
    quantity:1,attachments:[],formula:{material_cost:10,auxiliary_cost:20,labor_cost:30,spray_cost:0,attachment_fee:0},quick:{total_cost:100}};
  const mixed=await call('/api/quotes/confirm',{...payload,quote_id:'LOCAL-INDEPENDENT-MIXED',items:[cabinet,item]},token);
  assert.equal(mixed.status,200,JSON.stringify(mixed));assert.equal(mixed.body.history_items,1);
  assert.equal(pg.query('SELECT count(*) FROM calc.company_quote_history;'),'1');
  assert.equal(pg.query("SELECT jsonb_array_length(document_payload->'items') FROM calc.quote_document WHERE quote_id='LOCAL-INDEPENDENT-MIXED';"),'2');
  const board=catalog.body.items.find(row=>row.item_name==='安装板');assert.ok(board);
  const boardRule=board.rules.find(rule=>rule.products?.includes('JP'));assert.ok(boardRule);
  const sized=await call('/api/attachments/preview-standalone',{attachments:[{attachment_price_id:board.attachment_price_id,
    quantity:1,standalone_rule_id:boardRule.rule_id,standalone_material_code:'SUS304',manual_inputs:{宽度:1234,高度:987,材质密度:1,材质单价:1},
    standalone_cost_settings:{...settings,galvanized_price:7,carbon_price:99}}]},token);
  assert.equal(sized.status,200,JSON.stringify(sized));const own=sized.body.attachments[0];
  assert.equal(own.status,'CALCULATED',JSON.stringify(own));
  assert.equal(own.standalone_material_code,'SGCC');assert.equal(own.environment.width_mm,1234);
  assert.equal(own.environment.height_mm,987);assert.equal(own.environment.material_unit_price,7);
  const other=await call('/api/name-login',{name:'独立附件回归乙'});
  const forbidden=await request('/api/quotes/export',payload,other.body.token);assert.equal(forbidden.status,403);
 }finally{
  if(child&&child.exitCode===null){const ended=once(child,'exit');child.kill();await ended;}
  await pg.close();
 }
});
