-- Maintenance transaction:
--   1. preserves all V2 attachment snapshots and quote-line snapshots;
--   2. removes every legacy attachment_selection row;
--   3. activates the validated r4 attachment catalog;
--   4. removes every pre-version attachment price/classification row.
-- It does not modify dual_quote_result or any cabinet material/spray/auxiliary/labor catalog.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
SET LOCAL calc.attachment_v2_api_ready='on';

DO $$
DECLARE unexpected_fk text;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM calc.attachment_catalog_version
    WHERE data_version='xlsx-7b6fcb18de6f8969-r4'
      AND source_sha256='7b6fcb18de6f896942a627f70abbd91ba4e5587ed87e57abe837b4c03f043a64'
      AND status='STAGED'
  ) THEN
    RAISE EXCEPTION 'Refusing cleanup: attachment r4 is not the expected STAGED source';
  END IF;

  IF (SELECT count(*) FROM calc.attachment_price
      WHERE data_version='xlsx-7b6fcb18de6f8969-r4')<>226 THEN
    RAISE EXCEPTION 'Refusing cleanup: attachment r4 must contain exactly 226 rows';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM calc.attachment_selection s
    LEFT JOIN calc.attachment_price p USING(attachment_price_id)
    WHERE s.calculation_status IS NOT NULL
      AND s.attachment_price_id IS NOT NULL
      AND p.attachment_price_id IS NULL
  ) THEN
    RAISE EXCEPTION 'Refusing cleanup: a V2 attachment snapshot is already orphaned';
  END IF;

  SELECT string_agg(con.conrelid::regclass::text||'.'||con.conname,', ' ORDER BY con.conrelid::regclass::text,con.conname)
  INTO unexpected_fk
  FROM pg_constraint con
  WHERE con.contype='f'
    AND con.confrelid='calc.attachment_price'::regclass
    AND con.conrelid::regclass::text NOT IN (
      'calc.attachment_classification',
      'calc.attachment_selection',
      'calc.attachment_cost_rule_binding'
    );

  IF unexpected_fk IS NOT NULL THEN
    RAISE EXCEPTION 'Refusing cleanup: unexpected attachment_price foreign keys: %',unexpected_fk;
  END IF;
END $$;

LOCK TABLE calc.attachment_selection,calc.attachment_price,
           calc.attachment_classification,calc.attachment_cost_rule_binding
IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE attachment_cleanup_baseline ON COMMIT DROP AS
SELECT count(*) FILTER (WHERE calculation_status IS NULL)::bigint AS legacy_selection_rows,
       count(*) FILTER (WHERE calculation_status IS NOT NULL)::bigint AS v2_selection_rows
FROM calc.attachment_selection;

SELECT legacy_selection_rows AS legacy_selection_rows_to_delete,
       v2_selection_rows AS v2_selection_rows_to_keep
FROM attachment_cleanup_baseline;

-- User-authorized removal of old quotation attachment details.
-- V2 immutable snapshots (calculation_status IS NOT NULL) are preserved.
DELETE FROM calc.attachment_selection
WHERE calculation_status IS NULL;

-- Switch first so the API always has one valid attachment catalog at commit time.
SELECT calc.switch_attachment_catalog_v2('xlsx-7b6fcb18de6f8969-r4') AS activated_attachment_catalog;

-- Remove bindings before their legacy attachment prices. The r4 bindings are untouched.
DELETE FROM calc.attachment_cost_rule_binding b
USING calc.attachment_price p
WHERE b.attachment_price_id=p.attachment_price_id
  AND p.data_version IS NULL;

DELETE FROM calc.attachment_classification c
USING calc.attachment_price p
WHERE c.attachment_price_id=p.attachment_price_id
  AND p.data_version IS NULL;

DELETE FROM calc.attachment_price
WHERE data_version IS NULL;

DO $$
BEGIN
  IF (SELECT count(*) FROM calc.attachment_selection WHERE calculation_status IS NULL)<>0 THEN
    RAISE EXCEPTION 'Cleanup postcondition failed: legacy attachment selections remain';
  END IF;

  IF (SELECT count(*) FROM calc.attachment_selection WHERE calculation_status IS NOT NULL)<>
     (SELECT v2_selection_rows FROM attachment_cleanup_baseline) THEN
    RAISE EXCEPTION 'Cleanup postcondition failed: V2 attachment snapshot count changed';
  END IF;

  IF (SELECT count(*) FROM calc.attachment_price WHERE data_version IS NULL)<>0 THEN
    RAISE EXCEPTION 'Cleanup postcondition failed: legacy attachment prices remain';
  END IF;

  IF (SELECT count(*) FROM calc.attachment_price WHERE is_active)<>226
     OR (SELECT count(*) FROM calc.attachment_price
         WHERE is_active AND data_version='xlsx-7b6fcb18de6f8969-r4')<>226 THEN
    RAISE EXCEPTION 'Cleanup postcondition failed: r4 is not the only 226-row active catalog';
  END IF;

  IF (SELECT count(*) FROM calc.attachment_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (
       SELECT 1 FROM calc.attachment_catalog_version
       WHERE status='ACTIVE' AND data_version='xlsx-7b6fcb18de6f8969-r4'
     ) THEN
    RAISE EXCEPTION 'Cleanup postcondition failed: r4 version is not uniquely ACTIVE';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM calc.attachment_selection s
    LEFT JOIN calc.attachment_price p USING(attachment_price_id)
    WHERE s.attachment_price_id IS NOT NULL
      AND p.attachment_price_id IS NULL
  ) THEN
    RAISE EXCEPTION 'Cleanup postcondition failed: attachment selection orphan created';
  END IF;
END $$;

SELECT count(*) AS attachment_price_total,
       count(*) FILTER (WHERE is_active) AS attachment_price_active,
       count(*) FILTER (WHERE data_version IS NULL) AS legacy_price_rows
FROM calc.attachment_price;

SELECT count(*) FILTER (WHERE calculation_status IS NULL) AS legacy_selection_rows,
       count(*) FILTER (WHERE calculation_status IS NOT NULL) AS v2_selection_rows
FROM calc.attachment_selection;

SELECT data_version,status,activated_at
FROM calc.attachment_catalog_version
ORDER BY created_at;

COMMIT;
