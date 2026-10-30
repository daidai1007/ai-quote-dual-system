-- Read only. Also run using the actual API database role after grants.
SELECT to_regclass('calc.quote_scheme_contract_link') IS NOT NULL AS links_present,
 to_regprocedure('calc.register_generated_contract(text,uuid,text)') IS NOT NULL AS registration_present;
SELECT column_name,data_type,is_nullable FROM information_schema.columns
WHERE table_schema='calc' AND table_name='quote_scheme'
 AND column_name IN ('source_kind','contracted_at','contract_amount','contract_record_id','contract_version_no','contract_source_kind')
ORDER BY column_name;
SELECT c.conrelid::regclass AS table_name,c.conname,pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c WHERE c.contype='c' AND c.conname IN ('quote_scheme_status_check','quote_scheme_version_status_check');
SELECT tgname,tgenabled FROM pg_trigger WHERE tgrelid='calc.quote_scheme_contract_link'::regclass AND NOT tgisinternal;
SELECT has_table_privilege(current_user,'calc.quote_scheme_contract_link','SELECT')
 AND has_table_privilege(current_user,'calc.quote_scheme_contract_link','INSERT') AS can_link,
 has_sequence_privilege(current_user,'calc.quote_scheme_contract_link_link_id_seq','USAGE') AS can_number_link,
 has_function_privilege(current_user,'calc.register_generated_contract(text,uuid,text)','EXECUTE') AS can_register;
-- No historical backfill. Older contracts without a link are intentionally valid.
SELECT count(*) AS linked_new_contracts FROM calc.quote_scheme_contract_link;
SELECT count(*) AS invalid_scheme_contract_links
FROM calc.quote_scheme_contract_link l LEFT JOIN calc.quote_scheme s USING(scheme_id)
WHERE s.scheme_id IS NULL OR (l.source_kind='QUOTE' AND NOT EXISTS(SELECT 1 FROM calc.contract_generation g WHERE g.record_id=l.contract_record_id))
 OR (l.source_kind='LEDGER' AND NOT EXISTS(SELECT 1 FROM calc.ledger_contract_generation g WHERE g.record_id=l.contract_record_id));
