-- V2 quotation workflow: company profiles, confirmed multi-cabinet snapshots
-- and strict historical-order matching.  Run once after company_history_schema.sql.
BEGIN;

ALTER TABLE calc.ordering_company
  ADD COLUMN IF NOT EXISTS contact_name VARCHAR(120),
  ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(80),
  ADD COLUMN IF NOT EXISTS company_address TEXT;

-- The document stores the confirmed quote as an immutable business snapshot.
-- A later edit must be confirmed as a new quote_id/version, leaving this row
-- unchanged.  Formula and quick values are merely presented side-by-side here:
-- their calculation sources remain independent.
CREATE TABLE IF NOT EXISTS calc.quote_document (
  quote_id VARCHAR(80) PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES calc.ordering_company(company_id),
  quote_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'CONFIRMED'
    CHECK (status IN ('DRAFT', 'CONFIRMED', 'SUPERSEDED')),
  source_quote_id VARCHAR(80) REFERENCES calc.quote_document(quote_id),
  version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
  document_payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quote_document_company_date
  ON calc.quote_document(company_id, quote_date DESC, confirmed_at DESC);

-- Existing history rows remain valid.  New confirmed records include product
-- variant in the strict match key, so JS single and JS double never cross-fill.
CREATE INDEX IF NOT EXISTS idx_company_history_strict_match
  ON calc.company_quote_history (
    company_id, product_code, material_code, variant_code,
    width_mm, height_mm, depth_mm, created_at DESC
  );

COMMENT ON TABLE calc.quote_document IS
  '正式确认报价单快照；一张报价单可含多个柜型，公式法与快速报价并列存档';

COMMIT;
