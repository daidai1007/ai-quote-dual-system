-- Read-only identity/existence check. No credentials or order payloads returned.
BEGIN READ ONLY;
SELECT current_database() AS database_name,current_user AS execution_role,
       current_setting('server_version') AS server_version,inet_server_addr() AS server_address;
SELECT signature,to_regprocedure(signature) IS NOT NULL AS exists
FROM (VALUES
 ('calc.match_quick_quote(character varying,character varying,character varying,numeric,numeric,numeric,date)'),
 ('calc.get_cabinet_material_fixed_weight(character varying,character varying,character varying,numeric,numeric,numeric)'),
 ('calc.get_cabinet_spray_fixed_cost(character varying,character varying,character varying,numeric,numeric,numeric)'),
 ('calc.get_auxiliary_cost(character varying,character varying,character varying,character varying,integer,integer,integer)'),
 ('calc.get_labor_cost_with_dimension_match(character varying,character varying,character varying,numeric,numeric,numeric)')
) AS expected(signature);
SELECT to_regclass('calc.experience_dimension_match_backup') IS NOT NULL AS migration_backup_exists;
SELECT CASE WHEN to_regprocedure('calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)') IS NULL
  THEN 'NOT_INSTALLED'
  WHEN EXISTS (SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
      WHERE p.oid=to_regprocedure('calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)')
        AND md5(p.prosrc)='d56ee2d8703d1a8ad921ff173de409e7'
        AND l.lanname='sql' AND p.provolatile='i' AND p.proisstrict
        AND p.proparallel='s' AND NOT p.prosecdef AND p.proconfig IS NULL
        AND p.prorettype='numeric[]'::regtype AND NOT p.proretset)
  THEN 'KNOWN_HELPER' ELSE 'STOP_UNKNOWN_HELPER' END AS rank_helper_status;
COMMIT;
