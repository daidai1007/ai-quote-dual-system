import {evaluateFormula,round} from './attachment_formula.mjs';

const valueSql=value=>value==null?'NULL':typeof value==='number'?String(value):
  `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const positive=(value,label,{allowZero=false,max=1e7}={})=>{
  const n=Number(value);if(!Number.isFinite(n)||(allowZero?n<0:n<=0)||n>max)throw new Error(`${label}必须是有效${allowZero?'非负':'正'}数`);return n;
};
const familyOf=code=>{const value=String(code||'').trim().toUpperCase();return /^(JP|JS)_WIDE_EXP$/.test(value)?value:value.split('_')[0];};
function quantity(rule,environment){
  const q=rule.quantity_rule||{},w=environment.width_mm,h=environment.height_mm,d=environment.depth_mm;
  if(q.kind==='CONSTANT') return positive(q.value,'内部数量',{allowZero:true});
  if(q.kind==='JS_DEPTH_HEIGHT') return d>=350&&d<=1000&&h<1000?Number(q.when_true):Number(q.when_false);
  if(q.kind==='HEIGHT_GT') return h>Number(q.threshold)?Number(q.when_true):Number(q.when_false);
  if(q.kind==='JE_REINFORCEMENT') return (w>600&&h>1000)||(w>800&&h>600)?Number(q.when_true):Number(q.when_false);
  throw new Error(`不支持的柜体材料数量规则：${q.kind||'空'}`);
}
export function calculateCabinetMaterial(rules,environment){
  const family=familyOf(environment.product_code),single=Number(environment.single_door_count||0),double=Number(environment.double_door_count||0);
  const candidates=rules.filter(r=>r.family===family&&Number(r.single_door_count)===single&&Number(r.double_door_count)===double);
  if(!candidates.length) throw new Error(`最新柜体材料表没有 ${family} 门型 ${single}/${double} 的规则`);
  const profiles=[...new Set(candidates.map(r=>r.body_thickness_profile_mm).filter(v=>v!=null).map(Number))];
  const requested=environment.cabinet_body_thickness_mm==null?1.5:positive(environment.cabinet_body_thickness_mm,'柜体料厚',{max:20});
  const selected=profiles.length>1?candidates.filter(r=>Math.abs(Number(r.body_thickness_profile_mm)-requested)<1e-9):candidates;
  if(!selected.length)throw new Error(`${family} 没有柜体料厚 ${requested} mm 的材料规则`);
  const waste=positive(environment.waste_factor??1.2,'废料系数',{max:10});
  const priceByCode=new Map((environment.materials||[]).map(m=>[m.material_code,m]));
  const variables={宽度:positive(environment.width_mm,'宽度'),高度:positive(environment.height_mm,'高度'),深度:positive(environment.depth_mm,'深度')};
  const details=selected.map(rule=>{
    const area=evaluateFormula(rule.area_formula,variables);if(area<0)throw new Error(`${rule.part_name}面积为负数`);
    const internalQuantity=quantity(rule,environment);
    const materialCode=rule.fixed_material_code||environment.material_code;
    const material=priceByCode.get(materialCode);
    if(!material)throw new Error(`${rule.part_name}缺少材质 ${materialCode} 的密度或有效材料单价`);
    const density=positive(material.density_g_cm3,`${materialCode}密度`),unitPrice=positive(material.material_unit_price,`${materialCode}材料单价`);
    const netWeight=area*Number(rule.sheet_thickness_mm)*internalQuantity*density;
    const billableWeight=netWeight*waste;
    return {rule_id:rule.rule_id,part_name:rule.part_name,material_code:materialCode,area_m2:round(area,10),
      sheet_thickness_mm:Number(rule.sheet_thickness_mm),internal_quantity:internalQuantity,density_g_cm3:density,
      fixed_material_code:rule.fixed_material_code||null,
      net_weight_kg:round(netWeight,8),waste_factor:waste,billable_weight_kg:round(billableWeight,8),
      material_unit_price:unitPrice,material_cost:round(billableWeight*unitPrice,8),area_formula:rule.area_formula,
      quantity_rule:rule.quantity_rule,source_sheet:rule.source_sheet,source_row_no:rule.source_row_no,source_column:rule.source_column};
  });
  const grouped=[];
  for(const detail of details){let row=grouped.find(x=>x.material_code===detail.material_code&&x.material_unit_price===detail.material_unit_price);
    if(!row){row={material_code:detail.material_code,material_unit_price:detail.material_unit_price,net_weight_kg:0,billable_weight_kg:0,material_cost:0};grouped.push(row);}
    row.net_weight_kg+=detail.net_weight_kg;row.billable_weight_kg+=detail.billable_weight_kg;row.material_cost+=detail.material_cost;
  }
  for(const row of grouped){row.net_weight_kg=round(row.net_weight_kg,8);row.billable_weight_kg=round(row.billable_weight_kg,8);row.material_cost=round(row.material_cost,2);}
  return {data_version:environment.data_version,family,single_door_count:single,double_door_count:double,
    body_thickness_profile_mm:profiles.length>1?requested:(profiles[0]??null),waste_factor:waste,
    net_material_weight_kg:round(details.reduce((s,r)=>s+r.net_weight_kg,0),8),
    corrected_material_weight_kg:round(details.reduce((s,r)=>s+r.billable_weight_kg,0),8),
    material_cost:round(details.reduce((s,r)=>s+r.material_cost,0),2),material_details:grouped,part_details:details};
}

export function createCabinetMaterialService({runPsql}){
  const query=async sql=>{const output=await runPsql(sql);return JSON.parse(output.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  return {async calculate(input){
    const family=familyOf(input.product_code);if(!['JS','JP','JA','JE','JK','JM'].includes(family))return null;
    const date=input.quote_date;if(!/^\d{4}-\d{2}-\d{2}$/.test(date||''))throw new Error('报价日期无效');
    let data;
    try { data=await query(`SELECT jsonb_build_object(
      'data_version',v.data_version,'default_waste_factor',v.default_waste_factor,
      'rules',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.source_sheet,r.source_row_no,r.source_column),'[]') FROM calc.cabinet_material_rule r WHERE r.data_version=v.data_version AND r.family=${valueSql(family)}),
      'materials',(SELECT coalesce(jsonb_agg(jsonb_build_object('material_code',m.material_code,'density_g_cm3',m.density_g_cm3,
        'material_unit_price',calc.get_material_unit_price(m.material_code,${valueSql(date)}::date))),'[]') FROM calc.material m WHERE m.material_code IN (${valueSql(input.material_code)},'SECC')))
      FROM calc.cabinet_material_catalog_version v WHERE v.status='ACTIVE';`); }
    catch(error){
      if(/cabinet_material_(catalog_version|rule).*does not exist/is.test(String(error?.message||error)))return null;
      throw error;
    }
    if(!data)return null;
    return calculateCabinetMaterial(data.rules,{...input,data_version:data.data_version,materials:data.materials,
      waste_factor:input.waste_factor??data.default_waste_factor});
  },async persist(quoteId,result,material){
    if(!material)return;
    const formula=result.formula_cost||{},quick=result.quick_quote||{};
    const difference=Number.isFinite(Number(quick.total_cost))&&Number.isFinite(Number(formula.total_cost))
      ?round(Number(quick.total_cost)-Number(formula.total_cost),2):null;
    const snapshot={data_version:material.data_version,family:material.family,
      body_thickness_profile_mm:material.body_thickness_profile_mm,single_door_count:material.single_door_count,
      double_door_count:material.double_door_count,waste_factor:material.waste_factor,
      material_details:material.material_details,part_details:material.part_details};
    const output=await runPsql(`UPDATE calc.dual_quote_result SET
      formula_material_cost=${valueSql(formula.material_cost)},formula_total_cost=${valueSql(formula.total_cost)},
      difference_cost=${valueSql(difference)},formula_net_material_weight_kg=${valueSql(material.net_material_weight_kg)},
      formula_corrected_material_weight_kg=${valueSql(material.corrected_material_weight_kg)},
      formula_waste_factor=${valueSql(material.waste_factor)},cabinet_material_version=${valueSql(material.data_version)},
      cabinet_material_snapshot=${valueSql(JSON.stringify(snapshot))}::jsonb,updated_at=current_timestamp
      WHERE quote_id=${valueSql(quoteId)} RETURNING 1;`);
    if(!String(output||'').trim().split(/\r?\n/).some(line=>line.trim()==='1')){
      throw new Error(`柜体材料快照未保存：报价 ${quoteId} 不存在`);
    }
  }};
}

export function applyCabinetMaterial(result,material){
  if(!material)return result;
  const formula={...(result.formula_cost||{})},old=Number(formula.material_cost);
  if(!Number.isFinite(old)||!Number.isFinite(Number(formula.total_cost)))throw new Error('数据库基础公式材料成本缺失，不能应用最新柜体材料规则');
  formula.material_cost=material.material_cost;
  formula.total_cost=round(Number(formula.total_cost)-old+material.material_cost,2);
  Object.assign(formula,{net_material_weight_kg:material.net_material_weight_kg,
    corrected_material_weight_kg:material.corrected_material_weight_kg,waste_factor:material.waste_factor,
    cabinet_material_version:material.data_version,material_details:material.material_details,
    cabinet_material_part_details:material.part_details});
  return {...result,formula_cost:formula};
}
