-- Final read-only verification after activation and optional physical cleanup.
BEGIN READ ONLY;

SELECT CASE
  WHEN count(*) FILTER (WHERE p.is_active)=226
   AND count(*) FILTER (WHERE p.is_active AND p.data_version='xlsx-7b6fcb18de6f8969-r4')=226
   AND count(*) FILTER (WHERE p.is_active AND p.data_version IS DISTINCT FROM 'xlsx-7b6fcb18de6f8969-r4')=0
  THEN 'PASS' ELSE 'FAIL' END AS attachment_active_catalog,
  count(*) FILTER (WHERE p.is_active) AS active_rows
FROM calc.attachment_price p;

SELECT v.data_version,v.status,count(r.rule_id) AS rules
FROM calc.attachment_catalog_version v
LEFT JOIN calc.attachment_cost_rule r USING(data_version)
GROUP BY v.data_version,v.status,v.created_at ORDER BY v.created_at;

SELECT count(*) AS missing_classification
FROM calc.attachment_price p
LEFT JOIN calc.attachment_classification c USING(attachment_price_id)
WHERE p.is_active AND c.attachment_price_id IS NULL;

SELECT count(*) AS orphan_attachment_selections
FROM calc.attachment_selection s
LEFT JOIN calc.attachment_price p USING(attachment_price_id)
WHERE s.attachment_price_id IS NOT NULL AND p.attachment_price_id IS NULL;

SELECT count(*) AS error_snapshots_without_message
FROM calc.attachment_selection
WHERE calculation_status='ERROR' AND coalesce(btrim(error_message),'')='';

SELECT v.data_version,v.status,v.default_waste_factor,
       count(DISTINCT r.rule_id) AS area_rules,count(DISTINCT r.family) AS families,
       count(DISTINCT f.fixed_rule_id) AS fixed_rules,count(DISTINCT f.product_code) AS fixed_products,
       bool_or(f.apply_waste_factor) AS any_experience_waste_factor
FROM calc.cabinet_material_catalog_version v
LEFT JOIN calc.cabinet_material_rule r USING(data_version)
LEFT JOIN calc.cabinet_material_fixed_rule f USING(data_version)
GROUP BY v.data_version,v.status,v.default_waste_factor,v.created_at
ORDER BY v.created_at;

SELECT count(*) AS invalid_fixed_material_rows
FROM calc.cabinet_material_rule r
LEFT JOIN calc.material m ON m.material_code=r.fixed_material_code
WHERE r.fixed_material_code IS NOT NULL AND m.material_code IS NULL;

SELECT count(*) AS duplicate_material_fixed_identities FROM (
  SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm
  FROM calc.cabinet_material_fixed_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1
) duplicates;

SELECT v.data_version,v.status,count(DISTINCT r.rule_id) AS area_rules,count(DISTINCT r.family) AS families,
       count(DISTINCT f.fixed_rule_id) AS fixed_rules,count(DISTINCT f.product_code) AS fixed_products
FROM calc.cabinet_spray_catalog_version v
LEFT JOIN calc.cabinet_spray_rule r USING(data_version)
LEFT JOIN calc.cabinet_spray_fixed_rule f USING(data_version)
GROUP BY v.data_version,v.status,v.created_at ORDER BY v.created_at;

SELECT count(*) AS duplicate_spray_part_identities
FROM (
  SELECT family,body_thickness_profile_mm,single_door_count,double_door_count,part_name
  FROM calc.cabinet_spray_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY family,body_thickness_profile_mm,single_door_count,double_door_count,part_name
  HAVING count(*)>1
) duplicates;

SELECT count(*) AS duplicate_spray_fixed_identities
FROM (
  SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm
  FROM calc.cabinet_spray_fixed_rule r JOIN calc.cabinet_spray_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1
) duplicates;

SELECT v.data_version,v.status,count(DISTINCT p.profile_id) AS profiles,
       count(DISTINCT l.line_id) AS lines,count(DISTINCT r.rule_id) AS fixed_rules
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
LEFT JOIN calc.cabinet_auxiliary_fixed_rule r ON r.data_version=v.data_version
GROUP BY v.data_version,v.status,v.created_at ORDER BY v.created_at;

SELECT v.data_version,v.status,v.management_fee_rate,count(r.rule_id) AS rules
FROM calc.cabinet_labor_catalog_version v LEFT JOIN calc.cabinet_labor_rule r USING(data_version)
GROUP BY v.data_version,v.status,v.management_fee_rate,v.created_at ORDER BY v.created_at;

SELECT count(*) AS duplicate_labor_identities FROM (
  SELECT product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm
  FROM calc.cabinet_labor_rule r JOIN calc.cabinet_labor_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE'
  GROUP BY product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm HAVING count(*)>1
) d;

SELECT column_name
FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result'
  AND column_name IN (
    'formula_net_material_weight_kg','formula_corrected_material_weight_kg',
    'formula_waste_factor','cabinet_material_version','cabinet_material_snapshot',
    'cabinet_spray_version','cabinet_spray_snapshot',
    'cabinet_auxiliary_version','cabinet_auxiliary_snapshot',
    'cabinet_labor_version','cabinet_labor_snapshot'
  )
ORDER BY column_name;

COMMIT;
