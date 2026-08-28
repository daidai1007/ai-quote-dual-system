/*
 * Restore perimeter-first quick-quote matching in production and add the
 * manually priced door installation strip requested for the attachment
 * catalogue.  Safe to run repeatedly.
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
    /* Business rule: closest cabinet perimeter first; shape is a tie-breaker. */
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

UPDATE calc.attachment_price
SET attachment_category = '门安装条',
    model_code = '所有型号',
    variant = NULL,
    width_mm = NULL,
    height_mm = NULL,
    depth_mm = NULL,
    price = 20,
    price_text = '20',
    unit = '根',
    price_source = '人工新增',
    notes = '门安装条，人工选择数量；不参与折扣',
    source_file = 'repair_quick_perimeter_and_add_door_installation_strip.sql',
    source_sheet = '门安装条',
    source_row_no = 1,
    is_active = TRUE
WHERE item_name = '门安装条'
  AND attachment_price_id = (
    SELECT max(attachment_price_id)
    FROM calc.attachment_price
    WHERE item_name = '门安装条'
  );

INSERT INTO calc.attachment_price (
  attachment_category, item_name, model_code, variant,
  width_mm, height_mm, depth_mm,
  price, price_text, unit, price_source, notes,
  source_file, source_sheet, source_row_no, is_active
)
SELECT
  '门安装条', '门安装条', '所有型号', NULL,
  NULL, NULL, NULL,
  20, '20', '根', '人工新增', '门安装条，人工选择数量；不参与折扣',
  'repair_quick_perimeter_and_add_door_installation_strip.sql',
  '门安装条', 1, TRUE
WHERE NOT EXISTS (
  SELECT 1
  FROM calc.attachment_price
  WHERE item_name = '门安装条'
    AND is_active = TRUE
);

WITH ranked AS (
  SELECT attachment_price_id,
         row_number() OVER (ORDER BY attachment_price_id DESC) AS duplicate_rank
  FROM calc.attachment_price
  WHERE item_name = '门安装条'
    AND is_active = TRUE
)
UPDATE calc.attachment_price price
SET is_active = FALSE
FROM ranked
WHERE price.attachment_price_id = ranked.attachment_price_id
  AND ranked.duplicate_rank > 1;

UPDATE calc.attachment_classification classification
SET category_level1 = '门安装条',
    category_level2 = '',
    category_level3 = ''
FROM calc.attachment_price price
WHERE classification.attachment_price_id = price.attachment_price_id
  AND price.item_name = '门安装条'
  AND price.is_active = TRUE;

INSERT INTO calc.attachment_classification (
  attachment_price_id, category_level1, category_level2, category_level3
)
SELECT price.attachment_price_id, '门安装条', '', ''
FROM calc.attachment_price price
WHERE price.item_name = '门安装条'
  AND price.is_active = TRUE
  AND NOT EXISTS (
    SELECT 1
    FROM calc.attachment_classification classification
    WHERE classification.attachment_price_id = price.attachment_price_id
  );

DO $verify$
DECLARE
  selected_model TEXT;
  attachment_count INTEGER;
  attachment_mismatch INTEGER;
BEGIN
  /* Regression supplied by the operator: target 1200*365*565. */
  SELECT candidate.model_code
  INTO selected_model
  FROM (VALUES
    ('JE601230'::TEXT, 600::NUMERIC, 1230::NUMERIC, 300::NUMERIC),
    ('JE100100'::TEXT, 1000::NUMERIC, 1000::NUMERIC, 300::NUMERIC)
  ) AS candidate(model_code, width_mm, height_mm, depth_mm)
  ORDER BY
    abs((1200 + 565 + 365)
      - (candidate.width_mm + candidate.height_mm + candidate.depth_mm)),
    sqrt(power(1200 - candidate.width_mm, 2)
      + power(565 - candidate.height_mm, 2)
      + power(365 - candidate.depth_mm, 2))
  LIMIT 1;

  IF selected_model IS DISTINCT FROM 'JE601230' THEN
    RAISE EXCEPTION 'quick perimeter regression mismatch: %', selected_model;
  END IF;

  SELECT count(*)
  INTO attachment_count
  FROM calc.attachment_price
  WHERE item_name = '门安装条'
    AND is_active = TRUE;
  IF attachment_count <> 1 THEN
    RAISE EXCEPTION 'door installation strip active row count mismatch: %', attachment_count;
  END IF;

  SELECT count(*)
  INTO attachment_mismatch
  FROM calc.attachment_price price
  LEFT JOIN calc.attachment_classification classification
    ON classification.attachment_price_id = price.attachment_price_id
  WHERE price.item_name = '门安装条'
    AND price.is_active = TRUE
    AND (
      price.attachment_category IS DISTINCT FROM '门安装条'
      OR price.price IS DISTINCT FROM 20::NUMERIC
      OR price.unit IS DISTINCT FROM '根'
      OR price.source_file IS DISTINCT FROM 'repair_quick_perimeter_and_add_door_installation_strip.sql'
      OR price.source_sheet IS DISTINCT FROM '门安装条'
      OR price.source_row_no IS DISTINCT FROM 1
      OR classification.category_level1 IS DISTINCT FROM '门安装条'
      OR classification.category_level2 IS DISTINCT FROM ''
      OR classification.category_level3 IS DISTINCT FROM ''
    );
  IF attachment_mismatch <> 0 THEN
    RAISE EXCEPTION 'door installation strip migration mismatch: %', attachment_mismatch;
  END IF;
END;
$verify$;

COMMIT;
