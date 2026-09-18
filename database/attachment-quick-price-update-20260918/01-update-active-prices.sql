BEGIN;

CREATE TEMP TABLE attachment_quick_price_update(
  item_name text PRIMARY KEY,
  new_price numeric NOT NULL CHECK(new_price >= 0)
) ON COMMIT DROP;

INSERT INTO attachment_quick_price_update(item_name,new_price) VALUES
  ('风机KA1238HA2/B(卡固)',51),
  ('风机KA1238DC/24V(卡固)',55),
  ('风机KA1725HA2/B(卡固)',90),
  ('风机KA1725DC/24V(卡固)',135),
  ('风机KA2072HA2/B(卡固)',350),
  ('风机KA1238HA2/B(国产)',37),
  ('风机KA1725HA2/B(国产)',70),
  ('风机KA1725DC/24V(国产)',120),
  ('风机KA2072HA2/B(国产)',250),
  ('过滤网FU-9803A(卡固)',25),
  ('过滤网FU-9804A(卡固)',30),
  ('过滤网FU-9805A(卡固)',50),
  ('过滤网FU-9806A(卡固)',80),
  ('过滤网FU-9803A(国产)',15),
  ('过滤网FU-9804A(国产)',20),
  ('过滤网FU-9805A(国产)',30),
  ('过滤网FU-9806A(国产)',40);

DO $$
DECLARE matched integer;
BEGIN
  IF (SELECT count(*) FROM attachment_quick_price_update) <> 17 THEN
    RAISE EXCEPTION '价格表必须恰好包含17行';
  END IF;
  SELECT count(*) INTO matched
  FROM calc.attachment_price p
  JOIN attachment_quick_price_update u USING(item_name)
  WHERE p.data_version=(
    SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE'
  ) AND p.is_active;
  IF matched <> 17 THEN
    RAISE EXCEPTION '活动附件目录应精确匹配17行，实际匹配% 行',matched;
  END IF;
END $$;

SELECT p.data_version,p.item_name,p.quick_face_price AS old_price,u.new_price
FROM calc.attachment_price p
JOIN attachment_quick_price_update u USING(item_name)
WHERE p.data_version=(
  SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE'
) AND p.is_active
ORDER BY p.item_name
FOR UPDATE OF p;

UPDATE calc.attachment_price p
SET quick_face_price=u.new_price,
    price=round(u.new_price,2),
    price_text=u.new_price::text
FROM attachment_quick_price_update u
WHERE p.item_name=u.item_name
  AND p.data_version=(
    SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE'
  )
  AND p.is_active
RETURNING p.data_version,p.item_name,p.quick_face_price AS new_price;

DO $$
BEGIN
  IF EXISTS(
    SELECT 1
    FROM attachment_quick_price_update u
    LEFT JOIN calc.attachment_price p
      ON p.item_name=u.item_name
     AND p.data_version=(
       SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE'
     )
     AND p.is_active
    WHERE p.attachment_price_id IS NULL
       OR p.quick_face_price IS DISTINCT FROM u.new_price
       OR p.price IS DISTINCT FROM round(u.new_price,2)
  ) THEN
    RAISE EXCEPTION '附件快速价格更新验证失败';
  END IF;
END $$;

COMMIT;
