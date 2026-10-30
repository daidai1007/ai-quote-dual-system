// Opt-in integration test: a new disposable PostgreSQL cluster on loopback only.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';
import {createAttachmentService,sqlValue} from '../api/attachment_service.mjs';
import {PRICING_BASIS,moneyProduct,moneySum,quickOrderLineBreakdown} from '../quick_discount_rules.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const enabled=process.env.ATTACHMENT_PRECISION_DB_TEST==='1';
const baseResult=()=>({formula_cost:{material_cost:1000,auxiliary_cost:100,labor_cost:200,
  spray_cost:100,management_fee:84,total_cost:1484,attachment_fee:0},
quick_quote:{base_price:1000,total_cost:1000,attachment_fee:0}});

function documentItem(input,result,rows,quantity){
  const attachments=structuredClone(rows);
  const quick={base_price:1000,attachment_fee:moneySum(attachments.map(row=>row.quick_amount)),
    total_cost:moneySum([1000,...attachments.map(row=>row.quick_amount)])};
  const line=quickOrderLineBreakdown({quote:quick,attachments,discount:.5,cabinetQuantity:quantity});
  return {...input,name:'精度回归',specification:'800*600*(2000+100)',quantity,quick_discount:.5,
    formula_discount:1,freight_fee:0,attachment_contract:2,quote_line_id:result.quote_line_id,
    attachments,quick,quote_display:{attachment_source:'popup_v1',attachments:structuredClone(attachments),
      name:'精度回归',specification:'800*600*(2000+100)',unit:'台',quantity,discount:.5,
      unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:line.attachmentFee,
      material_difference:0,quick_base_price:1000,quick_attachment_fee:quick.attachment_fee,
      quick_total_cost:quick.total_cost,remark:'已确认弹窗'}};
}

