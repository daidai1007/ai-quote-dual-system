import { randomUUID } from 'node:crypto';
import { calculateAttachment, attachmentTotals } from './attachment_cost.mjs';
import { round } from './attachment_formula.mjs';
import {
  attachmentImageCatalogSql,
  attachmentImageTablesExistSql,
  normalizeAttachmentImages,
} from './attachment_image_query.mjs';

// SQL values are always UTF-8 hex literals; formulas are evaluated only by attachment_cost.
export const sqlValue = value => value == null ? 'NULL' : typeof value === 'number'
  ? (Number.isFinite(value) ? String(value) : (()=>{throw new Error('非有限数值');})())
  : `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const sqlJson=value=>`${sqlValue(JSON.stringify(value))}::jsonb`;
const canonical=value=>JSON.stringify(value, function(key,current) {
  return current && typeof current==='object' && !Array.isArray(current)
    ? Object.fromEntries(Object.entries(current).sort(([a],[b])=>a.localeCompare(b))) : current;
});
export const attachmentEnvironmentChange = (item, saved) => {
  for(const key of ['product_code','material_code','width_mm','height_mm','depth_mm','coating_type','quote_date'])
    if(String(item[key]??'')!==String(saved[key]??'')) return key;
  for(const key of ['cabinet_body_thickness_mm','waste_factor'])
    if(item[key]!=null && String(item[key])!==String(saved[key]??'')) return key;
  return null;
};
const id=value=>{
  if(!/^[1-9][0-9]*$/.test(String(value))||!Number.isSafeInteger(Number(value))) throw new Error('必须提供有效 attachment_price_id');
  return Number(value);
};
const uuid=value=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value||'')) throw new Error('报价行ID无效');return value;};
export const attachmentInput = a => {
  if(!a||typeof a!=='object'||Array.isArray(a)) throw new Error('附件选择必须是对象');
  const quantity=Number(a.quantity??1),sign=Number(a.attachment_price_sign??1);
  if(!Number.isFinite(quantity)||quantity<=0||![1,-1].includes(sign)) throw new Error('附件数量必须为正数，加减符号必须为1或-1');
  const manual=a.manual_inputs??{};
  if(!manual||typeof manual!=='object'||Array.isArray(manual)) throw new Error('人工尺寸必须是对象');
  const rawIndex=a.ganged_cabinet_index??a.ganged_fixed_base_index;
  const gangedIndex=rawIndex===undefined||rawIndex===null||rawIndex===''?null:Number(rawIndex);
  if(gangedIndex!==null&&(!Number.isSafeInteger(gangedIndex)||gangedIndex<0||gangedIndex>19)) throw new Error('并柜附件子柜序号无效');
  return {attachment_price_id:id(a.attachment_price_id),quantity,attachment_price_sign:sign,
    manual_inputs:manual,...(gangedIndex===null?{}:{ganged_cabinet_index:gangedIndex})};
};
export function applyAttachmentTotals(base,rows) {
  const totals=attachmentTotals(rows),formula={...(base.formula_cost||{})},quick={...(base.quick_quote||{})};
  formula.total_cost=formula.total_cost==null||totals.formula_attachment_fee==null?null:round(Number(formula.total_cost)-Number(formula.attachment_fee||0)+totals.formula_attachment_fee);
  quick.total_cost=quick.total_cost==null||totals.quick_attachment_fee==null?null:round(Number(quick.total_cost)-Number(quick.attachment_fee||0)+totals.quick_attachment_fee);
  formula.attachment_fee=totals.formula_attachment_fee;quick.attachment_fee=totals.quick_attachment_fee;
  return {...base,formula_cost:formula,quick_quote:quick,attachments:rows,attachment_contract:2,
    risk_flags:[...(base.risk_flags||[]),...totals.errors.map(r=>({code:'attachment_error',severity:'blocker',message:`${r.item_name}：${r.error}`}))]};
}

export function createAttachmentService({runPsql,calculateBase,env=process.env}) {
  const query=async sql=>{const text=await runPsql(sql);return JSON.parse(text.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  async function catalog() {
    const version=env.AI_QUOTE_ATTACHMENT_V2_VERSION||'';
    const condition=version?`data_version=${sqlValue(version)}`:"status='ACTIVE'";
    const versions=await query(`SELECT coalesce(jsonb_agg(to_jsonb(v)),'[]') FROM calc.attachment_catalog_version v WHERE ${condition};`);
    if(versions.length!==1) throw new Error('没有可用的附件V2目录；请配置已审查的目录版本');
    const v=versions[0];
    if(v.status!=='ACTIVE'&&!(v.status==='STAGED'&&env.AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED==='1')) throw new Error('附件目录尚未启用；待启用数据仅供明确配置的兼容测试');
    const items=await query(`SELECT coalesce(jsonb_agg(to_jsonb(a)||jsonb_build_object('rules',coalesce((
      SELECT jsonb_agg(to_jsonb(r)||jsonb_build_object(
        'products',(SELECT coalesce(jsonb_agg(product_code),'[]') FROM calc.attachment_cost_rule_product WHERE rule_id=r.rule_id),
        'materials',(SELECT coalesce(jsonb_agg(material_code),'[]') FROM calc.attachment_cost_rule_material WHERE rule_id=r.rule_id)))
      FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id)
      WHERE b.attachment_price_id=a.attachment_price_id),'[]')) ORDER BY a.source_row_no),'[]')
      FROM (SELECT p.attachment_price_id,c.category_level1,coalesce(c.category_level2,'') AS category_level2,
        coalesce(c.category_level3,'') AS category_level3,p.item_name,p.model_code,p.unit,p.color,p.width_mm,p.height_mm,p.depth_mm,
        p.quick_face_price AS price,p.data_version,p.source_file,p.source_sheet,p.source_row_no
        FROM calc.attachment_price p JOIN calc.attachment_classification c USING(attachment_price_id)
        WHERE p.data_version=${sqlValue(v.data_version)}${v.status==='ACTIVE'?' AND p.is_active':''}) a;`);
    const imageTablesExist=await query(attachmentImageTablesExistSql);
    const attachmentImages=imageTablesExist
      ? normalizeAttachmentImages(await query(attachmentImageCatalogSql))
      : [];
    return {items,attachment_images:attachmentImages,data_version:v.data_version,status:v.status,attachment_contract:2,catalog_write_supported:true};
  }
  async function preview(input) {
    if(!Array.isArray(input.attachments)||input.attachments.length>100) throw new Error('attachments必须为不超过100项的数组');
    const gangedCount=Number(input.ganged_cabinet_count||1);
    const gangedCabinets=Array.isArray(input.ganged_cabinets)?input.ganged_cabinets:[];
    const gangedInputs=Array.isArray(input.ganged_cabinet_inputs)?input.ganged_cabinet_inputs:gangedCabinets;
    if(!Number.isSafeInteger(gangedCount)||gangedCount<1||gangedCount>20) throw new Error('并柜数量必须为1至20的整数');
    if(gangedCount>1&&gangedCabinets.length!==gangedCount) throw new Error('并柜明细数量与并柜数量不一致');
    const selections=input.attachments.map(attachmentInput),data=await catalog();
    const quoteDate=input.quote_date;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(quoteDate||'')) throw new Error('报价日期无效');
    if(!['SECC','SUS304','SUS316'].includes(input.material_code)) throw new Error('材质必须为SECC、SUS304或SUS316');
    for(const key of ['width_mm','height_mm','depth_mm']) if(!Number.isFinite(Number(input[key]))||Number(input[key])<=0) throw new Error(`${key}必须为正数`);
    const prices=await query(`SELECT jsonb_build_object(
      'density_g_cm3',(SELECT density_g_cm3 FROM calc.material WHERE material_code=${sqlValue(input.material_code)}),
      'material_unit_price',calc.get_material_unit_price(${sqlValue(input.material_code)},${sqlValue(quoteDate)}::date),
      'spray_unit_price',CASE WHEN ${sqlValue(input.coating_type)}='不喷塑' THEN 0 ELSE calc.get_spray_unit_price(${sqlValue(quoteDate)}::date,${sqlValue(input.coating_type)}) END);`);
    const environment={quote_line_id:randomUUID(),product_code:input.product_code,material_code:input.material_code,
      width_mm:Number(input.width_mm),height_mm:Number(input.height_mm),depth_mm:Number(input.depth_mm),
      coating_type:input.coating_type,quote_date:quoteDate,
      cabinet_body_thickness_mm:Number(input.cabinet_body_thickness_mm??1.5),
      waste_factor:Number(input.waste_factor??1.2),ganged_cabinet_count:gangedCount,
      ganged_cabinets:gangedCabinets,...prices};
    const attachments=selections.map(selection=>{
      const item=data.items.find(a=>Number(a.attachment_price_id)===selection.attachment_price_id);
      if(!item) throw new Error(`附件ID ${selection.attachment_price_id} 不属于当前目录，请重新选择`);
      const child=selection.ganged_cabinet_index===undefined?null:gangedInputs[selection.ganged_cabinet_index];
      if(selection.ganged_cabinet_index!==undefined&&!child) throw new Error(`第 ${selection.ganged_cabinet_index+1} 个子柜不存在`);
      const attachmentEnvironment=child?{...environment,...child,quote_line_id:environment.quote_line_id,
        material_code:environment.material_code,coating_type:environment.coating_type,quote_date:environment.quote_date,
        density_g_cm3:environment.density_g_cm3,material_unit_price:environment.material_unit_price,
        spray_unit_price:environment.spray_unit_price}:environment;
      return {...calculateAttachment(selection,item,item.rules,attachmentEnvironment),
        ...(selection.ganged_cabinet_index===undefined?{}:{ganged_cabinet_index:selection.ganged_cabinet_index})};
    });
    return {attachments,environment,attachment_contract:2,catalog_version:data.data_version,...attachmentTotals(attachments)};
  }
  async function persistCalculated(input,previewed,base) {
    const lineId=previewed.environment.quote_line_id;
    const result={...applyAttachmentTotals(base,previewed.attachments),quote_id:input.quote_id,quote_line_id:lineId};
    const environment={...previewed.environment,model_code:input.model_code||'',quote_result:{...result,attachments:undefined}};
    const rows=previewed.attachments;
    const commands=[`INSERT INTO calc.attachment_quote_line(quote_line_id,quote_id,product_code,environment_snapshot)
      VALUES(${sqlValue(lineId)}::uuid,${sqlValue(input.quote_id)},${sqlValue(input.product_code)},${sqlJson(environment)});`];
    for(const row of rows){
      const values={quote_line_id:lineId,quote_id:input.quote_id,product_code:input.product_code,attachment_price_id:row.attachment_price_id,
        quantity:row.quantity,price_sign:row.attachment_price_sign,unit_price:row.face_price,
        item_name:row.item_name,model_code:row.model_code,calculation_status:row.status,
        cost_rule_id:row.rule_id??null,rule_version:row.rule_version??null,catalog_version:row.catalog_version,
        manual_inputs:row.manual_inputs,environment_snapshot:environment,quick_face_price:row.face_price,quick_amount:row.quick_amount,
        formula_unit_cost:row.formula_unit_cost,formula_amount:row.formula_amount,error_message:row.error??null,
        cost_snapshot:{...row,category_level2:row.category_level2||'',unit:row.unit||'',auxiliary_list:row.auxiliary_list||''}};
      commands.push(`INSERT INTO calc.attachment_selection(${Object.keys(values).join(',')}) VALUES(${Object.entries(values).map(([key,value])=>key==='quote_line_id'?`${sqlValue(value)}::uuid`:typeof value==='object'&&value!==null?sqlJson(value):sqlValue(value)).join(',')});`);
    }
    const saved=await query(`BEGIN;\n${commands.join('\n')}\n${snapshotSql(lineId)}\nCOMMIT;`);
    result.attachments=saved.attachments;return result;
  }
  async function calculate(input) {
    const previewed=await preview(input),lineId=previewed.environment.quote_line_id;
    // Each base calculation has a fresh private quote id and NO attachment inserts.
    const base=await calculateBase({...input,quote_id:`AV2_${lineId}`,attachments:[]});
    return persistCalculated(input,previewed,base);
  }
  async function snapshotGanged(input) {
    if(Number(input.ganged_cabinet_count||1)<=1) throw new Error('并柜附件快照要求至少两个子柜');
    const base=input.base_result;
    if(!base||typeof base!=='object'||Array.isArray(base)
      ||!base.formula_cost||typeof base.formula_cost!=='object'
      ||!base.quick_quote||typeof base.quick_quote!=='object') throw new Error('并柜基础报价结果无效');
    const previewed=await preview(input);
    return persistCalculated(input,previewed,{...base,formula_cost:{...base.formula_cost},quick_quote:{...base.quick_quote}});
  }
  function snapshotSql(lineId) {return `SELECT jsonb_build_object('environment',l.environment_snapshot,
    'attachments',coalesce((SELECT jsonb_agg(s.cost_snapshot||jsonb_build_object('attachment_selection_id',s.attachment_selection_id,'quote_line_id',s.quote_line_id) ORDER BY s.attachment_selection_id)
      FROM calc.attachment_selection s WHERE s.quote_line_id=l.quote_line_id),'[]'))
    FROM calc.attachment_quote_line l WHERE quote_line_id=${sqlValue(uuid(lineId))}::uuid;`;}
  async function hydrateDocument(input) {
    if(!input || typeof input!=='object' || !Array.isArray(input.items)) throw new Error('items are required');
    const items=[];
    for(const item of input.items||[]){
      if(item.attachment_contract!==2){
        if((item.attachments||[]).some(a=>a.catalog_version||a.rule_id||a.status)) throw new Error('附件V2报价缺少服务端报价行ID');
        const ids=(item.attachments||[]).filter(a=>a.attachment_price_id!=null).map(a=>id(a.attachment_price_id));
        if(ids.length && await query(`SELECT to_jsonb(EXISTS(SELECT 1 FROM calc.attachment_price WHERE attachment_price_id IN (${ids.join(',')}) AND data_version IS NOT NULL));`)) throw new Error('附件V2报价缺少服务端报价行ID');
        items.push(item);continue;
      }
      const saved=await query(snapshotSql(item.quote_line_id));
      if(!saved) throw new Error('附件报价行不存在，请重新计算');
      const changedKey=attachmentEnvironmentChange(item,saved.environment);
      if(changedKey) throw new Error(`报价环境已变化（${changedKey}），请重新计算附件`);
      if(Number(item.ganged_cabinet_count||1)!==Number(saved.environment.ganged_cabinet_count||1)
        ||canonical(item.ganged_cabinets||[])!==canonical(saved.environment.ganged_cabinets||[])) throw new Error('并柜明细已变化，请重新计算附件');
      if(canonical((item.attachments||[]).map(attachmentInput))!==canonical(saved.attachments.map(attachmentInput))) throw new Error('附件选择或人工参数已变化，请重新计算');
      if(saved.attachments.some(a=>a.status==='ERROR')) throw new Error('附件成本存在错误，不能确认或导出');
      const result=saved.environment.quote_result;
      const formula={...result.formula_cost};
      // Preserve the existing PRODUCT labor adjustment (13% management), never
      // apply it to attachment labor or introduce an attachment surcharge.
      const multiplier=Number(item.labor_multiplier??1);
      if(!Number.isFinite(multiplier)||multiplier<0.01||multiplier>10) throw new Error('人工倍率必须在0.01至10之间');
      if(formula.total_cost!=null && formula.labor_cost!=null && formula.management_fee!=null){
        const labor=Number(formula.labor_cost)*multiplier,management=labor*0.13;
        formula.total_cost=Number(formula.total_cost)-Number(formula.labor_cost)-Number(formula.management_fee)+labor+management;
        formula.labor_cost=labor;formula.management_fee=management;
      }
      // A frozen service result remains independent of later catalog and price updates.
      items.push({...item,attachments:saved.attachments,formula_base:result.formula_cost,
        formula,quick:result.quick_quote});
    }
    return {...input,items};
  }
  return {catalog,preview,calculate,snapshotGanged,hydrateDocument,hasActive:async()=>query("SELECT to_jsonb(EXISTS(SELECT 1 FROM calc.attachment_catalog_version WHERE status='ACTIVE'));")};
}
