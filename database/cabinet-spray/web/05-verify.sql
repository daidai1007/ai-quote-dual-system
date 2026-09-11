BEGIN READ ONLY;
SELECT data_version,status,source_sha256,activated_at
FROM calc.cabinet_spray_catalog_version ORDER BY created_at;
SELECT family,count(*) AS rules
FROM calc.cabinet_spray_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' GROUP BY family ORDER BY family;
SELECT count(*) AS duplicate_part_identities
FROM (
  SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,part_name
  FROM calc.cabinet_spray_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count,part_name
  HAVING count(*)>1
) duplicates;
SELECT product_code,profile_code,material_codes,count(*) AS fixed_rules
FROM calc.cabinet_spray_fixed_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' GROUP BY product_code,profile_code,material_codes ORDER BY product_code,profile_code,material_codes;
SELECT count(*) AS duplicate_fixed_identities FROM (
  SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm
  FROM calc.cabinet_spray_fixed_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1
) duplicates;
SELECT calc.get_cabinet_spray_fixed_cost('JQ_EXP','JQ609648','SECC',600,960,480) AS jq_secc,
       calc.get_cabinet_spray_fixed_cost('OP_TABLE_EXP','JM601210','SUS316',600,1200,1000) AS operation_table_sus316,
       calc.get_cabinet_spray_fixed_cost('JC_EXP','JC601660-1','SECC',600,1600,600) AS jc_luxury;
SELECT column_name FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result'
  AND column_name IN ('cabinet_spray_version','cabinet_spray_snapshot')
ORDER BY column_name;
COMMIT;
