BEGIN READ ONLY;

SELECT v.data_version,v.status,count(DISTINCT r.rule_id) AS area_rules,
       count(DISTINCT f.fixed_rule_id) AS fixed_rules
FROM calc.cabinet_spray_catalog_version v
LEFT JOIN calc.cabinet_spray_rule r USING(data_version)
LEFT JOIN calc.cabinet_spray_fixed_rule f USING(data_version)
GROUP BY v.data_version,v.status,v.created_at ORDER BY v.created_at;

SELECT to_regclass('calc.experience_spray_price') AS legacy_experience_spray_table,
       coalesce(s.n_live_tup,0) AS estimated_legacy_rows
FROM (SELECT 1) seed
LEFT JOIN pg_stat_user_tables s
  ON s.schemaname='calc' AND s.relname='experience_spray_price';

SELECT p.oid::regprocedure::text AS function_still_referencing_legacy_spray
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='calc' AND p.prokind IN ('f','p')
  AND pg_get_functiondef(p.oid) ILIKE '%calc.experience_spray_price%'
ORDER BY 1;

SELECT dependent_ns.nspname AS dependent_schema,dependent_view.relname AS dependent_view
FROM pg_depend d
JOIN pg_rewrite r ON r.oid=d.objid
JOIN pg_class dependent_view ON dependent_view.oid=r.ev_class
JOIN pg_namespace dependent_ns ON dependent_ns.oid=dependent_view.relnamespace
WHERE d.refobjid=to_regclass('calc.experience_spray_price')
ORDER BY 1,2;

COMMIT;
