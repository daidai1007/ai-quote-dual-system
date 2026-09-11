BEGIN READ ONLY;
SELECT v.data_version,v.source_file,v.source_sha256,v.source_files,v.status,
       count(DISTINCT r.rule_id) AS area_rules,count(DISTINCT r.family) AS families,
       count(DISTINCT f.fixed_rule_id) AS fixed_rules,count(DISTINCT f.product_code) AS fixed_products
FROM calc.cabinet_spray_catalog_version v
LEFT JOIN calc.cabinet_spray_rule r USING(data_version)
LEFT JOIN calc.cabinet_spray_fixed_rule f USING(data_version)
WHERE v.data_version='cabinet-spray-4b3d73c9cb7a6f26-v2'
GROUP BY v.data_version,v.source_file,v.source_sha256,v.source_files,v.status;
SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,count(*) AS parts
FROM calc.cabinet_spray_rule
WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2'
GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count
ORDER BY family,body_thickness_profile_mm,single_door_count,double_door_count;
SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,part_name,count(*)
FROM calc.cabinet_spray_rule
WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2'
GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count,part_name
HAVING count(*)>1;
SELECT product_code,profile_code,material_codes,count(*) AS fixed_rules
FROM calc.cabinet_spray_fixed_rule
WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2'
GROUP BY product_code,profile_code,material_codes ORDER BY product_code,profile_code,material_codes;
SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm,count(*)
FROM calc.cabinet_spray_fixed_rule
WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2'
GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1;
COMMIT;
