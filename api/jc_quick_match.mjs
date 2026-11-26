import {isJcProduct, selectedJcProfile} from './jc_profile.mjs';

const sql = value => `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const dimension = value => {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error('JC 匹配尺寸必须是有效正数');
  return number;
};
export function jcQuickMatchSql(input) {
  const profile = selectedJcProfile(input);
  if (!isJcProduct(input.product_code) || !profile) return null;
  const w = dimension(input.width_mm), h = dimension(input.height_mm), d = dimension(input.depth_mm);
  const date = String(input.quote_date || '');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('JC 报价日期无效');
  // Filter the existing catalogue before width/perimeter ranking. Do not call
  // the unrestricted matcher and filter its single winner afterwards.
  return `(SELECT p.quick_rule_id,p.product_code,p.model_code,p.material_code,
    p.reference_width_mm,p.reference_height_mm,p.reference_depth_mm,
    ROUND(p.quick_material_cost*p.ratio,6) AS quick_material_cost,p.quick_auxiliary_cost,
    ROUND(p.quick_labor_cost*p.ratio,6) AS quick_labor_cost,p.quick_attachment_fee,
    ROUND(p.quick_spray_cost*p.ratio,6) AS quick_spray_cost,
    ROUND(p.quick_management_fee*p.ratio,6) AS quick_management_fee,
    ROUND(COALESCE(p.quick_base_price,p.quick_total_cost)*p.ratio,6) AS quick_total_cost,
    CASE WHEN p.distance=0 THEN 'exact_dimension' WHEN p.range_rank=0 THEN 'dimension_range'
      ELSE 'nearest_dimension' END AS match_method,p.distance AS dimension_distance
    FROM (SELECT q.*,
      (${w}+${h}+${d})/(q.reference_width_mm+q.reference_height_mm+q.reference_depth_mm) AS ratio,
      abs(${w}-q.reference_width_mm) AS width_distance,
      abs((${w}+${h}+${d})-(q.reference_width_mm+q.reference_height_mm+q.reference_depth_mm)) AS perimeter_distance,
      abs(2*(${w}*${h}+${w}*${d}+${h}*${d})-2*(q.reference_width_mm*q.reference_height_mm+q.reference_width_mm*q.reference_depth_mm+q.reference_height_mm*q.reference_depth_mm)) AS area_distance,
      sqrt(power(${w}-q.reference_width_mm,2)+power(${h}-q.reference_height_mm,2)+power(${d}-q.reference_depth_mm,2)) AS distance,
      CASE WHEN ${w} BETWEEN COALESCE(q.min_width_mm,q.reference_width_mm) AND COALESCE(q.max_width_mm,q.reference_width_mm)
        AND ${h} BETWEEN COALESCE(q.min_height_mm,q.reference_height_mm) AND COALESCE(q.max_height_mm,q.reference_height_mm)
        AND ${d} BETWEEN COALESCE(q.min_depth_mm,q.reference_depth_mm) AND COALESCE(q.max_depth_mm,q.reference_depth_mm)
        THEN 0 ELSE 1 END AS range_rank
      FROM calc.quick_quote_experience q
      WHERE q.product_code='JC_EXP' AND q.material_code=${sql(input.material_code)} AND q.is_active=TRUE
        AND q.effective_from<=${sql(date)}::date AND (q.effective_to IS NULL OR ${sql(date)}::date<q.effective_to)
        AND (CASE WHEN upper(trim(q.model_code)) ~ '^JC[0-9]+-1$' THEN 'STANDARD'
          WHEN upper(trim(q.model_code)) ~ '^JC[0-9]+-2$' THEN 'LUXURY'
          WHEN upper(COALESCE(q.source_sheet,'')) ~ ${sql('豪华|LUXURY|DELUXE')} THEN 'LUXURY'
          WHEN upper(COALESCE(q.source_sheet,'')) ~ ${sql('标配|STANDARD')} THEN 'STANDARD'
          ELSE NULL END)=${sql(profile)}) p
    ORDER BY p.width_distance,p.perimeter_distance,p.area_distance,p.distance,p.range_rank,p.effective_from DESC,p.quick_rule_id DESC LIMIT 1)`;
}
export function assertJcQuickMatch(input, result) {
  if (isJcProduct(input.product_code) && selectedJcProfile(input)
      && result?.quick_quote?.base_price == null) {
    const type = selectedJcProfile(input) === 'LUXURY' ? '豪华型' : '标配型';
    throw Object.assign(new Error(`JC ${type}没有可用的同型面价记录，请核对价格目录；不会借用另一配置的面价。`), {statusCode:422});
  }
}
