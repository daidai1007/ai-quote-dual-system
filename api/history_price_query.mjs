const MAX_MATCH_TEXT_LENGTH = 500;

const requiredExactText = (input, key) => {
  const value = input?.[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${key} is required`);
  }
  const normalized = value.trim().normalize('NFC');
  if (normalized.length > MAX_MATCH_TEXT_LENGTH) {
    throw new Error(`${key} is too long`);
  }
  return normalized;
};

const sqlUnicodeText = (value) => {
  const hex = Buffer.from(String(value), 'utf8').toString('hex');
  return `convert_from(decode('${hex}', 'hex'), 'UTF8')`;
};

export const normalizeHistoryPriceMatchInput = (input) => ({
  company_name: requiredExactText(input, 'company_name'),
  specification: requiredExactText(input, 'specification'),
  cabinet_type: requiredExactText(input, 'cabinet_type'),
});

export const historyPriceMatchSql = (input) => {
  const match = normalizeHistoryPriceMatchInput(input);
  return `
WITH raw_matches AS (
  SELECT h.source_row_no,
         h.dingtalk_contract_no,
         h.tax_included_unit_price
  FROM calc."历史价格" h
  WHERE h.customer_name = ${sqlUnicodeText(match.company_name)}
    AND h.specification = ${sqlUnicodeText(match.specification)}
    AND h.cabinet_type = ${sqlUnicodeText(match.cabinet_type)}
), grouped_matches AS (
  SELECT dingtalk_contract_no,
         tax_included_unit_price,
         MAX(source_row_no) AS latest_source_row_no,
         COUNT(*) AS source_row_count
  FROM raw_matches
  GROUP BY dingtalk_contract_no, tax_included_unit_price
), visible_matches AS (
  SELECT *
  FROM grouped_matches
  ORDER BY latest_source_row_no DESC, dingtalk_contract_no
  LIMIT 50
)
SELECT jsonb_build_object(
  'matched', EXISTS (SELECT 1 FROM raw_matches),
  'source_row_count', (SELECT COUNT(*) FROM raw_matches),
  'unique_result_count', (SELECT COUNT(*) FROM grouped_matches),
  'items', COALESCE((
    SELECT jsonb_agg(jsonb_build_object(
      'dingtalk_contract_no', dingtalk_contract_no,
      'tax_included_unit_price', tax_included_unit_price,
      'source_row_count', source_row_count
    ) ORDER BY latest_source_row_no DESC, dingtalk_contract_no)
    FROM visible_matches
  ), '[]'::jsonb)
)::text;`;
};
