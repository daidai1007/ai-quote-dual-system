-- Operator supplies the EXISTING API role, e.g. psql -v attachment_api_role=...
-- No role/account is created. This task does not run this on production.
\set ON_ERROR_STOP on
\if :{?attachment_api_role}
BEGIN;
SELECT format('GRANT SELECT,INSERT,UPDATE ON calc.attachment_maintenance_revision TO %I', :'attachment_api_role') \gexec
SELECT format('GRANT SELECT,INSERT ON calc.attachment_maintenance_audit TO %I', :'attachment_api_role') \gexec
SELECT format('GRANT SELECT,INSERT,UPDATE ON calc.attachment_price TO %I', :'attachment_api_role') \gexec
SELECT format('GRANT SELECT,INSERT ON calc.attachment_classification,calc.attachment_cost_rule,calc.attachment_cost_rule_binding,calc.attachment_cost_rule_product,calc.attachment_cost_rule_material TO %I', :'attachment_api_role') \gexec
SELECT format('GRANT SELECT ON calc.attachment_catalog_version TO %I', :'attachment_api_role') \gexec
SELECT format('GRANT USAGE,SELECT ON SEQUENCE %s TO %I',pg_get_serial_sequence(t,col),:'attachment_api_role')
 FROM (VALUES('calc.attachment_price','attachment_price_id'),('calc.attachment_cost_rule','rule_id'),('calc.attachment_maintenance_audit','event_id')) x(t,col) \gexec
SELECT format('GRANT EXECUTE ON FUNCTION calc.maintain_fixed_attachment(jsonb,text,text) TO %I', :'attachment_api_role') \gexec
COMMIT;
\else
\echo 'Stop: provide attachment_api_role for the existing API database role.'
\quit 1
\endif
