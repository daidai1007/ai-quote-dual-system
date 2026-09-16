/*
 * Quick face-price selection is independent of door type and model text.
 * Product, material, effective date and dimensions remain matching inputs.
 * Candidate selection is width-first, then nearest cabinet perimeter.
 */
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE OR REPLACE FUNCTION calc.match_quick_quote(
  p_product_code VARCHAR,
  p_model_code VARCHAR DEFAULT NULL,
  p_material_code VARCHAR DEFAULT 'SECC',
  p_width_mm NUMERIC DEFAULT NULL,
  p_height_mm NUMERIC DEFAULT NULL,
  p_depth_mm NUMERIC DEFAULT NULL,
  p_as_of_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
  quick_rule_id BIGINT,
  product_code VARCHAR,
  model_code VARCHAR,
  material_code VARCHAR,
  reference_width_mm NUMERIC,
  reference_height_mm NUMERIC,
  reference_depth_mm NUMERIC,
  quick_material_cost NUMERIC,
  quick_auxiliary_cost NUMERIC,
  quick_labor_cost NUMERIC,
  quick_attachment_fee NUMERIC,
  quick_spray_cost NUMERIC,
  quick_management_fee NUMERIC,
  quick_total_cost NUMERIC,
  match_method VARCHAR,
  dimension_distance NUMERIC
)
LANGUAGE SQL
STABLE
AS $function$
  WITH canonical AS (
    SELECT CASE
      WHEN p_product_code ~ '^(JS|JP|JA|JE)_(SINGLE|DOUBLE)$'
        THEN regexp_replace(p_product_code,'_(SINGLE|DOUBLE)$','_SINGLE')
      WHEN p_product_code ~ '^(JM|JK)_(SINGLE|DOUBLE)$'
        THEN regexp_replace(p_product_code,'_(SINGLE|DOUBLE)$','')
      WHEN p_product_code='JC' THEN 'JC_EXP'
      WHEN p_product_code='JQ' THEN 'JQ_EXP'
      WHEN p_product_code=U&'\8D85\5BBDJP' THEN 'JP_WIDE_EXP'
      WHEN p_product_code=U&'\8D85\5BBDJS' THEN 'JS_WIDE_EXP'
      WHEN p_product_code=U&'\64CD\4F5C\53F0' THEN 'OP_TABLE_EXP'
      ELSE p_product_code END AS product_code
  ), candidates AS (
    SELECT q.*,
      CASE WHEN p_width_mm BETWEEN COALESCE(q.min_width_mm,q.reference_width_mm)
                              AND COALESCE(q.max_width_mm,q.reference_width_mm)
                 AND p_height_mm BETWEEN COALESCE(q.min_height_mm,q.reference_height_mm)
                              AND COALESCE(q.max_height_mm,q.reference_height_mm)
                 AND p_depth_mm BETWEEN COALESCE(q.min_depth_mm,q.reference_depth_mm)
                              AND COALESCE(q.max_depth_mm,q.reference_depth_mm)
           THEN 0 ELSE 1 END AS range_rank,
      sqrt(power(p_width_mm-q.reference_width_mm,2)
         + power(p_height_mm-q.reference_height_mm,2)
         + power(p_depth_mm-q.reference_depth_mm,2)) AS distance,
      abs(p_width_mm-q.reference_width_mm) AS width_distance,
      abs((p_width_mm+p_height_mm+p_depth_mm)
        -(q.reference_width_mm+q.reference_height_mm+q.reference_depth_mm)) AS perimeter_distance,
      CASE WHEN (q.reference_width_mm+q.reference_height_mm+q.reference_depth_mm)>0
        THEN (p_width_mm+p_height_mm+p_depth_mm)
          /(q.reference_width_mm+q.reference_height_mm+q.reference_depth_mm)
        ELSE 1 END AS perimeter_ratio
    FROM calc.quick_quote_experience q
    CROSS JOIN canonical c
    WHERE q.product_code=c.product_code
      AND q.material_code=p_material_code
      AND q.is_active=TRUE
      AND q.effective_from<=p_as_of_date
      AND (q.effective_to IS NULL OR p_as_of_date<q.effective_to)
      AND p_width_mm IS NOT NULL AND p_height_mm IS NOT NULL AND p_depth_mm IS NOT NULL
  ), best AS (
    SELECT * FROM candidates
    /* Business rule: closest width first; at that width, closest perimeter. */
    ORDER BY width_distance,perimeter_distance,distance,range_rank,
             effective_from DESC,quick_rule_id DESC
    LIMIT 1
  )
  SELECT b.quick_rule_id,b.product_code,b.model_code,b.material_code,
    b.reference_width_mm,b.reference_height_mm,b.reference_depth_mm,
    ROUND(b.quick_material_cost*b.perimeter_ratio,6),b.quick_auxiliary_cost,
    ROUND(b.quick_labor_cost*b.perimeter_ratio,6),b.quick_attachment_fee,
    ROUND(b.quick_spray_cost*b.perimeter_ratio,6),
    ROUND(b.quick_management_fee*b.perimeter_ratio,6),
    ROUND(COALESCE(b.quick_base_price,b.quick_total_cost)*b.perimeter_ratio,6),
    CASE WHEN b.distance=0 THEN 'exact_dimension'
         WHEN b.range_rank=0 THEN 'dimension_range'
         ELSE 'nearest_dimension' END::VARCHAR,
    b.distance
  FROM best b;
$function$;

DO $verify$
DECLARE
  v_single_rule BIGINT;
  v_double_rule BIGINT;
  v_single_price NUMERIC;
  v_double_price NUMERIC;
BEGIN
  SELECT quick_rule_id,quick_total_cost INTO v_single_rule,v_single_price
  FROM calc.match_quick_quote('JE_SINGLE','任意型号A','SECC',1200,565,365,DATE '2026-08-28');
  SELECT quick_rule_id,quick_total_cost INTO v_double_rule,v_double_price
  FROM calc.match_quick_quote('JE_DOUBLE','任意型号B','SECC',1200,565,365,DATE '2026-08-28');
  IF v_single_rule IS NULL OR v_single_rule IS DISTINCT FROM v_double_rule
     OR v_single_price IS DISTINCT FROM v_double_price THEN
    RAISE EXCEPTION 'Quick quote still changes with door/model: single %/%, double %/%',
      v_single_rule,v_single_price,v_double_rule,v_double_price;
  END IF;
END
$verify$;

COMMIT;
