-- Read-only verification after 01-clean-and-activate-r4.sql.
BEGIN READ ONLY;

SELECT CASE
  WHEN count(*) FILTER (WHERE is_active)=226
   AND count(*) FILTER (
         WHERE is_active AND data_version='xlsx-7b6fcb18de6f8969-r4'
       )=226
   AND count(*) FILTER (WHERE data_version IS NULL)=0
  THEN 'PASS' ELSE 'FAIL'
END AS attachment_cleanup_state,
count(*) AS attachment_price_total,
count(*) FILTER (WHERE is_active) AS active_rows,
count(*) FILTER (WHERE data_version IS NULL) AS legacy_price_rows
FROM calc.attachment_price;

SELECT data_version,status,source_sha256,activated_at
FROM calc.attachment_catalog_version
ORDER BY created_at;

SELECT count(*) FILTER (WHERE calculation_status IS NULL) AS legacy_selection_rows,
       count(*) FILTER (WHERE calculation_status IS NOT NULL) AS v2_selection_rows
FROM calc.attachment_selection;

SELECT count(*) AS active_prices_missing_classification
FROM calc.attachment_price p
LEFT JOIN calc.attachment_classification c USING(attachment_price_id)
WHERE p.is_active AND c.attachment_price_id IS NULL;

SELECT count(*) AS orphan_attachment_selections
FROM calc.attachment_selection s
LEFT JOIN calc.attachment_price p USING(attachment_price_id)
WHERE s.attachment_price_id IS NOT NULL
  AND p.attachment_price_id IS NULL;

-- These four formula-cost catalogs must remain STAGED during this attachment-only cleanup.
SELECT 'cabinet_material' AS catalog,data_version,status
FROM calc.cabinet_material_catalog_version
UNION ALL
SELECT 'cabinet_spray',data_version,status
FROM calc.cabinet_spray_catalog_version
UNION ALL
SELECT 'cabinet_auxiliary',data_version,status
FROM calc.cabinet_auxiliary_catalog_version
UNION ALL
SELECT 'cabinet_labor',data_version,status
FROM calc.cabinet_labor_catalog_version
ORDER BY catalog,data_version;

COMMIT;
