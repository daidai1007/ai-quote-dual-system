-- Manual deployment only. Does not change catalogue rows, bindings or history.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';

CREATE OR REPLACE FUNCTION calc.resolve_attachment_cost_rule(
  p_attachment_price_id bigint,p_product_code text,p_material_code text
)
RETURNS bigint LANGUAGE plpgsql STABLE AS $$
DECLARE
  candidates bigint[];
  product_candidates bigint[];
BEGIN
  SELECT array_agg(r.rule_id) INTO product_candidates
  FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id)
  WHERE b.attachment_price_id=p_attachment_price_id AND
    (NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_product p WHERE p.rule_id=r.rule_id)
     OR EXISTS(SELECT 1 FROM calc.attachment_cost_rule_product p
       WHERE p.rule_id=r.rule_id AND p.product_code=p_product_code));

  IF coalesce(cardinality(product_candidates),0)=0 AND EXISTS(
    SELECT 1 FROM calc.attachment_classification c
    WHERE c.attachment_price_id=p_attachment_price_id
      AND c.category_level1 IN ('控制柜附件','控制箱附件')
  ) THEN
    SELECT array_agg(r.rule_id) INTO product_candidates
    FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id)
    WHERE b.attachment_price_id=p_attachment_price_id
      AND NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_product p
        WHERE p.rule_id=r.rule_id AND position('WIDE' IN p.product_code)>0);
  END IF;
  IF coalesce(cardinality(product_candidates),0)=0 THEN RETURN NULL; END IF;

  IF EXISTS(SELECT 1 FROM calc.attachment_cost_rule_material m WHERE m.rule_id=ANY(product_candidates))
    AND (p_material_code IS NULL OR p_material_code NOT IN ('SECC','SUS304','SUS316')) THEN
    RAISE EXCEPTION '材质适用规则需要有效材质：SECC、SUS304或SUS316';
  END IF;
  WITH candidates AS (
    SELECT r.rule_id,CASE WHEN EXISTS(
      SELECT 1 FROM calc.attachment_cost_rule_product p
      WHERE p.rule_id=r.rule_id AND p.product_code=p_product_code
    ) THEN 1 ELSE 0 END AS priority
    FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id)
    WHERE b.attachment_price_id=p_attachment_price_id AND r.rule_id=ANY(product_candidates) AND
      (NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_material m WHERE m.rule_id=r.rule_id)
       OR EXISTS(SELECT 1 FROM calc.attachment_cost_rule_material m
         WHERE m.rule_id=r.rule_id AND m.material_code=p_material_code))
  ) SELECT array_agg(rule_id) INTO candidates FROM candidates
    WHERE priority=(SELECT max(priority) FROM candidates);
  IF coalesce(cardinality(candidates),0)=0 THEN
    RAISE EXCEPTION '当前材质 % 缺少附件成本规则',p_material_code;
  END IF;
  IF cardinality(candidates)>1 THEN RAISE EXCEPTION '同级成本规则冲突：%',candidates; END IF;
  RETURN candidates[1];
END $$;
COMMIT;
