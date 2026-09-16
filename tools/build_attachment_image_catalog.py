"""Build the reviewed PostgreSQL attachment-image import from a Word table.

The source document is treated as input data.  This script never connects to a
database; it emits SQL and a compact audit manifest for manual review.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass(frozen=True)
class ImageAsset:
    order: int
    filename: str
    mime_type: str
    sha256: str
    data: bytes


@dataclass(frozen=True)
class AttachmentRow:
    source_row_no: int
    item_name: str
    match_mode: str
    images: tuple[ImageAsset, ...]


def _text(cell: ET.Element) -> str:
    parts = [node.text or "" for node in cell.findall(f".//{{{W}}}t")]
    return " ".join("".join(parts).split())


def read_rows(path: Path) -> list[AttachmentRow]:
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall(f"{{{PR}}}Relationship")
            if rel.attrib.get("TargetMode") != "External"
        }
        table = document.find(f".//{{{W}}}tbl")
        if table is None:
            raise ValueError("Word 文件中没有附件表格")
        parsed: list[AttachmentRow] = []
        for row_index, row in enumerate(table.findall(f"{{{W}}}tr")):
            cells = row.findall(f"{{{W}}}tc")
            if row_index == 0:
                continue
            if len(cells) < 2:
                raise ValueError(f"第 {row_index + 1} 行缺少附件名称列")
            source_text = _text(cells[0])
            try:
                source_row_no = int(source_text)
            except ValueError as exc:
                raise ValueError(f"第 {row_index + 1} 行序号无效：{source_text!r}") from exc
            item_name = _text(cells[1])
            if not item_name:
                raise ValueError(f"第 {row_index + 1} 行附件名称为空")
            relation_ids: list[str] = []
            for cell in cells[2:]:
                for blip in cell.findall(f".//{{{A}}}blip"):
                    relation_id = blip.attrib.get(f"{{{R}}}embed")
                    if relation_id and relation_id not in relation_ids:
                        relation_ids.append(relation_id)
            assets: list[ImageAsset] = []
            for image_order, relation_id in enumerate(relation_ids, start=1):
                target = targets.get(relation_id)
                if not target:
                    raise ValueError(f"附件 {item_name!r} 的图片关系 {relation_id} 不存在")
                member = str(PurePosixPath("word") / PurePosixPath(target))
                data = archive.read(member)
                mime_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
                assets.append(ImageAsset(
                    order=image_order,
                    filename=PurePosixPath(target).name,
                    mime_type=mime_type,
                    sha256=hashlib.sha256(data).hexdigest(),
                    data=data,
                ))
            # The document intentionally gives one shared image for all fan
            # and filter variants.  Every other row is an exact name match
            # (with punctuation normalised by the client).
            match_mode = "PREFIX" if item_name in {"风机", "过滤网"} else "EXACT"
            parsed.append(AttachmentRow(source_row_no, item_name, match_mode, tuple(assets)))
    if len(parsed) != 50:
        raise ValueError(f"预期 50 个附件名称，实际 {len(parsed)} 个")
    names = [row.item_name for row in parsed]
    if len(names) != len(set(names)):
        raise ValueError("附件名称存在重复，不能安全地按名称关联")
    return parsed


def _utf8_sql(value: str) -> str:
    return f"convert_from(decode('{value.encode('utf-8').hex()}','hex'),'UTF8')"


def build_import_sql(source: Path, rows: list[AttachmentRow]) -> str:
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    source_name = source.name
    catalog_values = ",\n".join(
        "  (" + ", ".join((
            str(row.source_row_no),
            _utf8_sql(row.item_name),
            f"'{row.match_mode}'",
            _utf8_sql(source_name),
            f"'{source_sha}'",
        )) + ")"
        for row in rows
    )
    asset_values = ",\n".join(
        "  (" + ", ".join((
            _utf8_sql(row.item_name),
            str(asset.order),
            _utf8_sql(asset.mime_type),
            f"'{asset.sha256}'",
            f"decode('{base64.b64encode(asset.data).decode('ascii')}','base64')",
        )) + ")"
        for row in rows
        for asset in row.images
    )
    return f"""-- Generated from {source_name}; do not edit image bytes by hand.
-- Source SHA-256: {source_sha}
-- Adds attachment presentation data only.  No price or quote tables are changed.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

DO $$ BEGIN
  IF to_regclass('calc.attachment_image_catalog') IS NULL
     OR to_regclass('calc.attachment_image_asset') IS NULL THEN
    RAISE EXCEPTION 'Run 01-create.sql before importing attachment images';
  END IF;
END $$;

CREATE TEMP TABLE attachment_image_catalog_stage(
  source_row_no integer PRIMARY KEY,
  item_name text UNIQUE NOT NULL,
  match_mode text NOT NULL,
  source_document text NOT NULL,
  source_document_sha256 text NOT NULL
) ON COMMIT DROP;

INSERT INTO attachment_image_catalog_stage(
  source_row_no,item_name,match_mode,source_document,source_document_sha256
) VALUES
{catalog_values};

-- This Word document is authoritative for its 50 listed names.  Removing the
-- previous copy first also permits future row reordering or corrected names.
DELETE FROM calc.attachment_image_catalog c
WHERE c.source_document={_utf8_sql(source_name)}
   OR EXISTS(SELECT 1 FROM attachment_image_catalog_stage s WHERE s.item_name=c.item_name);

INSERT INTO calc.attachment_image_catalog(
  source_row_no,item_name,match_mode,source_document,source_document_sha256,updated_at
)
SELECT source_row_no,item_name,match_mode,source_document,source_document_sha256,now()
FROM attachment_image_catalog_stage;

INSERT INTO calc.attachment_image_asset(
  item_name,image_order,mime_type,image_sha256,image_data
) VALUES
{asset_values};

DO $$ DECLARE catalog_count integer; asset_count integer; BEGIN
  SELECT count(*) INTO catalog_count FROM calc.attachment_image_catalog
  WHERE source_document_sha256='{source_sha}';
  SELECT count(*) INTO asset_count FROM calc.attachment_image_asset a
  JOIN calc.attachment_image_catalog c USING(item_name)
  WHERE c.source_document_sha256='{source_sha}';
  IF catalog_count<>50 OR asset_count<>28 THEN
    RAISE EXCEPTION 'Attachment image import count mismatch: catalog %, assets %',catalog_count,asset_count;
  END IF;
END $$;

COMMIT;
"""


def write_outputs(source: Path, output_root: Path) -> None:
    rows = read_rows(source)
    output_root.mkdir(parents=True, exist_ok=True)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "source_document": source.name,
        "source_document_sha256": source_sha,
        "catalog_count": len(rows),
        "image_count": sum(len(row.images) for row in rows),
        "missing_image_count": sum(not row.images for row in rows),
        "items": [
            {
                "source_row_no": row.source_row_no,
                "item_name": row.item_name,
                "match_mode": row.match_mode,
                "images": [
                    {
                        "image_order": asset.order,
                        "filename": asset.filename,
                        "mime_type": asset.mime_type,
                        "sha256": asset.sha256,
                        "size_bytes": len(asset.data),
                    }
                    for asset in row.images
                ],
            }
            for row in rows
        ],
    }
    (output_root / "attachment-image-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root.parent / "web" / "02-import.sql").parent.mkdir(parents=True, exist_ok=True)
    (output_root.parent / "web" / "02-import.sql").write_text(
        build_import_sql(source, rows), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    write_outputs(args.source.resolve(), args.output_root.resolve())


if __name__ == "__main__":
    main()
