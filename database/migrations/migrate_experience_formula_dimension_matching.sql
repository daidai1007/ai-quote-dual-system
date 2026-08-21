/*
  Experience-product matching for the FORMULA quotation system.

  Business rules:
  1. Match only inside the same cabinet/product type.
  2. Drawing number/model_code is informational and never filters candidates.
  3. Select the minimum squared 3-D distance:
       (sample_width-input_width)^2
     + (sample_height-input_height)^2
     + (sample_depth-input_depth)^2
  4. Correct experience values by the cabinet perimeter ratio:
       input perimeter / sample perimeter
     = 4*(input W+H+D) / 4*(sample W+H+D).
  5. BOM auxiliary totals remain BOM totals and are not scaled again.
*/

BEGIN;

/* Nearest-dimension lookups are always scoped by cabinet type and material. */
CREATE INDEX IF NOT EXISTS idx_experience_product_model_match_dims
  ON calc.experience_product_model
    (experience_product_id, material_code, width_mm, height_mm, depth_mm)
  WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_labor_rule_experience_dims
  ON calc.labor_experience_rule
    (product_code, material_code, width_mm, height_mm, depth_mm)
  WHERE rule_scope = 'experience_product' AND is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_auxiliary_experience_match_dims
  ON calc.auxiliary_experience_price
    (product_code, material_code, width_mm, height_mm, depth_mm);

CREATE INDEX IF NOT EXISTS idx_experience_spray_match_dims
  ON calc.experience_spray_price
    (product_code, material_code, width_mm, height_mm, depth_mm);
SET client_encoding = 'UTF8';

