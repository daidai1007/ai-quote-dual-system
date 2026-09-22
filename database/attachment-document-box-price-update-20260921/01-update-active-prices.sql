BEGIN;

CREATE TEMP TABLE attachment_quick_price_update(
  item_name text PRIMARY KEY,
  new_price numeric NOT NULL CHECK(new_price>=0)
) ON COMMIT DROP;

INSERT INTO attachment_quick_price_update VALUES
  ('A3资料盒',30),
  ('A4资料盒',20);

DO $$
DECLARE matched integer;
BEGIN
  SELECT count(*) INTO matched
  FROM calc.attachment_price p JOIN attachment_quick_price_update u USING(item_name)
  WHERE p.data_version=(SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE')
    AND p.is_active;
  IF matched<>2 THEN RAISE EXCEPTION '活动附件目录应精确匹配2行，实际匹配%行',matched; END IF;
END $$;

UPDATE calc.attachment_price p
SET quick_face_price=u.new_price,price=round(u.new_price,2),price_text=u.new_price::text
FROM attachment_quick_price_update u
WHERE p.item_name=u.item_name
  AND p.data_version=(SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE')
  AND p.is_active;

SELECT p.data_version,p.item_name,p.quick_face_price,p.price
FROM calc.attachment_price p JOIN attachment_quick_price_update u USING(item_name)
WHERE p.data_version=(SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE')
  AND p.is_active ORDER BY p.item_name;

COMMIT;
