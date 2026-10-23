-- Additive contract metadata and immutable private Office blobs. No quote rows
-- or creator protections are changed. Apply manually after quote_scheme_center_v1.
BEGIN;
CREATE SEQUENCE IF NOT EXISTS calc.contract_record_number;
CREATE TABLE IF NOT EXISTS calc.contract_template_group (
 group_id UUID PRIMARY KEY, customer_code TEXT NOT NULL, customer_name TEXT NOT NULL,
 template_name TEXT NOT NULL CHECK(btrim(template_name)<>''), owner_user_id TEXT NOT NULL,
 owner_name TEXT NOT NULL, lock_version INTEGER NOT NULL DEFAULT 1,
 enabled BOOLEAN NOT NULL DEFAULT TRUE, is_default BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(owner_user_id,customer_code,template_name)
);
CREATE TABLE IF NOT EXISTS calc.contract_template_version (
 template_version_id BIGSERIAL PRIMARY KEY, group_id UUID NOT NULL REFERENCES calc.contract_template_group,
 version_no INTEGER NOT NULL CHECK(version_no>0), file_format TEXT NOT NULL CHECK(file_format IN ('docx','xlsx')),
 original_filename TEXT NOT NULL, file_content BYTEA NOT NULL CHECK(octet_length(file_content)<=8388608),
 file_sha256 TEXT NOT NULL, field_mapping JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(group_id,version_no)
);
CREATE TABLE IF NOT EXISTS calc.contract_generation_draft (
 draft_id UUID PRIMARY KEY, owner_user_id TEXT NOT NULL, owner_name TEXT NOT NULL,
 input_payload JSONB NOT NULL, lock_version INTEGER NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS calc.contract_generation (
 record_id UUID PRIMARY KEY, record_no TEXT NOT NULL UNIQUE,
 request_id UUID NOT NULL, input_sha256 TEXT NOT NULL, owner_user_id TEXT NOT NULL, owner_name TEXT NOT NULL,
 customer_code TEXT NOT NULL, customer_name TEXT NOT NULL, customer_contract_no TEXT NOT NULL,
 source_scheme_id BIGINT NOT NULL, source_version_no INTEGER NOT NULL,
 template_version_id BIGINT NOT NULL REFERENCES calc.contract_template_version,
 quote_method TEXT NOT NULL CHECK(quote_method IN ('QUICK','FORMULA')),
 generation_snapshot JSONB NOT NULL, file_format TEXT NOT NULL CHECK(file_format IN ('docx','xlsx')),
 file_content BYTEA NOT NULL CHECK(octet_length(file_content)<=16777216),file_sha256 TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),UNIQUE(owner_user_id,request_id),
 FOREIGN KEY(source_scheme_id,source_version_no) REFERENCES calc.quote_scheme_version(scheme_id,version_no)
);
CREATE INDEX IF NOT EXISTS idx_contract_generation_owner ON calc.contract_generation(owner_user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contract_template_owner ON calc.contract_template_group(owner_user_id,customer_code);
CREATE INDEX IF NOT EXISTS idx_contract_draft_owner ON calc.contract_generation_draft(owner_user_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS calc.contract_audit (
 audit_id BIGSERIAL PRIMARY KEY,resource_kind TEXT NOT NULL,resource_id TEXT NOT NULL,
 action TEXT NOT NULL,actor_user_id TEXT NOT NULL,actor_name TEXT NOT NULL,
 detail JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION calc.guard_contract_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'contract versions and generated files are immutable'; END; $$;
DROP TRIGGER IF EXISTS trg_contract_template_immutable ON calc.contract_template_version;
CREATE TRIGGER trg_contract_template_immutable BEFORE UPDATE OR DELETE ON calc.contract_template_version FOR EACH ROW EXECUTE FUNCTION calc.guard_contract_immutable();
DROP TRIGGER IF EXISTS trg_contract_generation_immutable ON calc.contract_generation;
CREATE TRIGGER trg_contract_generation_immutable BEFORE UPDATE OR DELETE ON calc.contract_generation FOR EACH ROW EXECUTE FUNCTION calc.guard_contract_immutable();
DROP TRIGGER IF EXISTS trg_contract_audit_immutable ON calc.contract_audit;
CREATE TRIGGER trg_contract_audit_immutable BEFORE UPDATE OR DELETE ON calc.contract_audit FOR EACH ROW EXECUTE FUNCTION calc.guard_contract_immutable();
COMMIT;
