import { evaluateFormula, formulaVariables, round } from './attachment_formula.mjs';

export const PRODUCT_CODES = Object.freeze({
  JS: ['JS', 'JS_SINGLE', 'JS_DOUBLE'], JP: ['JP', 'JP_SINGLE', 'JP_DOUBLE'],
  JA: ['JA', 'JA_SINGLE'], JE: ['JE', 'JE_SINGLE', 'JE_DOUBLE'], JM: ['JM'], JK: ['JK'],
  JP超宽: ['JP_WIDE_EXP'], JS超宽: ['JS_WIDE_EXP'],
});
export const COMPONENTS = Object.freeze({ weight_kg: '材料重量', material_cost: '材料成本', spray_area_m2: '喷塑面积', spray_cost: '喷塑成本', auxiliary_cost: '辅材', labor_cost: '人工' });
const AUTO = { 宽度: 'width_mm', 高度: 'height_mm', 深度: 'depth_mm', 材质密度: 'density_g_cm3', 材质单价: 'material_unit_price', 喷塑单价: 'spray_unit_price' };
export const MATERIAL_CODES = Object.freeze(['SECC', 'SUS304', 'SUS316']);
export function selectRule(rules, productCode, materialCode) {
  const productRules = rules.filter(r => !r.products?.length || r.products.includes(productCode));
  if (!productRules.length) return null;
  if (productRules.some(r => r.materials?.length) && !MATERIAL_CODES.includes(materialCode)) {
    throw new Error('材质适用规则需要有效材质：SECC、SUS304或SUS316');
  }
  const materialRules = productRules.filter(r => !r.materials?.length || r.materials.includes(materialCode));
  if (!materialRules.length) throw new Error(`当前材质 ${materialCode} 缺少附件成本规则`);
  const specific = materialRules.filter(r => r.products?.includes(productCode));
  const applicable = specific.length ? specific : materialRules.filter(r => !r.products?.length);
  if (applicable.length > 1) throw new Error(`同级成本规则冲突：${applicable.map(r => r.rule_id).join(', ')}`);
  return applicable[0] || null;
}
export function requiredParameters(rule) {
  if (!rule || rule.method === 'FIXED') return [];
  const results = new Set(Object.values(COMPONENTS));
  const names = new Set();
  for (const expression of Object.values(rule.formulas || {})) {
    if (expression !== null && expression !== undefined && expression !== '') {
      for (const name of formulaVariables(expression)) if (!results.has(name)) names.add(name);
    }
  }
  return [...names].map(name => ({ name, source: AUTO[name] ? 'ENVIRONMENT' : 'MANUAL', unit: name === '材质密度' ? 'g/cm³' : name === '材质单价' ? '元/kg' : name === '喷塑单价' ? '元/m²' : 'mm', required: true }));
}
const number = (v, label, positive = false) => {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean' || !Number.isFinite(Number(v)) || (positive ? Number(v) <= 0 : Number(v) < 0)) throw new Error(`${label}必须是${positive ? '正' : '非负'}数`);
  return Number(v);
};
export function calculateAttachment(selection, catalog, rules, environment) {
  const result = {
    attachment_price_id: catalog.attachment_price_id, catalog_version: catalog.data_version,
    quote_line_id: environment.quote_line_id, product_code: environment.product_code,
    category_level1: catalog.category_level1, category_level2: catalog.category_level2,
    item_name: catalog.item_name, model_code: catalog.model_code, color: catalog.color,
    unit: catalog.unit, quantity: selection.quantity, attachment_price_sign: selection.attachment_price_sign ?? 1,
    manual_inputs: structuredClone(selection.manual_inputs || {}), environment: structuredClone(environment),
    status: 'ERROR', formula_amount: null, formula_unit_cost: null, required_parameters: [],
    source_sheet: catalog.source_sheet, source_row_no: catalog.source_row_no,
  };
  try {
    const quantity = number(selection.quantity ?? 1, '附件数量', true);
    const sign = Number(selection.attachment_price_sign ?? 1);
    if (![1, -1].includes(sign)) throw new Error('加减符号只能为1或-1');
    // The same existing installation-board scope, checked against authoritative catalog data.
    const identity = [catalog.category_level1, catalog.category_level2, catalog.item_name, catalog.model_code].join(' ');
    if (sign === -1 && (!identity.includes('安装板') || identity.includes('安装板单发'))) throw new Error('只有安装板允许扣减');
    const facePrice = number(catalog.price, '面价');
    Object.assign(result, { quantity, attachment_price_sign: sign, face_price: facePrice, matched_price: facePrice, quick_amount: round(quantity * facePrice * sign) });
    const rule = selectRule(rules, environment.product_code, environment.material_code);
    if (!rule) { result.status = 'QUICK_ONLY'; result.status_text = '仅快速报价'; return result; }
    Object.assign(result, { rule_id: rule.rule_id, rule_version: rule.data_version, rule_materials: rule.materials || [], auxiliary_list: rule.auxiliary_list ?? '', rule_source_row: rule.source_row_no, calculation_notes: rule.notes || '', formulas: rule.formulas });
    result.required_parameters = requiredParameters(rule);
    if (rule.issues?.length) throw new Error(`源规则待确认：${rule.issues.join('；')}`);
    if (rule.method === 'FIXED') {
      result.formula_unit_cost = number(rule.fixed_cost, '固定成本');
      result.status = 'FIXED';
    } else {
      const variables = {};
      for (const [name, key] of Object.entries(AUTO)) variables[name] = environment[key];
      for (const parameter of result.required_parameters.filter(p => p.source === 'MANUAL')) variables[parameter.name] = number(result.manual_inputs[parameter.name], `人工尺寸 ${parameter.name}`, true);
      const remaining = new Set(Object.keys(COMPONENTS));
      while (remaining.size) {
        let progressed = false;
        for (const key of remaining) {
          const expression = rule.formulas?.[key];
          if (expression === null || expression === undefined || expression === '') {
            // A non-metal material-price expression (glass) has no weight, explicitly recorded.
            if (key === 'weight_kg' && rule.weight_not_applicable) { result[key] = null; remaining.delete(key); progressed = true; continue; }
            throw new Error(`源规则缺少${COMPONENTS[key]}`);
          }
          if (key === 'spray_cost' && environment.coating_type === '不喷塑') {
            variables[COMPONENTS[key]] = result[key] = 0; remaining.delete(key); progressed = true; continue;
          }
          const dependencies = formulaVariables(expression);
          if (dependencies.some(name => Object.values(COMPONENTS).includes(name) && variables[name] === undefined)) continue;
          // No spray price is needed when the actual area is zero.
          if (key === 'spray_cost' && variables.喷塑面积 === 0) {
            variables[COMPONENTS[key]] = result[key] = 0;
          } else {
            const value = evaluateFormula(expression, variables);
            if (value < 0) throw new Error(`${COMPONENTS[key]}计算为负数，请检查尺寸或公式`);
            variables[COMPONENTS[key]] = result[key] = value;
          }
          remaining.delete(key); progressed = true;
        }
        if (!progressed) throw new Error(`成本公式循环或缺少计算结果：${[...remaining].join(', ')}`);
      }
      // The installed snapshot guard compares costs at 8 decimal places.
      // Normalize monetary components before adding: binary tails around an
      // exact half-step must not make the DB reject an otherwise valid quote.
      for (const key of ['material_cost','spray_cost','auxiliary_cost','labor_cost']) result[key]=round(result[key],8);
      result.formula_unit_cost = round(result.material_cost + result.spray_cost + result.auxiliary_cost + result.labor_cost,8);
      result.status = 'CALCULATED';
    }
    result.formula_amount = round(quantity * result.formula_unit_cost * sign);
    result.status_text = result.status === 'FIXED' ? '固定成本' : '已计算';
  } catch (error) { result.status = 'ERROR'; result.error = error.message; result.status_text = error.message; result.formula_amount = null; result.formula_unit_cost = null; }
  return result;
}
export function attachmentTotals(rows) {
  const errors = rows.filter(r => r.status === 'ERROR');
  return { quick_attachment_fee: rows.some(r => r.quick_amount == null) ? null : round(rows.reduce((sum, r) => sum + r.quick_amount, 0)), formula_attachment_fee: errors.length ? null : round(rows.reduce((sum, r) => sum + (r.status === 'QUICK_ONLY' ? 0 : number(r.formula_amount == null ? null : Math.abs(r.formula_amount), '公式金额') * (r.formula_amount < 0 ? -1 : 1)), 0)), errors };
}
