import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseFormula, evaluateFormula, formulaVariables } from '../api/attachment_formula.mjs';
import { calculateAttachment, attachmentTotals, selectRule, requiredParameters, PRODUCT_CODES, MATERIAL_CODES } from '../api/attachment_cost.mjs';
import {attachmentCatalogFixture} from './helpers/attachment_catalog_fixture.mjs';
const bundle = JSON.parse(fs.readFileSync(new URL('../database/attachment-v2/generated/attachment-bundle.json', import.meta.url)));
const env = { quote_line_id: 'line-a', product_code: 'JP', width_mm: 800, height_mm: 2000, depth_mm: 600, material_code: 'SECC', density_g_cm3: 7.85, material_unit_price: 5, spray_unit_price: 10, coating_type: '橘纹', quote_date: '2026-09-10' };
const catalog = { attachment_price_id: 1, data_version: 'v', item_name: '安装板', category_level1: '安装板', category_level2: '', price: 483.46155, unit: '件' };
const dynamic = bundle.rules.find(r => r.source_row_no === 3);
const fixed = { rule_id: 2, method: 'FIXED', fixed_cost: 27.56, products: [], data_version: 'v', auxiliary_list: '说明\n保留换行' };

test('JM防雨顶按目录类别采用对应公式，保留原产品、数量和输入', () => {
  const {items}=attachmentCatalogFixture();
  const environment={...env,product_code:'JM',width_mm:600,depth_mm:600,
    material_unit_price:4.2,spray_unit_price:26};
  const cabinetArea=((600+353.5)*(600+195.7)+(600+97)*118*2)*1e-6;
  const boxArea=(600+247.5)*(600+182.5)*1e-6;
  for (const [category,area,auxiliary,labor,ruleId] of [
    ['控制柜附件',cabinetArea,60,4.5714+20.7143*.6+9.6429*.6,'R53'],
    ['控制箱附件',boxArea,0,8.5158+16.8345*1200*2*.001,'R44'],
  ]) {
    const item=items.find(row=>row.category_level1===category&&row.item_name==='防雨顶');
    const before=structuredClone({item,environment});
    for (const quantity of [1,3]) {
      const result=calculateAttachment({quantity,category_level1:category==='控制柜附件'?'控制箱附件':'控制柜附件'},
        item,item.rules,environment);
      const cost=area*1.5*7.85*4.2+area*26+auxiliary+labor;
      assert.equal(result.status,'CALCULATED',result.error);
      assert.equal(result.rule_id,ruleId);
      assert.ok(Math.abs(result.formula_unit_cost-cost)<1e-7);
      assert.equal(result.formula_amount,Math.round(cost*quantity*100)/100);
      assert.equal(result.environment.product_code,'JM');
      assert.equal(result.category_level1,category,'Use authoritative category, not client text');
    }
    assert.deepEqual({item,environment},before);
  }
});

test('控制箱和控制柜附件跨产品复用所属类别规则，保留超宽、材质及冲突校验', () => {
  const {items}=attachmentCatalogFixture();
  const products=[...new Set(Object.values(PRODUCT_CODES).flat()),'JC_EXP','OP_TABLE_EXP'];
  for (const item of items.filter(row=>['控制柜附件','控制箱附件'].includes(row.category_level1))) {
    for (const product_code of products) {
      const referenceProduct=item.category_level1==='控制柜附件'
        ? (product_code.includes('WIDE')?'JP_WIDE_EXP':'JP')
        : item.item_name==='JK安装板'?'JK':'JA_SINGLE';
      const environment={...env,product_code};
      const selection={quantity:2,manual_inputs:{玻璃门宽度:500,玻璃门高度:1400,通风顶罩高度:100}};
      const expected=calculateAttachment(selection,item,item.rules,{...environment,product_code:referenceProduct});
      const result=calculateAttachment(selection,item,item.rules,environment);
      assert.equal(result.status,expected.status,item.item_name+' / '+product_code+': '+result.error);
      assert.notEqual(result.status,'QUICK_ONLY',item.item_name+' / '+product_code);
      assert.equal(result.rule_id,expected.rule_id);
      assert.equal(result.formula_amount,expected.formula_amount);
      assert.equal(result.quick_amount,expected.quick_amount);
    }
  }
  const rule={...fixed,products:['JP'],materials:['SECC']};
  assert.equal(selectRule([rule],'JM','SECC','控制柜附件'),rule);
  assert.throws(()=>selectRule([rule],'JM','SUS304','控制柜附件'),/缺少附件成本规则/);
  assert.throws(()=>selectRule([rule,{...rule,rule_id:99}],'JM','SECC','控制柜附件'),/冲突/);
  assert.equal(selectRule([rule],'JM','SECC','安装附件'),null);
  assert.equal(selectRule([rule],'JM','SECC'),null);
});

