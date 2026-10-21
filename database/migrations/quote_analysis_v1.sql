-- Additive only. Run manually after quote_scheme_center_v1.sql; never by client startup.
BEGIN;
CREATE TABLE IF NOT EXISTS calc.quote_analysis_outcome (
  outcome_id BIGSERIAL PRIMARY KEY,
  customer_code TEXT NOT NULL CHECK (btrim(customer_code) <> ''),
  opportunity_key TEXT NOT NULL CHECK (btrim(opportunity_key) <> ''),
  product_code TEXT NOT NULL CHECK (btrim(product_code) <> ''),
  scheme_id BIGINT NOT NULL,
  version_no INTEGER NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('WON','LOST','PENDING')),
  result_at TIMESTAMPTZ NOT NULL,
  discount NUMERIC(14,6),
  quote_method TEXT NOT NULL CHECK (quote_method IN ('QUICK','FORMULA','UNKNOWN')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  actor_user_id TEXT NOT NULL,
  actor_name TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(customer_code,opportunity_key,product_code),
  FOREIGN KEY(scheme_id,version_no) REFERENCES calc.quote_scheme_version(scheme_id,version_no)
);
CREATE INDEX IF NOT EXISTS idx_quote_analysis_result_time
  ON calc.quote_analysis_outcome(result_at,customer_code,product_code);
CREATE TABLE IF NOT EXISTS calc.quote_analysis_outcome_audit (
  audit_id BIGSERIAL PRIMARY KEY,
  outcome_id BIGINT NOT NULL REFERENCES calc.quote_analysis_outcome(outcome_id),
  revision INTEGER NOT NULL,
  actor_user_id TEXT NOT NULL,
  actor_name TEXT NOT NULL,
  recorded_value JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMIT;
