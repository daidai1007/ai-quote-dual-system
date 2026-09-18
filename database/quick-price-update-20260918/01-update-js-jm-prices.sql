BEGIN;

CREATE TEMP TABLE quick_price_update(
  product_code text NOT NULL,
  model_code text,
  width_mm numeric NOT NULL,
  height_mm numeric NOT NULL,
  depth_mm numeric NOT NULL,
  new_price numeric NOT NULL CHECK(new_price >= 0),
  PRIMARY KEY(product_code,width_mm,height_mm,depth_mm)
) ON COMMIT DROP;

INSERT INTO quick_price_update(product_code,model_code,width_mm,height_mm,depth_mm,new_price) VALUES
  ('JS_SINGLE',NULL,1200,2200,600,4478.78),
  ('JM',NULL,600,1500,210,1948.39),
  ('JM',NULL,800,1500,300,2228.90),
  ('JM',NULL,1000,1500,300,2656.53),
  ('JM',NULL,1200,1500,300,2935.24),
  ('JM',NULL,800,1600,300,2335.85),
  ('JM',NULL,1000,1600,300,2776.91),
  ('JM',NULL,1200,1600,300,3069.74),
  ('JM',NULL,800,1800,300,2521.70),
  ('JM',NULL,1000,1800,300,3004.14),
  ('JM',NULL,1200,1800,300,3300.80);

DO $$
DECLARE bad record;
BEGIN
  IF (SELECT count(*) FROM quick_price_update) <> 11 THEN
    RAISE EXCEPTION '本次价格表必须恰好包含11行';
  END IF;
  SELECT u.*,m.matched INTO bad
  FROM quick_price_update u
  CROSS JOIN LATERAL (
    SELECT count(*) AS matched
    FROM calc.quick_quote_experience q
    WHERE q.product_code=u.product_code
      AND q.material_code='SECC'
      AND q.reference_width_mm=u.width_mm
      AND q.reference_height_mm=u.height_mm
      AND q.reference_depth_mm=u.depth_mm
      AND q.is_active
      AND q.effective_from<=current_date
      AND (q.effective_to IS NULL OR current_date<q.effective_to)
  ) m
  WHERE m.matched<>1
  LIMIT 1;
  IF FOUND THEN
    RAISE EXCEPTION '快速报价目标必须唯一匹配：% % %x%x%，实际% 行',
      bad.product_code,coalesce(bad.model_code,'(按尺寸)'),bad.width_mm,bad.height_mm,bad.depth_mm,bad.matched;
  END IF;
END $$;

SELECT q.quick_rule_id,q.product_code,q.model_code,q.material_code,
       q.reference_width_mm,q.reference_height_mm,q.reference_depth_mm,
       q.quick_base_price AS old_price,u.new_price
FROM calc.quick_quote_experience q
JOIN quick_price_update u
  ON q.product_code=u.product_code
 AND q.reference_width_mm=u.width_mm
 AND q.reference_height_mm=u.height_mm
 AND q.reference_depth_mm=u.depth_mm
WHERE q.material_code='SECC' AND q.is_active
  AND q.effective_from<=current_date
  AND (q.effective_to IS NULL OR current_date<q.effective_to)
ORDER BY q.product_code,q.reference_width_mm,q.reference_height_mm
FOR UPDATE OF q;

UPDATE calc.quick_quote_experience q
SET quick_base_price=u.new_price,
    quick_total_cost=u.new_price,
    notes=concat_ws('；',nullif(q.notes,''),'快速面价2026-09-18人工更新')
FROM quick_price_update u
WHERE q.product_code=u.product_code
  AND q.reference_width_mm=u.width_mm
  AND q.reference_height_mm=u.height_mm
  AND q.reference_depth_mm=u.depth_mm
  AND q.material_code='SECC' AND q.is_active
  AND q.effective_from<=current_date
  AND (q.effective_to IS NULL OR current_date<q.effective_to)
RETURNING q.quick_rule_id,q.product_code,q.model_code,
          q.reference_width_mm,q.reference_height_mm,q.reference_depth_mm,
          q.quick_base_price AS new_price;

DO $$
BEGIN
  IF EXISTS(
    SELECT 1 FROM quick_price_update u
    LEFT JOIN calc.quick_quote_experience q
      ON q.product_code=u.product_code
     AND q.reference_width_mm=u.width_mm
     AND q.reference_height_mm=u.height_mm
     AND q.reference_depth_mm=u.depth_mm
     AND q.material_code='SECC' AND q.is_active
     AND q.effective_from<=current_date
     AND (q.effective_to IS NULL OR current_date<q.effective_to)
    WHERE q.quick_rule_id IS NULL
       OR q.quick_base_price IS DISTINCT FROM u.new_price
       OR q.quick_total_cost IS DISTINCT FROM u.new_price
  ) THEN RAISE EXCEPTION '快速报价价格更新验证失败';
  END IF;
END $$;

COMMIT;
