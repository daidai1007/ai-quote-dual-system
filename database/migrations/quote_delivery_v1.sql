-- Manual additive migration. Run after quote_scheme_center_v1 and quote_name_scope_v1.
-- No startup migration, existing quote/owner/contract data is not rewritten.
BEGIN;
CREATE TABLE IF NOT EXISTS calc.quote_delivery_batch (
  batch_id uuid PRIMARY KEY,
  sender_user_id text NOT NULL,
  sender_name text NOT NULL,
  scheme_id bigint NOT NULL,
  source_version_no integer NOT NULL,
  quote_version integer NOT NULL CHECK (quote_version > 0),
  note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 200),
  request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[a-f0-9]{64}$'),
  document_sha256 text NOT NULL CHECK (document_sha256 ~ '^[a-f0-9]{64}$'),
  document_payload jsonb NOT NULL CHECK (document_payload->>'schema' = '1'),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (scheme_id, source_version_no)
    REFERENCES calc.quote_scheme_version(scheme_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_quote_delivery_sender ON calc.quote_delivery_batch(sender_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quote_delivery_source ON calc.quote_delivery_batch(scheme_id, created_at DESC);
CREATE TABLE IF NOT EXISTS calc.quote_delivery_recipient (
  delivery_id uuid PRIMARY KEY,
  batch_id uuid NOT NULL REFERENCES calc.quote_delivery_batch(batch_id),
  recipient_user_id text NOT NULL,
  recipient_name text NOT NULL,
  read_at timestamptz,
  UNIQUE(batch_id, recipient_user_id)
);
CREATE INDEX IF NOT EXISTS idx_quote_delivery_inbox ON calc.quote_delivery_recipient(recipient_user_id, batch_id);
CREATE TABLE IF NOT EXISTS calc.quote_delivery_output (
  output_id uuid PRIMARY KEY,
  delivery_id uuid NOT NULL REFERENCES calc.quote_delivery_recipient(delivery_id),
  actor_user_id text NOT NULL,
  output_kind text NOT NULL CHECK (output_kind IN ('PRINT', 'XLSX')),
  document_sha256 text NOT NULL CHECK (document_sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION calc.quote_delivery_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'sent quote document is immutable';
END;
$$;
DROP TRIGGER IF EXISTS trg_quote_delivery_batch_immutable ON calc.quote_delivery_batch;
CREATE TRIGGER trg_quote_delivery_batch_immutable BEFORE UPDATE OR DELETE ON calc.quote_delivery_batch
  FOR EACH ROW EXECUTE FUNCTION calc.quote_delivery_immutable();
DROP TRIGGER IF EXISTS trg_quote_delivery_output_immutable ON calc.quote_delivery_output;
CREATE TRIGGER trg_quote_delivery_output_immutable BEFORE UPDATE OR DELETE ON calc.quote_delivery_output
  FOR EACH ROW EXECUTE FUNCTION calc.quote_delivery_immutable();
CREATE OR REPLACE FUNCTION calc.quote_delivery_recipient_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'sent quote recipient is immutable'; END IF;
  IF (to_jsonb(NEW) - 'read_at') IS DISTINCT FROM (to_jsonb(OLD) - 'read_at')
     OR (OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at) THEN
    RAISE EXCEPTION 'sent quote recipient is immutable';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_quote_delivery_recipient_guard ON calc.quote_delivery_recipient;
CREATE TRIGGER trg_quote_delivery_recipient_guard BEFORE UPDATE OR DELETE ON calc.quote_delivery_recipient
  FOR EACH ROW EXECUTE FUNCTION calc.quote_delivery_recipient_guard();
COMMIT;
