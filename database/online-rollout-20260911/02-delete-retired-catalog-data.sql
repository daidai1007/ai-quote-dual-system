-- Physical cleanup after activation, smoke tests, and saved-quote reopen/export tests.
-- Deletes only retired/unreferenced catalog data. Never deletes quote history.
-- No CASCADE is used for attachment data; an unexpected dependency aborts the transaction.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

DO $$
BEGIN
  IF (SELECT count(*) FROM calc.attachment_price WHERE is_active)<>226
     OR (SELECT count(*) FROM calc.attachment_price
         WHERE is_active AND data_version='xlsx-7b6fcb18de6f8969-r4')<>226 THEN
    RAISE EXCEPTION 'Refusing cleanup: expected attachment r4 to be the only 226 active rows';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM calc.cabinet_material_catalog_version
                 WHERE status='ACTIVE'
                   AND data_version='cabinet-material-4f8bf726efa6568d-v2') THEN
    RAISE EXCEPTION 'Refusing cleanup: expected cabinet material v2 ACTIVE';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM calc.cabinet_spray_catalog_version
                 WHERE status='ACTIVE' AND data_version='cabinet-spray-4b3d73c9cb7a6f26-v2') THEN
    RAISE EXCEPTION 'Refusing cleanup: expected cabinet spray v2 ACTIVE';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM calc.cabinet_auxiliary_catalog_version
                 WHERE status='ACTIVE' AND data_version='cabinet-auxiliary-706c234a5de12a39-v2') THEN
    RAISE EXCEPTION 'Refusing cleanup: expected cabinet auxiliary v2 ACTIVE';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM calc.cabinet_labor_catalog_version
                 WHERE status='ACTIVE' AND data_version='cabinet-labor-a3d12580527a3eb6-v1') THEN
    RAISE EXCEPTION 'Refusing cleanup: expected cabinet labor v1 ACTIVE';
  END IF;
END $$;

LOCK TABLE calc.attachment_price IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE cleanup_baseline ON COMMIT DROP AS
SELECT count(*)::bigint AS attachment_selection_count
FROM calc.attachment_selection;

-- Preserve an entire retired attachment version when any saved selection references it.
CREATE TEMP TABLE purge_attachment_versions ON COMMIT DROP AS
SELECT v.data_version
FROM calc.attachment_catalog_version v
WHERE v.status='RETIRED'
  AND v.data_version<>'xlsx-7b6fcb18de6f8969-r4'
  AND NOT EXISTS (
    SELECT 1 FROM calc.attachment_selection s
    WHERE s.catalog_version=v.data_version OR s.rule_version=v.data_version
  );

CREATE TEMP TABLE purge_attachment_rules ON COMMIT DROP AS
SELECT r.rule_id
FROM calc.attachment_cost_rule r
JOIN purge_attachment_versions v USING(data_version);

CREATE TEMP TABLE purge_attachment_prices ON COMMIT DROP AS
SELECT p.attachment_price_id
FROM calc.attachment_price p
JOIN purge_attachment_versions v USING(data_version)
WHERE NOT EXISTS (
  SELECT 1 FROM calc.attachment_selection s
  WHERE s.attachment_price_id=p.attachment_price_id
);

-- Old pre-version catalog rows may be removed only when no quote history references them.
INSERT INTO purge_attachment_prices(attachment_price_id)
SELECT p.attachment_price_id
FROM calc.attachment_price p
WHERE p.data_version IS NULL
  AND NOT p.is_active
  AND NOT EXISTS (
    SELECT 1 FROM calc.attachment_selection s
    WHERE s.attachment_price_id=p.attachment_price_id
  );

SELECT (SELECT count(*) FROM purge_attachment_versions) AS retired_attachment_versions_to_delete,
       (SELECT count(*) FROM purge_attachment_rules) AS retired_attachment_rules_to_delete,
       (SELECT count(*) FROM purge_attachment_prices) AS old_attachment_prices_to_delete,
       (SELECT count(*) FROM calc.attachment_selection) AS history_rows_before_cleanup;

DELETE FROM calc.attachment_cost_rule_binding b
WHERE b.rule_id IN (SELECT rule_id FROM purge_attachment_rules)
   OR b.attachment_price_id IN (SELECT attachment_price_id FROM purge_attachment_prices);
DELETE FROM calc.attachment_cost_rule_product p
WHERE p.rule_id IN (SELECT rule_id FROM purge_attachment_rules);
DELETE FROM calc.attachment_cost_rule_material m
WHERE m.rule_id IN (SELECT rule_id FROM purge_attachment_rules);
DELETE FROM calc.attachment_cost_rule_parameter p
WHERE p.rule_id IN (SELECT rule_id FROM purge_attachment_rules);
DELETE FROM calc.attachment_classification c
WHERE c.attachment_price_id IN (SELECT attachment_price_id FROM purge_attachment_prices);
DELETE FROM calc.attachment_cost_rule r
WHERE r.rule_id IN (SELECT rule_id FROM purge_attachment_rules);
DELETE FROM calc.attachment_price p
WHERE p.attachment_price_id IN (SELECT attachment_price_id FROM purge_attachment_prices);
DELETE FROM calc.attachment_catalog_version v
WHERE v.data_version IN (SELECT data_version FROM purge_attachment_versions);

-- Replacement cabinet-material versions are snapshot based; deleting RETIRED versions
-- cascades only to their cabinet_material_rule and cabinet_material_fixed_rule children.
DELETE FROM calc.cabinet_material_catalog_version
WHERE status='RETIRED';
DELETE FROM calc.cabinet_spray_catalog_version
WHERE status='RETIRED';
DELETE FROM calc.cabinet_auxiliary_catalog_version
WHERE status='RETIRED';
DELETE FROM calc.cabinet_labor_catalog_version
WHERE status='RETIRED';

DO $$
BEGIN
  IF (SELECT count(*) FROM calc.attachment_price WHERE is_active)<>226
     OR (SELECT count(*) FROM calc.attachment_selection)<>
        (SELECT attachment_selection_count FROM cleanup_baseline) THEN
    RAISE EXCEPTION 'Cleanup postcondition failed; transaction will roll back';
  END IF;
  IF EXISTS (
    SELECT 1 FROM calc.attachment_selection s
    LEFT JOIN calc.attachment_price p ON p.attachment_price_id=s.attachment_price_id
    WHERE s.attachment_price_id IS NOT NULL AND p.attachment_price_id IS NULL
  ) THEN
    RAISE EXCEPTION 'Cleanup created an orphan attachment selection';
  END IF;
END $$;

SELECT count(*) AS attachment_price_total,
       count(*) FILTER (WHERE is_active) AS attachment_price_active,
       count(*) FILTER (WHERE data_version IS NULL) AS legacy_prices_retained_for_history
FROM calc.attachment_price;
SELECT count(*) AS attachment_selection_total_after_cleanup
FROM calc.attachment_selection;
SELECT data_version,status FROM calc.attachment_catalog_version ORDER BY created_at;
SELECT data_version,status FROM calc.cabinet_material_catalog_version ORDER BY created_at;
SELECT data_version,status FROM calc.cabinet_spray_catalog_version ORDER BY created_at;
SELECT data_version,status FROM calc.cabinet_auxiliary_catalog_version ORDER BY created_at;
SELECT data_version,status FROM calc.cabinet_labor_catalog_version ORDER BY created_at;

COMMIT;