test('real DB: exact catalogue audit, ordinary/ganged save, refresh and popup-driven Excel export',
  {skip:!enabled,timeout:90000},async t=>{
  const parent=path.join(root,'test-output');
  fs.mkdirSync(parent,{recursive:true});
  const folder=fs.mkdtempSync(path.join(parent,'attachment-precision-pg-'));
  const data=path.join(folder,'data');
  const bin=process.env.ATTACHMENT_PRECISION_PG_BIN||'G:/PostgreSQL/18/bin';
  const childEnv={...process.env,PGCLIENTENCODING:'UTF8'};
  for(const key of ['PGSERVICE','PGSERVICEFILE','PGPASSWORD','PGOPTIONS'])delete childEnv[key];
  const run=(exe,args,input)=>execFileSync(path.join(bin,exe),args,{input,encoding:'utf8',windowsHide:true,
    env:childEnv,timeout:30000,stdio:exe==='pg_ctl.exe'?'ignore':['pipe','pipe','pipe']})?.trim()??'';
  const reserve=net.createServer();
  await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
  const port=reserve.address().port;
  await new Promise(resolve=>reserve.close(resolve));
  run('initdb.exe',['-D',data,'-U','attachment_test','-A','trust','--encoding=UTF8','--no-locale']);
  try {
    run('pg_ctl.exe',['-D',data,'-l',path.join(folder,'server.log'),'-w','start','-o',`-h 127.0.0.1 -p ${port}`]);
    const sql=text=>run('psql.exe',['-X','-w','-h','127.0.0.1','-p',String(port),'-U','attachment_test',
      '-d','postgres','-v','ON_ERROR_STOP=1','-A','-t','-q'],text);
    const file=relative=>sql(fs.readFileSync(path.join(root,relative),'utf8'));
    file('tests/fixtures/attachment_online_schema_20260911.sql');
    file('database/attachment-v2/web/01-prepare.sql');
    const bundle=fs.readFileSync(path.join(root,'database/attachment-v2/generated/attachment-bundle.json'),'utf8');
    const version=JSON.parse(bundle).data_version;
    sql(`SELECT calc.stage_attachment_catalog_v2(convert_from(decode('${Buffer.from(bundle).toString('hex')}','hex'),'UTF8')::jsonb);
      BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2(${sqlValue(version)}); COMMIT;`);
    file('tests/fixtures/attachment_api_base_stub.sql');
    const queries=[];
    const service=createAttachmentService({env:{},calculateBase:async()=>baseResult(),
      runPsql:async text=>{queries.push(text);return sql(text);}});
    const initial=await service.catalog();
    const base=initial.items.find(row=>row.item_name==='固定底座'&&row.width_mm===800&&row.height_mm===100&&row.depth_mm===600);
    const side=initial.items.find(row=>row.item_name==='JP控制柜侧板'&&row.height_mm===2000&&row.depth_mm===600);
    const fan=initial.items.find(row=>row.category_level1==='风机');
    const board=initial.items.find(row=>row.item_name==='安装板'&&row.category_level1==='安装板');
    assert.ok(base&&side&&fan&&board);
    // Synthetic fractional fan price also exercises the non-sized path and
    // the difference between round(P*Q) and round(P)*Q.
    sql(`UPDATE calc.attachment_price SET quick_face_price=1.005,price=1.005 WHERE attachment_price_id=${fan.attachment_price_id};`);
    const catalogue=await service.catalog();
    const catalogueBefore=sql('SELECT jsonb_agg(to_jsonb(p) ORDER BY attachment_price_id) FROM calc.attachment_price p;');
    const guardBefore=sql("SELECT pg_get_functiondef('calc.guard_attachment_selection_v2()'::regprocedure);");
    const input={quote_id:'PRECISION',product_code:'JP',material_code:'SECC',width_mm:800,height_mm:2000,
      depth_mm:600,coating_type:'橘纹',quote_date:'2026-10-19',material_unit_price_override:4.2,
      pricing_basis:PRICING_BASIS,attachments:[]};
    let ordinary,ganged,gangedInput;
    const frozen=line=>sql(`SELECT to_jsonb(l)||jsonb_build_object('rows',
      (SELECT jsonb_agg(to_jsonb(s) ORDER BY attachment_selection_id) FROM calc.attachment_selection s
      WHERE s.quote_line_id=l.quote_line_id)) FROM calc.attachment_quote_line l
      WHERE l.quote_line_id=${sqlValue(line.quote_line_id)}::uuid;`);
    const audit=line=>JSON.parse(sql(`SELECT jsonb_agg(to_jsonb(s) ORDER BY attachment_selection_id)
      FROM calc.attachment_selection s WHERE quote_line_id=${sqlValue(line.quote_line_id)}::uuid;`));
    const checkAudit=line=>{
      for(const row of audit(line)){
        const item=catalogue.items.find(value=>value.attachment_price_id===row.attachment_price_id);
        const effective=line.attachments.find(value=>value.attachment_selection_id===row.attachment_selection_id);
        assert.equal(row.quick_face_price,item.price);
        assert.equal(row.quick_amount,moneyProduct(row.quantity,item.price,row.price_sign));
        assert.equal(row.cost_snapshot.catalogue_face_price,item.price);
        assert.equal(row.cost_snapshot.quick_amount,effective.quick_amount);
        assert.equal(row.cost_snapshot.formula_amount,effective.formula_amount);
      }
    };

    await t.test('screenshot configuration and quantity 1/10 persist full raw prices under unchanged strict guards',async()=>{
      for(const quantity of [1,10]){
        ordinary=await service.calculate({...input,attachments:[
          {attachment_price_id:base.attachment_price_id,quantity,manual_inputs:{底座高度:100}},
          {attachment_price_id:side.attachment_price_id,quantity},
          {attachment_price_id:fan.attachment_price_id,quantity},
        ]});
        checkAudit(ordinary);
        assert.ok(ordinary.attachments.every(row=>['CALCULATED','FIXED'].includes(row.status)));
        assert.equal(ordinary.attachments[0].catalogue_face_price,264.6081);
        assert.equal(ordinary.attachments[1].catalogue_face_price,737.216821);
        assert.equal(ordinary.attachments[2].quick_amount,moneyProduct(1.01,quantity));
      }
      const source=audit(ordinary)[0];
      const columns=sql("SELECT column_name FROM information_schema.columns WHERE table_schema='calc' AND table_name='attachment_selection' AND column_name<>'attachment_selection_id' ORDER BY ordinal_position;").split(/\r?\n/);
      const expressions=columns.map(column=>column==='quick_face_price'?'round(quick_face_price,2)':column);
      assert.throws(()=>sql(`INSERT INTO calc.attachment_selection(${columns.join(',')}) SELECT ${expressions.join(',')}
        FROM calc.attachment_selection WHERE attachment_selection_id=${source.attachment_selection_id};`),/附件目录版本或面价不一致/);
      const wrongVersion=columns.map(column=>column==='catalog_version'?"'wrong-version'":column);
      assert.throws(()=>sql(`INSERT INTO calc.attachment_selection(${columns.join(',')}) SELECT ${wrongVersion.join(',')}
        FROM calc.attachment_selection WHERE attachment_selection_id=${source.attachment_selection_id};`),/附件目录版本或面价不一致/);
    });

    await t.test('recalculation preserves precision, perimeter amounts, deductions and immutable old snapshots',async()=>{
      const before=frozen(ordinary);
      const fresh=await service.recalculateLine({quote_line_id:ordinary.quote_line_id,pricing_basis:PRICING_BASIS,
        attachments:[{attachment_price_id:base.attachment_price_id,quantity:2,manual_inputs:{底座高度:150}},
          {attachment_price_id:board.attachment_price_id,quantity:2,attachment_price_sign:-1}]});
      checkAudit(fresh);
      assert.notEqual(fresh.quote_line_id,ordinary.quote_line_id);
      assert.equal(frozen(ordinary),before);
      assert.notEqual(fresh.attachments[0].quick_amount,fresh.attachments[0].catalogue_quick_amount);
      assert.ok(fresh.attachments[1].quick_amount<0);
      assert.ok(fresh.attachments[1].formula_amount<0);
    });

    await t.test('ganged snapshot uses each child dimensions while audit prices remain catalogue originals',async()=>{
      const children=[{product_code:'JP_SINGLE',width_mm:800,height_mm:2000,depth_mm:600},
        {product_code:'JP_DOUBLE',width_mm:700,height_mm:1800,depth_mm:500}];
      gangedInput={...input,ganged_cabinet_count:2,ganged_cabinets:children,ganged_cabinet_inputs:children,
        attachments:children.map((child,index)=>({attachment_price_id:base.attachment_price_id,
          quantity:2,manual_inputs:{底座高度:100},ganged_cabinet_index:index})),base_result:baseResult()};
      ganged=await service.snapshotGanged(gangedInput);
      checkAudit(ganged);
      assert.deepEqual(ganged.attachments.map(row=>row.ganged_cabinet_index),[0,1]);
      assert.notEqual(ganged.attachments[0].quick_amount,ganged.attachments[1].quick_amount);
      assert.notEqual(ganged.attachments[0].formula_amount,ganged.attachments[1].formula_amount);
      assert.equal(sql('SELECT jsonb_agg(to_jsonb(p) ORDER BY attachment_price_id) FROM calc.attachment_price p;'),catalogueBefore);
      assert.equal(sql("SELECT pg_get_functiondef('calc.guard_attachment_selection_v2()'::regprocedure);"),guardBefore);
    });

    await t.test('legacy explicit manual cost and popup sale/zero survive catalogue changes and both Excel sheets for ordinary/ganged quantity 1/10',async()=>{
      const before=frozen(ordinary),beforeGanged=frozen(ganged);
      sql(`UPDATE calc.attachment_price SET quick_face_price=999.123456 WHERE attachment_price_id=${base.attachment_price_id};`);
      for(const [kind,result,request] of [['ordinary',ordinary,input],['ganged',ganged,gangedInput]]){
        for(const sale of [333.33,0]) for(const quantity of [1,10]){
          const rows=[{...result.attachments[0],quantity:3,formula_amount:75.25,
            formula_cost_edited:true,formula_unit_cost_override:75.25/3,
            quick_amount:sale,quick_amount_override:sale,custom_amount_edited:true}];
          const item=documentItem(request,result,rows,quantity);
          queries.length=0;
          const payload=await service.hydrateDocument({quote_id:'PRECISION-DOCUMENT',quote_date:input.quote_date,
            company_name:'精度测试',items:[item]});
          assert.equal(queries.length,1);
          assert.doesNotMatch(queries[0],/calc\.attachment_price\b|calc\.attachment_cost_rule\b|calc\.attachment_selection\b|\bINSERT\b/);
          const hydrated=payload.items[0];
          assert.equal(hydrated.attachments[0].quick_amount,sale);
          assert.equal(hydrated.attachments[0].formula_amount,75.25);
          assert.equal(hydrated.attachments[0].catalogue_face_price,264.6081);
          assert.equal(hydrated.quick.attachment_fee,sale);
          assert.equal(hydrated.formula.attachment_fee,75.25);
          const name=`${kind}-${sale}-${quantity}`;
          const source=path.join(folder,`${name}.json`),output=path.join(folder,`${name}.xlsx`);
          fs.writeFileSync(source,JSON.stringify(payload));
          execFileSync(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),source,output],
            {cwd:root,env:childEnv,windowsHide:true,timeout:30000,stdio:'pipe'});
          const workbook=new ExcelJS.Workbook();await workbook.xlsx.readFile(output);
          for(const [sheet,amount] of [['报价',sale],['成本',75.25]]){
            const table=workbook.getWorksheet(sheet);
            const column=table.getRow(10).values.findIndex(value=>value===base.item_name);
            assert.ok(column>0,`${name}: missing ${sheet} fixed-base column`);
            assert.equal(table.getCell(11,column).value,amount,`${name}: ${sheet}`);
          }
          assert.equal(workbook.getWorksheet('报价').getCell('F11').value,item.quote_display.unit_price);
          assert.equal(workbook.getWorksheet('报价').getCell('G11').value,item.quote_display.total);
          assert.equal(workbook.getWorksheet('成本').getCell('F11').value,hydrated.formula.total_cost);
          assert.equal(workbook.getWorksheet('成本').getCell('G11').value,moneyProduct(hydrated.formula.total_cost,quantity));
          const detail=workbook.getWorksheet('附件双报价明细');
          assert.equal(detail.getCell('L2').value,sale);
          assert.equal(detail.getCell('W2').value,75.25);
          assert.equal(detail.getCell('AF2').value,'当前附件弹窗确认快照');
        }
      }
      assert.equal(frozen(ordinary),before);
      assert.equal(frozen(ganged),beforeGanged);
    });
  }finally{
    if(fs.existsSync(path.join(data,'postmaster.pid')))run('pg_ctl.exe',['-D',data,'-w','stop','-m','fast']);
    if(!fs.existsSync(path.join(data,'postmaster.pid'))&&path.dirname(folder)===parent
      &&path.basename(folder).startsWith('attachment-precision-pg-')) fs.rmSync(folder,{recursive:true,force:true});
  }
});
