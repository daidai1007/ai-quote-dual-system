-- Read-only metadata/counts. Does not expose names, prices or quote payloads.
SELECT current_setting('server_version') AS postgres_version;
SELECT name,to_regclass(name) IS NOT NULL AS present FROM unnest(ARRAY[
 'calc.attachment_price','calc.attachment_classification','calc.attachment_cost_rule',
 'calc.attachment_cost_rule_binding','calc.attachment_cost_rule_product','calc.attachment_cost_rule_material',
 'calc.attachment_catalog_version','calc.attachment_selection','calc.attachment_quote_line']) name;
SELECT count(*) AS active_catalogs FROM calc.attachment_catalog_version WHERE status='ACTIVE';
SELECT count(*) AS saved_attachment_selections FROM calc.attachment_selection;
SELECT count(*) AS saved_quote_lines FROM calc.attachment_quote_line;
SELECT tgname,tgenabled FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN
 ('calc.attachment_selection'::regclass,'calc.attachment_quote_line'::regclass);
SELECT table_name,column_name,data_type,numeric_precision,numeric_scale,character_maximum_length
 FROM information_schema.columns WHERE table_schema='calc' AND table_name IN ('attachment_price','attachment_classification')
 ORDER BY table_name,ordinal_position;
SELECT c.relname,con.conname,pg_get_constraintdef(con.oid) AS definition FROM pg_constraint con
 JOIN pg_class c ON c.oid=con.conrelid WHERE con.conrelid IN ('calc.attachment_price'::regclass,'calc.attachment_classification'::regclass);
