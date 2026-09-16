BEGIN READ ONLY;
SELECT v.data_version,v.status,count(DISTINCT p.profile_id) AS profiles,
       count(DISTINCT l.line_id) AS lines,count(DISTINCT r.rule_id) AS fixed_rules
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
LEFT JOIN calc.cabinet_auxiliary_fixed_rule r ON r.data_version=v.data_version
GROUP BY v.data_version,v.status ORDER BY v.created_at;
SELECT count(*) FILTER(WHERE status='ACTIVE') AS active_versions FROM calc.cabinet_auxiliary_catalog_version;
SELECT p.product_code,p.single_door_count,p.double_door_count,m.material_code,count(*) AS profiles
FROM calc.cabinet_auxiliary_profile p
JOIN calc.cabinet_auxiliary_catalog_version v USING(data_version)
CROSS JOIN LATERAL jsonb_array_elements_text(p.material_codes) AS m(material_code)
WHERE v.status='ACTIVE'
GROUP BY p.product_code,p.single_door_count,p.double_door_count,m.material_code HAVING count(*)<>1;
SELECT calc.get_auxiliary_cost('JK','DEFAULT','','SECC',300,200,80) AS jk_secc,
       calc.get_auxiliary_cost('JQ_EXP','DEFAULT','JQ609648','SUS316',600,960,480) AS jq_sus316,
       calc.get_auxiliary_cost('JC_EXP','DEFAULT','JC601660-1','SECC',600,1600,600) AS jc_luxury;
COMMIT;
