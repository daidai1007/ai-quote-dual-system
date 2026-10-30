// Real API + a fresh, owned loopback PostgreSQL cluster; synthetic orders only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import net from 'node:net';
import ExcelJS from '@excel.js/exceljs';
import {PRICING_BASIS,quickOrderLineBreakdown,moneySum} from '../quick_discount_rules.mjs';
import {requiredParameters,selectRule} from '../api/attachment_cost.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('calculation preflight distinguishes V2 attachment IDs from legacy names', {timeout:300000}, async t => {
  const pg = await startLocalPostgres();
  let child;
  try {
    for (const file of ['tests/fixtures/attachment_online_schema_20260911.sql',
      'database/attachment-v2/web/01-prepare.sql', 'database/attachment-v2/web/02-stage.sql',
      'tests/fixtures/attachment_api_base_stub.sql', 'database/migrations/cabinet_material_v2.sql',
      'database/migrations/cabinet_spray_v2.sql', 'database/migrations/cabinet_labor_v1.sql',
      'database/migrations/cabinet_auxiliary_v1.sql', 'database/migrations/cabinet_auxiliary_v2.sql',
      'database/migrations/cabinet_auxiliary_v3.sql', 'database/migrations/quote_scheme_center_v1.sql',
      'database/migrations/quote_name_scope_v1.sql']) {
      pg.query(await readFile(new URL('../' + file, import.meta.url), 'utf8'));
    }
    pg.query('CREATE TABLE calc.dual_quote_result(quote_id text PRIMARY KEY);');
    const version = pg.query("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
    assert.match(version, /^xlsx-[a-f0-9]{16}-r[0-9]+$/);
    pg.query(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${version}'); COMMIT;`);

    const listener = net.createServer();
    listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
    const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
    const env = {...process.env, AI_QUOTE_API_HOST:'127.0.0.1', PORT:String(port),
      AI_QUOTE_API_KEY:'local-attachment-test', PSQL_PATH:pg.connection.psql,
      AI_QUOTE_DB_HOST:'127.0.0.1', AI_QUOTE_DB_PORT:String(pg.connection.port),
      AI_QUOTE_DB_USER:pg.connection.user, AI_QUOTE_DB_NAME:'postgres'};
    for (const key of ['DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGPASSFILE','PGOPTIONS',
      'PGPASSWORD','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','RENDER',
      'AI_QUOTE_PRINCIPALS_JSON','AI_QUOTE_ATTACHMENT_V2_VERSION','AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED']) delete env[key];
    env.PGSSLMODE='disable'; env.PGCONNECT_TIMEOUT='5';
    child = spawn(process.execPath, ['api/server.mjs'], {cwd:new URL('../', import.meta.url),
      env, windowsHide:true, stdio:['ignore','pipe','pipe']});
    let errors=''; child.stdout.resume(); child.stderr.on('data', chunk => { errors += chunk.toString(); });
    const base = `http://127.0.0.1:${port}`;
    let ready=false;
    for (let i=0;i<100;i++) {
      try { if ((await fetch(base+'/health')).ok) { ready=true; break; } } catch {}
      if (child.exitCode!==null) throw new Error('Local API stopped: '+errors.slice(-1500));
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    assert.ok(ready, 'Local API startup timed out');
    const request = async (route, body, token, extra={}) => fetch(base+route, {method:body?'POST':'GET',
      headers:{'x-ai-quote-key':'local-attachment-test','Content-Type':'application/json',
        ...(token?{Authorization:'Bearer '+token}:{}),...extra}, body:body?JSON.stringify(body):undefined});
    const call = async (...args) => {const r=await request(...args); return {status:r.status,body:await r.json()};};
    const login=await call('/api/name-login',{name:'附件回归人员甲'});
    const other=await call('/api/name-login',{name:'附件回归人员乙'});
    assert.equal(login.status,200); assert.equal(other.status,200);
    const token=login.body.token;
    const catalog=await call('/api/attachments/catalog?v=2',undefined,token);
    assert.equal(catalog.status,200,JSON.stringify(catalog));
    const limiter=catalog.body.items.find(row=>row.source_row_no===208);
    assert.ok(limiter);
    const cabinet=(quote_id,width_mm=800)=>({quote_id,product_code:'JP_SINGLE',material_code:'SECC',
      model_code:`${width_mm}*600*2100`,width_mm,height_mm:2100,depth_mm:600,quote_date:'2026-10-23',
      coating_type:'橘纹',attachments:[],material_unit_price_override:4.2,
      galvanized_sheet_unit_price_override:4.55,carbon_steel_unit_price_override:4.2,
      surface_treatment_unit_price_override:26});
    const selection={attachment_price_id:limiter.attachment_price_id,quantity:2,manual_inputs:{}};
    const v2={...cabinet('LOCAL-V2-SINGLE'),attachment_contract:2,attachments:[selection]};
    let single, batchResult, batch;

    await t.test('unnamed ID-only selection succeeds on single-cabinet HTTP route', async()=>{
      assert.equal(selection.item_name,undefined); assert.equal(selection.model_code,undefined);
      single=await call('/api/quotes/calculate-dual',v2,token);
      assert.equal(single.status,200,JSON.stringify(single));
      assert.equal(single.body.attachment_contract,2);
      assert.equal(single.body.attachments[0].item_name,'门限位器');
      assert.equal(single.body.attachments[0].formula_amount,12);
      assert.equal(single.body.attachments[0].quick_amount,40);
      assert.ok(single.body.quote_line_id);
    });

    await t.test('automatic fixed bases keep their ID, child index and amount in streamed batch', async()=>{
      const cabinets=[cabinet('LOCAL-V2-BATCH-0',1000),cabinet('LOCAL-V2-BATCH-1',800)];
      const bases=cabinets.map((row,ganged_cabinet_index)=>{
        const item=catalog.body.items.find(item=>item.item_name==='固定底座'&&Number(item.width_mm)===row.width_mm
          &&Number(item.depth_mm)===600&&Number(item.height_mm)===100);
        assert.ok(item,'Missing synthetic base selection for '+row.width_mm);
        return {attachment_price_id:item.attachment_price_id,quantity:1,ganged_cabinet_index,manual_inputs:{底座高度:100}};
      });
      batch={cabinets,attachment_payload:{...cabinets[0],width_mm:1800,attachment_contract:2,
        ganged_cabinet_count:2,ganged_cabinets:cabinets,attachments:bases}};
      const response=await request('/api/quotes/calculate-ganged',batch,token,{accept:'application/x-ndjson'});
      assert.equal(response.status,200);
      const events=(await response.text()).trim().split('\n').map(JSON.parse);
      assert.equal(events.at(-1).type,'result',JSON.stringify(events.at(-1)));
      batchResult=events.at(-1).result;
      assert.equal(batchResult.attachment_contract,2); assert.equal(batchResult.attachments.length,2);
      assert.deepEqual(batchResult.attachments.map(row=>row.ganged_cabinet_index),[0,1]);
      assert.deepEqual(batchResult.attachments.map(row=>row.attachment_price_id),bases.map(row=>row.attachment_price_id));
      const amounts=batchResult.attachments.reduce((sum,row)=>sum+row.quick_amount,0);
      assert.equal(batchResult.quick_quote.attachment_fee,amounts);
      assert.equal(batchResult.quick_quote.total_cost,400+amounts);
      assert.equal(pg.query('SELECT count(*) FROM calc.local_base_probe;'),'0','child writes are rolled back');
      assert.equal(pg.query("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='LOCAL-V2-BATCH-0';"),'2');
    });

    await t.test('fallback ganged snapshot accepts the same ID-only payload', async()=>{
      const input={...batch.attachment_payload,quote_id:'LOCAL-V2-FALLBACK',base_result:batchResult};
      const response=await call('/api/attachments/snapshot-ganged',input,token);
      assert.equal(response.status,200,JSON.stringify(response));
      assert.equal(response.body.quick_quote.total_cost,batchResult.quick_quote.total_cost);
    });

    await t.test('saved snapshot, confirmation and actual Excel export preserve prices and customer', async()=>{
      for (const [kind,input,result] of [['SINGLE',v2,single.body],['GANGED',{
        ...batch.attachment_payload,ganged_cabinet_inputs:batch.cabinets},batchResult]]) {
        const document={order_nature:'EXTERNAL',quote_id:'LOCAL-V2-DOCUMENT-'+kind,company_code:'LOCAL-V2-CUSTOMER-'+kind,
          company_name:'合成附件回归客户-'+kind,quote_date:v2.quote_date,
          items:[{...input,quote_line_id:result.quote_line_id,attachments:result.attachments,
            quantity:1,formula:result.formula_cost,quick:result.quick_quote}]};
        const saved=await call('/api/quotes/confirm',document,token);
        assert.equal(saved.status,200,JSON.stringify(saved));
        const reopened=await call('/api/company-history/match',{...input,company_code:document.company_code},token);
        assert.equal(reopened.status,200,JSON.stringify(reopened));
        assert.equal(reopened.body.payload.quick.total_cost,result.quick_quote.total_cost);
        assert.deepEqual(reopened.body.payload.attachments.map(row=>row.attachment_selection_id),
          result.attachments.map(row=>row.attachment_selection_id));
        const exported=await request('/api/quotes/export',document,token);
        assert.equal(exported.status,200,exported.status===200?'':await exported.text());
        const workbook=new ExcelJS.Workbook(); await workbook.xlsx.load(Buffer.from(await exported.arrayBuffer()));
        const cells=[]; workbook.eachSheet(sheet=>sheet.eachRow(row=>row.eachCell(cell=>cells.push(cell.value))));
        assert.ok(cells.some(value=>String(value).includes(document.company_name)));
        assert.ok(cells.includes(result.quick_quote.total_cost));
      }
    });

    await t.test('edited glass popup preview IDs do not become private resource references', async()=>{
      const glass=catalog.body.items.find(row=>row.item_name==='玻璃门');
      assert.ok(glass,'Synthetic staged catalogue must contain a glass door');
      // A renewed session keeps the same owner after an idle period. The cost
      // row remains the saved cabinet; only popup calculations are temporary.
      const renewed=await call('/api/name-login',{name:'附件回归人员甲'});
      assert.equal(renewed.body.person.user_id,login.body.person.user_id);
      const active=renewed.body.token;
      const foreign=await call('/api/quotes/calculate-dual',{...v2,quote_id:'LOCAL-FOREIGN-GLASS'},other.body.token);
      assert.equal(foreign.status,200,JSON.stringify(foreign));
      for (const [width,height] of [[400,400],[500,450]]) {
        const preview=await call('/api/attachments/preview',{...v2,quote_id:'PREVIEW',
          attachments:[{attachment_price_id:glass.attachment_price_id,quantity:1,
            manual_inputs:{玻璃门宽度:width,玻璃门高度:height}}]},active);
        assert.equal(preview.status,200,JSON.stringify(preview));
        const row=preview.body.attachments[0];
        assert.equal(row.status,'CALCULATED',JSON.stringify(row));
        assert.notEqual(row.quote_line_id,single.body.quote_line_id);
        assert.equal(pg.query(`SELECT count(*) FROM calc.quote_name_owner WHERE resource_key='${row.quote_line_id}';`),'0');
        const rows=[row];
        const quick={...single.body.quick_quote,base_price:single.body.quick_quote.base_price,
          attachment_fee:moneySum(rows.map(a=>a.quick_amount))};
        quick.total_cost=moneySum([quick.base_price,quick.attachment_fee]);
        const amounts=quickOrderLineBreakdown({quote:quick,attachments:rows,discount:.9,cabinetQuantity:2,freightFee:0});
        const item={...v2,quote_line_id:single.body.quote_line_id,pricing_basis:PRICING_BASIS,
          quantity:2,name:'本机玻璃门柜',specification:'800*600*2100',quick_discount:.9,
          attachments:rows,formula:single.body.formula_cost,quick,quote_display:{
            attachment_source:'popup_v1',attachments:structuredClone(rows),quantity:2,discount:.9,
            name:'本机玻璃门柜',specification:'800*600*2100',unit:'台',
            unit_price:amounts.equivalentUnitTotal,total:amounts.lineTotal,
            attachment_face_price:amounts.attachmentFee,material_difference:0,
            quick_base_price:quick.base_price,quick_attachment_fee:quick.attachment_fee,
            quick_total_cost:quick.total_cost,remark:'仅合成玻璃门回归'}};
        const document={order_nature:'EXTERNAL',quote_id:'LOCAL-GLASS-DOCUMENT-'+width,
          company_name:'合成玻璃门回归客户',company_code:'LOCAL-GLASS-CUSTOMER',quote_date:v2.quote_date,items:[item]};
        const before=pg.query('SELECT count(*) FROM calc.quote_document;');
        const checked=await call('/api/quotes/preview-check',document,active);
        assert.equal(checked.status,200,JSON.stringify(checked));
        assert.deepEqual(checked.body,{valid:true,checked_items:1,persisted:false});
        assert.equal(pg.query('SELECT count(*) FROM calc.quote_document;'),before);
        const snapshot={document:{order_nature:'EXTERNAL'},draft_items:[structuredClone(item)],
          quote_management:{versions:[{items:[structuredClone(item)]}]}};
        // Metadata must be removed before persistence as well: storing a
        // forged foreign metadata UUID must never grant later access to it.
        for(const savedItem of [snapshot.draft_items[0],snapshot.quote_management.versions[0].items[0]]) {
          savedItem.attachments[0].quote_line_id=foreign.body.quote_line_id;
          savedItem.attachments[0].environment.quote_line_id=foreign.body.quote_line_id;
        }
        const scheme=await call('/api/quote-schemes',{snapshot},active);
        assert.equal(scheme.status,201,JSON.stringify(scheme));
        const opened=await call('/api/quote-schemes/'+scheme.body.scheme_no,undefined,active);
        assert.equal(opened.status,200);
        assert.deepEqual(opened.body.snapshot.draft_items[0].attachments[0].manual_inputs,row.manual_inputs);
        assert.equal(opened.body.snapshot.draft_items[0].quote_display.total,amounts.lineTotal);
        for(const savedItem of [opened.body.snapshot.draft_items[0],opened.body.snapshot.quote_management.versions[0].items[0]]) {
          assert.equal(savedItem.quote_line_id,single.body.quote_line_id);
          for(const attachment of [savedItem.attachments[0],savedItem.quote_display.attachments[0]]) {
            assert.equal(attachment.quote_line_id,undefined);
            assert.equal(attachment.environment.quote_line_id,undefined);
          }
        }
        const confirmed=await call('/api/quotes/confirm',document,active);
        assert.equal(confirmed.status,200,JSON.stringify(confirmed));
        const exported=await request('/api/quotes/export',document,active);
        assert.equal(exported.status,200,exported.status===200?'':await exported.text());
        const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(Buffer.from(await exported.arrayBuffer()));
        assert.equal(workbook.getWorksheet('报价').getCell('F11').value,amounts.equivalentUnitTotal);
        assert.equal(workbook.getWorksheet('报价').getCell('G11').value,amounts.lineTotal);
        for(const route of ['/api/quotes/preview-check','/api/quotes/confirm','/api/quotes/export']) {
          const rejected=await call(route,document,other.body.token);
          assert.equal(rejected.status,403,JSON.stringify(rejected));
        }
        for(const field of ['quote_line_id','source_quote_line_id','quick_match_source_line_id']) {
          const forged=structuredClone(document);forged.items[0][field]=foreign.body.quote_line_id;
          const rejected=await call('/api/quotes/preview-check',forged,active);
          assert.equal(rejected.status,403,JSON.stringify(rejected));
        }
        for(const field of ['source_quote_line_id','quick_match_source_line_id']) {
          const forged=structuredClone(document);
          forged.items[0].attachments[0].environment[field]=foreign.body.quote_line_id;
          const rejected=await call('/api/quotes/preview-check',forged,active);
          assert.equal(rejected.status,403,JSON.stringify(rejected));
        }
        assert.equal(pg.query(`SELECT count(*) FROM calc.quote_name_owner WHERE resource_key='${row.quote_line_id}';`),'0');
      }
    });

    await t.test('every manual-dimension catalogue binding survives preview save reopen and export', async()=>{
      const manualNames=rule=>requiredParameters(rule).filter(p=>p.source==='MANUAL').map(p=>p.name);
      const inventory=catalog.body.items.filter(row=>(row.rules||[]).some(rule=>manualNames(rule).length));
      const families=[...new Set(inventory.map(row=>row.item_name))].sort();
      assert.deepEqual(families,['分段板','固定底座','外部眉头(柜体顶板上方)','无孔承板','有孔承板',
        '活动底座','玻璃门','侧门','通风顶罩'].sort());
      assert.equal(inventory.flatMap(row=>(row.rules||[]).filter(rule=>manualNames(rule).length)).length,113);
      const report={families,catalogue_items:inventory.length,manual_bindings:113,contexts:[],ui_cases:[]};
      const dimensions=(names,edit)=>Object.fromEntries(names.map(name=>[name,
        ['底座高度','通风顶罩高度','眉头高度'].includes(name)?100+edit*50:
          name==='分段板高度'?150+edit*50:name.includes('宽度')?600+edit*50:400+edit*50]));
      for(const material of ['SECC','SUS304','SUS316']) for(const mode of ['single','ganged']) {
        const key=material+'-'+mode;
        let payload={...cabinet('LOCAL-MANUAL-'+key),material_code:material,
          attachment_contract:2,pricing_basis:PRICING_BASIS};
        let result;
        if(mode==='ganged') {
          const children=[0,1].map(index=>({...cabinet('LOCAL-MANUAL-'+key+'-'+index,800+index*200),material_code:material}));
          payload={...payload,width_mm:1800,ganged_cabinet_count:2,ganged_cabinets:children,ganged_cabinet_inputs:children};
          result=await call('/api/quotes/calculate-ganged',{cabinets:children,attachment_payload:payload},token);
        } else result=await call('/api/quotes/calculate-dual',payload,token);
        assert.equal(result.status,200,JSON.stringify(result));
        payload.quote_id=result.body.quote_id;
        const cases=inventory.map(row=>({catalogue:row,names:manualNames(selectRule(row.rules,payload.product_code,material))}));
        assert.ok(cases.every(row=>row.names.length),'Every detected manual catalogue item is covered');
        for(const edit of [0,1]) {
          const completed=[];
          for(let offset=0;offset<cases.length;offset+=100) {
            const entries=cases.slice(offset,offset+100);
            const attachments=entries.map((entry,index)=>({attachment_price_id:entry.catalogue.attachment_price_id,
              quantity:1+(index%2),manual_inputs:dimensions(entry.names,edit),
              ...(mode==='ganged'?{ganged_cabinet_index:(offset+index)%2}:{})}));
            const preview=await call('/api/attachments/preview',{...payload,quote_id:'PREVIEW',attachments},token);
            assert.equal(preview.status,200,JSON.stringify(preview));
            preview.body.attachments.forEach((row,index)=>{
              assert.equal(row.status,'CALCULATED',JSON.stringify({name:row.item_name,error:row.error}));
              assert.deepEqual(row.manual_inputs,attachments[index].manual_inputs);
              assert.notEqual(row.quote_line_id,result.body.quote_line_id);
              assert.equal(row.environment.quote_line_id,row.quote_line_id);
              completed.push(row);
            });
          }
          const amounts=[];
          const items=completed.map((row,index)=>{
            const quick={...result.body.quick_quote,attachment_fee:row.quick_amount,
              total_cost:moneySum([result.body.quick_quote.base_price,row.quick_amount])};
            const amount=quickOrderLineBreakdown({quote:quick,attachments:[row],discount:.9,cabinetQuantity:2,freightFee:0});
            amounts.push(amount);
            const item={...payload,quote_line_id:result.body.quote_line_id,quantity:2,quick_discount:.9,
              name:row.item_name,specification:payload.model_code,attachments:[row],formula:result.body.formula_cost,quick,
              quote_display:{attachment_source:'popup_v1',attachments:[structuredClone(row)],quantity:2,discount:.9,
                name:row.item_name,specification:payload.model_code,unit:'台',unit_price:amount.equivalentUnitTotal,
                total:amount.lineTotal,attachment_face_price:amount.attachmentFee,material_difference:0,
                quick_base_price:quick.base_price,quick_attachment_fee:quick.attachment_fee,
                quick_total_cost:quick.total_cost,remark:'合成人工尺寸全量回归'}};
            if(material==='SECC'&&cases.findIndex(entry=>entry.catalogue.item_name===row.item_name)===index)
              report.ui_cases.push({mode,edit,names:cases[index].names,item:structuredClone(item)});
            return item;
          });
          const document={order_nature:'EXTERNAL',quote_id:'LOCAL-ALL-MANUAL-'+key+'-'+edit,
            company_name:'合成人工尺寸全量回归客户',company_code:'LOCAL-ALL-MANUAL-CUSTOMER',quote_date:payload.quote_date,items};
          const checked=await call('/api/quotes/preview-check',document,token);
          assert.equal(checked.status,200,JSON.stringify(checked));assert.equal(checked.body.checked_items,items.length);
          const created=await call('/api/quote-schemes',{snapshot:{document:{order_nature:'EXTERNAL'},draft_items:items,
            quote_management:{versions:[{items}]}}},token);
          assert.equal(created.status,201,JSON.stringify(created));
          const opened=await call('/api/quote-schemes/'+created.body.scheme_no,undefined,token);
          assert.equal(opened.status,200,JSON.stringify(opened));
          opened.body.snapshot.draft_items.forEach((item,index)=>{
            assert.deepEqual(item.attachments[0].manual_inputs,completed[index].manual_inputs);
            assert.equal(item.quote_display.total,amounts[index].lineTotal);
            assert.equal(item.attachments[0].quote_line_id,undefined);
            assert.equal(item.attachments[0].environment.quote_line_id,undefined);
          });
          const confirmed=await call('/api/quotes/confirm',document,token);
          assert.equal(confirmed.status,200,JSON.stringify(confirmed));
          const exported=await request('/api/quotes/export',document,token);
          assert.equal(exported.status,200,exported.status===200?'':await exported.text());
          const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(Buffer.from(await exported.arrayBuffer()));
          const sheet=workbook.getWorksheet('报价');
          amounts.forEach((amount,index)=>{
            assert.equal(sheet.getCell('F'+(11+index)).value,amount.equivalentUnitTotal);
            assert.equal(sheet.getCell('G'+(11+index)).value,amount.lineTotal);
          });
          const foreign=await call('/api/quotes/preview-check',document,other.body.token);
          assert.equal(foreign.status,403,JSON.stringify(foreign));
          // Required or invalid dimensions remain blocked independently of ID cleanup.
          const incomplete=structuredClone(document);
          for(const item of incomplete.items) {
            item.attachments[0].status='PENDING_MANUAL';item.attachments[0].pending_manual_dimensions=['缺少人工尺寸'];
            item.quote_display.attachments=structuredClone(item.attachments);
          }
          const invalid=await call('/api/quotes/preview-check',incomplete,token);
          assert.equal(invalid.status,422,JSON.stringify(invalid));
          report.contexts.push({material,mode,edit,rows:items.length,generated:true,saved:true,reopened:true,exported:true,scope_protected:true});
        }
      }
      t.diagnostic('ALL_MANUAL_DIMENSIONS '+JSON.stringify({families:report.families,bindings:report.manual_bindings,
        catalogue_items:report.catalogue_items,contexts:report.contexts.length,checked_rows:report.contexts.reduce((sum,row)=>sum+row.rows,0)}));
      if(process.env.AI_QUOTE_MANUAL_SCOPE_EVIDENCE_DIR) {
        const folder=new URL('file:///'+process.env.AI_QUOTE_MANUAL_SCOPE_EVIDENCE_DIR.replaceAll('\\','/')+'/');
        await mkdir(folder,{recursive:true});
        await writeFile(new URL('all-manual-dimensions.json',folder),JSON.stringify(report,null,2));
        const fixture=new URL('../test-output/attachment-cost-v2/',import.meta.url);await mkdir(fixture,{recursive:true});
        await writeFile(new URL('api-client-fixtures.json',fixture),JSON.stringify({catalog:catalog.body},null,2));
      }
    });

    await t.test('invalid V2 input and legacy nameless rows fail before ownership reservation', async()=>{
      const badRows=[{...selection,attachment_price_id:null},{...selection,attachment_price_id:0},
        {...selection,quantity:0},{...selection,manual_inputs:[]},{...selection,attachment_price_sign:0},
        {...selection,ganged_cabinet_index:20}];
      for (let index=0;index<badRows.length;index++) {
        const input={...v2,quote_id:'LOCAL-INVALID-'+index,attachments:[badRows[index]]};
        const response=await call('/api/quotes/calculate-dual',input,token);
        assert.equal(response.status,400,JSON.stringify(response));
        assert.equal(pg.query(`SELECT count(*) FROM calc.quote_name_owner WHERE resource_key='${input.quote_id}';`),'0');
      }
      const legacy=await call('/api/quotes/calculate-dual',{...v2,quote_id:'LOCAL-LEGACY',attachment_contract:undefined},token);
      assert.equal(legacy.status,400); assert.match(legacy.body.message,/requires model_code or item_name/);
      const invalidBatch=structuredClone(batch);
      invalidBatch.cabinets.forEach((row,index)=>{row.quote_id='LOCAL-INVALID-BATCH-'+index;});
      invalidBatch.attachment_payload.quote_id=invalidBatch.cabinets[0].quote_id;
      invalidBatch.attachment_payload.attachments[0].attachment_price_id=null;
      assert.equal((await call('/api/quotes/calculate-ganged',invalidBatch,token)).status,400);
      assert.equal(pg.query("SELECT count(*) FROM calc.quote_name_owner WHERE resource_key LIKE 'LOCAL-INVALID-BATCH-%';"),'0');
      const missing=await call('/api/quotes/calculate-dual',{...v2,quote_id:'LOCAL-UNKNOWN',attachments:[{...selection,attachment_price_id:9999999}]},token);
      assert.ok(missing.status>=400); assert.match(missing.body.message,/不属于当前目录/);
    });

    await t.test('another person cannot reuse the successful private quote identifier', async()=>{
      const response=await call('/api/quotes/calculate-dual',v2,other.body.token);
      assert.equal(response.status,403);
    });
  } finally {
    if (child&&child.exitCode===null) {const exited=once(child,'exit'); child.kill(); await exited;}
    await pg.close();
  }
});
