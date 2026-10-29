-- Prepared for manual deployment only. Never contains customer data.
-- Reuse the existing customer table and freeze actual contract values as before.
BEGIN;
ALTER TABLE calc.ordering_company
 ADD COLUMN IF NOT EXISTS contract_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
 ADD COLUMN IF NOT EXISTS contract_profile_version BIGINT NOT NULL DEFAULT 0;
COMMENT ON COLUMN calc.ordering_company.contract_profile IS 'Customer/buyer contract details; account and tax identifiers are JSON strings';
COMMENT ON COLUMN calc.ordering_company.contract_profile_version IS 'Optimistic lock for customer profile maintenance';
COMMIT;
