-- Compare saved counts with preflight when no new quotes are being created.
SELECT count(*) AS active_catalogs FROM calc.attachment_catalog_version WHERE status='ACTIVE';
SELECT count(*) AS saved_attachment_selections FROM calc.attachment_selection;
SELECT count(*) AS saved_quote_lines FROM calc.attachment_quote_line;
SELECT count(*) AS maintenance_events FROM calc.attachment_maintenance_audit;
SELECT count(*) AS retired_revision_still_active_should_be_zero FROM calc.attachment_maintenance_revision m
 JOIN calc.attachment_price p USING(attachment_price_id) WHERE NOT m.is_current AND p.is_active;
SELECT count(*) AS missing_fixed_rules_should_be_zero FROM calc.attachment_maintenance_revision m
 WHERE m.is_current AND NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_binding b
 JOIN calc.attachment_cost_rule r USING(rule_id) WHERE b.attachment_price_id=m.attachment_price_id AND r.method='FIXED');
SELECT tgname,tgenabled FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN
 ('calc.attachment_selection'::regclass,'calc.attachment_quote_line'::regclass,'calc.attachment_maintenance_audit'::regclass);
