import fs from 'node:fs/promises';
import path from 'node:path';
import { PRODUCT_CODES, MATERIAL_CODES, requiredParameters, selectRule } from '../api/attachment_cost.mjs';
import { parseFormula } from '../api/attachment_formula.mjs';

const [source, directory] = process.argv.slice(2);
if (!source || !directory) throw new Error('usage: node scripts/build_attachment_import.mjs raw.json output-directory');
const raw = JSON.parse(await fs.readFile(source, 'utf8'));
// Increment the conversion revision when confirmed mappings/overrides change.
const version = `xlsx-${raw.sha256.slice(0, 16)}-r4`;
const report = { source_sha256: raw.sha256, data_version: version, confirmations: ['M3 按乘以2.5；用户2026-09-10确认', '同一级分类、同名连续行继承空二级分类；用户2026-09-10确认'], transformations: [], issues: [], quick_only: [], unmapped_rules: [], mappings: [] };
const normalize = value => String(value ?? '').trim().replaceAll('（', '(').replaceAll('）', ')');
report.pending_mapping = [];
report.confirmations.push('公式法第59行空辅材金额按0；用户2026-09-10明确确认');
report.confirmations.push('2026-09-11：通风顶罩重量按(260+宽度-10)*(260+深度-10)*0.000001*材质密度*1.5；相邻括号为相乘');
report.confirmations.push('2026-09-11：公式表型号中的SECC/SUS304/SUS316代表适用材质，按程序当前材质匹配；快速面价适用于所有型号且不随材质变化');
report.confirmations.push('2026-09-11：搭扣锁快速103→公式33（3元）、铜排快速226→公式62（8.1元）明确对应；前三项门变形快速空二级分类补为公式表分类');
report.result_aliases = { 材料质量: '材料重量' };
report.units = { 材料重量: 'kg（源公式已含密度和换算，不再乘密度）', 材质密度: 'g/cm³', 喷塑面积: 'm²', 材质单价: '元/kg', 喷塑单价: '元/m²', 人工尺寸: 'mm' };
const split = value => normalize(value).split(/[,，、\\/]+/).map(x => x.trim()).filter(Boolean);
function rows(sheet) {
  let previous;
  return raw.sheets[sheet].map(row => {
    const values = { ...row.values };
    if (!normalize(values.二级分类) && previous?.一级分类 === values.一级分类 && previous?.名称 === values.名称 && previous.二级分类) {
      values.二级分类 = previous.二级分类;
      report.transformations.push({ sheet, row: row.source_row_no, field: '二级分类', before: row.values.二级分类, after: values.二级分类, reason: '已确认的同名连续行继承' });
    }
    previous = values;
    return { ...row, values };
  });
}
const common = (r, sheet) => ({ category_level1: normalize(r.values.一级分类), category_level2: normalize(r.values.二级分类), item_name: normalize(r.values.名称), model_code: normalize(r.values.型号), color: normalize(r.values.颜色), unit: normalize(r.values.单位), source_file: raw.source_file, source_sheet: sheet, source_row_no: r.source_row_no, data_version: version });
const catalog = rows('快速报价').map(r => ({ ...common(r, '快速报价'), import_key: `Q${r.source_row_no}`, price: r.values.面价, width_mm: r.values.宽度 || null, height_mm: r.values.高度 || null, depth_mm: r.values.深度 || null }));
const confirmedCategories = new Map([[103, 'JA、JE箱小方锁改为搭扣锁(1把)'], [104, 'JA、JE顶部加吊环(2个)'], [105, '平面锁改为MS830锁']]);
for (const item of catalog) {
  const name = confirmedCategories.get(item.source_row_no);
  if (name && item.category_level1 === '门变形' && item.item_name === name && !item.category_level2) {
    report.transformations.push({ sheet: '快速报价', row: item.source_row_no, field: '二级分类', before: '', after: name, reason: '2026-09-11用户明确确认此三项分类补齐，仅限已确认源行身份' });
    item.category_level2 = name;
  }
}
const columns = { weight_kg: '材料重量', material_cost: '材料成本', spray_area_m2: '喷塑面积', spray_cost: '喷塑成本', auxiliary_cost: '辅材', labor_cost: '人工' };
const rules = rows('公式法报价').map(r => {
  const v = r.values;
  const rule = { ...common(r, '公式法报价'), rule_id: `R${r.source_row_no}`, import_key: `R${r.source_row_no}`, method: v.备注 === '固定成本' ? 'FIXED' : 'CALCULATED', fixed_cost: v.备注 === '固定成本' ? v.成本 : null, products: [], product_text: v.产品 ?? '', formulas: {}, auxiliary_list: v.辅材清单 ?? '', issues: [], raw_values: r.values };
  const modelTokens = split(v.型号);
  rule.materials = modelTokens.length && modelTokens.every(code => MATERIAL_CODES.includes(code)) ? [...new Set(modelTokens)] : [];
  rule.model_semantics = rule.materials.length ? 'MATERIAL' : 'MODEL';
  if ((r.source_row_no === 33 && rule.category_level1 === '门变形' && rule.item_name === 'JA、JE箱小方锁改为搭扣锁(1把)' && rule.model_code === '小方锁MS813(锌合金)')
      || (r.source_row_no === 62 && rule.category_level1 === '其他附件' && rule.item_name === '铜排' && rule.model_code === '十字螺丝铜排')) {
    rule.model_semantics = 'DESCRIPTION';
    report.transformations.push({ sheet: '公式法报价', row: r.source_row_no, field: '型号语义', before: v.型号, after: '保留部件说明，绑定已确认同名快速附件', reason: '2026-09-11用户明确确认搭扣锁及铜排对应关系' });
  }
  if (rule.materials.length) report.transformations.push({ sheet: '公式法报价', row: r.source_row_no, field: '型号语义', before: v.型号, after: { materials: rule.materials }, reason: '用户确认型号中的材质代码是材质适用条件；保留型号原文，不当作产品列' });
  for (const code of split(v.产品)) {
    if (!PRODUCT_CODES[code]) rule.issues.push(`未知产品代码：${code}`);
    else rule.products.push(...PRODUCT_CODES[code]);
  }
  rule.products = [...new Set(rule.products)];
  if (rule.method === 'FIXED') {
    if (typeof rule.fixed_cost !== 'number' || rule.fixed_cost < 0) rule.issues.push('固定成本标记与成本值冲突');
  } else {
    if (normalize(v.成本) !== '材料成本+喷塑成本+辅材+人工') rule.issues.push('单位成本组成与已确认求和规则不一致');
    try { parseFormula(v.成本); } catch (error) { rule.issues.push(`成本：${error.message}`); }
    for (const [key, label] of Object.entries(columns)) {
      let expression = v[label] ?? null;
      if (r.source_row_no === 49 && key === 'weight_kg' && rule.item_name === '通风顶罩') {
        const previous = '（260+宽度-10）*（通风顶罩）*（260+深度-10）*0.000000001*材质密度*1.5';
        const confirmed = '(260+宽度-10)*(260+深度-10)*0.000001*材质密度*1.5';
        if (expression === previous || normalize(expression) === confirmed) {
          if (expression !== confirmed) report.transformations.push({ sheet: '公式法报价', cell: 'M49', before: expression, after: confirmed, reason: '2026-09-11用户确认的完整重量公式' });
          expression = confirmed;
        } else rule.issues.push('M49源内容不同于已审查原文和已确认公式，需重新核验');
      }
      if (r.source_row_no === 59 && key === 'auxiliary_cost' && expression === null && rule.item_name === '外部眉头(柜体顶板上方)') {
        expression = 0;
        report.transformations.push({ sheet: '公式法报价', cell: 'Q59', before: null, after: 0, reason: '用户本次明确确认辅材金额为0' });
      }
      if (r.source_row_no === 3 && key === 'weight_kg') {
        const expected = '（高度-72）*（宽度-26.6）*2.5*材质密度*0.000001*';
        if (expression === expected) {
          expression = '(高度-72)*(宽度-26.6)*2.5*材质密度*0.000001';
          report.transformations.push({ sheet: '公式法报价', cell: 'M3', before: expected, after: expression, reason: '用户本次明确确认' });
        }
      }
      if (typeof expression === 'string' && expression.startsWith('=')) {
        const before = expression;
        // Only same-row H/I/J references whose headers explicitly mean W/H/D.
        expression = expression.replace(/\$?([A-Z]+)\$?(\d+)/g, (cell, col, row) => {
          const variable = { H: '宽度', I: '高度', J: '深度' }[col];
          if (Number(row) !== r.source_row_no || !variable) { rule.issues.push(`未支持的单元格引用：${cell}`); return cell; }
          return variable;
        });
        if (before !== expression) report.transformations.push({ sheet: '公式法报价', row: r.source_row_no, field: label, before, after: expression, reason: '同一行尺寸列标题明确映射H/I/J→宽度/高度/深度' });
      }
      rule.formulas[key] = expression;
      if (expression == null) {
        if (key === 'weight_kg' && rule.item_name === '玻璃门') { rule.weight_not_applicable = true; rule.notes = '玻璃按Excel面积×55计算材料成本，无金属重量；55为源规则固定面价参数。'; }
        else rule.issues.push(`缺少${label}，不能默认0`);
      } else try { parseFormula(expression); } catch (error) { rule.issues.push(`${label}：${error.message}`); }
    }
    try { rule.parameters = requiredParameters(rule); } catch (error) { rule.issues.push(error.message); }
  }
  rule.parameters ||= [];
  rule.raw_values = raw.sheets['公式法报价'].find(original => original.source_row_no === r.source_row_no).values;
  return rule;
});
function identity(row) { return [row.category_level1, row.category_level2, row.item_name].join('\u001f'); }
const bindings = [];
for (const item of catalog) {
  if (typeof item.price !== 'number' || !Number.isFinite(item.price) || item.price < 0) report.issues.push({ quick_row: item.source_row_no, message: '面价不是非负数值' });
  const candidates = rules.filter(rule => identity(item) === identity(rule)
    && (rule.materials.length || rule.model_semantics === 'DESCRIPTION' || !rule.model_code || rule.model_code === '所有型号' || split(rule.model_code).some(model => split(item.model_code).includes(model)))
    && (!rule.color || rule.color === item.color));
  for (const rule of candidates) bindings.push({ attachment_key: item.import_key, rule_key: rule.import_key });
  report.mappings.push({ quick_row: item.source_row_no, identity: [item.category_level1, item.category_level2, item.item_name], model: item.model_code, formula_rows: candidates.map(r => r.source_row_no) });
  if (!candidates.length) {
    const sameName = rules.filter(rule => rule.item_name === item.item_name);
    (sameName.length ? report.pending_mapping : report.quick_only).push({ quick_row: item.source_row_no, name: item.item_name, category: [item.category_level1, item.category_level2], model: item.model_code });
    if (sameName.length) report.issues.push({ quick_row: item.source_row_no, message: '存在同名但分类/型号/颜色不匹配规则，须审查映射，不能擅自跨分类合并', rule_rows: sameName.map(r => r.source_row_no) });
  }
  for (const product of ['', ...new Set(candidates.flatMap(r => r.products))]) {
    for (const material of MATERIAL_CODES) {
      try { selectRule(candidates, product, material); }
      catch (error) { report.issues.push({ quick_row: item.source_row_no, product, material, message: error.message }); }
    }
  }
}
for (const rule of rules) {
  if (!bindings.some(b => b.rule_key === rule.import_key)) report.unmapped_rules.push(rule.source_row_no);
  if (rule.issues.length) report.issues.push({ rule_row: rule.source_row_no, messages: rule.issues });
}
report.counts = { quick: catalog.length, rules: rules.length, fixed: rules.filter(r => r.method === 'FIXED').length, calculated: rules.filter(r => r.method === 'CALCULATED').length, bindings: bindings.length, quick_only: report.quick_only.length, unmapped_rules: report.unmapped_rules.length, blockers: report.issues.length };
if (report.unmapped_rules.length) report.issues.push({ message: '成本规则未映射到任何快速附件', rows: report.unmapped_rules });
report.counts.blockers = report.issues.length;
report.counts.pending_mapping = report.pending_mapping.length;
const bundle = { data_version: version, source_sha256: raw.sha256, catalog, rules, bindings, report };
await fs.mkdir(directory, { recursive: true });
await fs.writeFile(path.join(directory, 'attachment-bundle.json'), JSON.stringify(bundle, null, 2));
await fs.writeFile(path.join(directory, 'mapping-report.json'), JSON.stringify(report, null, 2));
const hex = Buffer.from(JSON.stringify(bundle)).toString('hex');
await fs.writeFile(path.join(directory, '03-stage-and-switch.sql'), `-- Generated only from the inspected workbook; blocking issues fail inside the transaction.\n\\set ON_ERROR_STOP on\nBEGIN;\nSET LOCAL lock_timeout = '5s';\nSET LOCAL statement_timeout = '120s';\nCREATE TEMP TABLE attachment_import_stage(payload jsonb) ON COMMIT DROP;\nINSERT INTO attachment_import_stage VALUES (convert_from(decode('${hex}', 'hex'),'UTF8')::jsonb);\nSELECT calc.activate_attachment_catalog_v2(payload) FROM attachment_import_stage;\nCOMMIT;\n`);
await fs.writeFile(path.join(directory, '03-stage-only.sql'), `-- Import a validated STAGED catalog only. Does not switch the active catalog.\n-- Version: ${version}\n-- Source SHA-256: ${raw.sha256}\n\\set ON_ERROR_STOP on\nBEGIN;\nSET LOCAL lock_timeout = '5s';\nSET LOCAL statement_timeout = '120s';\nCREATE TEMP TABLE attachment_import_stage(payload jsonb) ON COMMIT DROP;\nINSERT INTO attachment_import_stage VALUES (convert_from(decode('${hex}', 'hex'),'UTF8')::jsonb);\nSELECT calc.stage_attachment_catalog_v2(payload) FROM attachment_import_stage;\nCOMMIT;\n`);
// Retire first and import next in ONE transaction: any import error restores the old active catalog.
// The caller must explicitly confirm application compatibility in this same session.
await fs.writeFile(path.join(directory, '03-replace-active-catalog.sql'), `-- Logical clearance only: preserve all catalog IDs, classifications and quotation history.\n-- Requires verified V2 API/client compatibility. Do not run during the database-only phase.\n-- Version: ${version}\n-- Source SHA-256: ${raw.sha256}\n\\set ON_ERROR_STOP on\nBEGIN;\nSET LOCAL lock_timeout = '5s';\nSET LOCAL statement_timeout = '120s';\nCREATE TEMP TABLE attachment_import_stage(payload jsonb) ON COMMIT DROP;\nINSERT INTO attachment_import_stage VALUES (convert_from(decode('${hex}', 'hex'),'UTF8')::jsonb);\nDO $$ BEGIN\n  IF current_setting('calc.attachment_v2_api_ready',true) IS DISTINCT FROM 'on' THEN\n    RAISE EXCEPTION 'API/client V2 compatibility must be verified before clearing the active catalog';\n  END IF;\n  PERFORM pg_advisory_xact_lock(hashtext('calc.attachment_catalog_v2'));\n  IF EXISTS(SELECT 1 FROM calc.attachment_catalog_version WHERE data_version=(SELECT payload->>'data_version' FROM attachment_import_stage)) THEN\n    RAISE EXCEPTION 'Version already exists; inspect it and use the staged-version switch procedure instead';\n  END IF;\nEND $$;\nLOCK TABLE calc.attachment_price IN SHARE ROW EXCLUSIVE MODE;\nUPDATE calc.attachment_price SET is_active=false WHERE is_active;\nSELECT calc.activate_attachment_catalog_v2(payload) FROM attachment_import_stage;\nDO $$ DECLARE v text; expected integer; BEGIN\n  SELECT payload->>'data_version',(payload#>>'{report,counts,quick}')::integer INTO v,expected FROM attachment_import_stage;\n  IF (SELECT count(*) FROM calc.attachment_price WHERE is_active AND data_version=v)<>expected\n    OR EXISTS(SELECT 1 FROM calc.attachment_price WHERE is_active AND data_version IS DISTINCT FROM v) THEN\n    RAISE EXCEPTION 'Active catalog acceptance failed';\n  END IF;\nEND $$;\nCOMMIT;\n`);
console.log(JSON.stringify(report.counts));
