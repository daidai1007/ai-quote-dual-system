-- Run after 02-import.sql. Every statement is read-only.
SELECT count(*) AS catalog_rows,
       count(*) FILTER(WHERE match_mode='PREFIX') AS prefix_rules,
       count(*) FILTER(WHERE match_mode='EXACT') AS exact_rules,
       count(*) FILTER(WHERE source_document_sha256='2eeaf27a213cc98b32c5629f5d94bb036479b05bf86b3030b4052c69925cf861') AS reviewed_source_rows
FROM calc.attachment_image_catalog;

SELECT count(*) AS image_rows,
       count(DISTINCT item_name) AS names_with_images,
       coalesce(sum(octet_length(image_data)),0) AS total_image_bytes,
       count(*) FILTER(WHERE mime_type NOT IN ('image/png','image/jpeg') OR octet_length(image_data)=0) AS invalid_images
FROM calc.attachment_image_asset;

SELECT c.source_row_no,c.item_name,c.match_mode,count(a.image_order) AS image_count
FROM calc.attachment_image_catalog c
LEFT JOIN calc.attachment_image_asset a USING(item_name)
WHERE c.source_document_sha256='2eeaf27a213cc98b32c5629f5d94bb036479b05bf86b3030b4052c69925cf861'
GROUP BY c.source_row_no,c.item_name,c.match_mode
ORDER BY c.source_row_no;

-- Active attachment names that do not match an image-catalog rule remain blank in the client.
SELECT DISTINCT p.item_name AS active_attachment_without_image_rule
FROM calc.attachment_price p
WHERE p.is_active
  AND NOT EXISTS (
    SELECT 1 FROM calc.attachment_image_catalog c
    WHERE (c.match_mode='EXACT' AND translate(p.item_name,'（）','()')=translate(c.item_name,'（）','()'))
       OR (c.match_mode='PREFIX' AND translate(p.item_name,'（）','()') LIKE translate(c.item_name,'（）','()') || '%')
  )
ORDER BY p.item_name;

