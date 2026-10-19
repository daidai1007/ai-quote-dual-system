-- Total-cost function for a pre-resolved spray cost.
-- Use calc.get_product_spray_cost(...) to obtain that value:
--   standard template = spray area * spray unit price
--   experience product = direct spray price
BEGIN;

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
  -- The database base has zero freight; API/client rederive with actual freight.
  WITH components AS (
    SELECT ROUND(p_corrected_material_weight_kg * p_material_price_per_kg, 2) AS material_cost,
      ROUND(COALESCE(p_auxiliary_cost, 0), 2) AS auxiliary_cost,
      ROUND(COALESCE(p_labor_cost, 0), 2) AS labor_cost,
      ROUND(COALESCE(p_attachment_fee, 0), 2) AS attachment_fee,
      ROUND(COALESCE(p_spray_cost, 0), 2) AS spray_cost
  ), fees AS (
    SELECT *, ROUND((material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost) * 0.06, 2) AS management_fee
    FROM components
  )
  SELECT material_cost, auxiliary_cost, labor_cost, attachment_fee, spray_cost, management_fee,
    material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost + management_fee AS total_cost
  FROM fees;
$function$;

COMMENT ON FUNCTION calc.calculate_total_cost_by_spray_cost(NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC)
IS 'Total cost using a resolved spray cost; supports both template area pricing and direct experience-product spray pricing.';

COMMIT;

-- Example: base 1564.30 + ROUND(1564.30 * 0.06, 2) = 1658.16 (freight zero).
SELECT *
FROM calc.calculate_total_cost_by_spray_cost(100, 4.20, 8.30, 1000, 50, 86);
