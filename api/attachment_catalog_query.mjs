// Read the attachment price catalogue together with its independent
// classification mapping.  Price/source fields remain owned by
// calc.attachment_price; categories never participate in price calculation.

// Some legacy attachment rows were imported before the database text encoding
// was standardised.  SQL returns all human-readable text as base64 bytes so
// Node can restore UTF-8 first and fall back to GB18030.
export const decodeStoredText = (value) => {
  if (value === null || value === undefined || value === '') return value ?? '';
  const bytes = Buffer.from(String(value), 'base64');
  const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  if (!utf8.includes('\uFFFD')) return utf8;
  try {
    return new TextDecoder('gb18030', { fatal: false }).decode(bytes);
  } catch {
    return utf8;
  }
};

export const decodeAttachmentCatalog = (rows) => rows.map((row) => ({
  attachment_price_id: row.attachment_price_id,
  category_level1: decodeStoredText(row.category_level1_b64),
  category_level2: decodeStoredText(row.category_level2_b64),
  category_level3: decodeStoredText(row.category_level3_b64),
  item_name: decodeStoredText(row.item_name_b64),
  model_code: decodeStoredText(row.model_code_b64),
  variant: decodeStoredText(row.variant_b64),
  width_mm: row.width_mm,
  height_mm: row.height_mm,
  depth_mm: row.depth_mm,
  price: row.price,
  price_text: decodeStoredText(row.price_text_b64),
  unit: decodeStoredText(row.unit_b64),
  price_source: decodeStoredText(row.price_source_b64),
  notes: decodeStoredText(row.notes_b64),
}));

export const attachmentCatalogSql = `
SELECT COALESCE(jsonb_agg(
  to_jsonb(x)
  ORDER BY x.category_level1_b64, x.category_level2_b64, x.category_level3_b64,
           x.item_name_b64, x.width_mm NULLS LAST, x.height_mm NULLS LAST, x.depth_mm NULLS LAST
), '[]'::jsonb)::text
FROM (
  -- Keep separate prices/sources for the same model.  A model may have
  -- multiple valid prices.  The UI exposes these as separate price choices.
  SELECT DISTINCT ON (
    encode(p.item_name::bytea, 'base64'),
    encode(COALESCE(p.model_code, '')::bytea, 'base64'),
    encode(COALESCE(p.variant, '')::bytea, 'base64'),
    p.width_mm, p.height_mm, p.depth_mm, p.price,
    encode(COALESCE(p.price_text, '')::bytea, 'base64'),
    encode(COALESCE(p.unit, '')::bytea, 'base64'),
    encode(COALESCE(p.price_source, '')::bytea, 'base64'),
    encode(COALESCE(p.notes, '')::bytea, 'base64'),
    encode(COALESCE(c.category_level1, '')::bytea, 'base64'),
    encode(COALESCE(c.category_level2, '')::bytea, 'base64'),
    encode(COALESCE(c.category_level3, '')::bytea, 'base64')
  )
    p.attachment_price_id,
    encode(COALESCE(c.category_level1, '')::bytea, 'base64') AS category_level1_b64,
    encode(COALESCE(c.category_level2, '')::bytea, 'base64') AS category_level2_b64,
    encode(COALESCE(c.category_level3, '')::bytea, 'base64') AS category_level3_b64,
    encode(p.item_name::bytea, 'base64') AS item_name_b64,
    encode(COALESCE(p.model_code, '')::bytea, 'base64') AS model_code_b64,
    encode(COALESCE(p.variant, '')::bytea, 'base64') AS variant_b64,
    p.width_mm, p.height_mm, p.depth_mm, p.price,
    encode(COALESCE(p.price_text, '')::bytea, 'base64') AS price_text_b64,
    encode(COALESCE(p.unit, '')::bytea, 'base64') AS unit_b64,
    encode(COALESCE(p.price_source, '')::bytea, 'base64') AS price_source_b64,
    encode(COALESCE(p.notes, '')::bytea, 'base64') AS notes_b64
  FROM calc.attachment_price p
  LEFT JOIN calc.attachment_classification c
    ON c.attachment_price_id = p.attachment_price_id
  WHERE p.is_active = TRUE
  ORDER BY
    encode(p.item_name::bytea, 'base64'),
    encode(COALESCE(p.model_code, '')::bytea, 'base64'),
    encode(COALESCE(p.variant, '')::bytea, 'base64'),
    p.width_mm, p.height_mm, p.depth_mm, p.price,
    encode(COALESCE(p.price_text, '')::bytea, 'base64'),
    encode(COALESCE(p.unit, '')::bytea, 'base64'),
    encode(COALESCE(p.price_source, '')::bytea, 'base64'),
    encode(COALESCE(p.notes, '')::bytea, 'base64'),
    encode(COALESCE(c.category_level1, '')::bytea, 'base64'),
    encode(COALESCE(c.category_level2, '')::bytea, 'base64'),
    encode(COALESCE(c.category_level3, '')::bytea, 'base64'),
    p.attachment_price_id DESC
) x;`;
