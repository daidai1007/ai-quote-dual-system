import {calculateAttachment, requiredParameters} from './attachment_cost.mjs';
import {money, moneyProduct, PRICING_BASIS} from '../quick_discount_rules.mjs';

export const STANDALONE_TYPE = 'standalone_attachment';
const dimensions = {宽度:'width_mm',高度:'height_mm',深度:'depth_mm'};
const environmentKeys = {...dimensions,材质密度:'density_g_cm3',材质单价:'material_unit_price',喷塑单价:'spray_unit_price'};
const valid=(value,zero=false)=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value))&&(zero?Number(value)>=0:Number(value)>0);
const label=row=>[row.model_code,...Object.entries(dimensions).filter(([,key])=>valid(row[key])).map(([name,key])=>`${name}${row[key]}`)].filter(Boolean).join(' · ')||`目录项 ${row.attachment_price_id}`;
const fail=message=>{throw new Error(message);};
const normalized=value=>String(value||'').normalize('NFKC').replace(/\s+/g,'');

/** No cabinet environment enters this function. A missing axis stays missing. */
export function calculateStandaloneAttachment(source, data) {
  if(!source||typeof source!=='object'||Array.isArray(source))fail('独立附件输入无效');
  if(source.quantity!=null&&Number(source.quantity)!==1)fail('独立附件内部数量固定为1，订购数量请在主表修改');
  if(source.custom===true){
    const manual=source.manual_inputs||{},missing=['成本单价','面价单价'].filter(name=>!valid(manual[name],true));
    const row={...source,item_name:String(source.item_name||source.name||'').trim(),quantity:1,
      attachment_price_sign:1,standalone_attachment:true,unit:source.unit||'件',catalog_version:'quote_local_v1',
      pending_manual_dimensions:missing,standalone_parameter_choices:{},
      required_parameters:['成本单价','面价单价'].map(name=>({name,source:'MANUAL',unit:'元'}))};
    if(!row.item_name)fail('独立附件名称不能为空');
    if(missing.length)return {...row,status:'PENDING_MANUAL',formula_amount:null,quick_amount:null};
    const sale=source.custom_amount_edited===true?source.unit_price_override:manual.面价单价;
    if(!valid(sale,true))fail('独立附件面价单价无效');
    const cost=source.custom_cost_edited===true?source.formula_unit_cost_override:manual.成本单价;
    if(!valid(cost,true))fail('独立附件成本单价无效');
    return {...row,status:'FIXED',formula_unit_cost:money(cost),formula_amount:money(cost),
      quick_amount:money(sale),quick_amount_override:money(sale),matched_price:money(sale),
      unit_price_override:money(sale),custom_amount_edited:source.custom_amount_edited===true,
      formula_cost_edited:true,formula_unit_cost_override:money(cost)};
  }
  let candidates=data.items.filter(row=>source.attachment_price_id!=null
    ?Number(row.attachment_price_id)===Number(source.attachment_price_id)
    :String(row.item_name||'')===String(source.item_name||source.name||'')
      &&(!source.category_level1||row.category_level1===source.category_level1)
      &&(!source.model_code||row.model_code===source.model_code));
  if(!candidates.length&&source.attachment_price_id==null){
    const name=normalized(source.item_name||source.name),category=normalized(source.category_level1);
    candidates=data.items.filter(row=>{
      const ownName=normalized(row.item_name),ownCategory=normalized(row.category_level1);
      return ((category===ownCategory&&(name===ownCategory||normalized(row.category_level2)===name))
        ||(['风机','滤网'].includes(category)&&ownCategory===category&&ownName.endsWith(name))
        ||(category==='照明灯/行程开关'&&ownCategory==='灯开关'&&[ownName,normalized(row.model_code)].some(value=>value===name))
        ||(name==='接地线-黄绿线'&&ownName.includes('接地线')&&/[黄红]绿线/.test(ownName))
        ||(name==='接地线-编织带'&&ownName.includes('接地线')&&ownName.includes('编织带')));
    });
  }
  if(!candidates.length)fail('价格库未找到该独立附件，请重新选择');
  const manual=source.manual_inputs||{};
  if(typeof manual!=='object'||Array.isArray(manual))fail('附件参数无效');
  const base={...source,quantity:1,attachment_price_sign:1,manual_inputs:structuredClone(manual),
    standalone_attachment:true,catalog_version:data.data_version,quick_amount:null,formula_amount:null,
    status:'PENDING_MANUAL',pending_manual_dimensions:[],standalone_parameter_choices:{}};
  const pending=(names,extra={})=>({...base,...extra,pending_manual_dimensions:names,
    required_parameters:names.map(name=>({name,source:'MANUAL',unit:environmentKeys[name]&&name==='材质密度'?'g/cm³':name.includes('单价')?'元': 'mm'}))});
  if(candidates.length!==1)return pending(['目录规格'],{
    standalone_parameter_choices:{目录规格:candidates.map(row=>({value:String(row.attachment_price_id),label:label(row)}))}});
  const catalog=candidates[0];
  Object.assign(base,{attachment_price_id:catalog.attachment_price_id,item_name:catalog.item_name,
    model_code:catalog.model_code||'',unit:catalog.unit||'件',category_level1:catalog.category_level1,
    category_level2:catalog.category_level2,category_level3:catalog.category_level3});
  const siblings=data.items.filter(row=>row.item_name===catalog.item_name&&row.category_level1===catalog.category_level1);
  if(siblings.length>1)base.standalone_parameter_choices.目录规格=siblings.map(row=>({value:String(row.attachment_price_id),label:label(row)}));
  const isBoard=String(catalog.item_name||'').includes('安装板');
  const requestedMaterial=isBoard?'SECC':source.standalone_material_code==='SGCC'?'SECC':source.standalone_material_code;
  let rules=catalog.rules||[];
  if(requestedMaterial)rules=rules.filter(rule=>!rule.materials?.length||rule.materials.includes(requestedMaterial));
  if(source.standalone_rule_id!=null)rules=rules.filter(rule=>String(rule.rule_id)===String(source.standalone_rule_id));
  if((catalog.rules||[]).length&&!rules.length)fail('所选材质或成本规则不适用于该附件');
  if(rules.length>1)return pending(['适用柜型'],{standalone_parameter_choices:{适用柜型:rules.map(rule=>({value:String(rule.rule_id),label:[rule.materials?.join('/'),[...new Set((rule.products||[]).map(value=>value.includes('WIDE')?value.split('_')[0]+' WIDE':value.split('_')[0]))].join(' / ')].filter(Boolean).join(' · ')||'通用'}))}});
  const rule=rules[0];
  let material=isBoard?'SGCC':source.standalone_material_code||'';
  if(rule?.materials?.length&&!material){
    if(rule.materials.length===1)material=rule.materials[0];
    else return pending(['材质'],{standalone_parameter_choices:{材质:rule.materials.map(value=>({value,label:value}))}});
  }
  if(!material&&requiredParameters(rule).some(p=>['材质密度','材质单价'].includes(p.name)))
    return pending(['材质'],{standalone_parameter_choices:{...base.standalone_parameter_choices,
      材质:['SECC','SGCC','SUS304','SUS316'].map(value=>({value,label:({SECC:'碳钢板',SGCC:'镀锌板',SUS304:'不锈钢304',SUS316:'不锈钢316'})[value]}))}});
  if(!isBoard&&requiredParameters(rule).some(p=>['材质密度','材质单价'].includes(p.name)))
    base.standalone_parameter_choices.材质=(rule?.materials?.length?rule.materials:['SECC','SGCC','SUS304','SUS316']).map(value=>({value,label:({SECC:'碳钢板',SGCC:'镀锌板',SUS304:'不锈钢304',SUS316:'不锈钢316'})[value]||value}));
  const environment={pricing_basis:PRICING_BASIS,product_code:rule?.products?.[0]||STANDALONE_TYPE,
    material_code:material==='SGCC'?'SECC':material,
    quote_date:source.standalone_quote_date||new Date().toISOString().slice(0,10)};
  for(const [name,key] of Object.entries(environmentKeys)) {
    const value=dimensions[name]?(manual[name]??catalog[key]):undefined;
    if(valid(value,name==='喷塑单价'))environment[key]=Number(value);
  }
  const settings=source.standalone_cost_settings||{};
  const priceKey={SECC:'carbon_price',SGCC:'galvanized_price',SUS304:'stainless_304_price',SUS316:'stainless_316_price'}[material];
  if(priceKey&&valid(settings[priceKey]))environment.material_unit_price=Number(settings[priceKey]);
  const density=data.material_densities?.[material]??(material==='SGCC'?data.material_densities?.SECC:undefined);
  if(valid(density))environment.density_g_cm3=Number(density);
  if(valid(settings.surface_price,true))environment.spray_unit_price=Number(settings.surface_price);
  // Manual glass/segment dimensions remain exactly the original formula inputs.
  environment.coating_type=environment.spray_unit_price===0?'不喷塑':'喷塑';
  const required=requiredParameters(rule),missing=[];
  for(const parameter of required){
    const value=parameter.source==='ENVIRONMENT'?environment[environmentKeys[parameter.name]]:manual[parameter.name];
    if(!valid(value,parameter.name==='喷塑单价')){
      if(['材质密度','材质单价','喷塑单价'].includes(parameter.name))fail(`请检查修改系数或材质资料：${parameter.name}缺失`);
      missing.push(parameter.name);
    }
  }
  if(!rule&&!valid(manual.成本单价,true))missing.push('成本单价');
  if(missing.length)return pending(missing,{standalone_environment:environment});
  const result=calculateAttachment({quantity:1,attachment_price_sign:1,manual_inputs:manual},catalog,rule?[rule]:[],environment);
  if(result.status==='ERROR')return {...base,...result,standalone_attachment:true};
  if(!rule){result.formula_unit_cost=money(manual.成本单价);result.formula_amount=result.formula_unit_cost;
    result.formula_cost_edited=true;result.formula_unit_cost_override=result.formula_unit_cost;
    result.required_parameters=[{name:'成本单价',source:'MANUAL',unit:'元'}];}
  // Keep the established quote-local selling-price override; recompute its extension.
  if(source.custom_amount_edited===true){
    if(!valid(source.unit_price_override,true)||Number(source.unit_price_override)>999999.99)fail('附件面价单价无效');
    result.unit_price_override=money(source.unit_price_override);result.quick_amount=result.quick_amount_override=moneyProduct(result.unit_price_override,1);result.custom_amount_edited=true;
  }
  return {...base,...result,standalone_attachment:true,pending_manual_dimensions:[],
    standalone_environment:environment,standalone_material_code:material,
    ...(rule?{standalone_rule_id:rule.rule_id}:{}),catalog_version:data.data_version};
}

export function assertStandaloneReady(row) {
  if(!row||row.standalone_attachment!==true||row.pending_manual_dimensions?.length
      ||!['FIXED','CALCULATED','QUICK_ONLY'].includes(row.status)
      ||!valid(row.formula_amount,true)||!valid(row.quick_amount,true))
    fail(`${row?.item_name||'独立附件'}：请先完善规格及成本参数`);
}
