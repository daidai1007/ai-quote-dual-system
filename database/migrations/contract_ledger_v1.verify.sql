-- Read-only metadata checks; no customer rows, file contents or prices emitted.
SELECT to_regclass('calc.ledger_contract_draft') IS NOT NULL AS ledger_drafts_present,
       to_regclass('calc.ledger_contract_generation') IS NOT NULL AS ledger_records_present;
SELECT tgname,tgenabled FROM pg_trigger
WHERE tgrelid=to_regclass('calc.ledger_contract_generation') AND NOT tgisinternal;
SELECT table_name,column_name,is_nullable
FROM information_schema.columns WHERE table_schema='calc'
  AND table_name='contract_generation' AND column_name IN('source_scheme_id','source_version_no','quote_method')
ORDER BY column_name;
SELECT has_table_privilege(current_user,'calc.ledger_contract_draft','SELECT,INSERT,UPDATE') AS can_use_ledger_drafts,
       has_table_privilege(current_user,'calc.ledger_contract_generation','SELECT,INSERT') AS can_generate_ledger_records;
