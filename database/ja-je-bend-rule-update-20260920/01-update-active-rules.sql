BEGIN;

DO $$
DECLARE material_rows integer; spray_rows integer;
BEGIN
  SELECT count(*) INTO material_rows FROM calc.cabinet_material_rule r
  JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.single_door_count=0 AND r.double_door_count=1
    AND ((r.family='JA' AND r.part_name='走线弯角件') OR (r.family='JE' AND r.part_name='走线弯角件1'));
  SELECT count(*) INTO spray_rows FROM calc.cabinet_spray_rule r
  JOIN calc.cabinet_spray_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.single_door_count=0 AND r.double_door_count=1
    AND r.family IN ('JA','JE') AND r.part_name='走线弯角件';
  IF material_rows<>3 OR spray_rows<>3 THEN
    RAISE EXCEPTION 'JA/JE走线弯角件规则数量异常：材料% 行，喷塑% 行',material_rows,spray_rows;
  END IF;
END $$;

UPDATE calc.cabinet_material_rule r SET quantity_rule='{"kind":"CONSTANT","value":4}'::jsonb
FROM calc.cabinet_material_catalog_version v
WHERE r.data_version=v.data_version AND v.status='ACTIVE'
  AND r.single_door_count=0 AND r.double_door_count=1
  AND ((r.family='JA' AND r.part_name='走线弯角件') OR (r.family='JE' AND r.part_name='走线弯角件1'));

UPDATE calc.cabinet_spray_rule r SET quantity_rule='{"kind":"CONSTANT","value":4}'::jsonb
FROM calc.cabinet_spray_catalog_version v
WHERE r.data_version=v.data_version AND v.status='ACTIVE'
  AND r.single_door_count=0 AND r.double_door_count=1
  AND r.family IN ('JA','JE') AND r.part_name='走线弯角件';

SELECT 'material' AS rule_type,r.data_version,r.family,r.part_name,r.body_thickness_profile_mm,r.quantity_rule
FROM calc.cabinet_material_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.single_door_count=0 AND r.double_door_count=1
  AND ((r.family='JA' AND r.part_name='走线弯角件') OR (r.family='JE' AND r.part_name='走线弯角件1'))
UNION ALL
SELECT 'spray',r.data_version,r.family,r.part_name,r.body_thickness_profile_mm,r.quantity_rule
FROM calc.cabinet_spray_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.single_door_count=0 AND r.double_door_count=1
  AND r.family IN ('JA','JE') AND r.part_name='走线弯角件';

COMMIT;