test('新增卡固 KA22060 全产品材质按目录面价270及固定成本209计算，不改写目录输入', () => {
  // Reduced public catalogue snapshot from task C; never connects to the API/DB.
  const fan=JSON.parse(fs.readFileSync(new URL('./fixtures/fan_ka22060ha2b.json',import.meta.url)));
  const before=structuredClone(fan);
  assert.equal(fan.model_code,null);
  assert.deepEqual(fan.rules[0].products,[]);
  assert.deepEqual(fan.rules[0].materials,[]);
  const products=[...new Set(Object.values(PRODUCT_CODES).flat())];
  assert.equal(products.length*MATERIAL_CODES.length,45);
  for(const product_code of products) for(const material_code of MATERIAL_CODES) {
    for(const quantity of [1,2]) {
      const row=calculateAttachment({quantity},fan,fan.rules,{...env,product_code,material_code});
      assert.equal(row.status,'FIXED');
      assert.equal(row.face_price,270);
      assert.equal(row.formula_unit_cost,209);
      assert.equal(row.quick_amount,270*quantity);
      assert.equal(row.formula_amount,209*quantity);
      assert.deepEqual(attachmentTotals([row]),{quick_attachment_fee:270*quantity,formula_attachment_fee:209*quantity,errors:[]});
    }
  }
  assert.deepEqual(fan,before);
});
test('完整变量识别、安全语法和错误拒绝', () => {
  assert.deepEqual(formulaVariables('(高度+底座高度)*材质密度'), ['高度','底座高度','材质密度']);
  assert.equal(evaluateFormula('材料质量*5', { 材料重量: 2 }),10);
  for (const expression of ['1*', '2**3', 'process.exit()', 'globalThis["x"]', '1;DROP TABLE a', '1/0', '1e999']) assert.throws(() => evaluateFormula(expression, {}));
  assert.equal(evaluateFormula('ROUND(MAX(2,ABS(-3))/2,2)',{}),1.5);
});
test('一次选择：精确面价和独立成本，重量不重复乘密度或数量', () => {
  const row = calculateAttachment({quantity: 3},catalog,[dynamic],env);
  const weight = (2000-72)*(800-26.6)*2.5*7.85*0.000001;
  assert.equal(row.status,'CALCULATED'); assert.equal(row.face_price,483.46155);
  assert.ok(Math.abs(row.weight_kg-weight)<1e-10);
  assert.equal(row.quick_amount,1450.38); assert.equal(row.spray_cost,0);
  assert.ok(Math.abs(row.formula_unit_cost-(weight*5+9.5+16+2.5*2800*2*.001))<1e-8);
});
test('快速独有、通用/专用优先、冲突、超宽与普通产品分开', () => {
  assert.equal(calculateAttachment({quantity:1},catalog,[],env).status,'QUICK_ONLY');
  assert.equal(attachmentTotals([calculateAttachment({quantity:1},catalog,[],env)]).formula_attachment_fee,0);
  assert.equal(selectRule([fixed,dynamic],'JP'),dynamic);
  assert.equal(selectRule([fixed,dynamic],'JP_WIDE_EXP'),fixed);
  assert.throws(()=>selectRule([fixed,{...fixed,rule_id:3}],'JP'),/冲突/);
});
test('材质及价格变化影响动态成本，面价和固定成本不变', () => {
  const a = calculateAttachment({quantity:2},catalog,[dynamic],env);
  const b = calculateAttachment({quantity:2},catalog,[dynamic],{...env,material_code:'SUS316',density_g_cm3:7.98,material_unit_price:31,spray_unit_price:29});
  assert.notEqual(a.formula_amount,b.formula_amount); assert.equal(a.quick_amount,b.quick_amount);
  assert.equal(calculateAttachment({quantity:2},catalog,[fixed],{}).formula_amount,55.12);
});
test('底座人工尺寸逐项保存，不允许用产品高度或默认零代替', () => {
  const rule = bundle.rules.find(r=>r.source_row_no===11);
  assert.ok(requiredParameters(rule).some(p=>p.name==='底座高度'&&p.source==='MANUAL'));
  const missing=calculateAttachment({quantity:1},catalog,[rule],env);
  assert.equal(missing.status,'ERROR'); assert.match(missing.error,/底座高度/);
  const first=calculateAttachment({quantity:1,manual_inputs:{底座高度:100}},catalog,[rule],env);
  const second=calculateAttachment({quantity:1,manual_inputs:{底座高度:200}},catalog,[rule],env);
  assert.notEqual(first.formula_amount,second.formula_amount); assert.equal(first.manual_inputs.底座高度,100);
});
test('缺少价格、公式错误、源疑点不能在汇总中静默排除', () => {
  const row=calculateAttachment({quantity:1},catalog,[dynamic],{...env,material_unit_price:null});
  assert.equal(row.status,'ERROR'); assert.equal(attachmentTotals([row]).formula_attachment_fee,null);
  const broken=calculateAttachment({quantity:1},catalog,[{...dynamic,issues:['待确认']}],env);
  assert.equal(broken.status,'ERROR');
});
test('喷塑为零与不喷塑有效；非零喷塑面积缺少价格报错', () => {
  const rule=bundle.rules.find(r=>r.source_row_no===2);
  assert.equal(calculateAttachment({quantity:1},catalog,[rule],{...env,spray_unit_price:null}).status,'ERROR');
  assert.equal(calculateAttachment({quantity:1},catalog,[rule],{...env,coating_type:'不喷塑',spray_unit_price:null}).spray_cost,0);
  assert.equal(calculateAttachment({quantity:1},catalog,[dynamic],{...env,spray_unit_price:null}).spray_cost,0);
});
test('符号范围、单位、辅材原文、内含件数及行归属', () => {
  const row=calculateAttachment({quantity:2,attachment_price_sign:-1},catalog,[fixed],env);
  assert.equal(row.formula_amount,-55.12); assert.equal(row.unit,'件'); assert.equal(row.auxiliary_list,'说明\n保留换行');
  assert.equal(calculateAttachment({quantity:1,attachment_price_sign:-1},{...catalog,item_name:'风机',category_level1:'风机'},[fixed],env).status,'ERROR');
  assert.equal(calculateAttachment({quantity:1},catalog,[fixed],{...env,quote_line_id:'line-b'}).quote_line_id,'line-b');
  const side=bundle.rules.find(r=>r.source_row_no===2);
  const a=calculateAttachment({quantity:1},catalog,[side],env),b=calculateAttachment({quantity:2},catalog,[side],env);
  assert.equal(a.weight_kg,b.weight_kg); assert.equal(a.auxiliary_cost,4.8);
});
test('全源规则检查、分类隔离、引用转换及源问题保持阻断', () => {
  assert.equal(bundle.catalog.length,226); assert.equal(bundle.rules.length,62);
  for(const r of bundle.rules) for(const expression of Object.values(r.formulas)) if(expression!=null) parseFormula(expression);
  for(const b of bundle.bindings) {
    const q=bundle.catalog.find(q=>q.import_key===b.attachment_key),r=bundle.rules.find(r=>r.import_key===b.rule_key);
    assert.deepEqual([q.category_level1,q.category_level2,q.item_name],[r.category_level1,r.category_level2,r.item_name]);
  }
  assert.match(bundle.rules.find(r=>r.source_row_no===45).formulas.auxiliary_cost,/高度/);
  assert.equal(bundle.rules.find(r=>r.source_row_no===49).issues.length,0);
  assert.equal(bundle.rules.find(r=>r.source_row_no===59).formulas.auxiliary_cost,0);
  assert.equal(bundle.rules.find(r=>r.source_row_no===59).issues.length,0);
});
test('确认后的通风顶罩重量正确，面积仍需要人工罩高', () => {
  const rule=bundle.rules.find(r=>r.source_row_no===49);
  assert.equal(rule.formulas.weight_kg,'(260+宽度-10)*(260+深度-10)*0.000001*材质密度*1.5');
  assert.deepEqual(requiredParameters(rule).filter(p=>p.source==='MANUAL').map(p=>p.name),['通风顶罩高度']);
  const row=calculateAttachment({quantity:2,manual_inputs:{通风顶罩高度:100}},catalog,[rule],env);
  assert.equal(row.status,'CALCULATED');
  assert.ok(Math.abs(row.weight_kg-10.5091875)<1e-10);
  assert.ok(Math.abs(row.spray_area_m2-1.2725)<1e-10);
  assert.equal(calculateAttachment({quantity:1},catalog,[rule],env).status,'ERROR');
});
test('三种材质精确匹配固定成本，快速面价不随材质改变', () => {
  for(const [quickRow,secc,stainless,face] of [[104,6.4,22,40],[105,22,157,50],[208,6,17.5,20]]) {
    const item=bundle.catalog.find(q=>q.source_row_no===quickRow);
    const keys=bundle.bindings.filter(b=>b.attachment_key===item.import_key).map(b=>b.rule_key);
    const rules=bundle.rules.filter(r=>keys.includes(r.import_key));
    for(const material of ['SECC','SUS304','SUS316']) {
      const row=calculateAttachment({quantity:2},item,rules,{...env,material_code:material});
      assert.equal(row.status,'FIXED'); assert.equal(row.formula_unit_cost,material==='SECC'?secc:stainless);
      assert.equal(row.quick_amount,face*2);
      const changed=calculateAttachment({quantity:2},item,rules,{...env,material_code:material,material_unit_price:999,spray_unit_price:888,density_g_cm3:1});
      assert.equal(changed.formula_amount,row.formula_amount);
    }
    assert.equal(calculateAttachment({quantity:1},item,rules,{...env,material_code:null}).status,'ERROR');
  }
});
test('材质匹配不能任取第一条、丢失参数不能仅快速报价，产品维度独立', () => {
  const secc={...fixed,rule_id:1,materials:['SECC']};
  const stainless={...fixed,rule_id:2,materials:['SUS304','SUS316'],fixed_cost:22};
  assert.equal(selectRule([stainless,secc],'JP','SECC'),secc);
  assert.equal(selectRule([secc,stainless],'JP','SUS316'),stainless);
  assert.throws(()=>selectRule([secc],'JP','SUS304'),/缺少附件成本规则/);
  assert.throws(()=>selectRule([secc,{...secc,rule_id:3}],'JP','SECC'),/冲突/);
  const productSpecific={...stainless,rule_id:4,products:['JP']};
  assert.equal(selectRule([stainless,productSpecific],'JP','SUS304'),productSpecific);
  assert.equal(selectRule([stainless,productSpecific],'JP_WIDE_EXP','SUS304'),stainless);
  assert.equal(selectRule([{...secc,products:['JP']}],'JS','SUS304'),null);
});
test('五项明确映射全部绑定、说明型号原文保留、无未决问题', () => {
  for(const [quickRow,formulaRows] of [[103,[33]],[104,[34,35]],[105,[36,37]],[208,[51,52]],[226,[62]]]) {
    assert.deepEqual(bundle.report.mappings.find(m=>m.quick_row===quickRow).formula_rows,formulaRows);
  }
  assert.equal(bundle.rules.find(r=>r.source_row_no===33).fixed_cost,3);
  assert.equal(bundle.rules.find(r=>r.source_row_no===62).fixed_cost,8.1);
  assert.equal(bundle.rules.find(r=>r.source_row_no===33).model_semantics,'DESCRIPTION');
  assert.equal(bundle.rules.find(r=>r.source_row_no===62).raw_values.型号,'十字螺丝铜排');
  assert.equal(bundle.report.counts.bindings,264);
  assert.equal(bundle.report.counts.blockers,0); assert.equal(bundle.report.counts.unmapped_rules,0);
});
