-- Additive Excel-ledger contract records. Existing quote-origin tables and
-- their EXTERNAL/version/ownership requirements are deliberately unchanged.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF to_regclass('calc.contract_template_version') IS NULL
    OR to_regprocedure('calc.guard_contract_immutable()') IS NULL THEN
   RAISE EXCEPTION 'Apply contract_templates_v1 before contract_ledger_v1';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS calc.ledger_contract_draft (
 draft_id uuid PRIMARY KEY, owner_user_id text NOT NULL, owner_name text NOT NULL,
 customer_name text NOT NULL, input_payload jsonb NOT NULL,
 lock_version integer NOT NULL DEFAULT 1 CHECK(lock_version>0),updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS calc.ledger_contract_generation (
 record_id uuid PRIMARY KEY,record_no text NOT NULL UNIQUE,
 request_id uuid NOT NULL,document_key text NOT NULL,input_sha256 text NOT NULL,
 owner_user_id text NOT NULL,owner_name text NOT NULL,
 customer_code text NOT NULL,customer_name text NOT NULL,customer_contract_no text NOT NULL,
 template_version_id bigint NOT NULL REFERENCES calc.contract_template_version,
 generation_snapshot jsonb NOT NULL CHECK(generation_snapshot->>'source_kind'='LEDGER'),
 file_format text NOT NULL CHECK(file_format IN ('docx','xlsx')),
 file_content bytea NOT NULL CHECK(octet_length(file_content)<=16777216),file_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(owner_user_id,request_id,document_key)
);
CREATE INDEX IF NOT EXISTS idx_ledger_contract_owner ON calc.ledger_contract_generation(owner_user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_contract_draft_owner ON calc.ledger_contract_draft(owner_user_id,updated_at DESC);
DROP TRIGGER IF EXISTS trg_ledger_contract_immutable ON calc.ledger_contract_generation;
CREATE TRIGGER trg_ledger_contract_immutable BEFORE UPDATE OR DELETE ON calc.ledger_contract_generation
 FOR EACH ROW EXECUTE FUNCTION calc.guard_contract_immutable();
COMMIT;
