// Attachment pictures are presentation data.  They are kept in independent
// tables and never join quote prices, quantities, rules or saved calculations.

export const attachmentImageTablesExistSql = `
SELECT to_jsonb(
  to_regclass('calc.attachment_image_catalog') IS NOT NULL
  AND to_regclass('calc.attachment_image_asset') IS NOT NULL
);`;

export const attachmentImageCatalogSql = `
SELECT COALESCE(jsonb_agg(
  jsonb_build_object(
    'item_name',c.item_name,
    'match_mode',c.match_mode,
    'images',COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'image_order',a.image_order,
        'mime_type',a.mime_type,
        'image_sha256',a.image_sha256,
        'data_base64',encode(a.image_data,'base64')
      ) ORDER BY a.image_order)
      FROM calc.attachment_image_asset a
      WHERE a.item_name=c.item_name
    ),'[]'::jsonb)
  ) ORDER BY c.source_row_no
),'[]'::jsonb)::text
FROM calc.attachment_image_catalog c;`;

export function normalizeAttachmentImages(value) {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => ({
    item_name: String(entry?.item_name || '').trim(),
    match_mode: entry?.match_mode === 'PREFIX' ? 'PREFIX' : 'EXACT',
    images: Array.isArray(entry?.images)
      ? entry.images.filter((image) => image && image.data_base64).map((image) => ({
        image_order: Number(image.image_order || 1),
        mime_type: String(image.mime_type || ''),
        image_sha256: String(image.image_sha256 || ''),
        data_base64: String(image.data_base64 || '').replace(/\s+/g, ''),
      }))
      : [],
  })).filter((entry) => entry.item_name);
}

