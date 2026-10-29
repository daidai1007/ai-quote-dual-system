-- Restore only this migration's definitions; refuse to overwrite later repairs.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $rollback$
DECLARE item record;identity regprocedure;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
      WHERE p.oid=to_regprocedure('calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)')
        AND md5(p.prosrc)='d56ee2d8703d1a8ad921ff173de409e7'
        AND l.lanname='sql' AND p.provolatile='i' AND p.proisstrict
        AND p.proparallel='s' AND NOT p.prosecdef AND p.proconfig IS NULL
        AND p.prorettype='numeric[]'::regtype AND NOT p.proretset) THEN
    RAISE EXCEPTION 'Rank helper missing or changed; manual review required';
  END IF;
  FOR item IN SELECT * FROM calc.experience_dimension_match_backup
    WHERE migration_key='width-perimeter-area-20261028-v1'
  LOOP
    identity:=to_regprocedure(item.function_identity);
    IF identity IS NULL OR md5(pg_get_functiondef(identity))<>item.patched_definition_md5 THEN
      RAISE EXCEPTION 'Matcher has newer changes; manual review required: %',item.function_identity;
    END IF;
    EXECUTE item.original_definition;
  END LOOP;
  DELETE FROM calc.experience_dimension_match_backup WHERE migration_key='width-perimeter-area-20261028-v1';
END;
$rollback$;
DROP FUNCTION calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric);
COMMIT;
