// Execute the real server functions with only HTTP listen and psql replaced.
// No socket or database is opened. Expose private functions in this test's VM
// copy; production source and its public exports remain unchanged.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const serverUrl=new URL('../api/server.mjs',import.meta.url);
const context=vm.createContext({console,process:{env:{}},Buffer,URL,setTimeout,clearTimeout,setInterval,clearInterval});
const imports=new Map();
let execute;
const source=fs.readFileSync(serverUrl,'utf8')+'\nexport {normalizeProductVariant,createQuoteServices};';
const module=new vm.SourceTextModule(source,{context,identifier:serverUrl.href,
 initializeImportMeta:meta=>{meta.url=serverUrl.href;}});
await module.link(async(specifier)=>{
 if(imports.has(specifier))return imports.get(specifier);
 let values;
 if(specifier==='node:http')values={default:{createServer:()=>({listen:()=>{}})}};
 else if(specifier==='./psql_runner.mjs')values={runPsqlCommand:async sql=>execute(sql)};
 else values=await import(specifier.startsWith('.')?new URL(specifier,serverUrl):specifier);
 const names=Object.keys(values);
 const linked=new vm.SyntheticModule(names,function(){for(const name of names)this.setExport(name,values[name]);},{context});
 imports.set(specifier,linked);return linked;
});
await module.evaluate();
const {normalizeProductVariant,createQuoteServices}=module.namespace;
const read=path=>JSON.parse(fs.readFileSync(new URL(path,import.meta.url)));
const cases=read('./fixtures/jc_profiles.json');
const bundles=Object.fromEntries(['material','spray','auxiliary','labor'].map(kind=>[kind,
 read(`../database/cabinet-${kind}/generated/cabinet-${kind}-bundle.json`)]));
const result={quote_id:'offline-jc',formula_cost:{material_cost:1,auxiliary_cost:1,labor_cost:1,
 spray_cost:1,management_fee:1,total_cost:5,attachment_fee:0},
 quick_quote:{base_price:1000,attachment_fee:0,total_cost:1000}};
const setup=({missing=null,noFace=false}={})=>{
 const calls=[];
 execute=async sql=>{
  calls.push(sql);
  if(sql.startsWith('BEGIN;'))return JSON.stringify(noFace?{...result,quick_quote:{base_price:null}}:result);
  for(const kind of Object.keys(bundles))if(sql.includes(`calc.cabinet_${kind}_catalog_version`)){
   if(kind===missing)return 'null';
   return JSON.stringify({...bundles[kind],materials:[{material_code:'SECC',density_g_cm3:7.85,material_unit_price:4.5}]});
  }
  throw new Error('Unexpected SQL in offline JC test: '+sql.slice(0,60));
 };
 return calls;
};
const input=row=>normalizeProductVariant({quote_id:'offline-jc',product_code:'JC_EXP',variant_code:'DEFAULT',
 model_code:row.model,material_code:'SECC',coating_type:'橘纹',width_mm:600,height_mm:1600,depth_mm:row.depth,
 quote_date:'2026-11-26',single_door_count:1,double_door_count:0,material_unit_price_override:4.5,
 surface_treatment_unit_price_override:26,attachments:[]});
for(const row of cases)test(`server flow: ${row.model} preserves ${row.profile} through all four cost services and face SQL`,async()=>{
 const calls=setup(),request=input(row);
 assert.equal(request.variant_code,row.profile);
 const response=await createQuoteServices().calculateBaseQuote(request);
 const expected=bundles.auxiliary.fixed_rules.find(rule=>rule.product_code==='JC_EXP'&&rule.profile_code===row.profile
  &&Number(rule.depth_mm)===row.depth&&(rule.material_codes||[]).includes('SECC'));
 assert.equal(response.formula_cost.auxiliary_cost,Number(expected.auxiliary_cost));
 const sql=calls.find(sql=>sql.startsWith('BEGIN;'));
 assert(sql.includes(Buffer.from(row.profile).toString('hex')));
 assert(!sql.includes('calc.match_quick_quote('),'typed JC must not call the mixed-profile face matcher');
 assert.equal(response.quick_quote.base_price,1000);
});
test('server flow: an incomplete cost catalogue fails before running the legacy quote calculation',async()=>{
 const calls=setup({missing:'spray'});
 await assert.rejects(createQuoteServices().calculateBaseQuote(input(cases[0])),/分型成本目录不完整/);
 assert(!calls.some(sql=>sql.startsWith('BEGIN;')));
});
test('server flow: missing same-profile face price is not a successful zero quotation',async()=>{
 setup({noFace:true});
 await assert.rejects(createQuoteServices().calculateBaseQuote(input(cases[2])),/豪华型.*同型面价/);
});
