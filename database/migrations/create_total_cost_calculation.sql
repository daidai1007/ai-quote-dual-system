-- V1.0 total-cost formula.
-- Formula:
-- total_cost = corrected_material_weight * material_price
--            + auxiliary_cost
--            + labor_cost
--            + attachment_fee
--            + product_area * spray_unit_price
--            + (material + auxiliary + cabinet labor + attachment + spray + freight) * 0.06
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
  -- The database base has zero freight; API/client rederive with actual freight.
  WITH components AS (
    SELECT ROUND(p_corrected_material_weight_kg * p_material_price_per_kg, 2) AS material_cost,
      ROUND(COALESCE(p_auxiliary_cost, 0), 2) AS auxiliary_cost,
      ROUND(COALESCE(p_labor_cost, 0), 2) AS labor_cost,
      ROUND(COALESCE(p_attachment_fee, 0), 2) AS attachment_fee,
      ROUND(COALESCE(p_product_area_m2, 0) * COALESCE(p_spray_unit_price, 0), 2) AS spray_cost
  ), fees AS (
    SELECT *, ROUND((material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost) * 0.06, 2) AS management_fee
    FROM components
  )
  SELECT material_cost, auxiliary_cost, labor_cost, attachment_fee, spray_cost, management_fee,
    material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost + management_fee AS total_cost
  FROM fees;
$function$;

COMMENT ON FUNCTION calc.calculate_total_cost(NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC)
IS 'Current total cost: material + auxiliary + cabinet labor + attachment + spray + 6% management; API/client include actual freight in its base.';

COMMIT;

-- Verification example:
-- Base 1598.30 + ROUND(1598.30 * 0.06, 2) = 1694.20 (freight zero).
SELECT *
FROM calc.calculate_total_cost(100, 4.20, 8.30, 1000, 50, 20, 6);
