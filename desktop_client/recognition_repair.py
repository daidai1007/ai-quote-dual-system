"""Runtime repairs for the recovered V3 drawing-recognition pipeline."""

from __future__ import annotations

import re


_NUMBER = re.compile(r"^\d{2,4}(?:\.\d+)?$")


def _numeric_tokens(engine: dict) -> list[tuple[float, float, float, float, str]]:
    values = []
    for token in engine.get("tokens") or []:
        text = str(token.get("text") or "").strip()
        if not _NUMBER.fullmatch(text):
            continue
        value = float(text)
        confidence = float(token.get("confidence") or 0)
        x = float(token.get("center_x") or 0)
        y = float(token.get("center_y") or 0)
        orientation = str(token.get("orientation") or "")
        values.append((value, confidence, x, y, orientation))
    return values


def _landscape_partial_dimensions(item: dict) -> dict[str, float]:
    """Recover only strongly positioned overall dimensions from OCR geometry.

    This intentionally returns a partial W/D result.  It does not guess a
    missing height.  On landscape engineering sheets the main front-view width
    is printed above the central view, while the side-view depth is printed
    below the left view.  Detail and title-block numbers are outside these two
    narrow zones.
    """

    evidence = item.get("ocr_engine_evidence") or {}
    engine = next(
        (
            value
            for key, value in evidence.items()
            if "rapidocr" in str(key).lower() and isinstance(value, dict)
        ),
        {},
    )
    if engine.get("geometry_policy") != "landscape_engineering_sheet":
        return {}

    tokens = _numeric_tokens(engine)
    width_values = [
        value
        for value, confidence, x, y, orientation in tokens
        if confidence >= 0.95
        and orientation == "horizontal"
        and 100 <= value <= 3000
        and 0.35 <= x <= 0.75
        and 0.06 <= y <= 0.20
    ]
    depth_values = [
        value
        for value, confidence, x, y, orientation in tokens
        if confidence >= 0.95
        and orientation == "horizontal"
        and 50 <= value <= 2000
        and 0.10 <= x <= 0.35
        and 0.20 <= y <= 0.58
    ]

    partial = {}
    if width_values:
        partial["W"] = max(width_values)
    if depth_values:
        partial["D"] = max(depth_values)
    return partial


def _decorative_dimensions(text: str) -> set[float]:
    values = set()
    for match in re.finditer(r"字[宽高]\s*[:：]?\s*(\d{2,4}(?:\.\d+)?)", text or ""):
        values.add(float(match.group(1)))
    return values


def repair_recognition_result(item: dict) -> dict:
    if not isinstance(item, dict) or item.get("error"):
        return item

    raw_text = str(item.get("raw_text") or item.get("text") or "")
    decorative = _decorative_dimensions(raw_text)
    geometry_partial = _landscape_partial_dimensions(item)

    targets = [item, *(item.get("cabinet_candidates") or [])]
    for target in targets:
        if not isinstance(target, dict) or target.get("specification"):
            continue
        partial = dict(target.get("partial_specification_dimensions") or {})
        partial = {
            key: value
            for key, value in partial.items()
            if float(value) not in decorative
        }
        partial.update(geometry_partial)
        target["partial_specification_dimensions"] = partial
        if geometry_partial:
            target["dimension_source"] = "rapidocr_token_geometry_partial"
        if partial and "H" not in partial:
            warning = "已识别图纸宽度/深度；高度未形成可靠证据，请对照原图补充。"
            warnings = list(target.get("specification_warnings") or [])
            if warning not in warnings:
                warnings.append(warning)
            target["specification_warnings"] = warnings
            target["warnings"] = warnings
    return item


def install_recognition_repair(namespace: dict) -> None:
    tools = namespace["DrawingRecognitionTools"]
    if getattr(tools, "_recognition_repair_installed", False):
        return

    original_recognize_document = tools.recognize_document

    def recognize_document_with_repair(cls, path: str) -> dict:
        return repair_recognition_result(original_recognize_document(path))

    tools.recognize_document = classmethod(recognize_document_with_repair)
    tools._recognition_repair_installed = True
