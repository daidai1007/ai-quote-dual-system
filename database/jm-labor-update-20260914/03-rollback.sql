BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

DO $rollback$
DECLARE v_active text;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_labor_catalog_version'));
  SELECT data_version INTO STRICT v_active
  FROM calc.cabinet_labor_catalog_version WHERE status='ACTIVE';
  IF v_active<>'cabinet-labor-01249192a2981dc7-v2' THEN
    RAISE EXCEPTION 'Refusing rollback: active labor version is %',v_active;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_labor_catalog_version
    WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1'
      AND status='RETIRED'
  ) THEN
    RAISE EXCEPTION 'Original labor version is missing or not RETIRED';
  END IF;
  UPDATE calc.cabinet_labor_catalog_version
  SET status='RETIRED',activated_at=NULL
  WHERE data_version='cabinet-labor-01249192a2981dc7-v2';
  UPDATE calc.cabinet_labor_catalog_version
  SET status='ACTIVE',activated_at=current_timestamp
  WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1';
END
$rollback$;

COMMIT;
