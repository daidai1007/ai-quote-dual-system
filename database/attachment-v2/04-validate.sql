\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT data_version,status,source_sha256,activated_at FROM calc.attachment_catalog_version;
SELECT data_version,count(*) AS catalog_rows,count(*) FILTER(WHERE is_active) AS active_rows,
       count(*) FILTER(WHERE quick_face_price IS NULL) AS missing_face_price,
       count(*) FILTER(WHERE quick_face_price IS DISTINCT FROM price) AS legacy_precision_projection_rows
FROM calc.attachment_price GROUP BY data_version;
SELECT data_version,method,count(*) FROM calc.attachment_cost_rule GROUP BY data_version,method;
SELECT ap.source_row_no AS quick_excel_row,ap.attachment_price_id,ap.quick_face_price,
       r.source_row_no AS formula_excel_row,r.rule_id,r.method,r.auxiliary_list,
       array_agg(pr.product_code) FILTER(WHERE pr.product_code IS NOT NULL) AS products,
       r.model_code AS source_model,r.model_semantics,
       (SELECT array_agg(m.material_code ORDER BY m.material_code) FROM calc.attachment_cost_rule_material m WHERE m.rule_id=r.rule_id) AS materials
FROM calc.attachment_price ap LEFT JOIN calc.attachment_cost_rule_binding b USING(attachment_price_id)
LEFT JOIN calc.attachment_cost_rule r USING(rule_id) LEFT JOIN calc.attachment_cost_rule_product pr USING(rule_id)
WHERE ap.data_version IS NOT NULL
GROUP BY ap.attachment_price_id,r.rule_id ORDER BY ap.source_row_no,r.source_row_no;
SELECT quote_line_id,calculation_status,count(*) FROM calc.attachment_selection
GROUP BY quote_line_id,calculation_status;
SELECT count(*) AS legacy_selection_rows FROM calc.attachment_selection WHERE calculation_status IS NULL;
COMMIT;
