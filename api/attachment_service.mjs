import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { calculateAttachment, attachmentTotals } from './attachment_cost.mjs';
import { round } from './attachment_formula.mjs';
import { materialUnitPriceFromSidebar } from './material_price_override.mjs';
import {PRICING_BASIS, money, moneySum, quickAttachmentLineAmount, validateQuoteDisplay, applyManagementFee} from '../quick_discount_rules.mjs';

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
const customText=(value,label,max=200)=>{
  const text=String(value??'').trim();
  if(!text) throw new Error(`人工新增附件${label}不能为空`);
  if(text.length>max) throw new Error(`人工新增附件${label}过长`);
  return text;
};
const customAmount=(value,label)=>{
  const number=Number(value);
  if(!Number.isFinite(number)||number<0||number>1e8) throw new Error(`人工新增附件${label}必须为有效非负数`);
  return number;
};
export const customAttachmentInput = value => {
  if(!value||typeof value!=='object'||Array.isArray(value)||value.custom!==true)
    throw new Error('人工新增附件必须明确标记 custom');
  const itemName=customText(value.item_name??value.name,'名称');
  const quantity=Number(value.quantity??1),sign=Number(value.attachment_price_sign??1);
  if(!Number.isFinite(quantity)||quantity<=0||quantity>10000) throw new Error('人工新增附件数量必须为有效正数');
  if(![1,-1].includes(sign)) throw new Error('人工新增附件加减符号无效');
  const unitSource=[value.unit_price_override,value.matched_price,value.unit_price,value.price]
    .find(entry=>entry!==null&&entry!==undefined&&entry!==''&&Number.isFinite(Number(entry)));
  const unitPrice=unitSource===undefined?null:customAmount(unitSource,'单价');
  const quickSource=[value.quick_amount_override,value.quick_amount]
    .find(entry=>entry!==null&&entry!==undefined&&entry!==''&&Number.isFinite(Number(entry)));
  const quickUnsigned=customAmount(
    quickSource===undefined?(unitPrice??0)*quantity:Math.abs(Number(quickSource)), '快速金额');
  const formulaSource=[value.formula_amount,value.custom_cost]
    .find(entry=>entry!==null&&entry!==undefined&&entry!==''&&Number.isFinite(Number(entry)));
  const formulaUnsigned=customAmount(
    formulaSource===undefined?quickUnsigned:Math.abs(Number(formulaSource)), '公式金额');
  const normalizedUnit=unitPrice??(quantity?quickUnsigned/quantity:0);
  return {custom:true,item_name:itemName,name:itemName,category_level1:'其他附件',
    attachment_category:'其他附件',unit:String(value.unit||'件').trim().slice(0,30)||'件',quantity,
    attachment_price_sign:sign,unit_price_override:normalizedUnit,matched_price:normalizedUnit,
    quick_amount_override:round(quickUnsigned*sign),quick_amount:round(quickUnsigned*sign),
    formula_amount:round(formulaUnsigned*sign),custom_cost:round(formulaUnsigned*sign)};
};
const addCustomAmount=(quote,amount)=>{
  const output={...(quote||{})};
  output.attachment_fee=round(Number(output.attachment_fee||0)+amount);
  if(output.total_cost!=null) output.total_cost=round(Number(output.total_cost)+amount);
  return output;
};
export function applyAttachmentTotals(base,rows,freightFee=0) {
  const totals=attachmentTotals(rows),formula={...(base.formula_cost||{})},quick={...(base.quick_quote||{})};
  formula.total_cost=formula.total_cost==null||totals.formula_attachment_fee==null?null:round(Number(formula.total_cost)-Number(formula.attachment_fee||0)+totals.formula_attachment_fee);
  quick.total_cost=quick.total_cost==null||totals.quick_attachment_fee==null?null:round(Number(quick.total_cost)-Number(quick.attachment_fee||0)+totals.quick_attachment_fee);
  formula.attachment_fee=totals.formula_attachment_fee;quick.attachment_fee=totals.quick_attachment_fee;
  return {...base,formula_cost:applyManagementFee(formula,freightFee),quick_quote:quick,attachments:rows,attachment_contract:2,
    risk_flags:[...(base.risk_flags||[]),...totals.errors.map(r=>({code:'attachment_error',severity:'blocker',message:`${r.item_name}：${r.error}`}))]};
}

