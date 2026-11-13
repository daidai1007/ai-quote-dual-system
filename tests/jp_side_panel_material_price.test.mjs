import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import os from 'node:os';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';
import {attachmentQuickPrice} from '../api/attachment_cost.mjs';
import {sqlValue} from '../api/attachment_service.mjs';
import {createAttachmentMaintenance} from '../api/attachment_maintenance.mjs';
import {money, moneyProduct, PRICING_BASIS, quickOrderLineBreakdown} from '../quick_discount_rules.mjs';
import {localApiSession, installLocalNameScope} from './helpers/local_api_session.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {quickQuotationAmount} from './quotation_layout_reader.mjs';

const specifications=[
  [997,1800,400,524.593927,1101], [998,1800,600,672.646139,1515],
  [999,2000,600,737.216821,1674], [1000,2000,800,897.352093,2130],
  [1001,2200,600,801.593298,1830], [1002,2200,800,981.821830,2340],
];
const sidePanel=(height_mm,depth_mm,price,sus304)=>({item_name:'JP控制柜侧板',category_level1:'侧板',
  height_mm,depth_mm,price,quick_face_prices_by_material:{SUS304:sus304}});

test('SUS304 prices preserve catalogue audit values and existing price precision for other materials',()=>{
  for (const [id,height,depth,base,sus304] of specifications) {
    for (const material of ['SECC','SUS304','SUS316']) {
      const input={attachment_price_id:id,quantity:2};
      const price=attachmentQuickPrice(input,sidePanel(height,depth,base,sus304),{
        height_mm:height,depth_mm:depth,material_code:material,pricing_basis:PRICING_BASIS,
      },2,1);
      assert.equal(price.catalogue_face_price,base);
      assert.equal(price.quick_amount,moneyProduct(2,money(material==='SUS304'?sus304:base)));
      assert.equal(price.material_quick_face_price,material==='SUS304'?sus304:undefined);
    }
  }
  const nonstandard=attachmentQuickPrice({},sidePanel(2000,600,737.216821,1674),{
    height_mm:2050,depth_mm:600,material_code:'SUS304',pricing_basis:PRICING_BASIS,
  },2,1);
  assert.equal(nonstandard.quick_amount,3412.38);
});