CREATE OR REPLACE FUNCTION calc.normalize_experience_product_code(p_product_code VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
IMMUTABLE
AS $function$
  SELECT CASE p_product_code
    WHEN 'JC' THEN 'JC_EXP'
    WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP_WIDE' THEN 'JP_WIDE_EXP'
    WHEN 'JP WIDE' THEN 'JP_WIDE_EXP'
    WHEN 'JS_WIDE' THEN 'JS_WIDE_EXP'
    WHEN 'JS WIDE' THEN 'JS_WIDE_EXP'
    WHEN 'OP_TABLE' THEN 'OP_TABLE_EXP'
    WHEN 'OP TABLE' THEN 'OP_TABLE_EXP'
    WHEN ('JP' || U&'\8D85\5BBD\67DC') THEN 'JP_WIDE_EXP'
    WHEN ('JS' || U&'\8D85\5BBD\67DC') THEN 'JS_WIDE_EXP'
    WHEN U&'\64CD\4F5C\53F0' THEN 'OP_TABLE_EXP'
    ELSE p_product_code
  END;
$function$;

/* ---------- Material weight ---------- */

CREATE OR REPLACE FUNCTION calc.get_experience_material_weight_by_dimension(
  p_product_code VARCHAR,
  p_material_code VARCHAR,
  p_width_mm NUMERIC,
  p_height_mm NUMERIC,
  p_depth_mm NUMERIC
)
RETURNS NUMERIC
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_product_code VARCHAR := calc.normalize_experience_product_code(p_product_code);
  v_match RECORD;
  v_ratio NUMERIC;
  v_target_density NUMERIC;
  v_base_density NUMERIC;
  v_weight NUMERIC;
BEGIN
  IF p_width_mm IS NULL OR p_height_mm IS NULL OR p_depth_mm IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT epm.*,
         CASE WHEN epm.material_code = p_material_code THEN 0 ELSE 1 END AS material_rank,
         abs((epm.width_mm + epm.height_mm + epm.depth_mm)
           - (p_width_mm + p_height_mm + p_depth_mm)) AS perimeter_distance,
         power(epm.width_mm - p_width_mm, 2)
           + power(epm.height_mm - p_height_mm, 2)
           + power(epm.depth_mm - p_depth_mm, 2) AS dimension_distance
    INTO v_match
  FROM calc.experience_product_model epm
  JOIN calc.experience_product ep
    ON ep.experience_product_id = epm.experience_product_id
  WHERE ep.product_code = v_product_code
    AND epm.is_active = TRUE
    AND (
      epm.material_code = p_material_code
      OR (p_material_code IN ('SUS304', 'SUS316') AND epm.material_code = 'SECC')
    )
  ORDER BY material_rank, perimeter_distance, dimension_distance, epm.model_id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  v_ratio := CASE
    WHEN (v_match.width_mm + v_match.height_mm + v_match.depth_mm) > 0
      THEN (p_width_mm + p_height_mm + p_depth_mm)
         / (v_match.width_mm + v_match.height_mm + v_match.depth_mm)
    ELSE 1
  END;
  v_weight := v_match.material_weight_kg * v_ratio;

  /* Explicit material rows from the workbook always have priority. */
  IF v_match.material_code = p_material_code OR p_material_code = 'SECC' THEN
    RETURN ROUND(v_weight, 6);
  END IF;

  SELECT density_g_cm3 INTO v_target_density
  FROM calc.material WHERE material_code = p_material_code;
  v_base_density := COALESCE(v_match.base_density_g_cm3,
    (SELECT density_g_cm3 FROM calc.material WHERE material_code = 'SECC'));

  IF v_target_density IS NULL OR v_base_density IS NULL OR v_base_density = 0 THEN
    RETURN NULL;
  END IF;
  RETURN ROUND(v_weight * v_target_density / v_base_density, 6);
END;
$function$;

/* Dimension-aware overload used by the unified formula calculation. */
CREATE OR REPLACE FUNCTION calc.get_corrected_material_weight_kg(
  p_product_code VARCHAR,
  p_model_code VARCHAR,
  p_material_code VARCHAR,
  p_width_mm NUMERIC,
  p_height_mm NUMERIC,
  p_depth_mm NUMERIC,
  p_base_material_weight_kg NUMERIC DEFAULT NULL
)
RETURNS NUMERIC
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_target_density NUMERIC;
  v_base_density NUMERIC;
BEGIN
  /* Formula templates supply their calculated SECC base weight. */
  IF p_base_material_weight_kg IS NOT NULL THEN
    IF p_material_code = 'SECC' THEN
      RETURN p_base_material_weight_kg;
    END IF;
    SELECT density_g_cm3 INTO v_target_density
    FROM calc.material WHERE material_code = p_material_code;
    SELECT density_g_cm3 INTO v_base_density
    FROM calc.material WHERE material_code = 'SECC';
    IF v_target_density IS NULL OR v_base_density IS NULL OR v_base_density = 0 THEN
      RETURN NULL;
    END IF;
    RETURN ROUND(p_base_material_weight_kg * v_target_density / v_base_density, 6);
  END IF;

  RETURN calc.get_experience_material_weight_by_dimension(
    p_product_code, p_material_code, p_width_mm, p_height_mm, p_depth_mm);
END;
$function$;

/* Compatibility overload. model_code is not a filter; its row is used only to obtain dimensions. */
CREATE OR REPLACE FUNCTION calc.get_corrected_material_weight_kg(
  p_product_code VARCHAR,
  p_model_code VARCHAR,
  p_material_code VARCHAR,
  p_base_material_weight_kg NUMERIC DEFAULT NULL
)
RETURNS NUMERIC
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_product_code VARCHAR := calc.normalize_experience_product_code(p_product_code);
  v_dims RECORD;
BEGIN
  IF p_base_material_weight_kg IS NOT NULL THEN
    RETURN calc.get_corrected_material_weight_kg(
      p_product_code, p_model_code, p_material_code,
      NULL, NULL, NULL, p_base_material_weight_kg);
  END IF;

  SELECT epm.width_mm, epm.height_mm, epm.depth_mm
    INTO v_dims
  FROM calc.experience_product_model epm
  JOIN calc.experience_product ep
    ON ep.experience_product_id = epm.experience_product_id
  WHERE ep.product_code = v_product_code
    AND epm.is_active = TRUE
  ORDER BY CASE WHEN epm.model_code = p_model_code THEN 0 ELSE 1 END,
           CASE WHEN epm.material_code = p_material_code THEN 0 ELSE 1 END,
           epm.model_id DESC
  LIMIT 1;

  IF NOT FOUND THEN RETURN NULL; END IF;
  RETURN calc.get_experience_material_weight_by_dimension(
    v_product_code, p_material_code,
    v_dims.width_mm, v_dims.height_mm, v_dims.depth_mm);
END;
$function$;

/* ---------- Labor ---------- */

CREATE OR REPLACE FUNCTION calc.get_labor_cost_with_dimension_match(
  p_product_code VARCHAR,
  p_model_code VARCHAR DEFAULT NULL,
  p_material_code VARCHAR DEFAULT 'SECC',
  p_width_mm NUMERIC DEFAULT NULL,
  p_height_mm NUMERIC DEFAULT NULL,
  p_depth_mm NUMERIC DEFAULT NULL
)
RETURNS TABLE (
  labor_cost NUMERIC,
  match_method VARCHAR,
  matched_rule_id BIGINT,
  matched_product_code VARCHAR,
  matched_model_code VARCHAR,
  matched_material_code VARCHAR,
  matched_width_mm NUMERIC,
  matched_height_mm NUMERIC,
  matched_depth_mm NUMERIC,
  perimeter_ratio NUMERIC,
  dimension_distance NUMERIC
)
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_product_code VARCHAR := calc.normalize_experience_product_code(p_product_code);
  v_match RECORD;
  v_ratio NUMERIC;
BEGIN
  IF p_width_mm IS NULL OR p_height_mm IS NULL OR p_depth_mm IS NULL THEN
    RETURN QUERY SELECT NULL::NUMERIC, 'no_match'::VARCHAR, NULL::BIGINT,
      NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR,
      NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC;
    RETURN;
  END IF;

  SELECT r.*,
         CASE WHEN r.material_code = p_material_code THEN 0 ELSE 1 END AS material_rank,
         abs((r.width_mm + r.height_mm + r.depth_mm)
           - (p_width_mm + p_height_mm + p_depth_mm)) AS perimeter_distance,
         power(r.width_mm - p_width_mm, 2)
           + power(r.height_mm - p_height_mm, 2)
           + power(r.depth_mm - p_depth_mm, 2) AS dimension_distance
    INTO v_match
  FROM calc.labor_experience_rule r
  WHERE r.is_active = TRUE
    AND (
      (r.rule_scope = 'experience_product' AND r.product_code = v_product_code)
      OR (r.rule_scope = 'template' AND r.template_code = v_product_code)
    )
    AND (
      r.material_code = p_material_code
      OR (p_material_code IN ('SUS304', 'SUS316') AND r.material_code = 'SECC')
    )
  ORDER BY material_rank, perimeter_distance, dimension_distance, r.labor_rule_id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN QUERY SELECT NULL::NUMERIC, 'no_match'::VARCHAR, NULL::BIGINT,
      NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR,
      NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC;
    RETURN;
  END IF;

  v_ratio := CASE
    WHEN (v_match.width_mm + v_match.height_mm + v_match.depth_mm) > 0
      THEN (p_width_mm + p_height_mm + p_depth_mm)
         / (v_match.width_mm + v_match.height_mm + v_match.depth_mm)
    ELSE 1
  END;

  RETURN QUERY SELECT
    ROUND(v_match.labor_cost * v_ratio, 2),
    CASE WHEN v_match.dimension_distance = 0 THEN 'exact' ELSE 'dimension_match' END::VARCHAR,
    v_match.labor_rule_id::BIGINT,
    COALESCE(v_match.product_code, v_match.template_code)::VARCHAR,
    v_match.model_code::VARCHAR,
    v_match.material_code::VARCHAR,
    v_match.width_mm,
    v_match.height_mm,
    v_match.depth_mm,
    ROUND(v_ratio, 6),
    ROUND(v_match.dimension_distance, 2);
END;
$function$;

CREATE OR REPLACE FUNCTION calc.get_labor_experience_cost(
  p_product_code VARCHAR,
  p_model_code VARCHAR DEFAULT NULL,
  p_material_code VARCHAR DEFAULT 'SECC',
  p_width_mm NUMERIC DEFAULT NULL,
  p_height_mm NUMERIC DEFAULT NULL,
  p_depth_mm NUMERIC DEFAULT NULL
)
RETURNS NUMERIC
LANGUAGE SQL
STABLE
AS $function$
  SELECT labor_cost
  FROM calc.get_labor_cost_with_dimension_match(
    p_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm);
$function$;

/* ---------- Auxiliary material ---------- */

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
  v_product_code VARCHAR := calc.normalize_experience_product_code(p_product_code);
  v_variant VARCHAR := COALESCE(NULLIF(p_variant_code, ''), 'DEFAULT');
  v_match RECORD;
  v_cost NUMERIC;
  v_ratio NUMERIC;
BEGIN
  /* Experience auxiliary values: same product + material, nearest dimensions. */
  IF p_width_mm IS NOT NULL AND p_height_mm IS NOT NULL AND p_depth_mm IS NOT NULL THEN
    SELECT e.*,
           abs((e.width_mm + e.height_mm + e.depth_mm)
             - (p_width_mm + p_height_mm + p_depth_mm)) AS perimeter_distance,
           power(e.width_mm - p_width_mm, 2)
             + power(e.height_mm - p_height_mm, 2)
             + power(e.depth_mm - p_depth_mm, 2) AS dimension_distance
      INTO v_match
    FROM calc.auxiliary_experience_price e
    WHERE e.product_code = v_product_code
      AND e.material_code = p_material_code
      AND e.width_mm IS NOT NULL
      AND e.height_mm IS NOT NULL
      AND e.depth_mm IS NOT NULL
    ORDER BY perimeter_distance, dimension_distance, e.auxiliary_experience_id DESC
    LIMIT 1;

    IF FOUND THEN
      v_ratio := CASE
        WHEN (v_match.width_mm + v_match.height_mm + v_match.depth_mm) > 0
          THEN (p_width_mm + p_height_mm + p_depth_mm)::NUMERIC
             / (v_match.width_mm + v_match.height_mm + v_match.depth_mm)
        ELSE 1
      END;
      RETURN ROUND(v_match.auxiliary_cost * v_ratio, 6);
    END IF;
  END IF;

  /* BOM totals are already defined per cabinet and are not perimeter-scaled. */
  SELECT b.source_total INTO v_cost
  FROM calc.auxiliary_bom b
  WHERE b.product_code = v_product_code
    AND b.variant_code = v_variant
  ORDER BY b.updated_at DESC, b.auxiliary_bom_id DESC
  LIMIT 1;
  IF FOUND THEN RETURN v_cost; END IF;

  IF v_variant <> 'DEFAULT' THEN
    SELECT b.source_total INTO v_cost
    FROM calc.auxiliary_bom b
    WHERE b.product_code = v_product_code
      AND b.variant_code = 'DEFAULT'
    ORDER BY b.updated_at DESC, b.auxiliary_bom_id DESC
    LIMIT 1;
    IF FOUND THEN RETURN v_cost; END IF;
  END IF;
  RETURN NULL;
END;
$function$;

/* ---------- Direct spray price ---------- */

CREATE OR REPLACE FUNCTION calc.get_direct_spray_cost(
  p_product_code VARCHAR,
  p_material_code VARCHAR,
  p_width_mm NUMERIC,
  p_height_mm NUMERIC,
  p_depth_mm NUMERIC
)
RETURNS NUMERIC
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_product_code VARCHAR := calc.normalize_experience_product_code(p_product_code);
  v_match RECORD;
  v_ratio NUMERIC;
BEGIN
  IF p_width_mm IS NULL OR p_height_mm IS NULL OR p_depth_mm IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT e.*,
         abs((e.width_mm + e.height_mm + e.depth_mm)
           - (p_width_mm + p_height_mm + p_depth_mm)) AS perimeter_distance,
         power(e.width_mm - p_width_mm, 2)
           + power(e.height_mm - p_height_mm, 2)
           + power(e.depth_mm - p_depth_mm, 2) AS dimension_distance
    INTO v_match
  FROM calc.experience_spray_price e
  WHERE e.product_code = v_product_code
    AND e.material_code = p_material_code
    AND e.width_mm IS NOT NULL
    AND e.height_mm IS NOT NULL
    AND e.depth_mm IS NOT NULL
  ORDER BY perimeter_distance, dimension_distance, e.updated_at DESC, e.experience_spray_price_id DESC
  LIMIT 1;

  IF NOT FOUND THEN RETURN NULL; END IF;
  v_ratio := CASE
    WHEN (v_match.width_mm + v_match.height_mm + v_match.depth_mm) > 0
      THEN (p_width_mm + p_height_mm + p_depth_mm)
         / (v_match.width_mm + v_match.height_mm + v_match.depth_mm)
    ELSE 1
  END;
  RETURN ROUND(v_match.direct_spray_cost * v_ratio, 6);
END;
$function$;

/* Compatibility overload. It does not use model_code for matching. */
CREATE OR REPLACE FUNCTION calc.get_direct_spray_cost(
  p_product_code VARCHAR,
  p_model_code VARCHAR,
  p_material_code VARCHAR DEFAULT 'SECC'
)
RETURNS NUMERIC
LANGUAGE SQL
STABLE
AS $function$
  SELECT e.direct_spray_cost
  FROM calc.experience_spray_price e
  WHERE e.product_code = calc.normalize_experience_product_code(p_product_code)
    AND e.material_code = p_material_code
  ORDER BY e.updated_at DESC, e.experience_spray_price_id DESC
  LIMIT 1;
$function$;

CREATE OR REPLACE FUNCTION calc.get_product_spray_cost(
  p_product_code VARCHAR,
  p_model_code VARCHAR,
  p_material_code VARCHAR,
  p_width_mm NUMERIC,
  p_height_mm NUMERIC,
  p_depth_mm NUMERIC,
  p_product_area_m2 NUMERIC,
  p_spray_unit_price NUMERIC
)
RETURNS NUMERIC
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_method VARCHAR;
BEGIN
  SELECT ep.spray_cost_method INTO v_method
  FROM calc.experience_product ep
  WHERE ep.product_code = calc.normalize_experience_product_code(p_product_code);
  IF v_method = 'direct' THEN
    RETURN calc.get_direct_spray_cost(
      p_product_code, p_material_code, p_width_mm, p_height_mm, p_depth_mm);
  END IF;

  SELECT ct.spray_cost_method INTO v_method
  FROM calc.cabinet_template ct
  WHERE ct.template_code = p_product_code;
  IF v_method = 'area_price' THEN
    RETURN calc.calculate_spray_cost(p_product_area_m2, p_spray_unit_price);
  END IF;
  RETURN NULL;
END;
$function$;

/* ---------- Unified total ---------- */

CREATE OR REPLACE FUNCTION calc.calculate_quote_total(
  p_quote_id VARCHAR,
  p_product_code VARCHAR,
  p_model_code VARCHAR,
  p_material_code VARCHAR,
  p_width_mm NUMERIC,
  p_height_mm NUMERIC,
  p_depth_mm NUMERIC,
  p_base_material_weight_kg NUMERIC DEFAULT NULL,
  p_product_area_m2 NUMERIC DEFAULT NULL,
  p_coating_type VARCHAR DEFAULT U&'\5E73\5149',
  p_variant_code VARCHAR DEFAULT NULL,
  p_as_of_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
  product_code VARCHAR,
  model_code VARCHAR,
  material_code VARCHAR,
  corrected_material_weight_kg NUMERIC,
  material_unit_price NUMERIC,
  material_cost NUMERIC,
  auxiliary_cost NUMERIC,
  labor_cost NUMERIC,
  product_area_m2 NUMERIC,
  spray_unit_price NUMERIC,
  spray_cost NUMERIC,
  attachment_fee NUMERIC,
  management_fee NUMERIC,
  total_cost NUMERIC
)
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_product_code VARCHAR := calc.normalize_experience_product_code(p_product_code);
  v_aux_product_code VARCHAR;
  v_variant VARCHAR;
  v_weight NUMERIC;
  v_material_price NUMERIC;
  v_auxiliary NUMERIC;
  v_labor NUMERIC;
  v_spray_unit NUMERIC;
  v_spray NUMERIC;
  v_attachment NUMERIC;
  v_base_result RECORD;
BEGIN
  v_weight := calc.get_corrected_material_weight_kg(
    v_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm, p_base_material_weight_kg);
  v_material_price := calc.get_material_unit_price(p_material_code, p_as_of_date);

  v_aux_product_code := CASE v_product_code
    WHEN 'JS_SINGLE' THEN 'JS'
    WHEN 'JS_DOUBLE' THEN 'JS'
    WHEN 'JP_SINGLE' THEN 'JP'
    WHEN 'JP_DOUBLE' THEN 'JP'
    WHEN 'JA_SINGLE' THEN 'JA'
    WHEN 'JE_SINGLE' THEN 'JE'
    WHEN 'JE_DOUBLE' THEN 'JE'
    WHEN 'JM' THEN 'JM'
    ELSE v_product_code
  END;
  v_variant := COALESCE(NULLIF(p_variant_code, ''), CASE v_product_code
    WHEN 'JS_SINGLE' THEN 'SINGLE'
    WHEN 'JS_DOUBLE' THEN 'DOUBLE'
    WHEN 'JP_SINGLE' THEN 'SINGLE'
    WHEN 'JP_DOUBLE' THEN 'DOUBLE'
    WHEN 'JE_SINGLE' THEN 'SINGLE'
    WHEN 'JE_DOUBLE' THEN 'DOUBLE'
    WHEN 'JP_WIDE_EXP' THEN 'WIDE'
    WHEN 'JS_WIDE_EXP' THEN 'WIDE'
    ELSE 'DEFAULT'
  END);

  v_auxiliary := calc.get_auxiliary_cost(
    v_aux_product_code, v_variant, '', p_material_code,
    p_width_mm::INTEGER, p_height_mm::INTEGER, p_depth_mm::INTEGER);
  v_labor := calc.get_labor_experience_cost(
    v_product_code, NULL, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm);
  v_spray_unit := calc.get_spray_unit_price(p_as_of_date, p_coating_type);
  v_spray := calc.get_product_spray_cost(
    v_product_code, '', p_material_code,
    p_width_mm, p_height_mm, p_depth_mm,
    p_product_area_m2, v_spray_unit);
  v_attachment := calc.get_attachment_fee(p_quote_id, v_product_code);

  SELECT * INTO v_base_result
  FROM calc.calculate_total_cost_by_spray_cost(
    v_weight, v_material_price, v_auxiliary, v_labor, v_attachment, v_spray);

  RETURN QUERY SELECT
    v_product_code, p_model_code, p_material_code,
    v_weight, v_material_price,
    v_base_result.material_cost, v_base_result.auxiliary_cost,
    v_base_result.labor_cost, p_product_area_m2, v_spray_unit,
    v_base_result.spray_cost, v_base_result.attachment_fee,
    v_base_result.management_fee, v_base_result.total_cost;
END;
$function$;

COMMENT ON FUNCTION calc.get_experience_material_weight_by_dimension(VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
IS 'Formula-system experience weight: same product type, nearest dimensions, perimeter-ratio correction; model code is not a filter.';
COMMENT ON FUNCTION calc.get_labor_cost_with_dimension_match(VARCHAR, VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
IS 'Same product type + nearest dimensions + 4*(W+H+D) perimeter-ratio correction; model code is informational only.';
COMMENT ON FUNCTION calc.get_auxiliary_cost(VARCHAR, VARCHAR, VARCHAR, VARCHAR, INTEGER, INTEGER, INTEGER)
IS 'Experience auxiliary values use same-type nearest dimensions and perimeter scaling; BOM totals remain unchanged.';
COMMENT ON FUNCTION calc.get_direct_spray_cost(VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
IS 'Direct spray experience price uses same product/material nearest dimensions and perimeter-ratio correction.';

COMMIT;
