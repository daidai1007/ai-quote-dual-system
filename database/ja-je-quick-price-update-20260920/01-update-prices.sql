BEGIN;

CREATE TEMP TABLE quick_price_update(
  product_code text NOT NULL, material_code text NOT NULL,
  width_mm numeric NOT NULL, height_mm numeric NOT NULL, depth_mm numeric NOT NULL,
  new_price numeric NOT NULL CHECK(new_price>=0),
  PRIMARY KEY(product_code,material_code,width_mm,height_mm,depth_mm)
) ON COMMIT DROP;

INSERT INTO quick_price_update VALUES
  ('JA_SINGLE','SECC',300,300,210,291),
  ('JA_SINGLE','SUS304',300,300,210,682),
  ('JA_SINGLE','SUS316',300,300,210,682),
  ('JA_SINGLE','SUS304',600,380,350,1055),
  ('JA_SINGLE','SUS316',600,380,350,1055),
  ('JE_SINGLE','SECC',800,1200,300,1187),
  ('JE_SINGLE','SUS304',800,1200,300,2276),
  ('JE_SINGLE','SUS316',800,1200,300,2276);

DO $$
DECLARE bad record;
BEGIN
  IF (SELECT count(*) FROM quick_price_update)<>8 THEN RAISE EXCEPTION '本次价格表必须恰好包含8行'; END IF;
  SELECT u.*,m.matched INTO bad FROM quick_price_update u
  CROSS JOIN LATERAL (
    SELECT count(*) AS matched FROM calc.quick_quote_experience q
    WHERE q.product_code=u.product_code AND q.material_code=u.material_code
      AND q.reference_width_mm=u.width_mm AND q.reference_height_mm=u.height_mm AND q.reference_depth_mm=u.depth_mm
      AND q.is_active AND q.effective_from<=current_date AND (q.effective_to IS NULL OR current_date<q.effective_to)
  ) m WHERE m.matched<>1 LIMIT 1;
  IF FOUND THEN RAISE EXCEPTION '快速报价目标必须唯一匹配：% % %x%x%，实际% 行',
    bad.product_code,bad.material_code,bad.width_mm,bad.height_mm,bad.depth_mm,bad.matched; END IF;
END $$;

UPDATE calc.quick_quote_experience q
SET quick_base_price=u.new_price,quick_total_cost=u.new_price,
    notes=concat_ws('；',nullif(q.notes,''),'快速面价2026-09-20人工更新')
FROM quick_price_update u
WHERE q.product_code=u.product_code AND q.material_code=u.material_code
  AND q.reference_width_mm=u.width_mm AND q.reference_height_mm=u.height_mm AND q.reference_depth_mm=u.depth_mm
  AND q.is_active AND q.effective_from<=current_date AND (q.effective_to IS NULL OR current_date<q.effective_to);

SELECT q.quick_rule_id,q.product_code,q.material_code,q.reference_width_mm,q.reference_height_mm,q.reference_depth_mm,
       q.quick_base_price,q.quick_total_cost
FROM calc.quick_quote_experience q JOIN quick_price_update u
  ON q.product_code=u.product_code AND q.material_code=u.material_code
 AND q.reference_width_mm=u.width_mm AND q.reference_height_mm=u.height_mm AND q.reference_depth_mm=u.depth_mm
WHERE q.is_active AND q.effective_from<=current_date AND (q.effective_to IS NULL OR current_date<q.effective_to)
ORDER BY q.product_code,q.reference_width_mm,q.material_code;

COMMIT;
