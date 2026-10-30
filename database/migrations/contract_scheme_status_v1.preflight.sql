-- Read only. Run on the intended database with ON_ERROR_STOP, before deployment.
DO $$ BEGIN
 IF to_regclass('calc.quote_scheme') IS NULL OR to_regclass('calc.quote_scheme_version') IS NULL
    OR to_regclass('calc.quote_scheme_snapshot') IS NULL OR to_regclass('calc.quote_scheme_item') IS NULL
    OR to_regclass('calc.quote_scheme_audit') IS NULL OR to_regclass('calc.contract_generation') IS NULL
    OR to_regclass('calc.ledger_contract_generation') IS NULL
    OR to_regprocedure('calc.next_quote_scheme_number()') IS NULL THEN
   RAISE EXCEPTION 'Apply existing scheme, contract and ledger schema prerequisites first';
 END IF;
END $$;
SELECT current_database() AS database_name,current_user AS execution_role;
SELECT c.conrelid::regclass AS table_name,c.conname,pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
WHERE c.contype='c' AND a.attname='status' AND c.conrelid IN ('calc.quote_scheme'::regclass,'calc.quote_scheme_version'::regclass);
SELECT status,count(*) AS scheme_count FROM calc.quote_scheme GROUP BY status ORDER BY status;
SELECT to_regprocedure('calc.register_generated_contract(text,uuid,text)') IS NOT NULL AS already_installed;
