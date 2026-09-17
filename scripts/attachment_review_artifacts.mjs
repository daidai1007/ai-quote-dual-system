import fs from 'node:fs/promises';
import path from 'node:path';
import { calculateAttachment } from '../api/attachment_cost.mjs';
const directory=process.argv[2];
if(!directory) throw new Error('usage: node scripts/attachment_review_artifacts.mjs bundle-directory');
const bundle=JSON.parse(await fs.readFile(path.join(directory,'attachment-bundle.json'),'utf8'));
const cell=value=>String(value??'').replaceAll('|','\\|').replaceAll('\n','<br>');
const lines=['# Excel源行映射检查','','来源SHA-256：`'+bundle.source_sha256+'`。转换版本：`'+bundle.data_version+'`。','',
  '行号均为Excel实际工作表行号，不是表内序号。名称规范全角括号及首尾空白；门变形、配置变形和其他附件按确认取消二级分类，其他分类继续采用已确认的连续行继承。产品、原型号和材质适用关系分别保存；搭扣锁及铜排按确认身份绑定。','',
  '| 快速表行 | 一级分类 | 二级分类 | 名称 | 型号 | 完整面价 | 公式表行 | 检查状态 |','|---|---|---|---|---|---|---|---|'];
for(const m of bundle.report.mappings) {
  const q=bundle.catalog.find(q=>q.source_row_no===m.quick_row);
  const pending=bundle.report.pending_mapping.some(p=>p.quick_row===m.quick_row);
  const blocked=bundle.rules.filter(r=>m.formula_rows.includes(r.source_row_no)&&r.issues.length);
  const state=pending?'待映射：禁止按仅快速报价跳过':blocked.length?'绑定规则有待确认问题':m.formula_rows.length?'已绑定；按当前产品及材质选择':'仅快速报价';
  lines.push('| '+[m.quick_row,...m.identity.slice(0,2),m.identity[2],m.model,q.price,m.formula_rows.join('、'),state].map(cell).join(' | ')+' |');
}
lines.push('','## 规则清单','','| 公式表行 | 方法 | 产品列原文 | 规范产品代码 | 型号原文 | 型号语义 | 适用材质（空为通用） | 人工变量 | 问题 |','|---|---|---|---|---|---|---|---|---|');
for(const r of bundle.rules) lines.push('| '+[r.source_row_no,r.method,r.product_text,r.products.join('、'),r.model_code,r.model_semantics,(r.materials||[]).join('、'),r.parameters.filter(p=>p.source==='MANUAL').map(p=>p.name).join('、'),r.issues.join('；')].map(cell).join(' | ')+' |');
await fs.writeFile(path.join(directory,'source-row-mapping.md'),lines.join('\n')+'\n');
const environment={quote_line_id:'11111111-1111-4111-8111-111111111111',product_code:'JP',width_mm:800,height_mm:2000,depth_mm:600,material_code:'SECC',density_g_cm3:7.85,material_unit_price:5,spray_unit_price:10,coating_type:'橘纹',quote_date:'2026-09-10'};
function sample(quickRow,quantity,manual_inputs={},material_code=environment.material_code) {
  const q=bundle.catalog.find(q=>q.source_row_no===quickRow);
  const bindings=bundle.bindings.filter(b=>b.attachment_key===q.import_key);
  const rules=bundle.rules.filter(r=>bindings.some(b=>b.rule_key===r.import_key));
  return calculateAttachment({quantity,manual_inputs},{...q,attachment_price_id:`LOCAL_SAMPLE_${q.import_key}`},rules,{...environment,material_code});
}
const baseRow=bundle.report.mappings.find(m=>m.formula_rows.includes(11)).quick_row;
const snapshots=[sample(13,2),sample(98,1),sample(baseRow,1,{底座高度:100}),sample(baseRow,1),sample(223,1)];
snapshots.push(sample(bundle.report.mappings.find(m=>m.formula_rows.includes(49)).quick_row,1,{通风顶罩高度:100}));
for(const row of [104,105,208]) for(const material of ['SECC','SUS304','SUS316']) snapshots.push(sample(row,1,{},material));
await fs.writeFile(path.join(directory,'calculation-samples.json'),JSON.stringify({notice:'仅本地说明样例，环境单价是测试输入，并非线上有效价格；ID为样例ID，不能用于正式报价。未完成现有客户端/导出接入。',snapshots},null,2));
console.log(`Wrote ${bundle.catalog.length} row mappings and ${snapshots.length} illustrative snapshots`);
