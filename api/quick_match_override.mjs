// Manual catalogue-size selection. Automatic matching and perimeter pricing
// remain owned by calc.match_quick_quote; never accept a client-supplied price.
import {randomUUID} from 'node:crypto';
import {ownerInsertSql} from './quote_access_scope.mjs';
import {sqlValue} from './attachment_service.mjs';
import {normalizeQuickDoorVariantInput} from './door_variant_rules.mjs';

const jsonSql = value => `${sqlValue(JSON.stringify(value))}::jsonb`;
const invalid = message => Object.assign(new Error(message), {statusCode: 422});
const uuid = value => {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value))
    throw invalid('报价行ID无效，请重新计算整柜');
  return value;
};
const dimension = (value, label) => {
  if (!['number', 'string'].includes(typeof value) || String(value).trim() === ''
      || !Number.isFinite(Number(value)) || Number(value) <= 0 || Number(value) > 1e6)
    throw invalid(`${label}必须为有效正数`);
  return Number(value);
};
export function checkedMatchSizes(value) {
  if (!Array.isArray(value) || !value.length || value.length > 20) throw invalid('请逐柜填写匹配尺寸');
  return value.map((row, index) => Object.fromEntries(['width_mm', 'depth_mm', 'height_mm']
    .map(key => [key, dimension(row?.[key], `柜体${index + 1} ${key}`)])));
}

export function quickMatchOverrideSql(environment, sizes) {
  const base = environment.quote_result;
  const count = Number(environment.ganged_cabinet_count || 1);
  if (!Number.isSafeInteger(count) || count < 1 || count > 20 || sizes.length !== count)
    throw invalid('匹配尺寸数量与原报价子柜数量不一致');
  const children = count > 1 ? environment.ganged_cabinets : [environment];
  if (!Array.isArray(children) || children.length !== count) throw invalid('原报价缺少子柜实际尺寸，请重新计算整柜');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(environment.quote_date || '')) throw invalid('原报价日期无效');
  const matched = base?.quick_quote?.matched_experience;
  const previous = count > 1 ? matched?.items : [matched];
  const queries = sizes.map((size, index) => {
    const source = children[index];
    const actual = ['width_mm', 'depth_mm', 'height_mm'].map(key => dimension(source[key], '原报价实际尺寸'));
    const fallback = normalizeQuickDoorVariantInput({...environment, ...source,
      single_door_count: 1, double_door_count: 0}).product_code;
    const product = previous?.[index]?.product_code || fallback;
    const perimeter = actual.map(sqlValue).join('+');
    return `SELECT ${index} AS cabinet_index,
      sqrt(power(${actual[0]}-qm.reference_width_mm,2)
        +power(${actual[1]}-qm.reference_depth_mm,2)+power(${actual[2]}-qm.reference_height_mm,2)) AS dimension_distance,
      ROUND(COALESCE(q.quick_base_price,q.quick_total_cost) * (${perimeter}) /
        (qm.reference_width_mm+qm.reference_height_mm+qm.reference_depth_mm),6) AS base_price,
      jsonb_build_object('quick_rule_id',q.quick_rule_id,'product_code',q.product_code,
        'model_code',q.model_code,'material_code',q.material_code,
        'reference_width_mm',qm.reference_width_mm,'reference_depth_mm',qm.reference_depth_mm,
        'reference_height_mm',qm.reference_height_mm,'quick_base_price',q.quick_base_price,
        'source_file',q.source_file,'source_sheet',q.source_sheet,'source_row_no',q.source_row_no,
        'manual_match',true) AS matched_experience
      FROM calc.match_quick_quote(${sqlValue(product)},NULL,${sqlValue(environment.material_code)},
        ${size.width_mm},${size.height_mm},${size.depth_mm},${sqlValue(environment.quote_date)}::date) qm
      JOIN calc.quick_quote_experience q USING(quick_rule_id)
      WHERE qm.reference_width_mm=${size.width_mm} AND qm.reference_depth_mm=${size.depth_mm}
        AND qm.reference_height_mm=${size.height_mm} AND qm.dimension_distance=0`;
  });
  return `SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY cabinet_index),'[]'::jsonb)
    FROM (${queries.join('\nUNION ALL\n')}) m;`;
}

