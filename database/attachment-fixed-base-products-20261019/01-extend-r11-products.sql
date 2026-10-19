BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

-- Same lock as the catalogue switch/import functions. Only extend the active
-- fixed-base rule's product links; do not rewrite formulas, prices or snapshots.
SELECT pg_advisory_xact_lock(hashtext('calc.attachment_catalog_v2'));

CREATE TEMP TABLE r11_extension_target(product_code text PRIMARY KEY) ON COMMIT DROP;
INSERT INTO r11_extension_target(product_code) VALUES
  ('JQ_EXP'),('JE'),('JE_SINGLE'),('JE_DOUBLE'),('JS_WIDE_EXP'),('JP_WIDE_EXP');

CREATE TEMP TABLE r11_extension_rule ON COMMIT DROP AS
SELECT r.rule_id,r.data_version
FROM calc.attachment_cost_rule r
JOIN calc.attachment_catalog_version v USING(data_version)
WHERE v.status='ACTIVE' AND r.import_key='R11';

DO $$
BEGIN
  IF (SELECT count(*) FROM calc.attachment_catalog_version WHERE status='ACTIVE')<>1 THEN
    RAISE EXCEPTION '必须且只能有一个活动附件目录版本';
  END IF;
  IF (SELECT count(*) FROM r11_extension_rule)<>1 THEN
    RAISE EXCEPTION '当前活动目录缺少唯一固定底座公式规则 R11';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.attachment_cost_rule r
    JOIN r11_extension_rule selected USING(rule_id)
    WHERE r.method='CALCULATED' AND r.category_level1='底座'
      AND r.category_level2='固定底座' AND r.item_name='固定底座'
  ) THEN
    RAISE EXCEPTION 'R11 不是预期的固定底座公式规则，请先核对';
  END IF;
END $$;

INSERT INTO calc.attachment_cost_rule_product(rule_id,product_code)
SELECT r.rule_id,t.product_code
FROM r11_extension_rule r CROSS JOIN r11_extension_target t
ON CONFLICT (rule_id,product_code) DO NOTHING;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM r11_extension_rule r CROSS JOIN r11_extension_target t
    WHERE NOT EXISTS (
      SELECT 1 FROM calc.attachment_cost_rule_product p
      WHERE p.rule_id=r.rule_id AND p.product_code=t.product_code
    )
  ) THEN
    RAISE EXCEPTION 'R11 新增产品关联不完整，已回滚';
  END IF;
END $$;

SELECT r.rule_id,r.data_version,r.import_key,r.method,
       array_agg(p.product_code ORDER BY p.product_code) AS products
FROM calc.attachment_cost_rule r
JOIN r11_extension_rule selected USING(rule_id)
JOIN calc.attachment_cost_rule_product p USING(rule_id)
GROUP BY r.rule_id,r.data_version,r.import_key,r.method;

COMMIT;
