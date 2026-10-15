BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

-- Extend the active fixed-base formula rule to JM without changing the
-- catalogue price, formula, historical snapshots, or other product rules.
CREATE TEMP TABLE active_attachment_version(
  data_version text PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO active_attachment_version(data_version)
SELECT data_version
FROM calc.attachment_catalog_version
WHERE status='ACTIVE';

DO $$
BEGIN
  IF (SELECT count(*) FROM active_attachment_version)<>1 THEN
    RAISE EXCEPTION '必须且只能有一个活动附件目录版本';
  END IF;
  IF (
    SELECT count(*)
    FROM calc.attachment_cost_rule r
    JOIN active_attachment_version v ON v.data_version=r.data_version
    WHERE r.import_key='R11'
  )<>1 THEN
    RAISE EXCEPTION '当前活动目录缺少唯一固定底座公式规则 R11';
  END IF;
END $$;

INSERT INTO calc.attachment_cost_rule_product(rule_id,product_code)
SELECT r.rule_id,'JM'
FROM calc.attachment_cost_rule r
JOIN active_attachment_version v ON v.data_version=r.data_version
WHERE r.import_key='R11'
  AND NOT EXISTS(
    SELECT 1
    FROM calc.attachment_cost_rule_product p
    WHERE p.rule_id=r.rule_id AND p.product_code='JM'
  );

DO $$
DECLARE v_rule_id bigint;
BEGIN
  SELECT r.rule_id INTO STRICT v_rule_id
  FROM calc.attachment_cost_rule r
  JOIN active_attachment_version v ON v.data_version=r.data_version
  WHERE r.import_key='R11';

  IF NOT EXISTS(
    SELECT 1 FROM calc.attachment_cost_rule_product
    WHERE rule_id=v_rule_id AND product_code='JM'
  ) THEN
    RAISE EXCEPTION 'R11 未成功增加 JM 适用产品';
  END IF;

  IF NOT EXISTS(
    SELECT 1 FROM calc.attachment_cost_rule_product
    WHERE rule_id=v_rule_id AND product_code='JS'
  ) OR NOT EXISTS(
    SELECT 1 FROM calc.attachment_cost_rule_product
    WHERE rule_id=v_rule_id AND product_code='JP'
  ) THEN
    RAISE EXCEPTION 'R11 原有 JS/JP 适用产品被意外改变';
  END IF;
END $$;

SELECT r.rule_id,r.data_version,r.import_key,r.method,
       array_agg(p.product_code ORDER BY p.product_code) AS products
FROM calc.attachment_cost_rule r
JOIN active_attachment_version v ON v.data_version=r.data_version
LEFT JOIN calc.attachment_cost_rule_product p USING(rule_id)
WHERE r.import_key='R11'
GROUP BY r.rule_id,r.data_version,r.import_key,r.method;

COMMIT;
