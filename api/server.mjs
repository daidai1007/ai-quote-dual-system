import http from 'node:http';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { normalizeCatalogAttachment } from './attachment_catalog_rules.mjs';
import { attachmentCatalogSql, decodeAttachmentCatalog } from './attachment_catalog_query.mjs';
import { normalizeDoorVariantInput, normalizeQuickDoorVariantInput } from './door_variant_rules.mjs';
import { historyPriceMatchSql } from './history_price_query.mjs';
import { buildPsqlArgs, resolveRuntimeConfig } from './runtime_config.mjs';

const RUNTIME_CONFIG = resolveRuntimeConfig();
const PORT = RUNTIME_CONFIG.port;
const HOST = RUNTIME_CONFIG.host;
const API_KEY = RUNTIME_CONFIG.apiKey;
const PSQL_PATH = RUNTIME_CONFIG.psqlPath;
const API_BUILD = '2026-08-26-signed-attachments-v1';
const DEPLOYMENT_BUILD = '20260826-signed-attachments-v4';
const DEFAULT_COATING_TYPE = '橘纹';
const MAX_REQUEST_BYTES = 16 * 1024 * 1024;
const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const json = (res, status, body) => {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
  });
  res.end(text);
};

const sqlText = (value) => {
  if (value === null || value === undefined) return 'NULL';
  return `'${String(value).replaceAll("'", "''")}'`;
};

// Send text to PostgreSQL as ASCII-only UTF-8 hex.  This avoids both the
// Windows console code page and U& literal collisions with JSON backslashes
// such as \" and \n in quotation notes.
const sqlUnicodeText = (value) => {
  if (value === null || value === undefined) return 'NULL';
  const hex = Buffer.from(String(value), 'utf8').toString('hex');
  return `convert_from(decode('${hex}', 'hex'), 'UTF8')`;
};

// OCR and imported spreadsheets can occasionally contain NUL characters or
// decomposed Unicode. PostgreSQL text/jsonb rejects NUL outright, so clean
// every incoming string once at the HTTP boundary and keep the rest of the
// application consistently UTF-8/NFC.
const sanitizeJsonValue = (value) => {
  if (typeof value === 'string') return value.replaceAll('\u0000', '').normalize('NFC');
  if (Array.isArray(value)) return value.map(sanitizeJsonValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitizeJsonValue(item)]));
  }
  return value;
};

const sqlNumber = (value, name, required = false) => {
  if (value === null || value === undefined || value === '') {
    if (required) throw new Error(`${name} is required`);
    return 'NULL';
  }
  const n = Number(value);
  if (!Number.isFinite(n)) throw new Error(`${name} must be numeric`);
  return String(n);
};

const positiveSqlNumber = (value, name, required = false) => {
  const sql = sqlNumber(value, name, required);
  if (sql !== 'NULL' && Number(value) <= 0) throw new Error(`${name} must be a positive number`);
  return sql;
};

const nonNegativeSqlNumber = (value, name, required = false) => {
  const sql = sqlNumber(value, name, required);
  if (sql !== 'NULL' && Number(value) < 0) throw new Error(`${name} must be a non-negative number`);
  return sql;
};

