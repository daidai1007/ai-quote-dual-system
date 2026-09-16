-- Read-only preflight. Run in the production database before any write step.
SELECT current_database() AS database_name,
       current_user AS database_user,
       to_regclass('calc.attachment_price') AS attachment_price_table,
       to_regclass('calc.attachment_image_catalog') AS existing_image_catalog,
       to_regclass('calc.attachment_image_asset') AS existing_image_asset;

SELECT count(*) AS active_attachment_prices,
       count(DISTINCT item_name) AS active_attachment_names
FROM calc.attachment_price
WHERE is_active;

SELECT data_version,status,source_sha256,activated_at
FROM calc.attachment_catalog_version
ORDER BY created_at DESC;

