BEGIN READ ONLY;

WITH active AS (
  SELECT data_version FROM calc.cabinet_labor_catalog_version WHERE status='ACTIVE'
), checks AS (
  SELECT
    (SELECT data_version FROM active)='cabinet-labor-01249192a2981dc7-v2' AS active_version_ok,
    (SELECT count(*) FROM calc.cabinet_labor_rule r JOIN active a USING(data_version))=58 AS rule_count_ok,
    (SELECT count(*) FROM calc.cabinet_labor_rule r JOIN active a USING(data_version)
      WHERE product_code='JM' AND material_codes='["SECC"]'::jsonb
        AND intercept=197.2715 AND slope=1.423229
        AND excluded_part_names='[]'::jsonb
        AND source_formula='人工 = 197.2715 + 1.423229 × 计价材料重量')=1 AS jm_secc_ok,
    (SELECT count(*) FROM calc.cabinet_labor_rule r JOIN active a USING(data_version)
      WHERE product_code='JM' AND material_codes='["SUS304","SUS316"]'::jsonb
        AND intercept=292.5932 AND slope=2.756249
        AND excluded_part_names='["安装板"]'::jsonb
        AND source_formula='人工 = 292.5932 + 2.756249 × 计价材料重量（去掉安装板的重量）')=1 AS jm_stainless_ok
)
SELECT *,
  CASE WHEN active_version_ok AND rule_count_ok AND jm_secc_ok AND jm_stainless_ok
       THEN 'PASS' ELSE 'FAIL' END AS result
FROM checks;

SELECT r.product_code,r.material_codes,r.intercept,r.slope,r.excluded_part_names,r.source_formula
FROM calc.cabinet_labor_rule r
JOIN calc.cabinet_labor_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.product_code='JM'
ORDER BY r.source_row_no;

COMMIT;
