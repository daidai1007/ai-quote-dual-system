BEGIN READ ONLY;

SELECT current_database(),current_user,now();

SELECT v.data_version,v.status,v.source_sha256,v.source_files,
       count(DISTINCT p.profile_id) AS profiles,
       count(DISTINCT l.line_id) AS bom_lines,
       count(DISTINCT r.rule_id) AS fixed_rules
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
LEFT JOIN calc.cabinet_auxiliary_fixed_rule r ON r.data_version=v.data_version
GROUP BY v.data_version,v.status,v.source_sha256,v.source_files,v.created_at
ORDER BY v.created_at;

SELECT to_regclass('calc.auxiliary_bom') AS old_auxiliary_bom,
       to_regclass('calc.auxiliary_bom_line') AS old_auxiliary_bom_line,
       to_regclass('calc.auxiliary_experience_price') AS old_auxiliary_experience_price,
       to_regclass('calc.v_auxiliary_bom_cost') AS old_bom_view,
       to_regclass('calc.v_auxiliary_experience_price') AS old_experience_view;

SELECT n.nspname AS schema_name,p.proname AS function_name,
       pg_get_function_identity_arguments(p.oid) AS arguments
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='calc' AND p.prokind IN ('f','p') AND (
  pg_get_functiondef(p.oid) ILIKE '%auxiliary_bom%'
  OR pg_get_functiondef(p.oid) ILIKE '%auxiliary_experience_price%')
ORDER BY p.proname;

COMMIT;
