-- Neon SQL Editor: read-only inspection before cabinet-spray migration.
BEGIN READ ONLY;
SELECT current_database() AS database_name,current_user AS database_role,version() AS server_version;
SELECT to_regclass('calc.spray_price') AS spray_price_table,
       to_regclass('calc.dual_quote_result') AS dual_quote_result_table,
       to_regclass('calc.cabinet_part_rule') AS legacy_shared_rule_table;
SELECT p.oid::regprocedure::text AS signature
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='calc' AND p.proname='get_spray_unit_price';
SELECT to_regclass('calc.cabinet_spray_catalog_version') AS version_table,
       to_regclass('calc.cabinet_spray_rule') AS area_rule_table,
       to_regclass('calc.cabinet_spray_fixed_rule') AS fixed_rule_table,
       to_regclass('calc.experience_spray_price') AS legacy_experience_spray_table;
COMMIT;
