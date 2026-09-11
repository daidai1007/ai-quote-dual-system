BEGIN READ ONLY;
SELECT v.data_version,v.source_file,v.source_sha256,v.status,
       count(r.rule_id) AS rules,count(DISTINCT r.family) AS families
FROM calc.cabinet_spray_catalog_version v
LEFT JOIN calc.cabinet_spray_rule r USING(data_version)
WHERE v.data_version='cabinet-spray-13f257f440859e3b-v1'
GROUP BY v.data_version,v.source_file,v.source_sha256,v.status;
SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,count(*) AS parts
FROM calc.cabinet_spray_rule
WHERE data_version='cabinet-spray-13f257f440859e3b-v1'
GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count
ORDER BY family,body_thickness_profile_mm,single_door_count,double_door_count;
SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,part_name,count(*)
FROM calc.cabinet_spray_rule
WHERE data_version='cabinet-spray-13f257f440859e3b-v1'
GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count,part_name
HAVING count(*)>1;
COMMIT;
