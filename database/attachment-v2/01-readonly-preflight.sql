-- Run against the intended target BEFORE approving migration assumptions.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT current_database(), current_user, version(), current_setting('server_encoding');
SELECT table_name,column_name,data_type,udt_name,character_maximum_length,
       numeric_precision,numeric_scale,is_nullable,column_default,is_identity
FROM information_schema.columns
WHERE table_schema='calc' AND table_name IN (
  'attachment_price','attachment_classification','attachment_selection',
  'material','material_price_history','spray_price','quote_document')
ORDER BY table_name,ordinal_position;
SELECT c.conrelid::regclass AS source_table,c.conname,c.contype,
       c.confrelid::regclass AS referenced_table,pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
WHERE c.conrelid IN (to_regclass('calc.attachment_price'),to_regclass('calc.attachment_classification'),to_regclass('calc.attachment_selection'))
   OR c.confrelid IN (to_regclass('calc.attachment_price'),to_regclass('calc.attachment_selection'));
SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
WHERE schemaname='calc' AND tablename LIKE 'attachment_%';
SELECT DISTINCT pg_describe_object(d.classid,d.objid,d.objsubid) AS dependent,
       pg_describe_object(d.refclassid,d.refobjid,d.refobjsubid) AS referenced,d.deptype
FROM pg_depend d WHERE d.refobjid IN (
  to_regclass('calc.attachment_price'),to_regclass('calc.attachment_classification'),to_regclass('calc.attachment_selection'));
SELECT p.oid::regprocedure AS signature,pg_get_functiondef(p.oid) AS definition
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='calc' AND p.prokind='f' AND
 (p.proname ILIKE '%attachment%' OR p.proname IN ('calculate_dual_quote','calculate_total_cost_for_quote','get_material_unit_price','get_spray_unit_price'));
SELECT schemaname,viewname,definition FROM pg_views
WHERE schemaname='calc' AND (definition ILIKE '%attachment%' OR viewname ILIKE '%attachment%');
SELECT event_object_table,trigger_name,action_statement FROM information_schema.triggers
WHERE event_object_schema='calc' AND event_object_table LIKE 'attachment_%';
SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class
WHERE oid IN (to_regclass('calc.attachment_price'),to_regclass('calc.attachment_selection'));
-- Aggregate counts only: no quote contents or customer data.
SELECT 'attachment_price' AS object_name,count(*) AS total,count(*) FILTER (WHERE is_active) AS active FROM calc.attachment_price
UNION ALL SELECT 'attachment_classification',count(*),NULL FROM calc.attachment_classification
UNION ALL SELECT 'attachment_selection',count(*),NULL FROM calc.attachment_selection;
SELECT attachment_price_id,count(*) FROM calc.attachment_classification GROUP BY attachment_price_id HAVING count(*)>1;
COMMIT;