function popupDocumentSnapshot(item, saved) {
  const visible=item.quote_display?.attachments;
  if(!Array.isArray(visible)||visible.length>100) throw new Error('附件显示快照必须为不超过100项的数组');
  const provided=item.attachments;
  if(!Array.isArray(provided)||provided.length!==visible.length) throw new Error('附件显示快照与提交清单不一致');
  const selection=row=>row?.custom===true?customAttachmentInput(row):attachmentInput(row);
  if(canonical(provided.map(selection))!==canonical(visible.map(selection)))
    throw new Error('附件显示快照与提交选择不一致');
  const rows=visible.map(source=>{
    const {attachment_selection_id,quote_line_id,...popupRow}=source;
    if(source?.custom===true){
      if(source.formula_amount==null||!Number.isFinite(Number(source.formula_amount)))
        throw new Error(`${source.item_name||'人工附件'}：人工新增附件成本未完成`);
      if(source.quick_amount==null||!Number.isFinite(Number(source.quick_amount)))
        throw new Error(`${source.item_name||'人工附件'}：人工新增附件金额未完成`);
      return {...popupRow,...customAttachmentInput(source)};
    }
    const selected=attachmentInput(source);
    const label=String(source.item_name||source.model_code||'未命名附件');
    const reject=reason=>{throw Object.assign(new Error(`${label}：${reason}`),
      {attachment_name:label,attachment_price_id:selected.attachment_price_id});};
    if(selected.quantity>10000) reject('附件数量超出范围');
    if(selected.ganged_cabinet_index!=null&&selected.ganged_cabinet_index>=Number(saved.environment.ganged_cabinet_count||1))
      reject('附件对应的子柜不存在');
    if(!['FIXED','CALCULATED','QUICK_ONLY'].includes(source.status)||source.pending_manual_dimensions?.length)
      reject(source.error||'附件成本或尺寸未完成，请先在附件弹窗完成计算');
    if(selected.attachment_price_sign===-1&&(!label.includes('安装板')||label.includes('安装板单发')))
      reject('该附件不允许扣减');
    const rawQuick=source.quick_amount_override!=null&&source.custom_amount_edited===true
      ?source.quick_amount_override:source.quick_amount;
    if(rawQuick==null||!Number.isFinite(Number(rawQuick))||Math.abs(Number(rawQuick))>1e8)
      reject('附件金额无效');
    const quick=quickAttachmentLineAmount(source);
    if(!Number.isFinite(quick)||Math.abs(quick)>1e8) reject('附件金额无效');
    const cost=source.status==='QUICK_ONLY'?0:source.formula_amount;
    if(cost==null||!Number.isFinite(Number(cost))||Math.abs(Number(cost))>1e8)
      reject('附件成本无效');
    if(quick*selected.attachment_price_sign<0||Number(cost)*selected.attachment_price_sign<0)
      reject('附件金额或成本与加减符号不一致');
    return {...popupRow,...selected,quick_amount:quick,formula_amount:money(cost)};
  });
  const result=saved.environment.quote_result;
  if(!result?.formula_cost||!result?.quick_quote) throw new Error('柜体成本快照不完整，请重新计算整柜');
  let formula={...result.formula_cost};
  const quick={...result.quick_quote};
  let baseCost;
  if(formula.total_cost!=null) baseCost=moneySum([formula.total_cost,-Number(formula.attachment_fee||0)]);
  else {
    const components=['material_cost','auxiliary_cost','labor_cost','spray_cost','management_fee'];
    if(components.some(key=>formula[key]==null||!Number.isFinite(Number(formula[key]))))
      throw new Error('柜体成本快照不完整，请重新计算整柜');
    baseCost=components.reduce((sum,key)=>sum+Number(formula[key]),0);
  }
  const multiplier=Number(item.labor_multiplier??1);
  if(!Number.isFinite(multiplier)||multiplier<0.01||multiplier>10) throw new Error('人工倍率必须在0.01至10之间');
  if(formula.labor_cost!=null&&formula.management_fee!=null){
    const labor=Number(formula.labor_cost)*multiplier;
    baseCost=baseCost-Number(formula.labor_cost)+labor;
    formula.labor_cost=labor;
  }
  formula.attachment_fee=moneySum(rows.map(row=>row.formula_amount));
  formula.total_cost=moneySum([baseCost,formula.attachment_fee]);
  formula=applyManagementFee(formula,item.freight_fee??item.freight??0);
  const basePrice=quick.base_price??(quick.total_cost==null?NaN:Number(quick.total_cost)-Number(quick.attachment_fee||0));
  if(!Number.isFinite(Number(basePrice))) throw new Error('柜体面价快照不完整，请重新计算整柜');
  quick.base_price=money(basePrice);
  quick.attachment_fee=moneySum(rows.map(quickAttachmentLineAmount));
  quick.total_cost=moneySum([quick.base_price,quick.attachment_fee]);
  const hydrated={...item,attachments:rows,formula,quick,formula_base:result.formula_cost,
    quote_display:{...item.quote_display,attachments:rows}};
  validateQuoteDisplay(hydrated);
  return hydrated;
}

