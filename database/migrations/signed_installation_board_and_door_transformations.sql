-- Signed installation-board pricing and the manually selected door-change catalogue.
-- Run manually against the target database after taking a branch/backup.
-- This migration never derives an automatic surcharge from door counts.
BEGIN;

ALTER TABLE calc.attachment_selection
  ADD COLUMN IF NOT EXISTS price_sign SMALLINT NOT NULL DEFAULT 1
  CHECK (price_sign IN (-1, 1));

CREATE OR REPLACE VIEW calc.v_attachment_selection_cost AS
SELECT
  s.attachment_selection_id,
  s.quote_id,
  s.product_code,
  s.model_code,
  s.attachment_price_id,
  s.item_name,
  s.variant,
  s.price_source,
  s.quantity,
  s.unit_price,
  s.price_text,
  s.cost_method,
  COALESCE(s.unit_price, p.price) AS effective_unit_price,
  CASE
    WHEN COALESCE(s.unit_price, p.price) IS NULL THEN NULL
    ELSE ROUND(s.quantity * COALESCE(s.unit_price, p.price) * s.price_sign, 2)
  END AS line_cost,
  s.notes,
  s.created_at,
  s.updated_at,
  s.price_sign
FROM calc.attachment_selection s
LEFT JOIN calc.attachment_price p
  ON p.attachment_price_id = s.attachment_price_id;

-- Keep the original positive price snapshot and store subtraction separately.
-- The existing 12-argument function remains available to old clients; the new
-- API calls this 13-argument overload explicitly with a SMALLINT final value.
CREATE OR REPLACE FUNCTION calc.add_attachment_selection(
  p_quote_id VARCHAR,
  p_product_code VARCHAR DEFAULT NULL,
  p_model_code VARCHAR DEFAULT NULL,
  p_item_name VARCHAR DEFAULT NULL,
  p_quantity NUMERIC DEFAULT 1,
  p_width_mm INTEGER DEFAULT NULL,
  p_height_mm INTEGER DEFAULT NULL,
  p_depth_mm INTEGER DEFAULT NULL,
  p_variant VARCHAR DEFAULT NULL,
  p_price_source VARCHAR DEFAULT NULL,
  p_unit_price_override NUMERIC DEFAULT NULL,
  p_notes TEXT DEFAULT NULL,
  p_price_sign SMALLINT DEFAULT 1
)
RETURNS BIGINT
LANGUAGE plpgsql
VOLATILE
AS $function$
DECLARE
  v_price calc.attachment_price%ROWTYPE;
  v_selection_id BIGINT;
  v_attachment_text TEXT;
BEGIN
  IF p_quote_id IS NULL OR btrim(p_quote_id) = '' THEN
    RAISE EXCEPTION 'quote_id is required';
  END IF;
  IF p_model_code IS NULL AND p_item_name IS NULL THEN
    RAISE EXCEPTION 'model_code or item_name is required';
  END IF;
  IF p_quantity IS NULL OR p_quantity < 0 THEN
    RAISE EXCEPTION 'quantity must be non-negative';
  END IF;
  IF p_price_sign NOT IN (-1, 1) THEN
    RAISE EXCEPTION 'price_sign must be 1 or -1';
  END IF;

  v_attachment_text := COALESCE(p_item_name, '') || ' ' || COALESCE(p_model_code, '');
  IF p_price_sign = -1
     AND (position('安装板' IN v_attachment_text) = 0 OR position('安装板单发' IN v_attachment_text) > 0) THEN
    RAISE EXCEPTION 'negative price_sign is allowed only for an installation board';
  END IF;

  SELECT ap.*
  INTO v_price
  FROM calc.attachment_price ap
  WHERE ap.is_active = TRUE
    AND (p_model_code IS NULL OR ap.model_code = p_model_code OR ap.model_code IS NULL OR ap.model_code = '所有型号')
    AND (p_item_name IS NULL OR ap.item_name = p_item_name)
    AND (p_width_mm IS NULL OR ap.width_mm = p_width_mm)
    AND (p_height_mm IS NULL OR ap.height_mm = p_height_mm)
    AND (p_depth_mm IS NULL OR ap.depth_mm = p_depth_mm)
    AND (p_variant IS NULL OR ap.variant = p_variant OR ap.variant IS NULL)
    AND (p_price_source IS NULL OR ap.price_source = p_price_source)
  ORDER BY
    CASE WHEN ap.model_code = p_model_code THEN 0 ELSE 1 END,
    CASE WHEN ap.item_name = p_item_name THEN 0 ELSE 1 END,
    ap.attachment_price_id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'attachment price not found: model=%, item=%, variant=%, source=%',
      p_model_code, p_item_name, p_variant, p_price_source;
  END IF;

  INSERT INTO calc.attachment_selection (
    quote_id, product_code, model_code, attachment_price_id,
    item_name, variant, price_source, quantity, unit_price,
    price_text, cost_method, notes, price_sign
  )
  VALUES (
    p_quote_id, p_product_code, v_price.model_code, v_price.attachment_price_id,
    v_price.item_name, v_price.variant, v_price.price_source, p_quantity,
    COALESCE(p_unit_price_override, v_price.price), v_price.price_text,
    'experience', p_notes, p_price_sign
  )
  RETURNING attachment_selection_id INTO v_selection_id;

  RETURN v_selection_id;
