/* V1.0 统一人工经验值查询函数
   规则：
   1) 产品/柜体模板、型号、材质、尺寸全部按精确条件匹配，柜型代码严格隔离；
   2) SUS304/SUS316 找不到本材质人工值时，回退到同尺寸 SECC 人工值；
   3) 未匹配时返回 NULL，由总成本函数按 0 计入，并可通过诊断查询发现；
   4) 非标尺寸只在同一标准产品类型/型号内匹配，不跨JS、JP、JA、JE等类型。
*/

CREATE OR REPLACE FUNCTION calc.get_labor_cost(
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
  WITH input AS (
    SELECT
      CASE p_product_code
        WHEN 'JC' THEN 'JC_EXP'
        WHEN 'JQ' THEN 'JQ_EXP'
        WHEN 'JP超宽柜' THEN 'JP_WIDE_EXP'
        WHEN 'JS超宽柜' THEN 'JS_WIDE_EXP'
        WHEN '操作台' THEN 'OP_TABLE_EXP'
        WHEN 'JS单门' THEN 'JS_SINGLE'
        WHEN 'JS双门' THEN 'JS_DOUBLE'
        WHEN 'JP单门' THEN 'JP_SINGLE'
        WHEN 'JP双门' THEN 'JP_DOUBLE'
        WHEN 'JA' THEN 'JA_SINGLE'
        WHEN 'JE单门' THEN 'JE_SINGLE'
        WHEN 'JE双门' THEN 'JE_DOUBLE'
        WHEN 'JK' THEN 'JK'
        WHEN 'JM' THEN 'JM'
        ELSE p_product_code
      END AS product_code,
      NULLIF(p_model_code, '') AS model_code,
      p_material_code AS material_code
  ), candidates AS (
    SELECT
      r.labor_cost,
      CASE WHEN r.material_code = i.material_code THEN 0 ELSE 1 END AS material_rank,
      CASE
        WHEN i.model_code IS NOT NULL AND r.model_code = i.model_code THEN 0
        WHEN r.model_code IS NULL OR r.model_code = '' THEN 1
        ELSE 2
      END AS model_rank,
      CASE WHEN r.rule_scope = 'experience_product' THEN 0 ELSE 1 END AS scope_rank,
      r.labor_rule_id
    FROM calc.labor_experience_rule r
    CROSS JOIN input i
    WHERE r.is_active = TRUE
      AND (
        (r.rule_scope = 'experience_product' AND r.product_code = i.product_code)
        OR (r.rule_scope = 'template' AND r.template_code = i.product_code)
      )
      AND (
        r.material_code = i.material_code
        OR (i.material_code IN ('SUS304', 'SUS316') AND r.material_code = 'SECC')
      )
      AND (
        i.model_code IS NULL
        OR r.model_code IS NULL
        OR r.model_code = ''
        OR r.model_code = i.model_code
      )
      AND (p_width_mm IS NULL OR r.width_mm = p_width_mm)
      AND (p_height_mm IS NULL OR r.height_mm = p_height_mm)
      AND (p_depth_mm IS NULL OR r.depth_mm = p_depth_mm)
  )
  SELECT c.labor_cost
  FROM candidates c
  ORDER BY c.material_rank, c.model_rank, c.scope_rank, c.labor_rule_id DESC
  LIMIT 1;
$function$;

/* 保留原函数名，兼容总成本函数和已有调用方。 */
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
  SELECT calc.get_labor_cost(
    p_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm
  );
$function$;

COMMENT ON FUNCTION calc.get_labor_cost(VARCHAR, VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
  IS '统一人工经验值查询：精确尺寸优先，SUS304/SUS316无值时回退SECC';

COMMENT ON FUNCTION calc.get_labor_experience_cost(VARCHAR, VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
  IS '兼容函数，转调calc.get_labor_cost';

/* 非标尺寸人工费用：精确值不存在时，匹配尺寸距离最小的标准经验值。 */
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
  v_product_code VARCHAR;
  v_model_code VARCHAR;
  v_exact RECORD;
  v_nearest RECORD;
  v_target_perimeter NUMERIC;
  v_standard_perimeter NUMERIC;
  v_ratio NUMERIC;
BEGIN
  v_product_code := CASE p_product_code
    WHEN 'JC' THEN 'JC_EXP'
    WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP超宽柜' THEN 'JP_WIDE_EXP'
    WHEN 'JS超宽柜' THEN 'JS_WIDE_EXP'
    WHEN '操作台' THEN 'OP_TABLE_EXP'
    WHEN 'JS单门' THEN 'JS_SINGLE'
    WHEN 'JS双门' THEN 'JS_DOUBLE'
    WHEN 'JP单门' THEN 'JP_SINGLE'
    WHEN 'JP双门' THEN 'JP_DOUBLE'
    WHEN 'JA' THEN 'JA_SINGLE'
    WHEN 'JE单门' THEN 'JE_SINGLE'
    WHEN 'JE双门' THEN 'JE_DOUBLE'
    WHEN 'JK' THEN 'JK'
    WHEN 'JM' THEN 'JM'
    ELSE p_product_code
  END;
  v_model_code := NULLIF(p_model_code, '');

  /* 第一优先级：完全匹配。 */
  SELECT r.*,
         CASE WHEN r.material_code = p_material_code THEN 0 ELSE 1 END AS material_rank,
         CASE WHEN v_model_code IS NOT NULL AND r.model_code = v_model_code THEN 0 ELSE 1 END AS model_rank
    INTO v_exact
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
    AND (
      v_model_code IS NULL
      OR r.model_code IS NULL
      OR r.model_code = ''
      OR r.model_code = v_model_code
    )
    AND (p_width_mm IS NULL OR r.width_mm = p_width_mm)
    AND (p_height_mm IS NULL OR r.height_mm = p_height_mm)
    AND (p_depth_mm IS NULL OR r.depth_mm = p_depth_mm)
  ORDER BY material_rank, model_rank, r.labor_rule_id DESC
  LIMIT 1;

  IF FOUND THEN
    RETURN QUERY SELECT
      v_exact.labor_cost,
      'exact'::VARCHAR,
      v_exact.labor_rule_id::BIGINT,
      COALESCE(v_exact.product_code, v_exact.template_code)::VARCHAR,
      v_exact.model_code::VARCHAR,
      v_exact.material_code::VARCHAR,
      v_exact.width_mm,
      v_exact.height_mm,
      v_exact.depth_mm,
      1.000000::NUMERIC,
      0.000000::NUMERIC;
    RETURN;
  END IF;

  /* 没有尺寸时无法进行最近尺寸匹配。 */
  IF p_width_mm IS NULL OR p_height_mm IS NULL OR p_depth_mm IS NULL THEN
    RETURN QUERY SELECT
      NULL::NUMERIC, 'no_match'::VARCHAR, NULL::BIGINT, NULL::VARCHAR,
      NULL::VARCHAR, NULL::VARCHAR, NULL::NUMERIC, NULL::NUMERIC,
      NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC;
    RETURN;
  END IF;

  /* 第二优先级：同产品/型号中，三维尺寸欧氏距离最小的标准记录。 */
  SELECT r.*,
         power(r.width_mm - p_width_mm, 2)
           + power(r.height_mm - p_height_mm, 2)
           + power(r.depth_mm - p_depth_mm, 2) AS dimension_distance,
         CASE WHEN r.material_code = p_material_code THEN 0 ELSE 1 END AS material_rank,
         CASE WHEN v_model_code IS NOT NULL AND r.model_code = v_model_code THEN 0 ELSE 1 END AS model_rank
    INTO v_nearest
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
    AND (
      v_model_code IS NULL
      OR r.model_code IS NULL
      OR r.model_code = ''
      OR r.model_code = v_model_code
    )
  ORDER BY material_rank, dimension_distance, model_rank, r.labor_rule_id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN QUERY SELECT
      NULL::NUMERIC, 'no_match'::VARCHAR, NULL::BIGINT, NULL::VARCHAR,
      NULL::VARCHAR, NULL::VARCHAR, NULL::NUMERIC, NULL::NUMERIC,
      NULL::NUMERIC, NULL::NUMERIC, NULL::NUMERIC;
    RETURN;
  END IF;

  v_target_perimeter := 4 * (p_width_mm + p_height_mm + p_depth_mm);
  v_standard_perimeter := 4 * (
    v_nearest.width_mm + v_nearest.height_mm + v_nearest.depth_mm
  );
  v_ratio := CASE
    WHEN v_standard_perimeter > 0 THEN v_target_perimeter / v_standard_perimeter
    ELSE 1
  END;

  RETURN QUERY SELECT
    ROUND(v_nearest.labor_cost * v_ratio, 2),
    'dimension_match'::VARCHAR,
    v_nearest.labor_rule_id::BIGINT,
    COALESCE(v_nearest.product_code, v_nearest.template_code)::VARCHAR,
    v_nearest.model_code::VARCHAR,
    v_nearest.material_code::VARCHAR,
    v_nearest.width_mm,
    v_nearest.height_mm,
    v_nearest.depth_mm,
    ROUND(v_ratio, 6),
    ROUND(v_nearest.dimension_distance, 2);
END;
$function$;

/* 总成本函数继续调用旧名称，但现在自动支持非标尺寸周长修正。 */
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
  SELECT m.labor_cost
  FROM calc.get_labor_cost_with_dimension_match(
    p_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm
  ) AS m;
$function$;

COMMENT ON FUNCTION calc.get_labor_cost_with_dimension_match(VARCHAR, VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
  IS '非标尺寸人工匹配：精确值优先，否则取三维尺寸距离最小记录并按4*(宽+高+深)周长比例修正';

COMMENT ON FUNCTION calc.get_labor_experience_cost(VARCHAR, VARCHAR, VARCHAR, NUMERIC, NUMERIC, NUMERIC)
  IS '统一人工费用查询，包含非标尺寸最近标准产品匹配和周长比例修正';
