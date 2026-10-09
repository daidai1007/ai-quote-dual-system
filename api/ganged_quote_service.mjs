// Deliberately request-scoped: new quotations always read current rules/prices.
// Share identical reads (and in-flight reads) between children, never writes or
// the SELECT which calls the mutating dual-quotation database function.
export function createBatchReadExecutor(runPsql, onReuse = () => {}) {
  const reads = new Map();
  return (sql, encoding = 'UTF8') => {
    const readOnly = /^\s*SELECT\b/i.test(sql)
      && !/\b(?:INSERT|UPDATE|DELETE|BEGIN|COMMIT|ROLLBACK|calculate_dual_quote)\b/i.test(sql);
    if (!readOnly) return runPsql(sql, encoding);
    const key = `${encoding}\0${sql}`;
    if (!reads.has(key)) {
      const pending = Promise.resolve().then(() => runPsql(sql, encoding));
      reads.set(key, pending);
      pending.catch(() => { if (reads.get(key) === pending) reads.delete(key); });
    } else onReuse();
    return reads.get(key);
  };
}

const sum = (results, section, key) => {
  const values = results.map(result => result[section]?.[key]);
  return values.some(value => value == null || !Number.isFinite(Number(value)))
    ? null : values.reduce((total, value) => total + Number(value), 0);
};
const optionalNumber = (value, name) => {
  if (value == null) return null;
  if (!Number.isFinite(Number(value)) || Number(value) < 0) throw new Error(`${name} must be non-negative number`);
  return Number(value);
};

export function validateGangedBatch(input, validateChild) {
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || !Array.isArray(input.cabinets) || input.cabinets.length < 2 || input.cabinets.length > 20)
    throw new Error('并柜批量计算 requires 2 to 20 cabinets');
  // Validate the entire request before any child can create a database result.
  const cabinets = input.cabinets.map(validateChild);
  if (new Set(cabinets.map(child => child.quote_id)).size !== cabinets.length)
    throw new Error('并柜子柜 quote_id must be unique');
  if (cabinets.some(child => child.attachments?.length))
    throw new Error('并柜附件 must be provided together in attachment_payload, not per cabinet');
  const attachmentTotal = Number(input.attachment_total ?? 0);
  if (!Number.isFinite(attachmentTotal)) throw new Error('attachment_total must be numeric');
  const areaTotal = optionalNumber(input.area_total, 'area_total');
  const attachment = input.attachment_payload;
  if (attachment != null && (typeof attachment !== 'object' || Array.isArray(attachment)))
    throw new Error('attachment_payload must be an object');
  if (attachment && (Number(attachment.ganged_cabinet_count) !== cabinets.length
      || !Array.isArray(attachment.ganged_cabinets) || attachment.ganged_cabinets.length !== cabinets.length))
    throw new Error('并柜附件子柜数量与批量计算不一致');
  if (attachment && attachment.ganged_cabinets.some((row, index) =>
    ['width_mm', 'height_mm', 'depth_mm'].some(key => Number(row[key]) !== Number(cabinets[index][key]))))
    throw new Error('并柜附件子柜尺寸与批量计算不一致');
  return {cabinets, attachmentTotal, areaTotal, attachment};
}

export async function calculateGangedBatch(input, {calculateChild, snapshotGanged, concurrency = 2, onProgress = () => {}}) {
  const {cabinets, attachmentTotal, areaTotal, attachment} = input;
  const results = new Array(cabinets.length);
  let next = 0, completed = 0, failed = false;
  onProgress('cabinet', {completed: 0, total: cabinets.length});
  // Bounded parallelism avoids opening a connection for every cabinet at once.
  // Wait for already-running children on error, and never publish a partial sum.
  await Promise.all(Array.from({length: Math.min(concurrency, cabinets.length)}, async () => {
    while (!failed && next < cabinets.length) {
      const index = next++;
      try {
        const result = await calculateChild(cabinets[index]);
        if (!result?.formula_cost || !result?.quick_quote) throw new Error('子柜报价结果无效');
        results[index] = result;
        onProgress('cabinet', {completed: ++completed, total: cabinets.length, child_index: index + 1});
      } catch (error) { failed = true; results[index] = {error}; }
    }
  }));
  const error = results.find(result => result?.error)?.error;
  if (error) throw error;
  const formula = Object.fromEntries(['material_cost', 'auxiliary_cost', 'labor_cost', 'spray_cost', 'management_fee',
    'net_material_weight_kg', 'corrected_material_weight_kg'].map(key => [key, sum(results, 'formula_cost', key)]));
  const baseTotal = sum(results, 'formula_cost', 'total_cost');
  formula.attachment_fee = attachmentTotal;
  formula.product_area_m2 = areaTotal ?? sum(results, 'formula_cost', 'product_area_m2');
  formula.total_cost = baseTotal == null ? null
    : baseTotal - (sum(results, 'formula_cost', 'attachment_fee') ?? 0) + attachmentTotal;
  formula.ganged_cabinet_costs = results.map((result, index) => ({
    cabinet_index: index + 1, ...Object.fromEntries(['model_code', 'product_code', 'width_mm', 'depth_mm', 'height_mm']
      .map(key => [key, cabinets[index][key]])), formula_cost: result.formula_cost,
  }));
  const quickBase = sum(results, 'quick_quote', 'base_price');
  const aggregate = {
    quote_id: cabinets[0].quote_id, formula_cost: formula,
    quick_quote: {base_price: quickBase, attachment_fee: attachmentTotal,
      total_cost: quickBase == null ? null : quickBase + attachmentTotal,
      match_method: 'ganged_cabinet_sum',
      dimension_distance: results.reduce((total, result) => total + Number(result.quick_quote.dimension_distance || 0), 0),
      matched_experience: {ganged_cabinet_count: results.length, items: results.map(result => result.quick_quote.matched_experience ?? null)}},
    risk_flags: results.flatMap(result => result.risk_flags || []), ganged_cabinet_results: results,
    ganged_weight_kg: formula.corrected_material_weight_kg, ganged_area_m2: formula.product_area_m2,
    ganged_batch_contract: 1,
  };
  // Only the server-produced base is used; catalog attachments are calculated
  // and snapshotted once, retaining each independent fixed-base child index.
  if (!attachment) return aggregate;
  onProgress('attachments', {completed: cabinets.length, total: cabinets.length});
  return snapshotGanged({...attachment, quote_id: aggregate.quote_id,
    ganged_cabinet_inputs: cabinets, base_result: aggregate});
}
