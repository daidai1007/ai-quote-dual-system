BEGIN;
-- No historical ownership is inferred or assigned by this migration.
CREATE TABLE IF NOT EXISTS calc.quote_name_owner (
 resource_kind text NOT NULL CHECK(resource_kind IN ('SCHEME','QUOTE_LINE','QUOTE_ID','QUOTE_DOCUMENT','COMPANY_HISTORY','HISTORY_PRICE')),
 resource_key text NOT NULL,
 owner_user_id text NOT NULL CHECK(owner_user_id ~ '^name-user:[0-9a-f]{64}$'),
 confirmed_by_name text NOT NULL,
 mapping_source text NOT NULL CHECK(mapping_source IN ('SESSION_CREATED','USER_CONFIRMED_LEGACY')),
 mapping_basis text NOT NULL DEFAULT 'NAME_ONLY session creation',
 confirmed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(resource_kind,resource_key)
);
CREATE INDEX IF NOT EXISTS quote_name_owner_person_idx ON calc.quote_name_owner(owner_user_id,resource_kind,resource_key);
CREATE TABLE IF NOT EXISTS calc.quote_name_workspace (
 owner_user_id text NOT NULL CHECK(owner_user_id ~ '^name-user:[0-9a-f]{64}$'),
 order_number text NOT NULL CHECK(length(order_number) BETWEEN 1 AND 100),
 workspace_payload jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_user_id,order_number)
);
COMMIT;
