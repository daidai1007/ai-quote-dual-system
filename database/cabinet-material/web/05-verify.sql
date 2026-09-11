-- Run after API deployment and catalog activation. Read-only.
BEGIN READ ONLY;
SELECT data_version,status,default_waste_factor,source_sha256,source_files,activated_at
FROM calc.cabinet_material_catalog_version ORDER BY created_at;
SELECT family,count(*) AS rules,count(*) FILTER(WHERE fixed_material_code='SECC') AS fixed_secc_rules
FROM calc.cabinet_material_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' GROUP BY family ORDER BY family;
SELECT product_code,profile_code,material_codes,count(*) AS fixed_rules,
       bool_or(apply_waste_factor) AS any_waste_factor
FROM calc.cabinet_material_fixed_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' GROUP BY product_code,profile_code,material_codes ORDER BY product_code,profile_code,material_codes;
SELECT count(*) AS duplicate_fixed_identities FROM (
  SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm
  FROM calc.cabinet_material_fixed_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1
) duplicates;
SELECT count(*) AS invalid_fixed_material_rows
FROM calc.cabinet_material_rule r LEFT JOIN calc.material m ON m.material_code=r.fixed_material_code
WHERE r.fixed_material_code IS NOT NULL AND m.material_code IS NULL;
SELECT calc.get_cabinet_material_fixed_weight('JQ_EXP','JQ609648','SECC',600,960,480) AS jq_secc,
       calc.get_cabinet_material_fixed_weight('OP_TABLE_EXP','JM601210','SUS316',600,1200,1000) AS operation_table_sus316,
       calc.get_cabinet_material_fixed_weight('JC_EXP','JC601660-1','SECC',600,1600,600) AS jc_luxury;
SELECT column_name FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result'
  AND column_name IN ('formula_net_material_weight_kg','formula_corrected_material_weight_kg',
    'formula_waste_factor','cabinet_material_version','cabinet_material_snapshot')
ORDER BY column_name;
COMMIT;