export function createAttachmentService({runPsql,calculateBase,env=process.env,onProgress=()=>{},onTiming=()=>{}}) {
  const query=async sql=>{const text=await runPsql(sql);return JSON.parse(text.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  function catalogCondition() {
    const version=env.AI_QUOTE_ATTACHMENT_V2_VERSION||'';
    return version?`data_version=${sqlValue(version)}`:"status='ACTIVE'";
  }
  function checkedCatalogVersion(versions) {
    if(versions.length!==1) throw new Error('没有可用的附件V2目录；请配置已审查的目录版本');
    const v=versions[0];
    if(v.status!=='ACTIVE'&&!(v.status==='STAGED'&&env.AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED==='1')) throw new Error('附件目录尚未启用；待启用数据仅供明确配置的兼容测试');
    return v;
  }
  function catalogItemsSql(version, activeFilter, selectedIds=null) {
    return `SELECT coalesce(jsonb_agg(to_jsonb(a)||jsonb_build_object('rules',coalesce((
      SELECT jsonb_agg(to_jsonb(r)||jsonb_build_object(
        'products',(SELECT coalesce(jsonb_agg(product_code),'[]') FROM calc.attachment_cost_rule_product WHERE rule_id=r.rule_id),
        'materials',(SELECT coalesce(jsonb_agg(material_code),'[]') FROM calc.attachment_cost_rule_material WHERE rule_id=r.rule_id)))
      FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id)
      WHERE b.attachment_price_id=a.attachment_price_id),'[]')) ORDER BY a.source_row_no),'[]')
      FROM (SELECT p.attachment_price_id,c.category_level1,coalesce(c.category_level2,'') AS category_level2,
        coalesce(c.category_level3,'') AS category_level3,p.item_name,p.model_code,p.unit,p.color,p.width_mm,p.height_mm,p.depth_mm,
        p.quick_face_price AS price,p.data_version,p.source_file,p.source_sheet,p.source_row_no
        FROM calc.attachment_price p JOIN calc.attachment_classification c USING(attachment_price_id)
        WHERE p.data_version=${version}${activeFilter}
          ${selectedIds===null?'':selectedIds.length?`AND p.attachment_price_id IN (${selectedIds.join(',')})`:'AND FALSE'}) a`;
  }
  async function catalog() {
    const versions=await query(`SELECT coalesce(jsonb_agg(to_jsonb(v)),'[]') FROM calc.attachment_catalog_version v WHERE ${catalogCondition()};`);
    const v=checkedCatalogVersion(versions);
    const items=await query(catalogItemsSql(sqlValue(v.data_version),v.status==='ACTIVE'?' AND p.is_active':'')+';');
    return {items,data_version:v.data_version,status:v.status,attachment_contract:2,catalog_write_supported:true};
  }
  async function preview(input, prepared=null) {
    onProgress('attachments');
    if(!Array.isArray(input.attachments)||input.attachments.length>100) throw new Error('attachments必须为不超过100项的数组');
    const gangedCount=Number(input.ganged_cabinet_count||1);
    const gangedCabinets=Array.isArray(input.ganged_cabinets)?input.ganged_cabinets:[];
    const gangedInputs=Array.isArray(input.ganged_cabinet_inputs)?input.ganged_cabinet_inputs:gangedCabinets;
    if(!Number.isSafeInteger(gangedCount)||gangedCount<1||gangedCount>20) throw new Error('并柜数量必须为1至20的整数');
    if(gangedCount>1&&gangedCabinets.length!==gangedCount) throw new Error('并柜明细数量与并柜数量不一致');
    const selections=input.attachments.map(attachmentInput),data=prepared?.catalog??await catalog();
    const quoteDate=input.quote_date;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(quoteDate||'')) throw new Error('报价日期无效');
    if(!['SECC','SUS304','SUS316'].includes(input.material_code)) throw new Error('材质必须为SECC、SUS304或SUS316');
    for(const key of ['width_mm','height_mm','depth_mm']) if(!Number.isFinite(Number(input[key]))||Number(input[key])<=0) throw new Error(`${key}必须为正数`);
    const prices=prepared?.prices??await query(`SELECT jsonb_build_object(
      'density_g_cm3',(SELECT density_g_cm3 FROM calc.material WHERE material_code=${sqlValue(input.material_code)}),
      'spray_unit_price',CASE WHEN ${sqlValue(input.coating_type)}='不喷塑' THEN 0 ELSE calc.get_spray_unit_price(${sqlValue(quoteDate)}::date,${sqlValue(input.coating_type)}) END);`);
    const environment={quote_line_id:randomUUID(),product_code:input.product_code,material_code:input.material_code,
      width_mm:Number(input.width_mm),height_mm:Number(input.height_mm),depth_mm:Number(input.depth_mm),
      coating_type:input.coating_type,quote_date:quoteDate,
      ...(input.pricing_basis?{pricing_basis:input.pricing_basis}:{}),
      cabinet_body_thickness_mm:Number(input.cabinet_body_thickness_mm??1.5),
      waste_factor:Number(input.waste_factor??1.2),ganged_cabinet_count:gangedCount,
      ganged_cabinets:gangedCabinets,...prices,material_unit_price:materialUnitPriceFromSidebar(input,input.material_code)};
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
    onProgress('snapshot');
    const lineId=previewed.environment.quote_line_id;
    const result={...applyAttachmentTotals(base,previewed.attachments,input.freight_fee??input.freight??0),quote_id:input.quote_id,quote_line_id:lineId};
    const environment={...previewed.environment,model_code:input.model_code||'',quote_result:{...result,attachments:undefined}};
    const rows=previewed.attachments;
    const commands=[`INSERT INTO calc.attachment_quote_line(quote_line_id,quote_id,product_code,environment_snapshot)
      VALUES(${sqlValue(lineId)}::uuid,${sqlValue(input.quote_id)},${sqlValue(input.product_code)},${sqlJson(environment)});`];
    for(const row of rows){
      const values={quote_line_id:lineId,quote_id:input.quote_id,product_code:input.product_code,attachment_price_id:row.attachment_price_id,
        quantity:row.quantity,price_sign:row.attachment_price_sign,unit_price:row.face_price,
        item_name:row.item_name,model_code:row.model_code,calculation_status:row.status,
        cost_rule_id:row.rule_id??null,rule_version:row.rule_version??null,catalog_version:row.catalog_version,
        // Retain the immutable catalogue-price extension for existing DB
        // guards; the effective perimeter amount is frozen in cost_snapshot
        // and quote_result, which drive responses, confirmation and export.
        manual_inputs:row.manual_inputs,environment_snapshot:environment,quick_face_price:row.face_price,quick_amount:row.catalogue_quick_amount??row.quick_amount,
        formula_unit_cost:row.formula_unit_cost,formula_amount:row.formula_amount,error_message:row.error??null,
        cost_snapshot:{...row,category_level2:row.category_level2||'',unit:row.unit||'',auxiliary_list:row.auxiliary_list||''}};
      commands.push(`INSERT INTO calc.attachment_selection(${Object.keys(values).join(',')}) VALUES(${Object.entries(values).map(([key,value])=>key==='quote_line_id'?`${sqlValue(value)}::uuid`:typeof value==='object'&&value!==null?sqlJson(value):sqlValue(value)).join(',')});`);
    }
    const saved=await query(`BEGIN;\n${commands.join('\n')}\n${snapshotSql(lineId)}\nCOMMIT;`);
    result.attachments=saved.attachments;return result;
  }
  async function calculate(input) {
    // Each base calculation has a fresh private quote id and NO attachment inserts.
    onProgress('cabinet');
    const base=await calculateBase({...input,quote_id:`AV2_${randomUUID()}`,attachments:[]});
    const previewed=await preview(input);
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
  async function recalculateLine(input) {
    if(!Array.isArray(input.attachments)||input.attachments.length>100) throw new Error('attachments必须为不超过100项的数组');
    const selections=input.attachments.map(attachmentInput);
    const selectedIds=[...new Set(selections.map(row=>row.attachment_price_id))];
    const lineId=uuid(input.quote_line_id);
    const timed=async(phase,action)=>{
      const started=performance.now();let success=false;
      try {const result=await action();success=true;return result;}
      finally {onTiming({phase,elapsed_ms:Math.round(performance.now()-started),success});}
    };
    // One MVCC-consistent read, only selected IDs and their bound rules. No cross-request cache.
    const context=await timed('read',()=>query(`WITH refresh_line AS (
      SELECT l.quote_line_id,l.environment_snapshot FROM calc.attachment_quote_line l
      WHERE l.quote_line_id=${sqlValue(lineId)}::uuid
    ), refresh_versions AS (
      SELECT to_jsonb(v) AS version FROM calc.attachment_catalog_version v WHERE ${catalogCondition()}
    ) SELECT jsonb_build_object(
      'saved',(SELECT jsonb_build_object('environment',l.environment_snapshot,
        'attachments',coalesce((SELECT jsonb_agg(s.cost_snapshot||jsonb_build_object(
          'attachment_selection_id',s.attachment_selection_id,'quote_line_id',s.quote_line_id)
          ORDER BY s.attachment_selection_id) FROM calc.attachment_selection s
          WHERE s.quote_line_id=l.quote_line_id),'[]'::jsonb)) FROM refresh_line l),
      'versions',(SELECT coalesce(jsonb_agg(version),'[]'::jsonb) FROM refresh_versions),
      'items',(${catalogItemsSql("(SELECT version->>'data_version' FROM refresh_versions LIMIT 1)",
        " AND ((SELECT version->>'status' FROM refresh_versions LIMIT 1)<>'ACTIVE' OR p.is_active)",selectedIds)}),
      'prices',(SELECT jsonb_build_object(
        'density_g_cm3',(SELECT density_g_cm3 FROM calc.material
          WHERE material_code=l.environment_snapshot->>'material_code'),
        'spray_unit_price',CASE WHEN l.environment_snapshot->>'coating_type'='不喷塑' THEN 0
          ELSE calc.get_spray_unit_price((l.environment_snapshot->>'quote_date')::date,
            l.environment_snapshot->>'coating_type') END) FROM refresh_line l));`));
    const saved=context?.saved;
    if(!saved?.environment?.quote_result) throw new Error('附件报价行不存在，请重新计算整柜');
    const environment=saved.environment;
    const supplied=input.environment||environment;
    if(attachmentEnvironmentChange(supplied,environment)
      ||canonical(supplied.ganged_cabinets||[])!==canonical(environment.ganged_cabinets||[]))
      throw new Error('柜体参数已变化，请重新计算整柜');
    // Reuse only the authoritative cabinet result. Never accept client totals
    // or rewrite the old snapshot (which remains an immutable audit record).
    const base=structuredClone(environment.quote_result);
    if(!base.formula_cost||typeof base.formula_cost!=='object'
      ||!base.quick_quote||typeof base.quick_quote!=='object')
      throw new Error('柜体成本快照不完整，请重新计算整柜');
    base.risk_flags=(base.risk_flags||[]).filter(risk=>risk.code!=='attachment_error');
    const formula=base.formula_cost;
    if(formula.total_cost==null){
      const components=['material_cost','auxiliary_cost','labor_cost','spray_cost','management_fee'];
      if(components.some(key=>formula[key]==null||!Number.isFinite(Number(formula[key]))))
        throw new Error('柜体成本快照不完整，请重新计算整柜');
      formula.total_cost=round(components.reduce((sum,key)=>sum+Number(formula[key]),0));
      formula.attachment_fee=0;
    }
    const children=environment.ganged_cabinets||[];
    const replay={...environment,...(input.pricing_basis?{pricing_basis:input.pricing_basis}:{}),quote_id:base.quote_id,
      material_unit_price_override:environment.material_unit_price,
      attachments:input.attachments,
      ganged_cabinet_inputs:children.map((child,index)=>{
        const previous=saved.attachments.find(row=>row.ganged_cabinet_index===index);
        return {...child,product_code:previous?.environment?.product_code||child.product_code||environment.product_code};
      })};
    const version=checkedCatalogVersion(context.versions);
    const previewed=await timed('calculate',async()=>{
      const result=await preview(replay,{
        catalog:{items:context.items,data_version:version.data_version,status:version.status},prices:context.prices,
      });
      const errors=result.attachments.filter(row=>row.status==='ERROR');
      if(errors.length){
        const error=new Error(errors.map(row=>`${row.item_name}：${row.error}`).join('；'));
        error.statusCode=422;
        error.issues=errors.map(row=>({attachment_price_id:row.attachment_price_id,
          attachment_name:row.item_name,reason:row.error}));
        throw error;
      }
      return result;
    });
    return timed('save',()=>persistCalculated(replay,previewed,base));
  }
  function snapshotSql(lineId) {return `SELECT jsonb_build_object('environment',l.environment_snapshot,
    'attachments',coalesce((SELECT jsonb_agg(s.cost_snapshot||jsonb_build_object('attachment_selection_id',s.attachment_selection_id,'quote_line_id',s.quote_line_id) ORDER BY s.attachment_selection_id)
      FROM calc.attachment_selection s WHERE s.quote_line_id=l.quote_line_id),'[]'))
    FROM calc.attachment_quote_line l WHERE quote_line_id=${sqlValue(uuid(lineId))}::uuid;`;}
  function snapshotsSql(lineIds, attachmentLineIds=lineIds) {
    if(!attachmentLineIds.length) return `SELECT coalesce(jsonb_object_agg(l.quote_line_id::text,
      jsonb_build_object('environment',l.environment_snapshot,'attachments','[]'::jsonb)),'{}'::jsonb)
      FROM calc.attachment_quote_line l
      WHERE l.quote_line_id IN (${lineIds.map(lineId=>`${sqlValue(lineId)}::uuid`).join(',')});`;
    return `WITH selected_lines AS (
      SELECT l.quote_line_id,l.environment_snapshot FROM calc.attachment_quote_line l
      WHERE l.quote_line_id IN (${lineIds.map(lineId=>`${sqlValue(lineId)}::uuid`).join(',')})
    ), selection_snapshots AS (
      SELECT s.quote_line_id,jsonb_agg(s.cost_snapshot||jsonb_build_object(
        'attachment_selection_id',s.attachment_selection_id,'quote_line_id',s.quote_line_id)
        ORDER BY s.attachment_selection_id) AS attachments
      FROM calc.attachment_selection s JOIN selected_lines l USING(quote_line_id)
      ${attachmentLineIds.length===lineIds.length?'':`WHERE s.quote_line_id IN (${attachmentLineIds.map(lineId=>`${sqlValue(lineId)}::uuid`).join(',')})`}
      GROUP BY s.quote_line_id
    )
    SELECT coalesce(jsonb_object_agg(l.quote_line_id::text,jsonb_build_object(
      'environment',l.environment_snapshot,'attachments',coalesce(s.attachments,'[]'::jsonb))),'{}'::jsonb)
    FROM selected_lines l LEFT JOIN selection_snapshots s USING(quote_line_id);`;}
  async function hydrateDocument(input) {
    if(!input || typeof input!=='object' || !Array.isArray(input.items)) throw new Error('items are required');
    // Request-local batching only: copied rows share the read, not their
    // validation or mutable results. Every later request reads fresh data.
    const lineIds=[...new Set(input.items.filter(item=>item?.attachment_contract===2)
      .map(item=>uuid(item.quote_line_id).toLowerCase()))];
    const attachmentLineIds=[...new Set(input.items.filter(item=>item?.attachment_contract===2
      &&!(item.pricing_basis===PRICING_BASIS&&item.quote_display?.attachment_source==='popup_v1'))
      .map(item=>uuid(item.quote_line_id).toLowerCase()))];
    const snapshots=lineIds.length?await query(snapshotsSql(lineIds,attachmentLineIds)):{};
    const items=[];
    for(const [itemIndex,item] of (input.items||[]).entries()){
      try {
      if(item.attachment_contract!==2){
        if((item.attachments||[]).some(a=>a.catalog_version||a.rule_id||a.status)) throw new Error('附件V2报价缺少服务端报价行ID');
        const ids=(item.attachments||[]).filter(a=>a.attachment_price_id!=null).map(a=>id(a.attachment_price_id));
        if(ids.length && await query(`SELECT to_jsonb(EXISTS(SELECT 1 FROM calc.attachment_price WHERE attachment_price_id IN (${ids.join(',')}) AND data_version IS NOT NULL));`)) throw new Error('附件V2报价缺少服务端报价行ID');
        validateQuoteDisplay(item);
        items.push(item);continue;
      }
      const saved=structuredClone(snapshots[item.quote_line_id.toLowerCase()]);
      if(!saved) throw new Error('附件报价行不存在，请重新计算');
      const providedAttachments=Array.isArray(item.attachments)?item.attachments:[];
      const customAttachments=providedAttachments.filter(row=>row?.custom===true).map(customAttachmentInput);
      const catalogAttachments=providedAttachments.filter(row=>row?.custom!==true);
      const changedKey=attachmentEnvironmentChange(item,saved.environment);
      if(changedKey) throw new Error(`报价环境已变化（${changedKey}），请重新计算附件`);
      if(Number(item.ganged_cabinet_count||1)!==Number(saved.environment.ganged_cabinet_count||1)
        ||canonical(item.ganged_cabinets||[])!==canonical(saved.environment.ganged_cabinets||[])) throw new Error('并柜明细已变化，请重新计算附件');
      if(item.pricing_basis===PRICING_BASIS&&item.quote_display?.attachment_source==='popup_v1'){
        // Keep the cabinet calculation anchored to its original snapshot.
        // Completed popup rows are the quote-local attachment source; document
        // generation never looks up the catalogue or persists/reprices them.
        items.push(popupDocumentSnapshot(item,saved));
        continue;
      }
      if(canonical(catalogAttachments.map(attachmentInput))!==canonical(saved.attachments.map(attachmentInput))) throw new Error('附件选择或人工参数已变化，请重新计算');
      const failedAttachments=saved.attachments.filter(a=>a.status==='ERROR');
      if(failedAttachments.length){
        const issues=failedAttachments.map(attachment=>({
          line_number:itemIndex+1,product_name:item.name||item.model_code||item.product_code||'未命名',
          product_code:item.product_code||'',attachment_price_id:attachment.attachment_price_id,
          attachment_name:attachment.item_name||attachment.model_code||'未命名附件',
          reason:attachment.error||'附件成本计算失败',
        }));
        const error=new Error('附件成本存在错误，不能确认或导出：\n'+issues.map(issue=>
          `第${issue.line_number}行报价（${issue.product_name}）的“${issue.attachment_name}”：${issue.reason}`).join('\n'));
        error.statusCode=422;error.issues=issues;
        throw error;
      }
      const result=saved.environment.quote_result;
      let formula={...result.formula_cost};
      // Adjust cabinet labor only; the final six-component base determines management.
      const multiplier=Number(item.labor_multiplier??1);
      if(!Number.isFinite(multiplier)||multiplier<0.01||multiplier>10) throw new Error('人工倍率必须在0.01至10之间');
      if(formula.total_cost!=null && formula.labor_cost!=null && formula.management_fee!=null){
        const labor=Number(formula.labor_cost)*multiplier;
        formula.total_cost=Number(formula.total_cost)-Number(formula.labor_cost)+labor;
        formula.labor_cost=labor;
      }
      const customFormulaTotal=customAttachments.reduce((sum,row)=>sum+Number(row.formula_amount),0);
      const customQuickTotal=customAttachments.reduce((sum,row)=>sum+Number(row.quick_amount),0);
      formula=addCustomAmount(formula,customFormulaTotal);
      let quick=addCustomAmount(result.quick_quote,customQuickTotal);
      let rows=[...saved.attachments,...customAttachments];
      if(item.pricing_basis===PRICING_BASIS){
        const display=item.quote_display;
        const visible=display?.attachments;
        if(!Array.isArray(visible)||visible.length!==rows.length) throw new Error(`第${itemIndex+1}行附件显示快照不完整`);
        const visibleCatalog=visible.filter(row=>row?.custom!==true);
        if(canonical(visibleCatalog.map(attachmentInput))!==canonical(saved.attachments.map(attachmentInput)))
          throw new Error(`第${itemIndex+1}行附件显示快照与计算选择不一致`);
        if(canonical(visible.filter(row=>row?.custom===true).map(customAttachmentInput))!==canonical(customAttachments))
          throw new Error(`第${itemIndex+1}行人工附件显示快照不一致`);
        const visibleRows=[...visibleCatalog,...visible.filter(row=>row?.custom===true)];
        rows=rows.map((row,index)=>{
          const shown=visibleRows[index];
          if(row.custom!==shown.custom && Boolean(row.custom)!==Boolean(shown.custom)) throw new Error('附件显示快照顺序不一致');
          const override=shown.quick_amount_override;
          const edited=shown.custom_amount_edited===true || (!Object.hasOwn(shown,'custom_amount_edited')
            && override!=null && Number(override)!==0);
          let amount=quickAttachmentLineAmount(row);
          if(edited){
            const value=override??shown.quick_amount;
            if(value==null||!Number.isFinite(Number(value))||Math.abs(Number(value))>1e8) throw new Error(`${row.item_name}：人工金额无效`);
            amount=money(value);
          } else if(quickAttachmentLineAmount(shown)!==amount){
            throw Object.assign(new Error(`第${itemIndex+1}行附件“${row.item_name}”金额不一致，请重新计算附件`),
              {attachment_name:row.item_name,attachment_price_id:row.attachment_price_id});
          }
          return {...row,formula_amount:money(row.formula_amount),quick_amount:amount,
            ...(edited?{quick_amount_override:amount,custom_amount_edited:true}:{} )};
        });
        const oldQuickFee=Number(quick.attachment_fee||0);
        const base=money(quick.base_price??(Number(quick.total_cost||0)-oldQuickFee));
        const quickFee=moneySum(rows.map(quickAttachmentLineAmount));
        quick={...quick,base_price:base,attachment_fee:quickFee,total_cost:moneySum([base,quickFee])};
        const formulaFee=moneySum(rows.map(row=>row.status==='QUICK_ONLY'?0:row.formula_amount));
        formula={...formula,total_cost:moneySum([Number(formula.total_cost||0),-Number(formula.attachment_fee||0),formulaFee]),attachment_fee:formulaFee};
        validateQuoteDisplay({...item,attachments:rows,formula,quick});
      }
      formula=applyManagementFee(formula,item.freight_fee??item.freight??0);
      // A frozen service result remains independent of later catalog and price updates.
      items.push({...item,attachments:rows,
        ...(item.pricing_basis===PRICING_BASIS?{quote_display:{...item.quote_display,attachments:rows}}:{}),formula_base:result.formula_cost,
        formula,quick});
      } catch(error) {
        if(item?.pricing_basis===PRICING_BASIS && !error.issues){
          error.statusCode=422;
          error.issues=[{line_number:itemIndex+1,product_name:item.name||item.product_code||'未命名',
            attachment_name:error.attachment_name||'报价／附件金额校验',
            ...(error.attachment_price_id?{attachment_price_id:error.attachment_price_id}:{}),reason:error.message}];
        }
        throw error;
      }
    }
    return {...input,items};
  }
  return {catalog,preview,calculate,snapshotGanged,recalculateLine,hydrateDocument,hasActive:async()=>query("SELECT to_jsonb(EXISTS(SELECT 1 FROM calc.attachment_catalog_version WHERE status='ACTIVE'));")};
}
