-- Read only: inspect the active fixed-base rule before/after the migration.
SELECT v.status,r.data_version,r.rule_id,r.import_key,
       r.category_level1,r.category_level2,r.item_name,r.method,
       r.formulas,
       array_agg(p.product_code ORDER BY p.product_code)
         FILTER (WHERE p.product_code IS NOT NULL) AS products
FROM calc.attachment_catalog_version v
JOIN calc.attachment_cost_rule r USING(data_version)
LEFT JOIN calc.attachment_cost_rule_product p USING(rule_id)
WHERE v.status='ACTIVE' AND r.import_key='R11'
GROUP BY v.status,r.rule_id;
