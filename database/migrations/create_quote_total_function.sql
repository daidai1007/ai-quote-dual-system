-- Unified V1.0 quote total-cost calculation.
-- Material weight and standard-template spray area are supplied by the
-- application because cabinet_part_rule stores Excel formulas as text.
-- The remaining price components are resolved from database lookup tables.
BEGIN;

-- Base total-cost function (safe to replace if it already exists).
CREATE OR REPLACE FUNCTION calc.calculate_total_cost_by_spray_cost(
  p_corrected_material_weight_kg NUMERIC,
  p_material_price_per_kg NUMERIC,
  p_auxiliary_cost NUMERIC DEFAULT 0,
  p_labor_cost NUMERIC DEFAULT 0,
  p_attachment_fee NUMERIC DEFAULT 0,
  p_spray_cost NUMERIC DEFAULT 0
)
RETURNS TABLE (
  material_cost NUMERIC,
  auxiliary_cost NUMERIC,
  labor_cost NUMERIC,
  attachment_fee NUMERIC,
  spray_cost NUMERIC,
  management_fee NUMERIC,
  total_cost NUMERIC
)
LANGUAGE SQL
IMMUTABLE
AS $function$
  SELECT ROUND(p_corrected_material_weight_kg * p_material_price_per_kg, 2),
         ROUND(COALESCE(p_auxiliary_cost, 0), 2),
         ROUND(COALESCE(p_labor_cost, 0), 2),
         ROUND(COALESCE(p_attachment_fee, 0), 2),
         ROUND(COALESCE(p_spray_cost, 0), 2),
         ROUND(COALESCE(p_labor_cost, 0) * 0.13, 2),
         ROUND(
           p_corrected_material_weight_kg * p_material_price_per_kg
           + COALESCE(p_auxiliary_cost, 0)
           + COALESCE(p_labor_cost, 0)
           + COALESCE(p_attachment_fee, 0)
           + COALESCE(p_spray_cost, 0)
           + COALESCE(p_labor_cost, 0) * 0.13,
           2
         );
$function$;

CREATE OR REPLACE FUNCTION calc.get_material_unit_price(
  p_material_code VARCHAR,
  p_as_of_date DATE DEFAULT CURRENT_DATE
)
RETURNS NUMERIC
LANGUAGE SQL
STABLE
AS $function$
  SELECT h.price_per_kg
  FROM calc.material_price_history h
  JOIN calc.material m ON m.material_id = h.material_id
  WHERE m.material_code = p_material_code
    AND h.effective_from <= p_as_of_date
    AND (h.effective_to IS NULL OR p_as_of_date < h.effective_to)
  ORDER BY h.effective_from DESC
  LIMIT 1;
$function$;

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
  v_product_code VARCHAR := CASE p_product_code
    WHEN 'JC' THEN 'JC_EXP'
    WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP超宽柜' THEN 'JP_WIDE_EXP'
    WHEN 'JS超宽柜' THEN 'JS_WIDE_EXP'
    WHEN '操作台' THEN 'OP_TABLE_EXP'
    ELSE p_product_code END;
  v_weight NUMERIC;
  v_base_density NUMERIC;
  v_target_density NUMERIC;
BEGIN
  -- Exact experience-material value has highest priority.
  SELECT epm.material_weight_kg
    INTO v_weight
  FROM calc.experience_product_model epm
  JOIN calc.experience_product ep
    ON ep.experience_product_id = epm.experience_product_id
  WHERE ep.product_code = v_product_code
    AND epm.model_code = p_model_code
    AND epm.material_code = p_material_code
    AND epm.is_active = TRUE
  ORDER BY epm.model_id DESC
  LIMIT 1;

  IF FOUND THEN
    RETURN v_weight;
  END IF;

  -- For formula templates, or when stainless experience data is absent,
  -- use the SECC/base weight and density correction.
  IF p_base_material_weight_kg IS NOT NULL THEN
    v_weight := p_base_material_weight_kg;
  ELSE
    SELECT epm.material_weight_kg, epm.base_density_g_cm3
      INTO v_weight, v_base_density
    FROM calc.experience_product_model epm
    JOIN calc.experience_product ep
      ON ep.experience_product_id = epm.experience_product_id
    WHERE ep.product_code = v_product_code
      AND epm.model_code = p_model_code
      AND epm.material_code = 'SECC'
      AND epm.is_active = TRUE
    ORDER BY epm.model_id DESC
    LIMIT 1;
  END IF;

  IF v_weight IS NULL THEN
    RETURN NULL;
  END IF;
  IF p_material_code = 'SECC' THEN
    RETURN v_weight;
  END IF;

  SELECT m.density_g_cm3 INTO v_target_density
  FROM calc.material m WHERE m.material_code = p_material_code;
  IF v_base_density IS NULL THEN
    SELECT m.density_g_cm3 INTO v_base_density
    FROM calc.material m WHERE m.material_code = 'SECC';
  END IF;

  IF v_target_density IS NULL OR v_base_density IS NULL OR v_base_density = 0 THEN
    RETURN v_weight;
  END IF;
  RETURN ROUND(v_weight * v_target_density / v_base_density, 6);
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
  SELECT r.labor_cost
  FROM calc.labor_experience_rule r
  WHERE r.is_active = TRUE
    AND r.material_code = p_material_code
    AND (
      (r.rule_scope = 'experience_product' AND r.product_code = p_product_code)
      OR (r.rule_scope = 'template' AND r.template_code = p_product_code)
    )
    AND (p_model_code IS NULL OR r.model_code IS NULL OR r.model_code = '' OR r.model_code = p_model_code)
    AND (p_width_mm IS NULL OR r.width_mm = p_width_mm)
    AND (p_height_mm IS NULL OR r.height_mm = p_height_mm)
    AND (p_depth_mm IS NULL OR r.depth_mm = p_depth_mm)
  ORDER BY
    CASE WHEN r.model_code = p_model_code THEN 0 ELSE 1 END,
    CASE WHEN r.rule_scope = 'experience_product' THEN 0 ELSE 1 END,
    r.labor_rule_id DESC
  LIMIT 1;
