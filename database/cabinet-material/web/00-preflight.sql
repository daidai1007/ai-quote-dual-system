-- Neon SQL Editor; read-only inspection before cabinet-material migration.
BEGIN READ ONLY;
SELECT current_database() AS database_name,current_user AS database_role,version() AS server_version;
SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default
FROM information_schema.columns
WHERE table_schema='calc' AND table_name IN
 ('material','material_price_history','dual_quote_result','cabinet_template','cabinet_part_rule','template_formula_mapping')
ORDER BY table_name,ordinal_position;
SELECT p.oid::regprocedure::text AS signature
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='calc' AND p.proname IN ('get_material_unit_price','calculate_dual_quote')
ORDER BY 1;
SELECT to_regclass('calc.cabinet_material_catalog_version') AS version_table,
       to_regclass('calc.cabinet_material_rule') AS rule_table;
SELECT material_code,density_g_cm3
FROM calc.material WHERE material_code IN ('SECC','SUS304','SUS316') ORDER BY material_code;
COMMIT;
