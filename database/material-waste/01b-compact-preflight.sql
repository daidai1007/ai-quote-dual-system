-- Neon SQL Editor: run the whole file. Read-only and compact enough to copy.
BEGIN READ ONLY;

-- Result 2: one row per relevant table column.
SELECT table_name,column_name,data_type,udt_name,numeric_precision,numeric_scale,
       is_nullable,column_default,is_generated
FROM information_schema.columns
WHERE table_schema='calc' AND table_name IN (
  'cabinet_template','cabinet_part_rule','experience_product_model','material')
ORDER BY table_name,ordinal_position;

-- Result 3: one row per weight/cost function. Copy the definition cells as text.
SELECT p.oid::regprocedure::text AS signature,pg_get_functiondef(p.oid) AS definition
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='calc' AND p.prokind='f' AND p.proname IN (
  'calculate_quote_total','calculate_dual_quote','calculate_total_cost_by_spray_cost',
  'calculate_total_cost_for_quote','get_corrected_material_weight_kg',
  'get_experience_material_weight_by_dimension')
ORDER BY signature;

-- Result 4: each material-cost template row and its stored M/weight expression.
-- A 1.2 literal is only flagged for review: it can mean waste factor or sheet thickness.
SELECT t.template_code,r.rule_id,r.source_row_no,r.part_name,r.include_material_cost,
       r.weight_formula,
       r.raw_rule->'formulas'->>9 AS raw_m_formula,
       concat_ws(' | ',r.weight_formula,r.raw_rule->'formulas'->>9)
         ~ '(^|[^0-9.])1[.]2([^0-9.]|$)' AS contains_literal_1_2
FROM calc.cabinet_part_rule r
JOIN calc.cabinet_template t ON t.template_id=r.template_id
WHERE r.include_material_cost
ORDER BY t.template_code,r.source_row_no,r.rule_id;

-- Result 5: compact coverage count per template.
SELECT t.template_code,count(*) FILTER (WHERE r.include_material_cost) AS material_rows,
       count(*) FILTER (WHERE r.include_material_cost AND
         concat_ws(' | ',r.weight_formula,r.raw_rule->'formulas'->>9)
           ~ '(^|[^0-9.])1[.]2([^0-9.]|$)') AS rows_containing_literal_1_2,
       count(*) FILTER (WHERE r.include_material_cost AND
         nullif(concat_ws('',r.weight_formula,r.raw_rule->'formulas'->>9),'') IS NULL)
         AS rows_missing_weight_formula
FROM calc.cabinet_part_rule r
JOIN calc.cabinet_template t ON t.template_id=r.template_id
GROUP BY t.template_code ORDER BY t.template_code;

COMMIT;
