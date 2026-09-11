-- Run only after the matching Render API and 2026.09.11 client are deployed.
-- Safe when an expected target is already ACTIVE; remaining switches are atomic.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
SET LOCAL calc.attachment_v2_api_ready='on';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM calc.attachment_catalog_version
    WHERE data_version='xlsx-7b6fcb18de6f8969-r4'
      AND source_sha256='7b6fcb18de6f896942a627f70abbd91ba4e5587ed87e57abe837b4c03f043a64'
      AND status IN ('STAGED','ACTIVE')
  ) THEN
    RAISE EXCEPTION 'Attachment r4 is not the expected STAGED/ACTIVE source';
  END IF;
  IF (SELECT count(*) FROM calc.attachment_price
      WHERE data_version='xlsx-7b6fcb18de6f8969-r4')<>226 THEN
    RAISE EXCEPTION 'Attachment r4 must contain exactly 226 rows';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_material_catalog_version
    WHERE data_version='cabinet-material-4f8bf726efa6568d-v2'
      AND source_sha256='4f8bf726efa6568df4ea540f162598f49b09f0174f61c3578ac5189721f17a7f'
      AND status IN ('STAGED','ACTIVE') AND default_waste_factor=1.2
  ) THEN
    RAISE EXCEPTION 'Cabinet material v2 is not the expected STAGED/ACTIVE source';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_material_rule
      WHERE data_version='cabinet-material-4f8bf726efa6568d-v2')<>241
     OR (SELECT count(*) FROM calc.cabinet_material_fixed_rule
      WHERE data_version='cabinet-material-4f8bf726efa6568d-v2')<>46 THEN
    RAISE EXCEPTION 'Cabinet material v2 must contain exactly 241 area rules and 46 fixed rules';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_spray_catalog_version
    WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2'
      AND source_sha256='4b3d73c9cb7a6f269ed4cbe7ea3880979550fece11ab5e527c295036a4581c30'
      AND status IN ('STAGED','ACTIVE')
  ) THEN
    RAISE EXCEPTION 'Cabinet spray v2 is not the expected STAGED/ACTIVE source';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_spray_rule
      WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2')<>202
     OR (SELECT count(*) FROM calc.cabinet_spray_fixed_rule
      WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2')<>46 THEN
    RAISE EXCEPTION 'Cabinet spray v2 must contain 202 area rules and 46 fixed rules';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_auxiliary_catalog_version
    WHERE data_version='cabinet-auxiliary-706c234a5de12a39-v2'
      AND source_sha256='706c234a5de12a39ec5f32ab0ce8174066c94317d467cedcbb62843b728c214f'
      AND status IN ('STAGED','ACTIVE')
  ) OR (SELECT count(*) FROM calc.cabinet_auxiliary_profile
        WHERE data_version='cabinet-auxiliary-706c234a5de12a39-v2')<>16
     OR (SELECT count(*) FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
        WHERE p.data_version='cabinet-auxiliary-706c234a5de12a39-v2')<>255
     OR (SELECT count(*) FROM calc.cabinet_auxiliary_fixed_rule
        WHERE data_version='cabinet-auxiliary-706c234a5de12a39-v2')<>72 THEN
    RAISE EXCEPTION 'Cabinet auxiliary v2 is not the expected complete STAGED/ACTIVE source';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_labor_catalog_version
    WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1'
      AND source_sha256='a3d12580527a3eb69eedd47b35107b0c8577333d1a52a7331ce8730dd866d1bd'
      AND status IN ('STAGED','ACTIVE') AND management_fee_rate=0.13
  ) OR (SELECT count(*) FROM calc.cabinet_labor_rule
        WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1')<>57 THEN
    RAISE EXCEPTION 'Cabinet labor v1 is not the expected complete STAGED/ACTIVE source';
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM calc.attachment_catalog_version
            WHERE data_version='xlsx-7b6fcb18de6f8969-r4' AND status='STAGED') THEN
    PERFORM calc.switch_attachment_catalog_v2('xlsx-7b6fcb18de6f8969-r4');
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_material_catalog_version
            WHERE data_version='cabinet-material-4f8bf726efa6568d-v2' AND status='STAGED') THEN
    PERFORM calc.activate_cabinet_material_catalog_v2('cabinet-material-4f8bf726efa6568d-v2');
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_spray_catalog_version
            WHERE data_version='cabinet-spray-4b3d73c9cb7a6f26-v2' AND status='STAGED') THEN
    PERFORM calc.activate_cabinet_spray_catalog_v2('cabinet-spray-4b3d73c9cb7a6f26-v2');
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_catalog_version
            WHERE data_version='cabinet-auxiliary-706c234a5de12a39-v2' AND status='STAGED') THEN
    PERFORM calc.activate_cabinet_auxiliary_catalog_v2('cabinet-auxiliary-706c234a5de12a39-v2');
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_labor_catalog_version
            WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1' AND status='STAGED') THEN
    PERFORM calc.activate_cabinet_labor_catalog_v1('cabinet-labor-a3d12580527a3eb6-v1');
  END IF;
END $$;

DO $$
BEGIN
  IF (SELECT count(*) FROM calc.attachment_price WHERE is_active)<>226
     OR (SELECT count(*) FROM calc.attachment_price
         WHERE is_active AND data_version='xlsx-7b6fcb18de6f8969-r4')<>226 THEN
    RAISE EXCEPTION 'Post-switch attachment active-row assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.attachment_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.attachment_catalog_version
                    WHERE status='ACTIVE' AND data_version='xlsx-7b6fcb18de6f8969-r4') THEN
    RAISE EXCEPTION 'Post-switch attachment version assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_material_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.cabinet_material_catalog_version
                    WHERE status='ACTIVE' AND data_version='cabinet-material-4f8bf726efa6568d-v2') THEN
    RAISE EXCEPTION 'Post-switch cabinet material version assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_spray_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.cabinet_spray_catalog_version
                    WHERE status='ACTIVE' AND data_version='cabinet-spray-4b3d73c9cb7a6f26-v2') THEN
    RAISE EXCEPTION 'Post-switch cabinet spray version assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_auxiliary_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.cabinet_auxiliary_catalog_version
                    WHERE status='ACTIVE' AND data_version='cabinet-auxiliary-706c234a5de12a39-v2') THEN
    RAISE EXCEPTION 'Post-switch cabinet auxiliary version assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_labor_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.cabinet_labor_catalog_version
                    WHERE status='ACTIVE' AND data_version='cabinet-labor-a3d12580527a3eb6-v1') THEN
    RAISE EXCEPTION 'Post-switch cabinet labor version assertion failed';
  END IF;
END $$;

SELECT 'attachment' AS catalog,data_version,status,activated_at
FROM calc.attachment_catalog_version ORDER BY created_at;
SELECT 'cabinet_material' AS catalog,data_version,status,activated_at
FROM calc.cabinet_material_catalog_version ORDER BY created_at;
SELECT 'cabinet_spray' AS catalog,data_version,status,activated_at
FROM calc.cabinet_spray_catalog_version ORDER BY created_at;
SELECT 'cabinet_auxiliary' AS catalog,data_version,status,activated_at
FROM calc.cabinet_auxiliary_catalog_version ORDER BY created_at;
SELECT 'cabinet_labor' AS catalog,data_version,status,activated_at
FROM calc.cabinet_labor_catalog_version ORDER BY created_at;

COMMIT;
