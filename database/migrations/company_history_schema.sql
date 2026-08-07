-- Company-scoped historical orders for optional auto-fill suggestions.
-- This data is independent from both formula and quick-price calculations.
CREATE TABLE IF NOT EXISTS calc.ordering_company (
  company_id BIGSERIAL PRIMARY KEY,
  company_code VARCHAR(80) NOT NULL UNIQUE,
  company_name VARCHAR(200) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS calc.company_quote_history (
  history_id BIGSERIAL PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES calc.ordering_company(company_id),
  quote_id VARCHAR(80),
  product_code VARCHAR(60) NOT NULL,
  model_code VARCHAR(160),
  material_code VARCHAR(30) NOT NULL,
  coating_type VARCHAR(80),
  variant_code VARCHAR(30),
  width_mm NUMERIC(12,3) NOT NULL,
  height_mm NUMERIC(12,3) NOT NULL,
  depth_mm NUMERIC(12,3) NOT NULL,
  request_payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_history_match
  ON calc.company_quote_history (
    company_id, product_code, material_code,
    width_mm, height_mm, depth_mm, created_at DESC
  );

COMMENT ON TABLE calc.ordering_company IS '报价下单公司主数据';
COMMENT ON TABLE calc.company_quote_history IS '按下单公司保存的已确认历史订单输入';
