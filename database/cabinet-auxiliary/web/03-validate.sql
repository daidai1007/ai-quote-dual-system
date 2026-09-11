BEGIN READ ONLY;
SELECT data_version,status,source_sha256 FROM calc.cabinet_auxiliary_catalog_version
WHERE data_version='cabinet-auxiliary-1dc400290ae91924-v1';
SELECT p.product_code,count(DISTINCT p.profile_id) AS profiles,count(l.line_id) AS lines
FROM calc.cabinet_auxiliary_profile p LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
WHERE p.data_version='cabinet-auxiliary-1dc400290ae91924-v1' GROUP BY p.product_code ORDER BY p.product_code;
SELECT p.product_code,p.single_door_count,p.double_door_count,count(*)
FROM calc.cabinet_auxiliary_profile p WHERE p.data_version='cabinet-auxiliary-1dc400290ae91924-v1'
GROUP BY p.product_code,p.single_door_count,p.double_door_count HAVING count(*)>1;
SELECT count(*) AS unsupported_quantity_rules FROM calc.cabinet_auxiliary_line l
JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
WHERE p.data_version='cabinet-auxiliary-1dc400290ae91924-v1'
  AND l.quantity_rule->>'kind' NOT IN ('CONSTANT','HEIGHT_GT');
COMMIT;
