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
SELECT column_name FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result'
  AND column_name IN ('cabinet_spray_version','cabinet_spray_snapshot')
ORDER BY column_name;
COMMIT;
