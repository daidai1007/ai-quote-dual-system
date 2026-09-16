-- Additive attachment presentation schema. It does not change quote prices or calculations.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

DO $$ BEGIN
  IF to_regnamespace('calc') IS NULL OR to_regclass('calc.attachment_price') IS NULL THEN
    RAISE EXCEPTION 'Existing calc.attachment_price must be present before adding image tables';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS calc.attachment_image_catalog (
  item_name text PRIMARY KEY,
  source_row_no integer NOT NULL UNIQUE CHECK(source_row_no>0),
  match_mode text NOT NULL DEFAULT 'EXACT' CHECK(match_mode IN ('EXACT','PREFIX')),
  source_document text NOT NULL,
  source_document_sha256 text NOT NULL CHECK(source_document_sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(btrim(item_name)<>'')
);

CREATE TABLE IF NOT EXISTS calc.attachment_image_asset (
  item_name text NOT NULL REFERENCES calc.attachment_image_catalog(item_name) ON DELETE CASCADE,
  image_order smallint NOT NULL CHECK(image_order>0),
  mime_type text NOT NULL CHECK(mime_type IN ('image/png','image/jpeg')),
  image_sha256 text NOT NULL CHECK(image_sha256 ~ '^[a-f0-9]{64}$'),
  image_data bytea NOT NULL CHECK(octet_length(image_data)>0 AND octet_length(image_data)<=10485760),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(item_name,image_order)
);

COMMENT ON TABLE calc.attachment_image_catalog IS
  '附件展示图片的名称匹配目录；不参与任何报价、数量或公式计算。';
COMMENT ON TABLE calc.attachment_image_asset IS
  '附件展示图片二进制数据；缺图附件只保留catalog行，不插入asset行。';

COMMIT;