const sqlDirectory=process.env.JP_SIDE_PANEL_SQL_DIR;
test('isolated HTTP, PostgreSQL and Excel use the C migration and preserve approved snapshots',
  {skip:!sqlDirectory,timeout:180_000},async()=>{
    const pg=await startLocalPostgres({outputRoot:os.tmpdir()});
    const sql=pg.query;
    const repoFile=relative=>fs.readFile(new URL('../'+relative,import.meta.url),'utf8');
    const migration=async file=>sql(await fs.readFile(path.join(sqlDirectory,file),'utf8'));
    let server;
    try {
      for (const file of ['tests/fixtures/attachment_online_schema_20260911.sql',
        'database/attachment-v2/web/01-prepare.sql','tests/fixtures/attachment_api_base_stub.sql',
        ...['cabinet_material_v2.sql','cabinet_spray_v2.sql','cabinet_auxiliary_v3.sql','cabinet_labor_v1.sql',
          'attachment_maintenance.sql'].map(name=>'database/migrations/'+name)]) sql(await repoFile(file));
      installLocalNameScope(sql);
      sql("SELECT setval(pg_get_serial_sequence('calc.attachment_price','attachment_price_id'),997,false)");
      const bundle=await repoFile('database/attachment-v2/generated/attachment-bundle.json');
      const version=sql(`SELECT calc.stage_attachment_catalog_v2(${sqlValue(bundle)}::jsonb)`);
      sql(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2(${sqlValue(version)}); COMMIT;`);
      await migration('草案01-建立材质面价结构.sql');

      const reserve=net.createServer();
      await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
      const port=reserve.address().port;
      await new Promise(resolve=>reserve.close(resolve));
      const environment={...process.env,DATABASE_URL:'',PGSSLMODE:'disable',RENDER:'',
        AI_QUOTE_API_KEY:'local-regression-only',AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),
        PSQL_PATH:pg.connection.psql,AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:String(pg.connection.port),
        AI_QUOTE_DB_USER:pg.connection.user,AI_QUOTE_DB_NAME:pg.connection.database,AI_QUOTE_ATTACHMENT_V2_VERSION:''};
      for (const key of ['PGSERVICE','PGSERVICEFILE','PGPASSWORD','PGPASSFILE','PGHOSTADDR','PGOPTIONS'])
        delete environment[key];
      // Collect psql diagnostics only inside the synthetic loopback fixture.
      const launch=`const child=require('node:child_process');
        const spawn=child.spawn;
        child.spawn=(...args)=>{
          const proc=spawn(...args);
          if(String(args[0]).toLowerCase().endsWith('psql.exe')) proc.stderr.on('data',data=>process.stderr.write(data));
          return proc;
        };
        require('node:module').syncBuiltinESMExports();
        import('./api/server.mjs');`;
      server=spawn(process.execPath,['-e',launch],{cwd:new URL('../',import.meta.url),
        windowsHide:true,env:environment});
      let serverErrors='';
      server.stderr.on('data',chunk=>{serverErrors+=String(chunk);});
      await new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>reject(new Error('Local API did not start')),10_000);
        server.stdout.on('data',data=>{if(String(data).includes('listening')){clearTimeout(timeout);resolve();}});
        server.once('error',error=>{clearTimeout(timeout);reject(error);});
        server.once('exit',code=>{clearTimeout(timeout);reject(new Error('Local API exited '+code));});
      });
      const api=await localApiSession(`http://127.0.0.1:${port}`);
      const call=async(route,payload,expected=200)=>{
        const response=await api.fetch(route,payload?{method:'POST',headers:{'content-type':'application/json'},
          body:JSON.stringify(payload)}:{});
        const body=await response.json();
        assert.equal(response.status,expected,JSON.stringify(body)+'\n'+serverErrors.slice(-3000));
        return body;
      };
      const selection=(id=999,quantity=2)=>({attachment_price_id:id,quantity});
      const quoteInput=(overrides={})=>({quote_id:'LOCAL_SIDE_OLD',product_code:'JP_SINGLE',
        material_code:'SUS304',width_mm:800,height_mm:2000,depth_mm:600,quote_date:'2026-11-12',
        coating_type:'不喷塑',material_unit_price_override:16,galvanized_sheet_unit_price_override:5,
        carbon_steel_unit_price_override:5,attachment_contract:2,attachment_material_price_contract:1,
        pricing_basis:PRICING_BASIS,attachments:[selection()],...overrides});
      function document(id,input,calculated,rows=calculated.attachments) {
        const quick={...calculated.quick_quote,attachment_fee:rows[0].quick_amount,
          total_cost:calculated.quick_quote.base_price+rows[0].quick_amount};
        const amounts=quickOrderLineBreakdown({quote:quick,attachments:rows,discount:1,cabinetQuantity:1,freightFee:0});
        const name='JP 侧板联调',specification=input.height_mm?'800×600×'+input.height_mm:'2000×600',unit=input.unit||'台';
        const item={...input,name,specification,quantity:1,unit,
          quick,attachments:rows,quick_discount:1,formula_discount:1,freight_fee:0,quote_line_id:calculated.quote_line_id,
          quote_display:{attachment_source:'popup_v1',attachments:rows,name,specification,unit,quantity:1,discount:1,
            unit_price:amounts.equivalentUnitTotal,total:amounts.lineTotal,attachment_face_price:amounts.attachmentFee,
            material_difference:0,quick_base_price:quick.base_price,quick_attachment_fee:quick.attachment_fee,
            quick_total_cost:quick.total_cost,remark:'本机联调'}};
        return {quote_id:id,quote_date:input.quote_date,company_name:'本机测试',company_code:id,
          order_nature:'EXTERNAL',items:[item]};
      }
      const exportTotal=async doc=>{
        const response=await api.fetch('/api/quotes/export',{method:'POST',headers:{'content-type':'application/json'},
          body:JSON.stringify(doc)});
        assert.equal(response.status,200,response.ok?'':await response.text());
        const workbook=new ExcelJS.Workbook();
        await workbook.xlsx.load(Buffer.from(await response.arrayBuffer()));
        return quickQuotationAmount(workbook.getWorksheet('报价').getCell('G11'));
      };

      const oldInput=quoteInput({attachment_material_price_contract:undefined});
      const old=await call('/api/quotes/calculate-dual',oldInput);
      assert.equal(old.attachments[0].quick_amount,1474.44);
      const oldDocument=document('LOCAL_SIDE_DOC_OLD',oldInput,old);
      await call('/api/quotes/confirm',oldDocument);
      const independent={attachment_price_id:999,standalone_material_code:'SUS304',
        standalone_cost_settings:{galvanized_price:5,carbon_price:5,stainless_304_price:16,
          stainless_316_price:32.4,surface_price:0}};
      const independentDocument=(id,rows)=>document(id,{
        item_type:'standalone_attachment',attachment_contract:'standalone_v1',
        product_code:'STANDALONE_ATTACHMENT',quote_date:'2026-11-12',unit:rows[0].unit,
        pricing_basis:PRICING_BASIS,scheme2_cost_settings:independent.standalone_cost_settings,
      },{quick_quote:{base_price:0},attachments:rows});
      const beforeIndependent=await call('/api/attachments/preview-standalone',{attachments:[independent]});
      const oldIndependent=independentDocument('LOCAL_SIDE_INDEPENDENT_OLD',beforeIndependent.attachments);
      await call('/api/quotes/confirm',oldIndependent);

      await migration('草案02-启用六档SUS304面价.sql');
      const staleDraft=document('LOCAL_SIDE_DOC_OLD_UNCONFIRMED',oldInput,old);
      for (const route of ['/api/quotes/preview-check','/api/quotes/confirm-check','/api/quotes/confirm']) {
        const legacy=await call(route,staleDraft,422);
        assert.match(legacy.message,/更新报价客户端/);
      }
      const updatedDraft={...staleDraft,attachment_material_price_contract:1};
      const recalculation=await call('/api/quotes/confirm-check',updatedDraft,422);
      assert.match(recalculation.message,/材质面价已变更，请重新计算/);
      assert.equal(sql("SELECT count(*) FROM calc.quote_document WHERE quote_id='LOCAL_SIDE_DOC_OLD_UNCONFIRMED'"),'0');
      const catalogue=await call('/api/attachments/catalog?v=2');
      const maintainer={identityMode:'NAME_ONLY',displayName:'戴晨丽',userId:'name-user:'+'0'.repeat(64)};
      const maintenance=await createAttachmentMaintenance({runPsql:async text=>sql(text)}).list(maintainer);
      const managedPanel=maintenance.items.find(item=>item.attachment_price_id===999);
      assert.equal(Number(managedPanel.quick_face_price),737.216821);
      assert.equal(managedPanel.quick_face_prices_by_material.SUS304,1674);
      assert.equal(managedPanel.editable,false);
      for (const [id,height,depth,base,sus304] of specifications) {
        const row=catalogue.items.find(item=>item.attachment_price_id===id);
        assert.equal(row.price,base);
        assert.equal(row.quick_face_prices_by_material.SUS304,sus304);
        for (const material of ['SECC','SUS304','SUS316']) {
          const result=await call('/api/attachments/preview',quoteInput({material_code:material,height_mm:height,
            depth_mm:depth,attachments:[selection(id)]}));
          assert.equal(result.attachments[0].quick_amount,moneyProduct(2,money(material==='SUS304'?sus304:base)));
          if (id===999 && material==='SUS304')
            assert.equal(result.attachments[0].formula_amount,old.attachments[0].formula_amount);
        }
      }
      const oldClient=await call('/api/attachments/preview',quoteInput({
        attachment_material_price_contract:undefined,
      }),400);
      assert.match(oldClient.message,/更新报价客户端/);
      const freshInput=quoteInput({quote_id:'LOCAL_SIDE_NEW',height_mm:2050});
      const fresh=await call('/api/quotes/calculate-dual',freshInput);
      assert.equal(fresh.attachments[0].quick_amount,3412.38);
      const ganged=await call('/api/attachments/preview',quoteInput({
        ganged_cabinet_count:2,ganged_cabinets:[
          {product_code:'JP_SINGLE',width_mm:400,height_mm:2000,depth_mm:600},
          {product_code:'JP_SINGLE',width_mm:400,height_mm:2050,depth_mm:600}],
        attachments:[{...selection(),ganged_cabinet_index:1}],
      }));
      assert.equal(ganged.attachments[0].quick_amount,3412.38);
      const standalone=await call('/api/attachments/preview-standalone',{
        attachments:[independent],attachment_material_price_contract:1});
      assert.equal(standalone.attachments[0].quick_amount,1674);
      const oldStandalone=await call('/api/attachments/preview-standalone',{attachments:[independent]},400);
      assert.match(oldStandalone.message,/更新报价客户端/);
      const newIndependent=independentDocument('LOCAL_SIDE_INDEPENDENT_NEW',standalone.attachments);
      await call('/api/quotes/confirm',newIndependent);
      assert.equal(await exportTotal(oldIndependent),737.22);
      assert.equal(await exportTotal(newIndependent),1674);
      const reprice=await call('/api/attachments/recalculate-line',{quote_line_id:fresh.quote_line_id,
        attachments:[selection(999,1)],attachment_material_price_contract:1,pricing_basis:PRICING_BASIS});
      assert.equal(reprice.attachments[0].quick_amount,1706.19);
      assert.equal(fresh.attachments[0].catalogue_face_price,737.216821);
      assert.equal(fresh.attachments[0].material_quick_face_price,1674);
      const doc=document('LOCAL_SIDE_DOC_NEW',freshInput,fresh);
      const underpriced={...fresh.attachments[0],quick_amount:1474.44,unit_price_override:737.22};
      const invalid=await call('/api/quotes/confirm-check',document('LOCAL_SIDE_DOC_BAD',freshInput,fresh,[underpriced]),422);
      assert.match(invalid.message,/自动金额与材质面价不一致/);
      const manual={...underpriced,quick_amount_override:1474.44,custom_amount_edited:true};
      await call('/api/quotes/confirm-check',document('LOCAL_SIDE_DOC_MANUAL',freshInput,fresh,[manual]));
      await call('/api/quotes/confirm',doc);
      const stored=JSON.parse(sql("SELECT document_payload FROM calc.quote_document WHERE quote_id='LOCAL_SIDE_DOC_NEW'"));
      assert.equal(stored.items[0].attachments[0].quick_amount,3412.38);
      assert.equal(stored.items[0].attachments[0].formula_amount,fresh.attachments[0].formula_amount);
      const reopened=await call('/api/company-history/match',{...freshInput,company_code:doc.company_code});
      assert.equal(reopened.payload.attachments[0].quick_amount,3412.38);
      assert.equal(await exportTotal(oldDocument),oldDocument.items[0].quote_display.total);
      assert.equal(await exportTotal(doc),doc.items[0].quote_display.total);

      await migration('草案03-撤回本批SUS304面价.sql');
      const withdrawnDraft={...doc,quote_id:'LOCAL_SIDE_DOC_WITHDRAWN_UNCONFIRMED'};
      const withdrawn=await call('/api/quotes/confirm-check',withdrawnDraft,422);
      assert.match(withdrawn.message,/材质面价已变更，请重新计算/);
      assert.equal(await exportTotal(doc),doc.items[0].quote_display.total);
      assert.equal(await exportTotal(newIndependent),1674);
      const independentAgain=await call('/api/attachments/preview-standalone',{
        attachments:standalone.attachments,attachment_material_price_contract:1});
      assert.equal(independentAgain.attachments[0].quick_amount,737.22);
      assert.equal(independentAgain.attachments[0].quick_price_material_code,undefined);
      const afterRollback=await call('/api/attachments/preview',oldInput);
      assert.equal(afterRollback.attachments[0].quick_amount,1474.44);
      assert.equal(afterRollback.attachments[0].formula_amount,old.attachments[0].formula_amount);
    } catch (error) {
      const log=await fs.readFile(pg.logFile,'utf8');
      console.error(log.split(/\r?\n/).filter(line=>/\b(?:ERROR|FATAL):/.test(line)).slice(-8).join('\n'));
      throw error;
    } finally {
      if (server && server.exitCode==null && server.signalCode==null) {
        const closed=once(server,'exit');
        server.kill();
        await closed;
      }
      await pg.close();
    }
  });
