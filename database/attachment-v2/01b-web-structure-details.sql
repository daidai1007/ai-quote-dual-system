-- Web SQL editor: one SELECT, one row; no psql commands and no business data.
WITH targets AS (
  SELECT oid,relname FROM pg_class
  WHERE oid IN (to_regclass('calc.attachment_price'),
    to_regclass('calc.attachment_classification'),to_regclass('calc.attachment_selection'))
), columns_info AS (
  SELECT table_name,column_name,data_type,udt_name,character_maximum_length,
    numeric_precision,numeric_scale,is_nullable,column_default,is_identity
  FROM information_schema.columns
  WHERE table_schema='calc' AND table_name IN (SELECT relname FROM targets)
  ORDER BY table_name,ordinal_position
), constraints_info AS (
  SELECT c.conrelid::regclass::text AS source_table,c.conname,c.contype,
    c.confrelid::regclass::text AS referenced_table,pg_get_constraintdef(c.oid) AS definition
  FROM pg_constraint c
  WHERE c.conrelid IN (SELECT oid FROM targets) OR c.confrelid IN (SELECT oid FROM targets)
  ORDER BY source_table,c.conname
), indexes_info AS (
  SELECT tablename,indexname,indexdef FROM pg_indexes
  WHERE schemaname='calc' AND tablename IN (SELECT relname FROM targets)
  ORDER BY tablename,indexname
), triggers_info AS (
  SELECT t.tgrelid::regclass::text AS table_name,t.tgname,t.tgenabled,
    pg_get_triggerdef(t.oid) AS definition,pg_get_functiondef(t.tgfoid) AS function_definition
  FROM pg_trigger t WHERE t.tgrelid IN (SELECT oid FROM targets) AND NOT t.tgisinternal
), policies_info AS (
  SELECT * FROM pg_policies WHERE schemaname='calc' AND tablename IN (SELECT relname FROM targets)
), access_info AS (
  SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,
    pg_get_userbyid(c.relowner) AS owner,c.relacl,
    has_table_privilege(c.oid,'SELECT') AS can_select,
    has_table_privilege(c.oid,'INSERT') AS can_insert,
    has_table_privilege(c.oid,'UPDATE') AS can_update
  FROM pg_class c WHERE c.oid IN (SELECT oid FROM targets)
), dependencies_info AS (
  SELECT DISTINCT pg_describe_object(d.classid,d.objid,d.objsubid) AS dependent,
    pg_describe_object(d.refclassid,d.refobjid,d.refobjsubid) AS referenced,d.deptype
  FROM pg_depend d WHERE d.refclassid='pg_class'::regclass AND d.refobjid IN (SELECT oid FROM targets)
), functions_info AS (
  SELECT p.oid::regprocedure::text AS signature,pg_get_functiondef(p.oid) AS definition
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='calc' AND p.prokind='f' AND
    (p.proname ILIKE '%attachment%' OR p.proname IN ('calculate_dual_quote','calculate_total_cost_for_quote'))
), views_info AS (
  SELECT viewname,definition FROM pg_views WHERE schemaname='calc'
    AND (definition ILIKE '%attachment%' OR viewname ILIKE '%attachment%')
)
SELECT jsonb_pretty(jsonb_build_object(
  'database',current_database(),'role',current_user,'server',version(),
  'columns',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM columns_info x),'[]'::jsonb),
  'constraints',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM constraints_info x),'[]'::jsonb),
  'indexes',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM indexes_info x),'[]'::jsonb),
  'triggers',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM triggers_info x),'[]'::jsonb),
  'policies',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM policies_info x),'[]'::jsonb),
  'access',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM access_info x),'[]'::jsonb),
  'dependencies',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM dependencies_info x),'[]'::jsonb),
  'functions',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM functions_info x),'[]'::jsonb),
  'views',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM views_info x),'[]'::jsonb)
)) AS attachment_structure_report;
