BEGIN;

DO $$
DECLARE material_rows integer; spray_rows integer;
BEGIN
  SELECT count(*) INTO material_rows
  FROM calc.cabinet_material_rule r
  JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1';
  SELECT count(*) INTO spray_rows
  FROM calc.cabinet_spray_rule r
  JOIN calc.cabinet_spray_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1';
  IF material_rows<>10 OR spray_rows<>10 THEN
    RAISE EXCEPTION 'JS左右侧板-1规则数量异常：材料% 行，喷塑% 行',material_rows,spray_rows;
  END IF;
END $$;

SELECT 'material' AS rule_type,r.rule_id,r.body_thickness_profile_mm,
       r.single_door_count,r.double_door_count,r.area_formula,r.quantity_rule
FROM calc.cabinet_material_rule r
JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1'
UNION ALL
SELECT 'spray',r.rule_id,r.body_thickness_profile_mm,
       r.single_door_count,r.double_door_count,r.area_formula,r.quantity_rule
FROM calc.cabinet_spray_rule r
JOIN calc.cabinet_spray_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1'
ORDER BY rule_type,body_thickness_profile_mm,single_door_count,double_door_count;

UPDATE calc.cabinet_material_rule r
SET area_formula='(高度+50.5)*(深度+64)*0.000001',
    quantity_rule='{"kind":"JS_DEPTH_HEIGHT","when_true":1,"when_false":2}'::jsonb
FROM calc.cabinet_material_catalog_version v
WHERE r.data_version=v.data_version AND v.status='ACTIVE'
  AND r.family='JS' AND r.part_name='左右侧板-1'
RETURNING r.rule_id,r.body_thickness_profile_mm,r.single_door_count,r.double_door_count;

UPDATE calc.cabinet_spray_rule r
SET area_formula='(高度+50.5)*(深度+64)*0.000001',
    quantity_rule='{"kind":"JS_DEPTH_HEIGHT","when_true":1,"when_false":2}'::jsonb
FROM calc.cabinet_spray_catalog_version v
WHERE r.data_version=v.data_version AND v.status='ACTIVE'
  AND r.family='JS' AND r.part_name='左右侧板-1'
RETURNING r.rule_id,r.body_thickness_profile_mm,r.single_door_count,r.double_door_count;

DO $$
BEGIN
  IF EXISTS(
    SELECT 1 FROM calc.cabinet_material_rule r
    JOIN calc.cabinet_material_catalog_version v USING(data_version)
    WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1'
      AND (r.area_formula<>'(高度+50.5)*(深度+64)*0.000001'
        OR r.quantity_rule<>'{"kind":"JS_DEPTH_HEIGHT","when_true":1,"when_false":2}'::jsonb)
  ) OR EXISTS(
    SELECT 1 FROM calc.cabinet_spray_rule r
    JOIN calc.cabinet_spray_catalog_version v USING(data_version)
    WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1'
      AND (r.area_formula<>'(高度+50.5)*(深度+64)*0.000001'
        OR r.quantity_rule<>'{"kind":"JS_DEPTH_HEIGHT","when_true":1,"when_false":2}'::jsonb)
  ) THEN RAISE EXCEPTION 'JS左右侧板-1更新验证失败';
  END IF;
END $$;

SELECT 'material' AS rule_type,r.rule_id,r.body_thickness_profile_mm,
       r.single_door_count,r.double_door_count,r.area_formula,r.quantity_rule
FROM calc.cabinet_material_rule r
JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1'
UNION ALL
SELECT 'spray',r.rule_id,r.body_thickness_profile_mm,
       r.single_door_count,r.double_door_count,r.area_formula,r.quantity_rule
FROM calc.cabinet_spray_rule r
JOIN calc.cabinet_spray_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.family='JS' AND r.part_name='左右侧板-1'
ORDER BY rule_type,body_thickness_profile_mm,single_door_count,double_door_count;

COMMIT;
