BEGIN;

DO $$
DECLARE rule_rows integer;
BEGIN
  SELECT count(*) INTO rule_rows
  FROM calc.cabinet_material_rule r
  JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='后背板加强筋';
  IF rule_rows<>4 THEN
    RAISE EXCEPTION 'JS后背板加强筋规则数量异常：% 行',rule_rows;
  END IF;
END $$;

UPDATE calc.cabinet_material_rule r
SET quantity_rule='{"kind":"WIDTH_GT","threshold":1000,"when_true":1,"when_false":0}'::jsonb
FROM calc.cabinet_material_catalog_version v
WHERE r.data_version=v.data_version AND v.status='ACTIVE'
  AND r.family='JS' AND r.part_name='后背板加强筋';

SELECT r.data_version,r.rule_id,r.body_thickness_profile_mm,
       r.single_door_count,r.double_door_count,r.quantity_rule
FROM calc.cabinet_material_rule r
JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='后背板加强筋'
ORDER BY r.body_thickness_profile_mm,r.single_door_count,r.double_door_count;

COMMIT;