export function createQuickMatchOverrideService({runPsql}) {
  const query = async sql => {
    const output = await runPsql(sql);
    return JSON.parse(output.trim().split(/\r?\n/).filter(Boolean).at(-1) || 'null');
  };
  return async input => {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw invalid('请提供报价行及匹配尺寸');
    const sourceId = uuid(input.quote_line_id), sizes = checkedMatchSizes(input.matched_sizes);
    const saved = await query(`SELECT jsonb_build_object('environment',l.environment_snapshot,'quote_id',l.quote_id)
      FROM calc.attachment_quote_line l WHERE quote_line_id=${sqlValue(sourceId)}::uuid;`);
    const environment = saved?.environment;
    const base = environment?.quote_result;
    if (!base?.quick_quote || !base?.formula_cost || !saved.quote_id) throw invalid('柜体报价快照不完整，请重新计算整柜');
    const count = Number(environment.ganged_cabinet_count || 1);
    const matches = await query(quickMatchOverrideSql(environment, sizes));
    if (!Array.isArray(matches) || matches.length !== count
        || matches.some((row, index) => row.cabinet_index !== index || row.base_price == null
          || !Number.isFinite(Number(row.base_price)) || Number(row.base_price) < 0))
      throw invalid('指定尺寸在该产品、材质和报价日期的有效目录中没有完全对应的价格，原报价未修改');
    const lineId = randomUUID();
    const quick = {...base.quick_quote,
      base_price: Math.round(matches.reduce((sum, row) => sum + Number(row.base_price), 0) * 1e6) / 1e6,
      match_method: count > 1 ? 'ganged_cabinet_sum' : 'manual_dimension',
      manual_match: true, manual_matched_sizes: sizes,
      dimension_distance: matches.reduce((sum, row) => sum + Number(row.dimension_distance || 0), 0),
      matched_experience: count > 1
        ? {ganged_cabinet_count: count, items: matches.map(row => row.matched_experience)}
        : matches[0].matched_experience};
    quick.total_cost = Math.round((quick.base_price + Number(quick.attachment_fee || 0)) * 1e6) / 1e6;
    const result = {...base, quote_line_id: lineId, quick_quote: quick};
    if (Array.isArray(base.ganged_cabinet_results)) {
      result.ganged_cabinet_results = base.ganged_cabinet_results.map((child, index) => ({...child,
        quick_quote: {...child.quick_quote, base_price: Number(matches[index].base_price),
          total_cost: Number(matches[index].base_price) + Number(child.quick_quote?.attachment_fee || 0),
          matched_experience: matches[index].matched_experience, match_method: 'manual_dimension'}}));
    }
    const next = {...environment, quote_id: saved.quote_id, quote_line_id: lineId, quote_result: result,
      quick_match_source_line_id: sourceId};
    // Append only the cabinet snapshot. Attachment rows are supplied by the
    // confirmed popup at document time, not replayed from an obsolete catalogue.
    // The source-line link retains the original audit trail without rewriting
    // or reinserting old selections through current catalogue validation.
    const persisted = await query(`BEGIN;
      SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='25s';
      ${ownerInsertSql('QUOTE_LINE',sqlValue(lineId))}
      INSERT INTO calc.attachment_quote_line(quote_line_id,quote_id,product_code,environment_snapshot)
      VALUES(${sqlValue(lineId)}::uuid,${sqlValue(saved.quote_id)},
        ${sqlValue(environment.product_code)},${jsonSql(next)});
      SELECT jsonb_build_object('quote_line_id',l.quote_line_id,
        'quick_quote',l.environment_snapshot->'quote_result'->'quick_quote')
      FROM calc.attachment_quote_line l WHERE l.quote_line_id=${sqlValue(lineId)}::uuid;
      COMMIT;`);
    if (!persisted?.quote_line_id || !persisted?.quick_quote) throw new Error('手动匹配报价快照保存失败');
    return {...persisted, source_quote_line_id: sourceId, attachment_contract: 2};
  };
}
