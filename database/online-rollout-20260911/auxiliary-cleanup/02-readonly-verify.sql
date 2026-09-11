BEGIN READ ONLY;

SELECT CASE
  WHEN to_regclass('calc.auxiliary_bom') IS NULL
   AND to_regclass('calc.auxiliary_bom_line') IS NULL
   AND to_regclass('calc.auxiliary_experience_price') IS NULL
  THEN 'PASS' ELSE 'FAIL' END AS legacy_auxiliary_cleanup_state;

SELECT v.data_version,v.status,count(DISTINCT p.profile_id) AS profiles,
       count(DISTINCT l.line_id) AS bom_lines,count(DISTINCT r.rule_id) AS fixed_rules
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
LEFT JOIN calc.cabinet_auxiliary_fixed_rule r ON r.data_version=v.data_version
GROUP BY v.data_version,v.status;

SELECT calc.get_auxiliary_cost('JK','DEFAULT','','SECC',300,200,80) AS jk_secc,
       calc.get_auxiliary_cost('JQ_EXP','DEFAULT','JQ609648','SUS316',600,960,480) AS jq_sus316,
       calc.get_auxiliary_cost('JC_EXP','DEFAULT','JC601660-1','SECC',600,1600,600) AS jc_luxury;

COMMIT;