$function$;

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
  p_coating_type VARCHAR DEFAULT '平光',
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
  v_product_code VARCHAR := CASE p_product_code
    WHEN 'JC' THEN 'JC_EXP'
    WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP超宽柜' THEN 'JP_WIDE_EXP'
    WHEN 'JS超宽柜' THEN 'JS_WIDE_EXP'
    WHEN '操作台' THEN 'OP_TABLE_EXP'
    ELSE p_product_code END;
  v_aux_product_code VARCHAR;
  v_aux_model_code VARCHAR;
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
    ELSE v_product_code END;
  v_variant := COALESCE(NULLIF(p_variant_code, ''), CASE v_product_code
    WHEN 'JS_SINGLE' THEN 'SINGLE'
    WHEN 'JS_DOUBLE' THEN 'DOUBLE'
    WHEN 'JP_SINGLE' THEN 'SINGLE'
    WHEN 'JP_DOUBLE' THEN 'DOUBLE'
    WHEN 'JE_SINGLE' THEN 'SINGLE'
    WHEN 'JE_DOUBLE' THEN 'DOUBLE'
    WHEN 'JP_WIDE_EXP' THEN 'WIDE'
    WHEN 'JS_WIDE_EXP' THEN 'WIDE'
    ELSE 'DEFAULT' END);
  v_aux_model_code := CASE WHEN v_aux_product_code = 'JK' THEN '' ELSE p_model_code END;
  v_auxiliary := calc.get_auxiliary_cost(
    v_aux_product_code, v_variant, v_aux_model_code, p_material_code,
    p_width_mm::INTEGER, p_height_mm::INTEGER, p_depth_mm::INTEGER);

  v_labor := calc.get_labor_experience_cost(
    v_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm);

  v_spray_unit := calc.get_spray_unit_price(p_as_of_date, p_coating_type);
  v_spray := calc.get_product_spray_cost(
    v_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm,
    p_product_area_m2, v_spray_unit);
  v_attachment := calc.get_attachment_fee(p_quote_id, v_product_code);

  SELECT * INTO v_base_result
  FROM calc.calculate_total_cost_by_spray_cost(
    v_weight, v_material_price, v_auxiliary, v_labor, v_attachment, v_spray);

  RETURN QUERY SELECT
    v_product_code,
    p_model_code,
    p_material_code,
    v_weight,
    v_material_price,
    v_base_result.material_cost,
    v_base_result.auxiliary_cost,
    v_base_result.labor_cost,
    p_product_area_m2,
    v_spray_unit,
    v_base_result.spray_cost,
    v_base_result.attachment_fee,
    v_base_result.management_fee,
    v_base_result.total_cost;
END;
$function$;

COMMENT ON FUNCTION calc.calculate_quote_total(VARCHAR, VARCHAR, VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, VARCHAR, VARCHAR, DATE)
IS 'Unified V1.0 cost: material + auxiliary + labor + attachment + spray + labor*13%. Standard template weight/area are supplied from the formula engine; experience products are looked up from model tables.';

COMMIT;

-- Example (replace TEST-001 and dimensions with an actual quote):
-- SELECT * FROM calc.calculate_quote_total(
--   'TEST-001', 'JP_WIDE_EXP', 'JP131860', 'SECC',
--   1300, 1800, 600, NULL, NULL, '平光', 'WIDE'
-- );
