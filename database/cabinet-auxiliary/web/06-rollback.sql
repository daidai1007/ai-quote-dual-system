BEGIN;
SET LOCAL lock_timeout='5s';
DO $$
DECLARE v_previous text;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_auxiliary_catalog_version'));
  SELECT data_version INTO v_previous FROM calc.cabinet_auxiliary_catalog_version
  WHERE status='RETIRED' AND data_version<>'cabinet-auxiliary-189ae4efbfcb40f5-v3' ORDER BY created_at DESC LIMIT 1;
  IF v_previous IS NULL THEN RAISE EXCEPTION 'No previous RETIRED auxiliary version is available'; END IF;
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='RETIRED',activated_at=NULL WHERE data_version='cabinet-auxiliary-189ae4efbfcb40f5-v3' AND status='ACTIVE';
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=v_previous;
END $$;
COMMIT;