const productCodeValue = (value, name = 'product_code') => {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${name} is required`);
  return value.trim().toUpperCase();
};

const shanghaiDate = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());

const dateValue = (value) => {
  const date = value || shanghaiDate();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('quote_date must be YYYY-MM-DD');
  return date;
};

const clientErrorStatus = (error) => {
  const message = String(error?.message || '');
  return /required|requires|must be|cannot exceed|too large|too long|positive number|non-negative number|valid UTF-8 JSON|provided together|door combination|negative price sign only/i.test(message)
    ? 400 : 500;
};

const validateRequest = (input) => {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('JSON body is required');
  for (const key of ['quote_id', 'material_code']) {
    if (!input[key] || typeof input[key] !== 'string') throw new Error(`${key} is required`);
  }
  const productCode = productCodeValue(input.product_code);
  for (const key of ['width_mm', 'height_mm', 'depth_mm']) {
    const n = Number(input[key]);
    if (!Number.isFinite(n) || n <= 0) throw new Error(`${key} must be a positive number`);
  }
  if (input.attachments !== undefined && !Array.isArray(input.attachments)) {
    throw new Error('attachments must be an array');
  }
  if ((input.attachments || []).length > 100) throw new Error('attachments cannot exceed 100 items');
  return {
    ...input,
    product_code: productCode,
    attachments: (input.attachments || []).map((attachment) => (
      attachment?.product_code
        ? { ...attachment, product_code: productCodeValue(attachment.product_code, 'attachment product_code') }
        : attachment
    )),
  };
};

const normalizeProductVariant = (input = {}) => {
  const doorNormalized = normalizeDoorVariantInput(input);
  const quickNormalized = normalizeQuickDoorVariantInput(input);
  const productCode = String(doorNormalized.product_code || '').trim();
  const variantCode = String(doorNormalized.variant_code || '').trim().toUpperCase();
  if (productCode === 'JP_WIDE_EXP' || productCode === 'JS_WIDE_EXP') {
    return {
      ...doorNormalized,
      variant_code: 'WIDE',
      quick_product_code: quickNormalized.product_code,
    };
  }
  if (productCode === 'JM' && (!variantCode || variantCode === 'DEFAULT')) {
    return {
      ...doorNormalized,
      variant_code: 'SINGLE',
      quick_product_code: quickNormalized.product_code,
    };
  }
  return {
    ...doorNormalized,
    quick_product_code: quickNormalized.product_code || doorNormalized.product_code,
  };
};

const attachmentStatements = (input) => (input.attachments || []).map((a, index) => {
  if (!a || typeof a !== 'object' || Array.isArray(a)) throw new Error(`attachments[${index}] must be an object`);
  if (!a.model_code && !a.item_name) {
    throw new Error(`attachments[${index}] requires model_code or item_name`);
  }
  const priceSign = Number(a.attachment_price_sign ?? 1);
  if (![1, -1].includes(priceSign)) {
    throw new Error(`attachments[${index}].attachment_price_sign must be 1 or -1`);
  }
  const attachmentText = [
    a.category_level1, a.category_level2, a.category_level3, a.item_name, a.model_code,
  ].map((value) => String(value || '')).join(' ');
  if (priceSign === -1 && (!attachmentText.includes('安装板') || attachmentText.includes('安装板单发'))) {
    throw new Error(`attachments[${index}] can use a negative price sign only for an installation board`);
  }
  return `SELECT calc.add_attachment_selection(${[
    sqlText(input.quote_id),
    sqlText(a.product_code || input.product_code),
    sqlUnicodeText(a.model_code ?? null),
    sqlUnicodeText(a.item_name ?? null),
    positiveSqlNumber(a.quantity ?? 1, `attachments[${index}].quantity`, true),
    a.width_mm == null || a.width_mm === '' ? 'NULL' : positiveSqlNumber(a.width_mm, `attachments[${index}].width_mm`, true),
    a.height_mm == null || a.height_mm === '' ? 'NULL' : positiveSqlNumber(a.height_mm, `attachments[${index}].height_mm`, true),
    a.depth_mm == null || a.depth_mm === '' ? 'NULL' : positiveSqlNumber(a.depth_mm, `attachments[${index}].depth_mm`, true),
    sqlUnicodeText(a.variant ?? null),
    sqlUnicodeText(a.price_source ?? null),
    a.unit_price_override == null || a.unit_price_override === ''
      ? 'NULL' : nonNegativeSqlNumber(a.unit_price_override, `attachments[${index}].unit_price_override`, true),
    sqlUnicodeText(a.notes ?? null),
    `${sqlNumber(priceSign, `attachments[${index}].attachment_price_sign`, true)}::SMALLINT`,
  ].join(', ')});`;
});

const buildSql = (input) => {
  const args = [
    sqlText(input.quote_id),
    sqlText(input.product_code),
    // model_code is a user-facing specification / drawing name and may
    // contain Chinese text. A plain Windows psql -c argument can corrupt it
    // through the active console code page, so use a Unicode escape literal.
    sqlUnicodeText(input.model_code ?? ''),
    sqlText(input.material_code),
    sqlNumber(input.width_mm, 'width_mm', true),
    sqlNumber(input.height_mm, 'height_mm', true),
    sqlNumber(input.depth_mm, 'depth_mm', true),
    sqlNumber(input.base_material_weight_kg, 'base_material_weight_kg'),
    sqlNumber(input.product_area_m2, 'product_area_m2'),
    sqlUnicodeText(input.coating_type || DEFAULT_COATING_TYPE),
    sqlText(input.variant_code ?? null),
    sqlText(dateValue(input.quote_date)),
  ];
  // Override the source-file default with a Unicode-safe value. This keeps
  // older UTF-8/console-encoded sample files from changing the coating name.
  args[9] = sqlUnicodeText(input.coating_type || DEFAULT_COATING_TYPE);
  const statements = attachmentStatements(input);
  const attachmentSql = statements.length ? `${statements.join('\n')}\n` : '';
  return `${attachmentSql}
SELECT jsonb_build_object(
  'quote_id', r.quote_id,
  'formula_cost', jsonb_build_object(
    'material_cost', r.formula_material_cost,
    'auxiliary_cost', r.formula_auxiliary_cost,
    'labor_cost', r.formula_labor_cost,
    'attachment_fee', r.formula_attachment_fee,
    'product_area_m2', r.formula_product_area_m2,
    'spray_cost', r.formula_spray_cost,
    'management_fee', r.formula_management_fee,
    'total_cost', r.formula_total_cost
  ),
  'quick_quote', jsonb_build_object(
    -- Formula calculation remains on the original product path.  Quick base
    -- is independently matched on the approved family-aware door variant.
    'base_price', CASE WHEN qm.quick_rule_id IS NULL THEN NULL ELSE qm.quick_total_cost END,
    'attachment_fee', r.quick_attachment_fee,
    'total_cost', CASE WHEN qm.quick_rule_id IS NULL THEN NULL
                       ELSE qm.quick_total_cost + COALESCE(r.quick_attachment_fee, 0) END,
    'match_method', qm.match_method,
    'dimension_distance', qm.dimension_distance,
    'matched_experience', CASE WHEN q.quick_rule_id IS NULL THEN NULL ELSE jsonb_build_object(
      'quick_rule_id', q.quick_rule_id,
      'product_code', q.product_code,
      'model_code', q.model_code,
      'material_code', q.material_code,
      'reference_width_mm', q.reference_width_mm,
      'reference_height_mm', q.reference_height_mm,
      'reference_depth_mm', q.reference_depth_mm,
      'quick_base_price', q.quick_base_price,
      'source_file', q.source_file,
      'source_sheet', q.source_sheet,
      'source_row_no', q.source_row_no
    ) END
  ),
  'risk_flags', CASE WHEN qm.quick_rule_id IS NULL THEN COALESCE(r.risk_flags, '[]'::jsonb)
    ELSE COALESCE((
      SELECT jsonb_agg(flag)
      FROM jsonb_array_elements(COALESCE(r.risk_flags, '[]'::jsonb)) flag
      WHERE flag->>'code' <> 'quick_quote_missing'
    ), '[]'::jsonb) END
)::text
FROM (SELECT * FROM calc.calculate_dual_quote(${args.join(', ')})) r
LEFT JOIN LATERAL calc.match_quick_quote(
  ${sqlText(input.quick_product_code || input.product_code)},
  ${sqlUnicodeText(input.model_code ?? '')},
  ${sqlText(input.material_code)},
  ${sqlNumber(input.width_mm, 'width_mm', true)},
  ${sqlNumber(input.height_mm, 'height_mm', true)},
  ${sqlNumber(input.depth_mm, 'depth_mm', true)},
  ${sqlText(dateValue(input.quote_date))}
) qm ON TRUE
LEFT JOIN LATERAL (
  SELECT q0.* FROM calc.quick_quote_experience q0
  WHERE q0.quick_rule_id = qm.quick_rule_id
) q ON TRUE;`;
};

const runPsql = (sql, clientEncoding = 'UTF8') => new Promise((resolve, reject) => {
  const child = spawn(PSQL_PATH, buildPsqlArgs(RUNTIME_CONFIG), {
    env: { ...process.env, PGCLIENTENCODING: clientEncoding },
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  let settled = false;
  const timeout = setTimeout(() => {
    if (settled) return;
    settled = true;
    if (!child.killed) child.kill();
    reject(new Error(`database command timed out after ${RUNTIME_CONFIG.psqlTimeoutMs} ms`));
  }, RUNTIME_CONFIG.psqlTimeoutMs);
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => { stdout += chunk; });
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  const fail = (error) => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    reject(error);
  };
  child.on('error', fail);
  child.stdin.on('error', fail);
  child.on('close', (code) => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    if (code !== 0) reject(new Error(stderr.trim() || `psql exited with code ${code}`));
    else resolve(stdout.trim());
  });
  // Send SQL through stdin instead of the Windows command line.  Confirmed
  // quotations can contain long OCR remarks and many cabinet snapshots;
  // passing that SQL with `-c` eventually exceeds CreateProcess' command-line
  // limit and makes spawn fail with ENAMETOOLONG.
  child.stdin.end(`${sql}\n`, 'utf8');
});

const addAttachmentCatalogSql = (input) => {
  const item = normalizeCatalogAttachment(input);
  const values = {
    itemName: sqlUnicodeText(item.item_name),
    modelCode: sqlUnicodeText(item.model_code),
    variant: sqlUnicodeText(item.variant),
    width: item.width_mm === null ? 'NULL' : sqlNumber(item.width_mm, 'width_mm'),
    height: item.height_mm === null ? 'NULL' : sqlNumber(item.height_mm, 'height_mm'),
    depth: item.depth_mm === null ? 'NULL' : sqlNumber(item.depth_mm, 'depth_mm'),
    price: sqlNumber(item.price, 'price', true),
    priceText: sqlUnicodeText(item.price_text),
    unit: sqlUnicodeText(item.unit),
    source: sqlUnicodeText(item.price_source),
    notes: sqlUnicodeText(item.notes),
  };
  return {
    item,
    sql: `
WITH existing AS (
  SELECT attachment_price_id
  FROM calc.attachment_price
  WHERE is_active = TRUE
    AND item_name = ${values.itemName}
    AND model_code IS NOT DISTINCT FROM ${values.modelCode}
    AND variant IS NOT DISTINCT FROM ${values.variant}
    AND width_mm IS NOT DISTINCT FROM ${values.width}
    AND height_mm IS NOT DISTINCT FROM ${values.height}
    AND depth_mm IS NOT DISTINCT FROM ${values.depth}
    AND price = ${values.price}
    AND COALESCE(unit, '') = COALESCE(${values.unit}, '')
    AND COALESCE(price_source, '') = COALESCE(${values.source}, '')
  ORDER BY attachment_price_id DESC
  LIMIT 1
), inserted AS (
  INSERT INTO calc.attachment_price (
    item_name, model_code, variant, width_mm, height_mm, depth_mm,
    price, price_text, unit, price_source, notes, is_active
  )
  SELECT ${values.itemName}, ${values.modelCode}, ${values.variant},
         ${values.width}, ${values.height}, ${values.depth},
         ${values.price}, ${values.priceText}, ${values.unit},
         ${values.source}, ${values.notes}, TRUE
  WHERE NOT EXISTS (SELECT 1 FROM existing)
  RETURNING attachment_price_id
), chosen AS (
  SELECT attachment_price_id, TRUE AS created FROM inserted
  UNION ALL
  SELECT attachment_price_id, FALSE AS created FROM existing
)
SELECT jsonb_build_object(
  'saved', TRUE,
  'created', created,
  'attachment_price_id', attachment_price_id
)::text
FROM chosen
LIMIT 1;`,
  };
};

// Formula quotation inputs are sourced from PostgreSQL.  The client receives
// the persisted template metadata and part formulas once, then evaluates the
// same rules locally for responsive dimension editing; no workbook is read at
// runtime.
const formulaTemplateSql = (productCode) => `
SELECT COALESCE(jsonb_agg(to_jsonb(x)), '[]'::jsonb)::text
FROM (
  SELECT m.template_code,
         m.source_sheet,
         m.width_cell,
         m.height_cell,
         m.depth_cell,
         m.option_cells,
         m.weight_output_cell,
         m.area_output_cell,
         m.weight_method,
         m.area_unit,
         t.weight_formula AS template_weight_formula,
         t.area_formula AS template_area_formula,
         jsonb_agg(to_jsonb(r) ORDER BY r.source_row_no) AS rules
  FROM calc.template_formula_mapping m
  JOIN calc.cabinet_template t ON t.template_code = m.template_code
  JOIN calc.cabinet_part_rule r ON r.template_id = t.template_id
  WHERE m.template_code = ${sqlText(productCode)}
    AND m.is_active = TRUE
    AND t.is_active = TRUE
  GROUP BY m.template_code, m.source_sheet, m.width_cell, m.height_cell,
           m.depth_cell, m.option_cells, m.weight_output_cell,
           m.area_output_cell, m.weight_method, m.area_unit,
           t.weight_formula, t.area_formula
) x;`;

// Product choices are database-driven; the client does not maintain a
// hard-coded list. Formula templates and experience products are returned
// together for the selector.
const productCatalogSql = `
WITH products AS (
  SELECT 1 AS sort_order, template_code AS product_code,
         template_name AS product_name, 'formula' AS product_method,
         default_width_mm, default_height_mm, default_depth_mm,
         '[]'::jsonb AS models
  FROM calc.cabinet_template
  WHERE is_active = TRUE
  UNION ALL
  SELECT 2 AS sort_order, product_code, product_name, 'experience' AS product_method,
         NULL::numeric, NULL::numeric, NULL::numeric,
         COALESCE((
           SELECT jsonb_agg(jsonb_build_object(
             'model_code', epm.model_code,
             'width_mm', epm.width_mm,
             'height_mm', epm.height_mm,
             'depth_mm', epm.depth_mm
           ) ORDER BY epm.model_code, epm.model_id)
           FROM calc.experience_product_model epm
           WHERE epm.experience_product_id = ep.experience_product_id
             AND epm.is_active = TRUE
         ), '[]'::jsonb) AS models
  FROM calc.experience_product ep
  WHERE ep.is_active = TRUE
), materials AS (
  SELECT COALESCE(jsonb_agg(jsonb_build_object(
    'code', m.material_code,
    'name', COALESCE(NULLIF(to_jsonb(m)->>'material_name', ''), m.material_code)
  ) ORDER BY m.material_code), '[]'::jsonb) AS value
  FROM calc.material m
  WHERE COALESCE((to_jsonb(m)->>'is_active')::boolean, TRUE)
), coatings AS (
  SELECT COALESCE(jsonb_agg(c.name ORDER BY c.name), '[]'::jsonb) AS value
  FROM (
    SELECT DISTINCT COALESCE(
      NULLIF(to_jsonb(s)->>'coating_type', ''),
      NULLIF(to_jsonb(s)->>'spray_type', ''),
      NULLIF(to_jsonb(s)->>'surface_type', '')
    ) AS name
    FROM calc.spray_price s
    WHERE COALESCE((to_jsonb(s)->>'is_active')::boolean, TRUE)
  ) c
  WHERE c.name IS NOT NULL
)
SELECT jsonb_build_object(
  'items', COALESCE((SELECT jsonb_agg(to_jsonb(p) - 'sort_order' ORDER BY p.sort_order, p.product_code) FROM products p), '[]'::jsonb),
  'materials', (SELECT value FROM materials),
  'coatings', (SELECT value FROM coatings),
  'source', 'postgresql'
)::text;`;

const companyCatalogSql = `
SELECT COALESCE(jsonb_agg(to_jsonb(x) ORDER BY x.company_name, x.company_code), '[]'::jsonb)::text
FROM (
  SELECT company_code, company_name, contact_name, contact_phone, company_address
  FROM calc.ordering_company
  WHERE is_active = TRUE
) x;`;

const historyMatchSql = (input) => {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('JSON body is required');
  const required = ['company_code', 'material_code'];
  for (const key of required) {
    if (!input[key] || typeof input[key] !== 'string') throw new Error(`${key} is required`);
  }
  const productCode = productCodeValue(input.product_code);
  for (const key of ['width_mm', 'height_mm', 'depth_mm']) {
    if (!Number.isFinite(Number(input[key])) || Number(input[key]) <= 0) {
      throw new Error(`${key} must be a positive number`);
    }
  }
  return `
SELECT COALESCE((
  SELECT jsonb_build_object(
    'matched', TRUE,
    'history_id', h.history_id,
    'quote_id', h.quote_id,
    'company_code', c.company_code,
    'company_name', c.company_name,
    'created_at', h.created_at,
    'payload', h.request_payload
  )
  FROM calc.company_quote_history h
  JOIN calc.ordering_company c ON c.company_id = h.company_id
  WHERE c.company_code = ${sqlUnicodeText(input.company_code)}
    AND h.product_code = ${sqlUnicodeText(productCode)}
    AND h.material_code = ${sqlUnicodeText(input.material_code)}
    AND COALESCE(h.variant_code, '') = COALESCE(${sqlUnicodeText(input.variant_code ?? '')}, '')
    AND h.width_mm = ${sqlNumber(input.width_mm, 'width_mm')}
    AND h.height_mm = ${sqlNumber(input.height_mm, 'height_mm')}
    AND h.depth_mm = ${sqlNumber(input.depth_mm, 'depth_mm')}
  ORDER BY h.created_at DESC, h.history_id DESC
  LIMIT 1
), '{"matched":false}'::jsonb)::text;`;
};

const companyHistoryInsertSql = (input) => {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('JSON body is required');
  const required = ['company_code', 'material_code'];
  for (const key of required) {
    if (!input[key] || typeof input[key] !== 'string') throw new Error(`${key} is required`);
  }
  const productCode = productCodeValue(input.product_code);
  for (const key of ['width_mm', 'height_mm', 'depth_mm']) {
    if (!Number.isFinite(Number(input[key])) || Number(input[key]) <= 0) {
      throw new Error(`${key} must be a positive number`);
    }
  }
  if (input.payload !== undefined && (
    !input.payload || typeof input.payload !== 'object' || Array.isArray(input.payload)
  )) throw new Error('payload must be an object');
  const payload = input.payload || input;
  return `
WITH company AS (
  INSERT INTO calc.ordering_company (company_code, company_name, is_active)
  VALUES (
    ${sqlUnicodeText(input.company_code)},
    ${sqlUnicodeText(input.company_name ?? payload.company_name ?? input.company_code)},
    TRUE
  )
  ON CONFLICT (company_code) DO UPDATE
    SET company_name = EXCLUDED.company_name, is_active = TRUE
  RETURNING company_id
), inserted AS (
  INSERT INTO calc.company_quote_history (
    company_id, quote_id, product_code, model_code, material_code,
    coating_type, variant_code, width_mm, height_mm, depth_mm, request_payload
  )
  SELECT company_id,
         ${sqlUnicodeText(input.quote_id ?? payload.quote_id ?? null)},
         ${sqlUnicodeText(productCode)},
         ${sqlUnicodeText(input.model_code ?? payload.model_code ?? null)},
         ${sqlUnicodeText(input.material_code)},
         ${sqlUnicodeText(input.coating_type ?? payload.coating_type ?? null)},
         ${sqlUnicodeText(input.variant_code ?? payload.variant_code ?? null)},
         ${sqlNumber(input.width_mm, 'width_mm')},
         ${sqlNumber(input.height_mm, 'height_mm')},
         ${sqlNumber(input.depth_mm, 'depth_mm')},
         ${sqlUnicodeText(JSON.stringify(payload))}::jsonb
  FROM company
  RETURNING history_id, quote_id
)
SELECT COALESCE((SELECT jsonb_build_object('saved', TRUE, 'history_id', history_id, 'quote_id', quote_id) FROM inserted),
                '{"saved":false,"reason":"company_not_found"}'::jsonb)::text;`;
};

// A quotation document is a frozen business snapshot.  Formula and quick
// values are stored together only for presentation/export; their source
// calculations remain independent database systems.
const confirmQuoteSql = (input) => {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('JSON body is required');
  if (!input.quote_id || !input.company_name || !Array.isArray(input.items) || !input.items.length) {
    throw new Error('quote_id, company_name and at least one item are required');
  }
  const quoteDate = dateValue(input.quote_date);
  const companyCode = String(input.company_code || input.company_name).trim();
  const normalizedItems = input.items.map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error(`items[${index}] must be an object`);
    }
    return { ...item, product_code: productCodeValue(item.product_code, `items[${index}].product_code`) };
  });
  const snapshot = {
    quote_id: input.quote_id,
    quote_date: quoteDate,
    company_code: companyCode,
    company_name: input.company_name,
    items: normalizedItems,
  };
  const historyRows = normalizedItems.map((item, index) => {
    for (const field of ['material_code']) {
      if (!item[field]) throw new Error(`items[${index}].${field} is required`);
    }
    for (const field of ['width_mm', 'height_mm', 'depth_mm']) {
      if (!Number.isFinite(Number(item[field])) || Number(item[field]) <= 0) {
        throw new Error(`items[${index}].${field} must be a positive number`);
      }
    }
    return `(
      ${sqlUnicodeText(input.quote_id)},
      ${sqlUnicodeText(item.product_code)}, ${sqlUnicodeText(item.model_code ?? null)},
      ${sqlUnicodeText(item.material_code)}, ${sqlUnicodeText(item.coating_type ?? null)},
      ${sqlUnicodeText(item.variant_code ?? null)},
      ${sqlNumber(item.width_mm, `items[${index}].width_mm`)},
      ${sqlNumber(item.height_mm, `items[${index}].height_mm`)},
      ${sqlNumber(item.depth_mm, `items[${index}].depth_mm`)},
      ${sqlUnicodeText(JSON.stringify(item))}::jsonb
    )`;
  }).join(',\n');
  return `
WITH c AS (
  INSERT INTO calc.ordering_company
    (company_code, company_name, contact_name, contact_phone, company_address, is_active)
  VALUES (
    ${sqlUnicodeText(companyCode)}, ${sqlUnicodeText(input.company_name)},
    ${sqlUnicodeText(input.contact_name ?? null)}, ${sqlUnicodeText(input.contact_phone ?? null)},
    ${sqlUnicodeText(input.company_address ?? null)}, TRUE
  )
  ON CONFLICT (company_code) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    contact_name = COALESCE(EXCLUDED.contact_name, calc.ordering_company.contact_name),
    contact_phone = COALESCE(EXCLUDED.contact_phone, calc.ordering_company.contact_phone),
    company_address = COALESCE(EXCLUDED.company_address, calc.ordering_company.company_address),
    is_active = TRUE
  RETURNING company_id
), doc AS (
  INSERT INTO calc.quote_document
    (quote_id, company_id, quote_date, status, document_payload)
  SELECT ${sqlUnicodeText(input.quote_id)}, company_id, ${sqlText(quoteDate)}::date,
         'CONFIRMED', ${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb
  FROM c
  RETURNING quote_id
), hist AS (
  INSERT INTO calc.company_quote_history
    (company_id, quote_id, product_code, model_code, material_code,
     coating_type, variant_code, width_mm, height_mm, depth_mm, request_payload)
  SELECT c.company_id, v.* FROM (VALUES ${historyRows}) AS v(
    quote_id, product_code, model_code, material_code,
    coating_type, variant_code, width_mm, height_mm, depth_mm, request_payload
  )
  JOIN c ON TRUE
  RETURNING history_id
)
SELECT jsonb_build_object(
  'confirmed', TRUE, 'quote_id', (SELECT quote_id FROM doc),
  'history_items', (SELECT count(*) FROM hist)
)::text;`;
};

const readBody = (req) => new Promise((resolve, reject) => {
  const chunks = [];
  let byteLength = 0;
  let failed = false;
  req.on('data', (chunk) => {
    if (failed) return;
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    byteLength += bytes.length;
    if (byteLength > MAX_REQUEST_BYTES) {
      failed = true;
      reject(new Error(`request body is too large (maximum ${MAX_REQUEST_BYTES / 1024 / 1024} MB)`));
      return;
    }
    chunks.push(bytes);
  });
  req.on('end', () => {
    if (failed) return;
    try {
      const data = Buffer.concat(chunks).toString('utf8');
      resolve(sanitizeJsonValue(JSON.parse(data || '{}')));
    } catch {
      reject(new Error('request body must be valid UTF-8 JSON'));
    }
  });
  req.on('error', reject);
});

const runWorkbookExporter = async (payload) => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'ai-quote-export-'));
  const inputPath = path.join(tempDir, 'quote.json');
  const outputPath = path.join(tempDir, 'quote.xlsx');
  const scriptPath = path.join(PROJECT_ROOT, 'export_dual_quote_workbook.mjs');
  try {
    await fs.writeFile(inputPath, JSON.stringify(payload), 'utf8');
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [scriptPath, inputPath, outputPath], {
        cwd: PROJECT_ROOT,
        env: process.env,
        windowsHide: true,
      });
      let stdout = '';
      let stderr = '';
      child.stdout.on('data', (data) => { stdout += data.toString(); });
      child.stderr.on('data', (data) => { stderr += data.toString(); });
      child.on('error', reject);
      child.on('close', (code) => {
        if (code === 0) resolve();
        else reject(new Error(stderr.trim() || stdout.trim() || `Excel exporter exited with code ${code}`));
      });
    });
    return await fs.readFile(outputPath);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
};

const auxiliaryLookupKey = (item = {}) => {
  const normalizedItem = normalizeProductVariant(item);
  const productCode = productCodeValue(normalizedItem.product_code);
  const variant = String(normalizedItem.variant_code || '').trim().toUpperCase();
  const mappedProduct = {
    JS_SINGLE: 'JS', JS_DOUBLE: 'JS',
    JP_SINGLE: 'JP', JP_DOUBLE: 'JP',
    JA_SINGLE: 'JA', JE_SINGLE: 'JE', JE_DOUBLE: 'JE',
  }[productCode] || productCode;
  const mappedVariant = variant || ({
    JS_SINGLE: 'SINGLE', JS_DOUBLE: 'DOUBLE',
    JP_SINGLE: 'SINGLE', JP_DOUBLE: 'DOUBLE',
    JA_SINGLE: 'DEFAULT', JE_SINGLE: 'SINGLE', JE_DOUBLE: 'DOUBLE',
    JP_WIDE_EXP: 'WIDE', JS_WIDE_EXP: 'WIDE',
  }[productCode] || 'DEFAULT');
  return { product_code: mappedProduct, variant_code: mappedVariant };
};

// Cost-detail export enrichment is intentionally read-only.  It exposes the
// database-owned prices and BOM rows used to explain an already calculated
// formula quotation; it never recalculates or overwrites the quote itself.
const exportCostDetailSql = (payload) => {
  const requests = (payload.items || []).map((item, itemIndex) => {
    const key = auxiliaryLookupKey(item);
    return {
      item_index: itemIndex,
      product_code: key.product_code,
      variant_code: key.variant_code,
      material_code: item.material_code || 'SECC',
      coating_type: item.coating_type || DEFAULT_COATING_TYPE,
      quote_date: dateValue(item.quote_date || payload.quote_date),
    };
  });
  const requestJson = sqlUnicodeText(JSON.stringify(requests));
  return `WITH requested AS (
    SELECT
      (value->>'item_index')::integer AS item_index,
      value->>'product_code' AS product_code,
      value->>'variant_code' AS variant_code,
      value->>'material_code' AS material_code,
      value->>'coating_type' AS coating_type,
      (value->>'quote_date')::date AS quote_date
    FROM jsonb_array_elements(${requestJson}::jsonb)
  ), enriched AS (
    SELECT r.*, b.auxiliary_bom_id, b.source_total, b.source_file, b.source_sheet
    FROM requested r
    LEFT JOIN LATERAL (
      SELECT b0.*
      FROM calc.auxiliary_bom b0
      WHERE b0.product_code = r.product_code
        AND b0.variant_code = r.variant_code
      ORDER BY b0.updated_at DESC NULLS LAST, b0.auxiliary_bom_id DESC
      LIMIT 1
    ) b ON TRUE
  )
  SELECT COALESCE(jsonb_agg(jsonb_build_object(
    'item_index', e.item_index,
    'material_unit_price', calc.get_material_unit_price(e.material_code, e.quote_date),
    'spray_unit_price', calc.get_spray_unit_price(e.quote_date, e.coating_type),
    'auxiliary_method', CASE WHEN e.auxiliary_bom_id IS NULL THEN 'experience' ELSE 'bom' END,
    'auxiliary_source_total', e.source_total,
    'auxiliary_source_file', e.source_file,
    'auxiliary_source_sheet', e.source_sheet,
    'auxiliary_lines', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'line_no', l.line_no,
        'item_code', l.item_code,
        'item_name', l.item_name,
        'spec_model', l.spec_model,
        'material_name', l.material_name,
        'quantity', COALESCE(l.qty_per_unit, l.source_quantity, 0),
        'unit_price', l.unit_price,
        'line_total', l.line_total,
        'source_sheet', l.source_sheet,
        'source_row_no', l.source_row_no
      ) ORDER BY l.line_no, l.auxiliary_bom_line_id)
      FROM calc.auxiliary_bom_line l
      WHERE l.auxiliary_bom_id = e.auxiliary_bom_id
    ), '[]'::jsonb)
  ) ORDER BY e.item_index), '[]'::jsonb)::text
  FROM enriched e;`;
};

const enrichExportCostDetails = async (payload) => {
  const items = Array.isArray(payload.items) ? payload.items : [];
  if (!items.length) return payload;
  const output = await runPsql(exportCostDetailSql(payload));
  const details = output ? JSON.parse(output.split(/\r?\n/).filter(Boolean).at(-1)) : [];
  const byIndex = new Map(details.map((detail) => [Number(detail.item_index), detail]));
  return {
    ...payload,
    items: items.map((item, index) => {
      const detail = byIndex.get(index) || {};
      const formula = { ...(item.formula || {}) };
      const materialUnitPrice = Number(detail.material_unit_price);
      const sprayUnitPrice = Number(detail.spray_unit_price);
      if (Number.isFinite(materialUnitPrice) && materialUnitPrice > 0) {
        formula.material_unit_price = materialUnitPrice;
        if (formula.corrected_material_weight_kg == null && Number.isFinite(Number(formula.material_cost))) {
          formula.corrected_material_weight_kg = Number(formula.material_cost) / materialUnitPrice;
        }
      }
      if (Number.isFinite(sprayUnitPrice)) formula.spray_unit_price = sprayUnitPrice;
      return {
        ...item,
        formula,
        auxiliary_detail: {
          method: detail.auxiliary_method || 'experience',
          source_total: detail.auxiliary_source_total,
          source_file: detail.auxiliary_source_file,
          source_sheet: detail.auxiliary_source_sheet,
          lines: Array.isArray(detail.auxiliary_lines) ? detail.auxiliary_lines : [],
        },
      };
    }),
  };
};

const databaseReadinessSql = `
SELECT jsonb_build_object(
  'schema_ready', to_regnamespace('calc') IS NOT NULL,
  'product_ready', to_regclass('calc.cabinet_template') IS NOT NULL
    OR to_regclass('calc.experience_product') IS NOT NULL,
  'material_ready', to_regclass('calc.material') IS NOT NULL,
  'spray_ready', to_regclass('calc.spray_price') IS NOT NULL,
  'auxiliary_ready', to_regclass('calc.auxiliary_bom') IS NOT NULL,
  'attachment_ready', to_regclass('calc.attachment_price') IS NOT NULL,
  'attachment_classification_ready', to_regclass('calc.attachment_classification') IS NOT NULL,
  'calculation_ready', EXISTS (
    SELECT 1
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'calc' AND p.proname = 'calculate_dual_quote'
  )
)::text;`;

const getDatabaseReadiness = async () => {
  const output = await runPsql(databaseReadinessSql);
  const line = output.split(/\r?\n/).map((item) => item.trim()).filter(Boolean).at(-1);
  return line ? JSON.parse(line) : {};
};

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    // Keep the public liveness check database-free. Render calls it frequently;
    // querying Neon here would prevent a free test database from scaling down.
    return json(res, 200, {
      ok: true,
      service: 'ai-quote-dual-api',
      build: API_BUILD,
      deployment: DEPLOYMENT_BUILD,
      database_checked: false,
    });
  }
  if (API_KEY && req.url?.startsWith('/api/') && String(req.headers['x-ai-quote-key'] || '') !== API_KEY) {
    return json(res, 401, { error: 'unauthorized', message: 'invalid client access key' });
  }
  if (req.method === 'GET' && req.url === '/api/health/database') {
    try {
      const checks = await getDatabaseReadiness();
      const ready = Object.values(checks).every(Boolean);
      return json(res, ready ? 200 : 503, { ready, checks, build: API_BUILD });
    } catch (error) {
      return json(res, 503, {
        ready: false,
        error: 'database_unavailable',
        message: String(error?.message || 'database connection failed'),
        build: API_BUILD,
      });
    }
  }
  if (req.method === 'GET' && req.url === '/api/companies/catalog') {
    try {
      const output = await runPsql(companyCatalogSql);
      return json(res, 200, { items: output ? JSON.parse(output) : [], source: 'postgresql' });
    } catch (error) {
      return json(res, 500, { error: 'company_catalog_failed', message: error.message });
    }
  }
  if (req.method === 'POST' && req.url === '/api/company-history/match') {
    try {
      const input = await readBody(req);
      const output = await runPsql(historyMatchSql(input));
      return json(res, 200, output ? JSON.parse(output) : { matched: false });
    } catch (error) {
      return json(res, clientErrorStatus(error), {
        error: 'company_history_match_failed',
        message: error.message,
      });
    }
  }
  if (req.method === 'POST' && req.url === '/api/history-prices/match') {
    try {
      const input = await readBody(req);
      const output = await runPsql(historyPriceMatchSql(input));
      return json(res, 200, output ? JSON.parse(output) : { matched: false, items: [] });
    } catch (error) {
      return json(res, clientErrorStatus(error), {
        error: 'history_price_match_failed',
        message: error.message,
      });
    }
  }
  if (req.method === 'POST' && req.url === '/api/company-history') {
    try {
      const input = await readBody(req);
      const output = await runPsql(companyHistoryInsertSql(input));
      return json(res, 200, output ? JSON.parse(output) : { saved: false });
    } catch (error) {
      return json(res, clientErrorStatus(error), {
        error: 'company_history_save_failed',
        message: error.message,
      });
    }
  }
  if (req.method === 'POST' && req.url === '/api/quotes/confirm') {
    try {
      const input = await readBody(req);
      const output = await runPsql(confirmQuoteSql(input));
      return json(res, 200, output ? JSON.parse(output) : { confirmed: false });
    } catch (error) {
      return json(res, clientErrorStatus(error), { error: 'quote_confirm_failed', message: error.message });
    }
  }
  if (req.method === 'POST' && req.url === '/api/quotes/confirm-check') {
    try {
      const input = await readBody(req);
      // Exercise the real inserts, constraints and UTF-8/jsonb conversion,
      // then roll everything back. This endpoint is used by the desktop
      // client's export preflight and by regression tests.
      const output = await runPsql(`BEGIN;\n${confirmQuoteSql(input)}\nROLLBACK;`);
      const checked = output ? JSON.parse(output) : { confirmed: false };
      return json(res, 200, { ...checked, dry_run: true, persisted: false });
    } catch (error) {
      return json(res, clientErrorStatus(error), { error: 'quote_confirm_check_failed', message: error.message });
    }
  }
  if (req.method === 'GET' && req.url === '/api/products/catalog') {
    try {
      const output = await runPsql(productCatalogSql);
      return json(res, 200, output ? JSON.parse(output) : {
        items: [], materials: [], coatings: [], source: 'postgresql',
      });
    } catch (error) {
      return json(res, 500, { error: 'product_catalog_failed', message: error.message });
    }
  }
  if (req.method === 'GET' && req.url === '/api/attachments/catalog') {
    try {
      // Old attachment imports contain a small number of non-UTF8 bytes.
      // The SQL response is base64-only, so SQL_ASCII is safe here and avoids
      // psql failing before Node can restore those legacy values.
      const output = await runPsql(attachmentCatalogSql, 'SQL_ASCII');
      return json(res, 200, { items: output ? decodeAttachmentCatalog(JSON.parse(output)) : [] });
    } catch (error) {
      return json(res, 500, { error: 'attachment_catalog_failed', message: error.message });
    }
  }
  if (req.method === 'POST' && req.url === '/api/attachments/catalog') {
    try {
      const input = await readBody(req);
      const command = addAttachmentCatalogSql(input);
      const output = await runPsql(command.sql);
      const saved = output ? JSON.parse(output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).at(-1)) : {};
      return json(res, 200, { ...saved, item: command.item, source: 'postgresql' });
    } catch (error) {
      const message = String(error?.message || 'attachment catalogue write failed');
      return json(res, clientErrorStatus(error), { error: 'attachment_catalog_save_failed', message });
    }
  }
  if (req.method === 'POST' && req.url === '/api/quotes/formula-template') {
    try {
      const input = await readBody(req);
      if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('JSON body is required');
      const productCode = productCodeValue(input.product_code);
      const output = await runPsql(formulaTemplateSql(productCode));
      const rows = output ? JSON.parse(output) : [];
      if (!rows.length) {
        return json(res, 404, { error: 'formula_template_not_found', message: `no formula template for ${productCode}` });
      }
      return json(res, 200, { template: rows[0], source: 'postgresql' });
    } catch (error) {
      return json(res, clientErrorStatus(error), { error: 'formula_template_failed', message: error.message });
    }
  }
  if (req.method === 'POST' && req.url === '/api/quotes/export') {
    try {
      const input = await readBody(req);
      if (!input || typeof input !== 'object' || Array.isArray(input)) {
        return json(res, 400, { error: 'quote_export_failed', message: 'JSON body is required' });
      }
      if (!Array.isArray(input.items) || input.items.length === 0) {
        return json(res, 400, { error: 'quote_export_failed', message: 'items are required' });
      }
      const enrichedInput = await enrichExportCostDetails(input);
      const workbook = await runWorkbookExporter(enrichedInput);
      res.writeHead(200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Length': workbook.length,
        'Content-Disposition': 'attachment; filename="dual-quote.xlsx"',
      });
      return res.end(workbook);
    } catch (error) {
      return json(res, clientErrorStatus(error), { error: 'quote_export_failed', message: error.message });
    }
  }
  if (req.method !== 'POST' || req.url !== '/api/quotes/calculate-dual') {
    return json(res, 404, { error: 'not_found' });
  }
  try {
    const input = normalizeProductVariant(validateRequest(await readBody(req)));
    const output = await runPsql(buildSql(input));
    if (!output) throw new Error('database returned no quote result');
    // Attachment selection adds one INSERT result before the final JSON row.
    // Parse the final non-empty line so both empty-attachment and selected-
    // attachment requests use the same response path.
    const jsonLine = output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).at(-1);
    json(res, 200, JSON.parse(jsonLine));
  } catch (error) {
    json(res, clientErrorStatus(error), {
      error: 'dual_quote_failed',
      message: error.message,
    });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`AI quote dual API listening on http://${HOST}:${PORT}`);
});
