BEGIN READ ONLY;
SELECT data_version,status,source_sha256,source_files
FROM calc.cabinet_auxiliary_catalog_version
WHERE data_version='cabinet-auxiliary-706c234a5de12a39-v2';
SELECT p.product_code,count(DISTINCT p.profile_id) AS profiles,count(l.line_id) AS lines
FROM calc.cabinet_auxiliary_profile p LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
WHERE p.data_version='cabinet-auxiliary-706c234a5de12a39-v2'
GROUP BY p.product_code ORDER BY p.product_code;
SELECT product_code,count(*) AS fixed_rules
FROM calc.cabinet_auxiliary_fixed_rule
WHERE data_version='cabinet-auxiliary-706c234a5de12a39-v2'
GROUP BY product_code ORDER BY product_code;
SELECT p.product_code,p.single_door_count,p.double_door_count,count(*)
FROM calc.cabinet_auxiliary_profile p
WHERE p.data_version='cabinet-auxiliary-706c234a5de12a39-v2'
GROUP BY p.product_code,p.single_door_count,p.double_door_count HAVING count(*)>1;
SELECT count(*) AS unsupported_quantity_rules FROM calc.cabinet_auxiliary_line l
JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
WHERE p.data_version='cabinet-auxiliary-706c234a5de12a39-v2'
  AND l.quantity_rule->>'kind' NOT IN ('CONSTANT','HEIGHT_GT');
COMMIT;
