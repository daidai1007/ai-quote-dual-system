BEGIN READ ONLY;
SELECT v.data_version,v.source_file,v.source_sha256,v.status,v.default_waste_factor,
       count(r.rule_id) AS rules,count(DISTINCT r.family) AS families
FROM calc.cabinet_material_catalog_version v LEFT JOIN calc.cabinet_material_rule r USING(data_version)
WHERE v.data_version='cabinet-material-91cc0a5f841b7455-v1'
GROUP BY v.data_version,v.source_file,v.source_sha256,v.status,v.default_waste_factor;
SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,count(*) AS parts
FROM calc.cabinet_material_rule WHERE data_version='cabinet-material-91cc0a5f841b7455-v1'
GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count
ORDER BY family,body_thickness_profile_mm,single_door_count,double_door_count;
SELECT family,count(*) FILTER(WHERE fixed_material_code='SECC') AS fixed_secc_rows,
       count(*) FILTER(WHERE fixed_material_code IS NULL) AS selected_material_rows
FROM calc.cabinet_material_rule WHERE data_version='cabinet-material-91cc0a5f841b7455-v1'
GROUP BY family ORDER BY family;
COMMIT;
