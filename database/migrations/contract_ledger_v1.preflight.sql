-- Read-only checks. Run against the intended database before the migration.
SELECT current_database() AS database_name,current_user AS execution_role,
       to_regclass('calc.contract_template_version') IS NOT NULL AS templates_present,
       to_regclass('calc.contract_record_number') IS NOT NULL AS number_sequence_present,
       to_regclass('calc.contract_audit') IS NOT NULL AS audit_present,
       to_regprocedure('calc.guard_contract_immutable()') IS NOT NULL AS immutable_guard_present;
SELECT table_name,column_name,is_nullable
FROM information_schema.columns WHERE table_schema='calc'
  AND table_name='contract_generation' AND column_name IN('source_scheme_id','source_version_no','quote_method')
ORDER BY column_name;
