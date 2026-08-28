/*
 * Enforce the production quick-quote rule: choose the smallest W+H+D
 * difference first, and use three-dimensional distance only as a tie-breaker.
 *
 * Production regression:
 *   JE_SINGLE / SECC / input 1200 x 365 x 565
 *   must select quick_rule_id 1011 / 600 x 300 x 1200.
 *
 * Safe to run repeatedly. This migration changes only the matching function.
 */
BEGIN;

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
    SELECT CASE p_product_code
      WHEN 'JC' THEN 'JC_EXP'
      WHEN 'JQ' THEN 'JQ_EXP'
      WHEN U&'\8D85\5BBDJP' THEN 'JP_WIDE_EXP'
      WHEN U&'\8D85\5BBDJS' THEN 'JS_WIDE_EXP'
      WHEN U&'\64CD\4F5C\53F0' THEN 'OP_TABLE_EXP'
      ELSE p_product_code END AS product_code
  ), candidates AS (
    SELECT q.*,
      CASE WHEN NULLIF(p_model_code, '') IS NOT NULL
                 AND NULLIF(q.model_code, '') = NULLIF(p_model_code, '')
           THEN 0 ELSE 1 END AS model_rank,
      CASE WHEN p_width_mm BETWEEN COALESCE(q.min_width_mm, q.reference_width_mm)
                              AND COALESCE(q.max_width_mm, q.reference_width_mm)
                 AND p_height_mm BETWEEN COALESCE(q.min_height_mm, q.reference_height_mm)
                              AND COALESCE(q.max_height_mm, q.reference_height_mm)
                 AND p_depth_mm BETWEEN COALESCE(q.min_depth_mm, q.reference_depth_mm)
                              AND COALESCE(q.max_depth_mm, q.reference_depth_mm)
           THEN 0 ELSE 1 END AS range_rank,
      sqrt(power(p_width_mm - q.reference_width_mm, 2)
         + power(p_height_mm - q.reference_height_mm, 2)
         + power(p_depth_mm - q.reference_depth_mm, 2)) AS distance,
      abs((p_width_mm + p_height_mm + p_depth_mm)
        - (q.reference_width_mm + q.reference_height_mm + q.reference_depth_mm))
        AS perimeter_distance,
      CASE
        WHEN (q.reference_width_mm + q.reference_height_mm + q.reference_depth_mm) > 0
        THEN (p_width_mm + p_height_mm + p_depth_mm)
           / (q.reference_width_mm + q.reference_height_mm + q.reference_depth_mm)
        ELSE 1
      END AS perimeter_ratio
    FROM calc.quick_quote_experience q
    CROSS JOIN canonical c
    WHERE q.product_code = c.product_code
      AND q.material_code = p_material_code
      AND q.is_active = TRUE
      AND q.effective_from <= p_as_of_date
      AND (q.effective_to IS NULL OR p_as_of_date < q.effective_to)
      AND p_width_mm IS NOT NULL
      AND p_height_mm IS NOT NULL
      AND p_depth_mm IS NOT NULL
  ), best AS (
    SELECT *
    FROM candidates
    ORDER BY perimeter_distance, distance, model_rank, range_rank,
             effective_from DESC, quick_rule_id DESC
    LIMIT 1
  )
  SELECT b.quick_rule_id, b.product_code, b.model_code, b.material_code,
         b.reference_width_mm, b.reference_height_mm, b.reference_depth_mm,
         ROUND(b.quick_material_cost * b.perimeter_ratio, 6),
         b.quick_auxiliary_cost,
         ROUND(b.quick_labor_cost * b.perimeter_ratio, 6),
         b.quick_attachment_fee,
         ROUND(b.quick_spray_cost * b.perimeter_ratio, 6),
         ROUND(b.quick_management_fee * b.perimeter_ratio, 6),
         ROUND(
           COALESCE(b.quick_base_price, b.quick_total_cost)
           * b.perimeter_ratio,
           6
         ),
         CASE
           WHEN b.model_rank = 0 AND b.distance = 0 THEN 'exact_model_dimension'
           WHEN b.range_rank = 0 THEN 'dimension_range'
           ELSE 'nearest_dimension'
         END::VARCHAR,
         b.distance
  FROM best b;
$function$;

DO $verify$
DECLARE
  selected_rule_id BIGINT;
  selected_width NUMERIC;
  selected_height NUMERIC;
  selected_depth NUMERIC;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM calc.quick_quote_experience q
    WHERE q.quick_rule_id = 1011
      AND q.product_code = 'JE_SINGLE'
      AND q.material_code = 'SECC'
      AND q.reference_width_mm = 600
      AND q.reference_height_mm = 1200
      AND q.reference_depth_mm = 300
      AND q.is_active = TRUE
      AND q.effective_from <= DATE '2026-08-28'
      AND (q.effective_to IS NULL OR DATE '2026-08-28' < q.effective_to)
  ) THEN
    RAISE EXCEPTION 'required quick quote rule 1011 is missing or ineligible';
  END IF;

  SELECT matched.quick_rule_id,
         matched.reference_width_mm,
         matched.reference_height_mm,
         matched.reference_depth_mm
  INTO selected_rule_id, selected_width, selected_height, selected_depth
  FROM calc.match_quick_quote(
    'JE_SINGLE', '', 'SECC', 1200, 565, 365, DATE '2026-08-28'
  ) matched;

  IF selected_rule_id IS DISTINCT FROM 1011
     OR selected_width IS DISTINCT FROM 600::NUMERIC
     OR selected_height IS DISTINCT FROM 1200::NUMERIC
     OR selected_depth IS DISTINCT FROM 300::NUMERIC THEN
    RAISE EXCEPTION
      'quick perimeter regression mismatch: rule %, size %x%x%',
      selected_rule_id, selected_width, selected_height, selected_depth;
  END IF;
END;
$verify$;

COMMIT;
