-- Production preflight for the 2026-09-11 attachment and formula-cost catalogs rollout.
-- Read-only: safe to run before any deployment or catalog switch.
BEGIN READ ONLY;

SELECT current_database() AS database_name,
       current_user AS database_role,
       version() AS server_version,
       current_setting('server_encoding') AS server_encoding;

SELECT table_name
FROM information_schema.tables
WHERE table_schema='calc'
  AND table_name IN (
    'attachment_price','attachment_classification','attachment_selection',
    'attachment_catalog_version','attachment_cost_rule',
    'attachment_cost_rule_product','attachment_cost_rule_material',
    'attachment_cost_rule_binding','attachment_cost_rule_parameter',
    'attachment_quote_line','cabinet_material_catalog_version',
    'cabinet_material_rule','cabinet_material_fixed_rule','cabinet_spray_catalog_version','cabinet_spray_rule','cabinet_spray_fixed_rule',
    'cabinet_labor_catalog_version','cabinet_labor_rule',
    'cabinet_auxiliary_catalog_version','cabinet_auxiliary_profile','cabinet_auxiliary_line','cabinet_auxiliary_fixed_rule',
    'experience_spray_price','cabinet_part_rule','dual_quote_result'
  )
ORDER BY table_name;

SELECT data_version,status,source_sha256,created_at,activated_at
FROM calc.attachment_catalog_version
ORDER BY created_at;

SELECT v.data_version,v.status,
       (SELECT count(*) FROM calc.attachment_price p
        WHERE p.data_version=v.data_version) AS catalog_rows,
       (SELECT count(*) FROM calc.attachment_price p
        WHERE p.data_version=v.data_version AND p.is_active) AS active_rows,
       (SELECT count(*) FROM calc.attachment_cost_rule r
        WHERE r.data_version=v.data_version) AS cost_rules
FROM calc.attachment_catalog_version v
ORDER BY v.created_at;

SELECT count(*) AS attachment_price_total,
       count(*) FILTER (WHERE is_active) AS attachment_price_active,
       count(*) FILTER (WHERE data_version IS NULL) AS legacy_price_rows
FROM calc.attachment_price;

SELECT count(*) AS attachment_selection_total,
       count(*) FILTER (WHERE calculation_status IS NULL) AS legacy_selection_rows,
       count(*) FILTER (WHERE calculation_status IS NOT NULL) AS v2_selection_rows
FROM calc.attachment_selection;

SELECT count(*) AS inactive_legacy_prices_not_referenced_by_history
FROM calc.attachment_price p
WHERE p.data_version IS NULL
  AND NOT p.is_active
  AND NOT EXISTS (
    SELECT 1 FROM calc.attachment_selection s
    WHERE s.attachment_price_id=p.attachment_price_id
  );

SELECT CASE WHEN to_regclass('calc.cabinet_material_catalog_version') IS NULL
            THEN 'NOT_CREATED' ELSE 'CREATED' END AS cabinet_material_schema_state;
SELECT CASE WHEN to_regclass('calc.cabinet_spray_catalog_version') IS NULL
            THEN 'NOT_CREATED' ELSE 'CREATED' END AS cabinet_spray_schema_state;
SELECT CASE WHEN to_regclass('calc.cabinet_labor_catalog_version') IS NULL
            THEN 'NOT_CREATED' ELSE 'CREATED' END AS cabinet_labor_schema_state;
SELECT CASE WHEN to_regclass('calc.cabinet_auxiliary_catalog_version') IS NULL
            THEN 'NOT_CREATED' ELSE 'CREATED' END AS cabinet_auxiliary_schema_state;

-- Version/rule details are checked by cabinet-material/web/03-validate.sql after
-- the additive schema has been created. Do not reference those optional tables
-- here because PostgreSQL resolves relation names before evaluating a CASE.

-- Every foreign key touching the current or replacement attachment/cabinet tables.
SELECT con.conrelid::regclass::text AS source_table,
       con.conname,
       pg_get_constraintdef(con.oid) AS definition,
       con.confrelid::regclass::text AS referenced_table
FROM pg_constraint con
WHERE con.contype='f'
  AND (
    con.conrelid IN (
      SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='calc' AND c.relname ~ '^(attachment_|cabinet_)'
    )
    OR con.confrelid IN (
      SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='calc' AND c.relname ~ '^(attachment_|cabinet_)'
    )
  )
ORDER BY source_table,con.conname;

-- Inventory only. A name match does not prove that an object can be dropped.
SELECT c.relkind,n.nspname AS schema_name,c.relname AS object_name,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='calc'
  AND c.relkind IN ('r','p')
  AND (c.relname ILIKE '%attachment%' OR c.relname ILIKE '%cabinet%')
ORDER BY c.relname;

COMMIT;
