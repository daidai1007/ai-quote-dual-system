-- Auxiliary-cost lookup layer.
-- Run after import_auxiliary_costs.sql.
BEGIN;

CREATE OR REPLACE FUNCTION calc.get_auxiliary_cost(
  p_product_code VARCHAR,
  p_variant_code VARCHAR DEFAULT 'DEFAULT',
  p_model_code VARCHAR DEFAULT '',
  p_material_code VARCHAR DEFAULT NULL,
  p_width_mm INTEGER DEFAULT NULL,
  p_height_mm INTEGER DEFAULT NULL,
  p_depth_mm INTEGER DEFAULT NULL
)
RETURNS NUMERIC
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_cost NUMERIC;
  v_variant VARCHAR := COALESCE(NULLIF(p_variant_code, ''), 'DEFAULT');
BEGIN
  -- Experience-value lookup: exact material and exact model/dimensions.
  SELECT e.auxiliary_cost
    INTO v_cost
  FROM calc.auxiliary_experience_price e
  WHERE e.product_code = p_product_code
    AND e.model_code = COALESCE(p_model_code, '')
    AND e.material_code = p_material_code
    AND e.width_mm IS NOT DISTINCT FROM p_width_mm
    AND e.height_mm IS NOT DISTINCT FROM p_height_mm
    AND e.depth_mm IS NOT DISTINCT FROM p_depth_mm
  ORDER BY e.updated_at DESC, e.auxiliary_experience_id DESC
  LIMIT 1;

  IF FOUND THEN
    RETURN v_cost;
  END IF;

  -- BOM lookup: BOM is material-independent and stores the per-cabinet total.
  SELECT b.source_total
    INTO v_cost
  FROM calc.auxiliary_bom b
  WHERE b.product_code = p_product_code
    AND b.variant_code = v_variant
  ORDER BY b.updated_at DESC, b.auxiliary_bom_id DESC
  LIMIT 1;

  IF FOUND THEN
    RETURN v_cost;
  END IF;

  -- Optional fallback to DEFAULT for callers that do not know the variant.
  IF v_variant <> 'DEFAULT' THEN
    SELECT b.source_total
      INTO v_cost
    FROM calc.auxiliary_bom b
    WHERE b.product_code = p_product_code
      AND b.variant_code = 'DEFAULT'
    ORDER BY b.updated_at DESC, b.auxiliary_bom_id DESC
    LIMIT 1;

    IF FOUND THEN
      RETURN v_cost;
    END IF;
  END IF;

  RETURN NULL;
END;
$function$;

COMMENT ON FUNCTION calc.get_auxiliary_cost(VARCHAR, VARCHAR, VARCHAR, VARCHAR, INTEGER, INTEGER, INTEGER)
IS 'Returns exact auxiliary experience value first, then material-independent BOM total; NULL means no source value exists.';

CREATE OR REPLACE VIEW calc.v_auxiliary_experience_price AS
SELECT
  product_code,
  model_code,
  width_mm,
  height_mm,
  depth_mm,
  material_code,
  auxiliary_cost,
  'experience'::VARCHAR(20) AS auxiliary_cost_method,
  source_file,
  source_sheet,
  source_row_no
FROM calc.auxiliary_experience_price;

CREATE OR REPLACE VIEW calc.v_auxiliary_bom_cost AS
SELECT
  b.product_code,
  b.variant_code,
  b.source_total AS auxiliary_cost,
  b.source_total_qty,
  COUNT(l.auxiliary_bom_line_id)::INTEGER AS line_count,
  'bom'::VARCHAR(20) AS auxiliary_cost_method,
  b.source_file,
  b.source_sheet
FROM calc.auxiliary_bom b
LEFT JOIN calc.auxiliary_bom_line l
  ON l.auxiliary_bom_id = b.auxiliary_bom_id
GROUP BY b.product_code, b.variant_code, b.source_total, b.source_total_qty,
         b.source_file, b.source_sheet;

COMMIT;

-- Verification examples. Expected values:
-- JK SECC 300x200x80 = 8.300000
-- JK SUS304 300x200x80 = 30.290598
-- JS single BOM = 107.5800
-- JQ BOM = 95.8000
-- JC SUS304 is NULL because the workbook currently has no JC stainless entry.
SELECT 'JK_SECC' AS test_case,
       calc.get_auxiliary_cost('JK', 'DEFAULT', '', 'SECC', 300, 200, 80) AS auxiliary_cost
UNION ALL
SELECT 'JK_SUS304',
       calc.get_auxiliary_cost('JK', 'DEFAULT', '', 'SUS304', 300, 200, 80)
UNION ALL
SELECT 'JS_SINGLE_BOM',
       calc.get_auxiliary_cost('JS', 'SINGLE')
UNION ALL
SELECT 'JQ_BOM',
       calc.get_auxiliary_cost('JQ_EXP', 'DEFAULT')
UNION ALL
SELECT 'JC_SUS304_MISSING',
       calc.get_auxiliary_cost('JC_EXP', 'DEFAULT', 'JC601660-1', 'SUS304', 600, 1600, 600);
