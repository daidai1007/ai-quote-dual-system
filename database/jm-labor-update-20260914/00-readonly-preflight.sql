BEGIN READ ONLY;

SELECT current_database() AS database_name,current_user AS database_user;

SELECT data_version,status,management_fee_rate,activated_at
FROM calc.cabinet_labor_catalog_version
WHERE status='ACTIVE';

SELECT count(*) AS active_rule_count
FROM calc.cabinet_labor_rule r
JOIN calc.cabinet_labor_catalog_version v USING(data_version)
WHERE v.status='ACTIVE';

SELECT r.product_code,r.material_codes,r.intercept,r.slope,r.excluded_part_names,
       r.source_formula,r.source_sheet,r.source_row_no
FROM calc.cabinet_labor_rule r
JOIN calc.cabinet_labor_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.product_code='JM'
ORDER BY r.source_row_no;

COMMIT;
