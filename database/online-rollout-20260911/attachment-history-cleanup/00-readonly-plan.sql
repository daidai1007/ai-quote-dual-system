-- Read-only plan for removing legacy attachment history and catalog rows.
-- Safe to run before the maintenance transaction.
BEGIN READ ONLY;

SELECT current_database() AS database_name,
       current_user AS database_role,
       now() AS checked_at;

SELECT data_version,status,source_sha256,created_at,activated_at
FROM calc.attachment_catalog_version
ORDER BY created_at;

SELECT count(*) FILTER (WHERE data_version IS NULL) AS legacy_price_rows,
       count(*) FILTER (WHERE data_version IS NULL AND is_active) AS legacy_price_active_rows,
       count(*) FILTER (WHERE data_version='xlsx-7b6fcb18de6f8969-r4') AS r4_price_rows,
       count(*) FILTER (WHERE data_version='xlsx-7b6fcb18de6f8969-r4' AND is_active) AS r4_active_rows
FROM calc.attachment_price;

SELECT count(*) FILTER (WHERE calculation_status IS NULL) AS legacy_selection_rows_to_delete,
       count(*) FILTER (WHERE calculation_status IS NOT NULL) AS v2_selection_rows_to_keep
FROM calc.attachment_selection;

SELECT count(DISTINCT quote_id) AS quote_ids_losing_legacy_attachment_details,
       min(created_at) AS oldest_legacy_selection,
       max(created_at) AS newest_legacy_selection
FROM calc.attachment_selection
WHERE calculation_status IS NULL;

-- The cleanup script is intentionally closed to the three known referencing tables.
-- Any additional foreign key must be inspected before deletion.
SELECT con.conrelid::regclass::text AS source_table,
       con.conname,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
WHERE con.contype='f'
  AND con.confrelid='calc.attachment_price'::regclass
ORDER BY source_table,con.conname;

SELECT count(*) AS v2_orphans_before_cleanup
FROM calc.attachment_selection s
LEFT JOIN calc.attachment_price p USING(attachment_price_id)
WHERE s.calculation_status IS NOT NULL
  AND s.attachment_price_id IS NOT NULL
  AND p.attachment_price_id IS NULL;

COMMIT;
