import {evaluateFormula,round} from './attachment_formula.mjs';

const valueSql=value=>value==null?'NULL':typeof value==='number'?String(value):
  `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const finite=(value,label,{allowZero=false,max=1e7}={})=>{
  const n=Number(value);if(!Number.isFinite(n)||(allowZero?n<0:n<=0)||n>max)throw new Error(`${label}必须是有效${allowZero?'非负':'正'}数`);return n;
};
const codeOf=value=>String(value||'').trim().toUpperCase();
const familyOf=code=>{const value=codeOf(code);return /^(JP|JS)_WIDE_EXP$/.test(value)?value:value.split('_')[0];};
const fixedProducts=new Set(['JC_EXP','JQ_EXP','JP_WIDE_EXP','JS_WIDE_EXP','OP_TABLE_EXP']);
function quantity(rule,environment){
  const q=rule.quantity_rule||{},d=environment.depth_mm,h=environment.height_mm;
  if(q.kind==='CONSTANT')return finite(q.value,'喷塑内部数量',{allowZero:true});
  if(q.kind==='JS_DEPTH_HEIGHT')return d>=350&&d<=1000&&h<1000?Number(q.when_true):Number(q.when_false);
  throw new Error(`不支持的柜体喷塑数量规则：${q.kind||'空'}`);
}

export function calculateCabinetSpray(rules,environment){
  const family=familyOf(environment.product_code),single=Number(environment.single_door_count||0),double=Number(environment.double_door_count||0);
  const candidates=rules.filter(rule=>rule.family===family&&Number(rule.single_door_count)===single&&Number(rule.double_door_count)===double);
  if(!candidates.length)throw new Error(`最新柜体喷塑表没有 ${family} 门型 ${single}/${double} 的规则`);
  const profiles=[...new Set(candidates.map(rule=>rule.body_thickness_profile_mm).filter(value=>value!=null).map(Number))];
  const requested=environment.cabinet_body_thickness_mm==null?1.5:finite(environment.cabinet_body_thickness_mm,'柜体料厚',{max:20});
  const selected=profiles.length>1?candidates.filter(rule=>Math.abs(Number(rule.body_thickness_profile_mm)-requested)<1e-9):candidates;
  if(!selected.length)throw new Error(`${family} 没有柜体料厚 ${requested} mm 的喷塑规则`);
  const variables={宽度:finite(environment.width_mm,'宽度'),高度:finite(environment.height_mm,'高度'),深度:finite(environment.depth_mm,'深度')};
  const details=selected.map(rule=>{
    const areaPerPiece=evaluateFormula(rule.area_formula,variables);
    if(!Number.isFinite(areaPerPiece)||areaPerPiece<0)throw new Error(`${rule.part_name}喷塑面积无效`);
    const internalQuantity=quantity(rule,environment),totalArea=areaPerPiece*internalQuantity;
    return {rule_id:rule.rule_id,part_name:rule.part_name,area_per_piece_m2:round(areaPerPiece,10),
      internal_quantity:internalQuantity,total_area_m2:round(totalArea,10),area_formula:rule.area_formula,
      quantity_rule:rule.quantity_rule,source_sheet:rule.source_sheet,source_row_no:rule.source_row_no,source_column:rule.source_column};
  });
  const unitPrice=finite(environment.spray_unit_price,'喷塑单价',{allowZero:true});
  const area=round(details.reduce((sum,row)=>sum+row.total_area_m2,0),8);
  return {data_version:environment.data_version,family,single_door_count:single,double_door_count:double,
    body_thickness_profile_mm:profiles.length>1?requested:(profiles[0]??null),coating_type:environment.coating_type,
    spray_unit_price:unitPrice,product_area_m2:area,spray_cost:round(area*unitPrice,2),part_details:details};
}

function jcProfile(environment){
  const variant=codeOf(environment.variant_code),model=codeOf(environment.model_code);
  if(/LUXURY|DELUXE|豪华/.test(variant)||/-1$/.test(model))return 'LUXURY';
  if(/STANDARD|DEFAULT|标配/.test(variant)||/-2$/.test(model))return 'STANDARD';
  return null;
}

export function calculateCabinetSprayFixed(rules,environment){
  const product=codeOf(environment.product_code);
  let candidates=(rules||[]).filter(rule=>rule.product_code===product&&(rule.material_codes||[]).includes(codeOf(environment.material_code)));
  if(product==='JC_EXP'){
    const profile=jcProfile(environment);
    if(!profile)throw new Error('JC 喷塑成本必须通过型号后缀 -1/-2 或产品配置明确豪华型/标配版');
    candidates=candidates.filter(rule=>rule.profile_code===profile);
  }
  if(!candidates.length)throw new Error(`${product} ${environment.material_code} 没有适用的最新喷塑价格`);
  const width=finite(environment.width_mm,'宽度'),height=finite(environment.height_mm,'高度'),depth=finite(environment.depth_mm,'深度');
  const exact=candidates.filter(rule=>Number(rule.width_mm)===width&&Number(rule.height_mm)===height&&Number(rule.depth_mm)===depth);
  if(exact.length>1)throw new Error(`${product} 喷塑固定价格存在同级冲突`);
  let matched,matchMethod,ratio=1;
  if(exact.length===1){matched=exact[0];matchMethod='FIXED_EXACT';}
  else{
    const scalable=candidates.filter(rule=>rule.allow_dimension_scale);
    if(!scalable.length)throw new Error(`${product} 没有 ${width}×${height}×${depth} 的喷塑价格`);
    const rank=rule=>[Math.abs(Number(rule.width_mm)+Number(rule.height_mm)+Number(rule.depth_mm)-width-height-depth),
      (Number(rule.width_mm)-width)**2+(Number(rule.height_mm)-height)**2+(Number(rule.depth_mm)-depth)**2];
    scalable.sort((a,b)=>rank(a)[0]-rank(b)[0]||rank(a)[1]-rank(b)[1]
      ||Number(b.fixed_rule_id||0)-Number(a.fixed_rule_id||0)||Number(b.source_row_no||0)-Number(a.source_row_no||0));
    matched=scalable[0];matchMethod='FIXED_DIMENSION_SCALE';
    ratio=(width+height+depth)/(Number(matched.width_mm)+Number(matched.height_mm)+Number(matched.depth_mm));
  }
  const noSpray=String(environment.coating_type||'').trim()==='不喷塑';
  return {data_version:environment.data_version,product_code:product,method:'FIXED',match_method:matchMethod,
    coating_type:environment.coating_type,spray_unit_price:noSpray?0:null,product_area_m2:null,
    spray_cost:noSpray?0:round(Number(matched.spray_cost)*ratio,2),perimeter_ratio:round(ratio,6),
    source_sheet:matched.source_sheet,source_row_no:Number(matched.source_row_no),reference_model_code:matched.model_code,
    reference_width_mm:Number(matched.width_mm),reference_height_mm:Number(matched.height_mm),reference_depth_mm:Number(matched.depth_mm),
    matched_rule:matched,part_details:[]};
}

export function createCabinetSprayService({runPsql}){
  const query=async sql=>{const output=await runPsql(sql);return JSON.parse(output.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  return {async calculate(input){
    const product=codeOf(input.product_code),family=familyOf(product),usesFormula=['JS','JP','JA','JE','JK','JM'].includes(family)&&!product.includes('WIDE');
    if(!usesFormula&&!fixedProducts.has(product))return null;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(input.quote_date||''))throw new Error('报价日期无效');
    let data;
    try {data=await query(`SELECT jsonb_build_object(
      'data_version',v.data_version,
      'rules',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.source_sheet,r.source_row_no,r.source_column),'[]')
        FROM calc.cabinet_spray_rule r WHERE r.data_version=v.data_version AND r.family=${valueSql(family)}),
      'fixed_rules',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.source_sheet,r.source_row_no),'[]')
        FROM calc.cabinet_spray_fixed_rule r WHERE r.data_version=v.data_version AND r.product_code=${valueSql(product)}),
      'spray_unit_price',CASE WHEN ${valueSql(input.coating_type)}='不喷塑' THEN 0
        ELSE calc.get_spray_unit_price(${valueSql(input.quote_date)}::date,${valueSql(input.coating_type)}) END
      ) FROM calc.cabinet_spray_catalog_version v WHERE v.status='ACTIVE';`);}
    catch(error){
      if(/cabinet_spray_(catalog_version|rule|fixed_rule).*does not exist/is.test(String(error?.message||error)))return null;
      throw error;
    }
    if(!data)return null;
    if(fixedProducts.has(product))return calculateCabinetSprayFixed(data.fixed_rules,{...input,product_code:product,data_version:data.data_version});
    return calculateCabinetSpray(data.rules,{...input,data_version:data.data_version,spray_unit_price:data.spray_unit_price});
  },async persist(quoteId,result,spray){
    if(!spray)return;
    const formula=result.formula_cost||{};
    const snapshot={data_version:spray.data_version,method:spray.method??'AREA_FORMULA',family:spray.family,product_code:spray.product_code,
      match_method:spray.match_method,body_thickness_profile_mm:spray.body_thickness_profile_mm,
      single_door_count:spray.single_door_count,double_door_count:spray.double_door_count,coating_type:spray.coating_type,
      spray_unit_price:spray.spray_unit_price,product_area_m2:spray.product_area_m2,spray_cost:spray.spray_cost,
      perimeter_ratio:spray.perimeter_ratio,source_sheet:spray.source_sheet,source_row_no:spray.source_row_no,
      reference_model_code:spray.reference_model_code,reference_width_mm:spray.reference_width_mm,
      reference_height_mm:spray.reference_height_mm,reference_depth_mm:spray.reference_depth_mm,
      matched_rule:spray.matched_rule,part_details:spray.part_details};
    const output=await runPsql(`UPDATE calc.dual_quote_result SET formula_product_area_m2=${valueSql(formula.product_area_m2)},
      formula_spray_cost=${valueSql(formula.spray_cost)},formula_total_cost=${valueSql(formula.total_cost)},
      difference_cost=${valueSql(Number.isFinite(Number(result.quick_quote?.total_cost))&&Number.isFinite(Number(formula.total_cost))?round(Number(result.quick_quote.total_cost)-Number(formula.total_cost),2):null)},
      cabinet_spray_version=${valueSql(spray.data_version)},cabinet_spray_snapshot=${valueSql(JSON.stringify(snapshot))}::jsonb,
      updated_at=current_timestamp WHERE quote_id=${valueSql(quoteId)} RETURNING 1;`);
    if(!String(output||'').trim().split(/\r?\n/).some(line=>line.trim()==='1'))throw new Error(`柜体喷塑快照未保存：报价 ${quoteId} 不存在`);
  }};
}

export function applyCabinetSpray(result,spray){
  if(!spray)return result;
  const formula={...(result.formula_cost||{})},old=Number(formula.spray_cost);
  if(!Number.isFinite(old)||!Number.isFinite(Number(formula.total_cost)))throw new Error('数据库基础公式喷塑成本缺失，不能应用最新柜体喷塑规则');
  formula.spray_cost=spray.spray_cost;
  if(spray.product_area_m2!=null&&Number.isFinite(Number(spray.product_area_m2)))formula.product_area_m2=spray.product_area_m2;
  formula.total_cost=round(Number(formula.total_cost)-old+spray.spray_cost,2);
  Object.assign(formula,{...(spray.spray_unit_price!=null&&Number.isFinite(Number(spray.spray_unit_price))?{spray_unit_price:spray.spray_unit_price}:{}),cabinet_spray_version:spray.data_version,
    cabinet_spray_method:spray.method??'AREA_FORMULA',cabinet_spray_match_method:spray.match_method??'AREA_FORMULA',
    cabinet_spray_source_sheet:spray.source_sheet??null,cabinet_spray_source_row_no:spray.source_row_no??null,
    cabinet_spray_reference_model_code:spray.reference_model_code??null,
    cabinet_spray_reference_width_mm:spray.reference_width_mm??null,
    cabinet_spray_reference_height_mm:spray.reference_height_mm??null,
    cabinet_spray_reference_depth_mm:spray.reference_depth_mm??null,
    cabinet_spray_perimeter_ratio:spray.perimeter_ratio??null,cabinet_spray_part_details:spray.part_details});
  return {...result,formula_cost:formula};
}
