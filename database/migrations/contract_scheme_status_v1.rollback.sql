-- Manual rollback ONLY before any new contract has used this feature.
-- This script refuses to delete contracts, schemes or associations.
BEGIN;
SET LOCAL lock_timeout='5s';
LOCK TABLE calc.quote_scheme,calc.quote_scheme_version,calc.quote_scheme_contract_link IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM calc.quote_scheme_contract_link)
    OR EXISTS(SELECT 1 FROM calc.quote_scheme WHERE status='CONTRACT' OR source_kind='LEDGER_CONTRACT' OR contract_record_id IS NOT NULL)
    OR EXISTS(SELECT 1 FROM calc.quote_scheme_version WHERE status='CONTRACT') THEN
   RAISE EXCEPTION 'New contract data exists; rollback refused. Keep schema and use a forward fix.';
 END IF;
END $$;
DROP FUNCTION calc.register_generated_contract(text,uuid,text);
DROP TABLE calc.quote_scheme_contract_link;
DROP FUNCTION calc.guard_scheme_contract_link();
ALTER TABLE calc.quote_scheme DROP CONSTRAINT quote_scheme_status_check;
ALTER TABLE calc.quote_scheme_version DROP CONSTRAINT quote_scheme_version_status_check;
ALTER TABLE calc.quote_scheme ADD CONSTRAINT quote_scheme_status_check CHECK(status IN ('DRAFT','QUOTED','REVISING','ARCHIVED','VOID'));
ALTER TABLE calc.quote_scheme_version ADD CONSTRAINT quote_scheme_version_status_check CHECK(status IN ('QUOTED','ARCHIVED','VOID'));
ALTER TABLE calc.quote_scheme DROP COLUMN source_kind,DROP COLUMN contracted_at,DROP COLUMN contract_amount,
 DROP COLUMN contract_record_id,DROP COLUMN contract_version_no,DROP COLUMN contract_source_kind;
COMMIT;
