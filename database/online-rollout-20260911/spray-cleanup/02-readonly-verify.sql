BEGIN READ ONLY;

SELECT CASE WHEN to_regclass('calc.experience_spray_price') IS NULL THEN 'PASS' ELSE 'FAIL' END
  AS legacy_spray_cleanup_state;

SELECT v.data_version,v.status,count(DISTINCT r.rule_id) AS area_rules,
       count(DISTINCT f.fixed_rule_id) AS fixed_rules
FROM calc.cabinet_spray_catalog_version v
LEFT JOIN calc.cabinet_spray_rule r USING(data_version)
LEFT JOIN calc.cabinet_spray_fixed_rule f USING(data_version)
GROUP BY v.data_version,v.status;

SELECT calc.get_cabinet_spray_fixed_cost('JQ_EXP','JQ609648','SECC',600,960,480) AS jq_secc,
       calc.get_cabinet_spray_fixed_cost('OP_TABLE_EXP','JM601210','SUS316',600,1200,1000) AS operation_table_sus316,
       calc.get_cabinet_spray_fixed_cost('JC_EXP','JC601660-1','SECC',600,1600,600) AS jc_luxury;

COMMIT;
