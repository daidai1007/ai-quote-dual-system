BEGIN READ ONLY;

WITH definition AS (
  SELECT pg_get_functiondef(p.oid) AS body
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='calc' AND p.proname='match_quick_quote'
    AND pg_get_function_identity_arguments(p.oid)=
      'p_product_code character varying, p_model_code character varying, p_material_code character varying, p_width_mm numeric, p_height_mm numeric, p_depth_mm numeric, p_as_of_date date'
), single_quote AS (
  SELECT quick_rule_id,quick_total_cost
  FROM calc.match_quick_quote('JE_SINGLE','任意型号A','SECC',1200,565,365,DATE '2026-08-28')
), double_quote AS (
  SELECT quick_rule_id,quick_total_cost
  FROM calc.match_quick_quote('JE_DOUBLE','任意型号B','SECC',1200,565,365,DATE '2026-08-28')
), checks AS (
  SELECT
    (SELECT count(*) FROM definition)=1 AS function_exists,
    NOT EXISTS(SELECT 1 FROM definition WHERE position('model_rank' in body)>0) AS model_ignored,
    EXISTS(SELECT 1 FROM definition WHERE position('regexp_replace' in body)>0) AS door_code_normalized,
    EXISTS(SELECT 1 FROM definition WHERE position('ORDER BY width_distance, perimeter_distance' in body)>0
      OR position('ORDER BY width_distance,perimeter_distance' in body)>0) AS width_then_perimeter,
    (SELECT quick_rule_id FROM single_quote) IS NOT NULL AS sample_matched,
    (SELECT quick_rule_id FROM single_quote) IS NOT DISTINCT FROM
      (SELECT quick_rule_id FROM double_quote) AS same_rule,
    (SELECT quick_total_cost FROM single_quote) IS NOT DISTINCT FROM
      (SELECT quick_total_cost FROM double_quote) AS same_face_price
)
SELECT *,CASE WHEN function_exists AND model_ignored AND door_code_normalized AND width_then_perimeter
  AND sample_matched AND same_rule AND same_face_price THEN 'PASS' ELSE 'FAIL' END AS result
FROM checks;

SELECT count(*) AS active_quick_rows
FROM calc.quick_quote_experience
WHERE is_active=TRUE
  AND effective_from<=CURRENT_DATE
  AND (effective_to IS NULL OR CURRENT_DATE<effective_to);

COMMIT;
