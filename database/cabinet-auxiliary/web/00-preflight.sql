BEGIN READ ONLY;
SELECT current_database(),current_user,version();
SELECT to_regclass('calc.dual_quote_result') AS dual_quote_result,
       to_regclass('calc.auxiliary_bom') AS old_auxiliary_bom,
       to_regclass('calc.auxiliary_bom_line') AS old_auxiliary_bom_line,
       to_regclass('calc.auxiliary_experience_price') AS old_auxiliary_experience_price,
       to_regclass('calc.cabinet_auxiliary_catalog_version') AS versioned_auxiliary,
       to_regclass('calc.cabinet_auxiliary_fixed_rule') AS versioned_fixed_rules;
SELECT column_name,data_type FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result' ORDER BY ordinal_position;
SELECT v.data_version,v.status,count(DISTINCT p.profile_id) AS profiles,
       count(DISTINCT l.line_id) AS lines,count(DISTINCT r.rule_id) AS fixed_rules
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
LEFT JOIN calc.cabinet_auxiliary_fixed_rule r ON r.data_version=v.data_version
GROUP BY v.data_version,v.status,v.created_at ORDER BY v.created_at;
COMMIT;
