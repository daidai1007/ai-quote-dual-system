-- Run after API deployment and catalog activation. Read-only.
BEGIN READ ONLY;
SELECT data_version,status,default_waste_factor,source_sha256,activated_at
FROM calc.cabinet_material_catalog_version ORDER BY created_at;
SELECT family,count(*) AS rules,count(*) FILTER(WHERE fixed_material_code='SECC') AS fixed_secc_rules
FROM calc.cabinet_material_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' GROUP BY family ORDER BY family;
SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,count(*) AS part_rows
FROM calc.cabinet_material_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE'
GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count
ORDER BY family,body_thickness_profile_mm,single_door_count,double_door_count;
SELECT count(*) AS invalid_fixed_material_rows
FROM calc.cabinet_material_rule r LEFT JOIN calc.material m ON m.material_code=r.fixed_material_code
WHERE r.fixed_material_code IS NOT NULL AND m.material_code IS NULL;
SELECT column_name FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result'
  AND column_name IN ('formula_net_material_weight_kg','formula_corrected_material_weight_kg',
    'formula_waste_factor','cabinet_material_version','cabinet_material_snapshot')
ORDER BY column_name;
COMMIT;
