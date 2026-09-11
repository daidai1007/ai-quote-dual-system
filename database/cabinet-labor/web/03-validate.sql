BEGIN READ ONLY;
SELECT data_version,status,source_sha256,management_fee_rate
FROM calc.cabinet_labor_catalog_version WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1';
SELECT rule_kind,count(*) FROM calc.cabinet_labor_rule
WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1' GROUP BY rule_kind ORDER BY rule_kind;
SELECT product_code,count(*) FROM calc.cabinet_labor_rule
WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1' GROUP BY product_code ORDER BY product_code;
SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm,count(*)
FROM calc.cabinet_labor_rule WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1'
GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1;
SELECT 'EXPECTED_GAP' AS status,'JM SUS304/SUS316 has no source rule' AS detail
WHERE NOT EXISTS(SELECT 1 FROM calc.cabinet_labor_rule
  WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1' AND product_code='JM' AND material_codes ? 'SUS304');
COMMIT;
