-- V1.0 total-cost formula.
-- Formula:
-- total_cost = corrected_material_weight * material_price
--            + auxiliary_cost
--            + labor_cost
--            + attachment_fee
--            + product_area * spray_unit_price
--            + labor_cost * 0.13
BEGIN;

CREATE OR REPLACE FUNCTION calc.calculate_total_cost(
  p_corrected_material_weight_kg NUMERIC,
  p_material_price_per_kg NUMERIC,
  p_auxiliary_cost NUMERIC DEFAULT 0,
  p_labor_cost NUMERIC DEFAULT 0,
  p_attachment_fee NUMERIC DEFAULT 0,
  p_product_area_m2 NUMERIC DEFAULT 0,
  p_spray_unit_price NUMERIC DEFAULT 0
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
  WITH inputs AS (
    SELECT
      p_corrected_material_weight_kg * p_material_price_per_kg AS material_cost_raw,
      COALESCE(p_auxiliary_cost, 0) AS auxiliary_cost_raw,
      COALESCE(p_labor_cost, 0) AS labor_cost_raw,
      COALESCE(p_attachment_fee, 0) AS attachment_fee_raw,
      COALESCE(p_product_area_m2, 0) * COALESCE(p_spray_unit_price, 0) AS spray_cost_raw
  ), components AS (
    SELECT
      ROUND(material_cost_raw, 2) AS material_cost,
      ROUND(auxiliary_cost_raw, 2) AS auxiliary_cost,
      ROUND(labor_cost_raw, 2) AS labor_cost,
      ROUND(attachment_fee_raw, 2) AS attachment_fee,
      ROUND(spray_cost_raw, 2) AS spray_cost,
      ROUND(labor_cost_raw * 0.13, 2) AS management_fee,
      material_cost_raw + auxiliary_cost_raw + labor_cost_raw
        + attachment_fee_raw + spray_cost_raw + labor_cost_raw * 0.13 AS total_cost_raw
    FROM inputs
  )
  SELECT material_cost,
         auxiliary_cost,
         labor_cost,
         attachment_fee,
         spray_cost,
         management_fee,
         ROUND(total_cost_raw, 2) AS total_cost
  FROM components;
$function$;

COMMENT ON FUNCTION calc.calculate_total_cost(NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC)
IS 'V1.0 total cost: corrected material weight*material price + auxiliary + labor + attachment + product area*spray price + labor*13%.';

COMMIT;

-- Verification example:
-- 100 kg * 4.20 + 8.30 + 1000 + 50 + 20 m2 * 6 + 1000 * 0.13 = 1728.30
SELECT *
FROM calc.calculate_total_cost(100, 4.20, 8.30, 1000, 50, 20, 6);
