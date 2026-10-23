-- TEMPLATE ONLY. No production allocation is authorized by this task.
-- Replace NULLs only with a separately user-confirmed scheme allocation list.
-- Derive owner_user_id using api/name_login_service.mjs:nameUserId.
-- Explicitly enable the commented confirmation setting only after that review.
BEGIN;
-- SET LOCAL ai_quote.legacy_scope_mapping_confirmation='USER_APPROVED_LIST';
CREATE TEMP TABLE approved_name_scope_assignments(
 scheme_id bigint,owner_user_id text,owner_display_name text,confirmed_by_name text,mapping_basis text
) ON COMMIT DROP;
INSERT INTO approved_name_scope_assignments VALUES(NULL,NULL,NULL,NULL,NULL);
DO $$ BEGIN
 IF current_setting('ai_quote.legacy_scope_mapping_confirmation',true) IS DISTINCT FROM 'USER_APPROVED_LIST'
   OR EXISTS(SELECT 1 FROM approved_name_scope_assignments WHERE scheme_id IS NULL
     OR owner_user_id IS NULL OR owner_user_id !~ '^name-user:[0-9a-f]{64}$'
     OR nullif(btrim(owner_display_name),'') IS NULL OR nullif(btrim(confirmed_by_name),'') IS NULL OR nullif(btrim(mapping_basis),'') IS NULL)
 THEN RAISE EXCEPTION 'No confirmed allocation list: template blocked, no ownership assigned'; END IF;
 IF EXISTS(SELECT scheme_id FROM approved_name_scope_assignments GROUP BY scheme_id HAVING count(DISTINCT owner_user_id)>1)
   OR EXISTS(SELECT 1 FROM approved_name_scope_assignments a WHERE NOT EXISTS(SELECT 1 FROM calc.quote_scheme s WHERE s.scheme_id=a.scheme_id))
   OR EXISTS(SELECT 1 FROM approved_name_scope_assignments a JOIN calc.quote_scheme s USING(scheme_id) WHERE s.creator_user_id LIKE 'name-user:%')
   OR EXISTS(SELECT 1 FROM approved_name_scope_assignments a JOIN calc.quote_name_owner own
     ON own.resource_kind='SCHEME' AND own.resource_key=a.scheme_id::text WHERE own.owner_user_id<>a.owner_user_id)
 THEN RAISE EXCEPTION 'Allocation conflicts or missing schemes: no ownership assigned'; END IF;
 IF EXISTS(SELECT 1 FROM approved_name_scope_assignments WHERE owner_user_id<>'name-user:'||encode(sha256(convert_to(normalize(btrim(owner_display_name),NFC),'UTF8')),'hex'))
 THEN RAISE EXCEPTION 'Name identity mismatch: no ownership assigned'; END IF;
END $$;
INSERT INTO calc.quote_name_owner(resource_kind,resource_key,owner_user_id,confirmed_by_name,mapping_source,mapping_basis)
SELECT DISTINCT 'SCHEME',scheme_id::text,owner_user_id,confirmed_by_name,'USER_CONFIRMED_LEGACY',mapping_basis
FROM approved_name_scope_assignments ON CONFLICT DO NOTHING;
COMMIT;