END;
$function$;

-- Move the former one-off item into 门变形 without changing its original
-- model, price or source fields.  If an earlier draft of this migration was
-- applied, reactivate only the newest record.  All other 配置变形 rows keep
-- their existing classification, active status and price records unchanged.
WITH legacy_item AS (
  SELECT attachment_price_id
  FROM calc.attachment_price
  WHERE item_name = 'JS、JP单开门改为上下门'
  ORDER BY is_active DESC, attachment_price_id DESC
  LIMIT 1
)
UPDATE calc.attachment_price price
SET is_active = TRUE,
    attachment_category = '门变形'
FROM legacy_item
WHERE price.attachment_price_id = legacy_item.attachment_price_id;

WITH wanted(source_row_no, item_name, price) AS (
  VALUES
    (1, 'JS、JP后背板改为单开门'::VARCHAR, 150::NUMERIC),
    (2, 'JS、JP后背板改为双开门'::VARCHAR, 270::NUMERIC),
    (3, 'JS、JP单开门改为双开门'::VARCHAR, 150::NUMERIC),
    (4, 'JA、JE单开门改为双开门'::VARCHAR, 60::NUMERIC)
)
INSERT INTO calc.attachment_price (
  attachment_category, item_name, model_code, variant, width_mm, height_mm, depth_mm,
  price, price_text, unit, price_source, notes,
  source_file, source_sheet, source_row_no, is_active
)
SELECT
  '门变形', wanted.item_name, '所有型号', NULL, NULL, NULL, NULL,
  wanted.price, wanted.price::TEXT, '元', '门变形',
  '人工选择的门变形附件；不根据门数量自动增加附加值',
  'signed_installation_board_and_door_transformations.sql', '门变形',
  wanted.source_row_no, TRUE
FROM wanted
WHERE NOT EXISTS (
  SELECT 1
  FROM calc.attachment_price existing
  WHERE existing.is_active = TRUE
    AND existing.item_name = wanted.item_name
    AND existing.model_code = '所有型号'
    AND existing.price = wanted.price
    AND existing.price_source = '门变形'
);

-- “门变形” is a new, closed first-level catalogue.  Four rows use the new
-- source and the migrated legacy row keeps its original source and price.
-- Keep exactly one active row for each approved item.
UPDATE calc.attachment_price
SET is_active = FALSE
WHERE is_active = TRUE
  AND price_source = '门变形'
  AND item_name NOT IN (
    'JS、JP后背板改为单开门',
    'JS、JP后背板改为双开门',
    'JS、JP单开门改为双开门',
    'JA、JE单开门改为双开门'
  );

WITH ranked_legacy AS (
  SELECT
    attachment_price_id,
    row_number() OVER (
      ORDER BY is_active DESC, attachment_price_id DESC
    ) AS duplicate_rank
  FROM calc.attachment_price
  WHERE item_name = 'JS、JP单开门改为上下门'
)
UPDATE calc.attachment_price price
SET is_active = FALSE
FROM ranked_legacy
WHERE price.attachment_price_id = ranked_legacy.attachment_price_id
  AND ranked_legacy.duplicate_rank > 1;

WITH ranked AS (
  SELECT
    attachment_price_id,
    row_number() OVER (
      PARTITION BY item_name
      ORDER BY attachment_price_id DESC
    ) AS duplicate_rank
  FROM calc.attachment_price
  WHERE is_active = TRUE
    AND price_source = '门变形'
    AND item_name IN (
      'JS、JP后背板改为单开门',
      'JS、JP后背板改为双开门',
      'JS、JP单开门改为双开门',
      'JA、JE单开门改为双开门'
    )
)
UPDATE calc.attachment_price price
SET is_active = FALSE
FROM ranked
WHERE price.attachment_price_id = ranked.attachment_price_id
  AND ranked.duplicate_rank > 1;

UPDATE calc.attachment_classification classification
SET category_level1 = '门变形',
    category_level2 = price.item_name,
    category_level3 = ''
FROM calc.attachment_price price
WHERE classification.attachment_price_id = price.attachment_price_id
  AND price.is_active = TRUE
  AND (
    price.item_name = 'JS、JP单开门改为上下门'
    OR (
      price.price_source = '门变形'
      AND price.item_name IN (
        'JS、JP后背板改为单开门',
        'JS、JP后背板改为双开门',
        'JS、JP单开门改为双开门',
        'JA、JE单开门改为双开门'
      )
    )
  );

INSERT INTO calc.attachment_classification (
  attachment_price_id, category_level1, category_level2, category_level3
)
SELECT price.attachment_price_id, '门变形', price.item_name, ''
FROM calc.attachment_price price
WHERE price.is_active = TRUE
  AND (
    price.item_name = 'JS、JP单开门改为上下门'
    OR (
      price.price_source = '门变形'
      AND price.item_name IN (
        'JS、JP后背板改为单开门',
        'JS、JP后背板改为双开门',
        'JS、JP单开门改为双开门',
        'JA、JE单开门改为双开门'
      )
    )
  )
  AND NOT EXISTS (
    SELECT 1
    FROM calc.attachment_classification existing
    WHERE existing.attachment_price_id = price.attachment_price_id
  );

COMMIT;
