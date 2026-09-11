-- Run only after the matching Render API and 2026.09.11 client are deployed.
-- All five catalog switches are atomic: any failed assertion rolls back all.
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
      AND status='STAGED'
  ) THEN
    RAISE EXCEPTION 'Attachment r4 is not the expected STAGED source';
  END IF;
  IF (SELECT count(*) FROM calc.attachment_price
      WHERE data_version='xlsx-7b6fcb18de6f8969-r4')<>226 THEN
    RAISE EXCEPTION 'Attachment r4 must contain exactly 226 rows';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_material_catalog_version
    WHERE data_version='cabinet-material-91cc0a5f841b7455-v1'
      AND source_sha256='91cc0a5f841b74559a34a7408a604e41d5fe76e8db3743b20a32ff657c2b2151'
      AND status='STAGED' AND default_waste_factor=1.2
  ) THEN
    RAISE EXCEPTION 'Cabinet material v1 is not the expected STAGED source';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_material_rule
      WHERE data_version='cabinet-material-91cc0a5f841b7455-v1')<>241 THEN
    RAISE EXCEPTION 'Cabinet material v1 must contain exactly 241 rules';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_spray_catalog_version
    WHERE data_version='cabinet-spray-13f257f440859e3b-v1'
      AND source_sha256='13f257f440859e3b0922aa690241c1b43068d687042b9bd3b2eccc2aab051fd9'
      AND status='STAGED'
  ) THEN
    RAISE EXCEPTION 'Cabinet spray v1 is not the expected STAGED source';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_spray_rule
      WHERE data_version='cabinet-spray-13f257f440859e3b-v1')<>202 THEN
    RAISE EXCEPTION 'Cabinet spray v1 must contain exactly 202 rules';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_auxiliary_catalog_version
    WHERE data_version='cabinet-auxiliary-1dc400290ae91924-v1'
      AND source_sha256='1dc400290ae9192473d61a4dafb3545ba744eb0eb8a62650448a6219b0f7840a'
      AND status='STAGED'
  ) OR (SELECT count(*) FROM calc.cabinet_auxiliary_profile
        WHERE data_version='cabinet-auxiliary-1dc400290ae91924-v1')<>16
     OR (SELECT count(*) FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
        WHERE p.data_version='cabinet-auxiliary-1dc400290ae91924-v1')<>255 THEN
    RAISE EXCEPTION 'Cabinet auxiliary v1 is not the expected complete STAGED source';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM calc.cabinet_labor_catalog_version
    WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1'
      AND source_sha256='a3d12580527a3eb69eedd47b35107b0c8577333d1a52a7331ce8730dd866d1bd'
      AND status='STAGED' AND management_fee_rate=0.13
  ) OR (SELECT count(*) FROM calc.cabinet_labor_rule
        WHERE data_version='cabinet-labor-a3d12580527a3eb6-v1')<>57 THEN
    RAISE EXCEPTION 'Cabinet labor v1 is not the expected complete STAGED source';
  END IF;
END $$;

SELECT calc.switch_attachment_catalog_v2('xlsx-7b6fcb18de6f8969-r4');
SELECT calc.activate_cabinet_material_catalog_v1('cabinet-material-91cc0a5f841b7455-v1');
SELECT calc.activate_cabinet_spray_catalog_v1('cabinet-spray-13f257f440859e3b-v1');
SELECT calc.activate_cabinet_auxiliary_catalog_v1('cabinet-auxiliary-1dc400290ae91924-v1');
SELECT calc.activate_cabinet_labor_catalog_v1('cabinet-labor-a3d12580527a3eb6-v1');

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
                    WHERE status='ACTIVE' AND data_version='cabinet-material-91cc0a5f841b7455-v1') THEN
    RAISE EXCEPTION 'Post-switch cabinet material version assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_spray_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.cabinet_spray_catalog_version
                    WHERE status='ACTIVE' AND data_version='cabinet-spray-13f257f440859e3b-v1') THEN
    RAISE EXCEPTION 'Post-switch cabinet spray version assertion failed';
  END IF;
  IF (SELECT count(*) FROM calc.cabinet_auxiliary_catalog_version WHERE status='ACTIVE')<>1
     OR NOT EXISTS (SELECT 1 FROM calc.cabinet_auxiliary_catalog_version
                    WHERE status='ACTIVE' AND data_version='cabinet-auxiliary-1dc400290ae91924-v1') THEN
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
