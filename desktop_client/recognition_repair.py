"""Runtime repairs for the recovered V3 drawing-recognition pipeline."""

from __future__ import annotations

import re
import math

from recognition_dimensions import reconcile_recognition_dimensions
from native_dimension_lines import attach_dimension_line_suggestions, inspect_single_page_pdf


_NUMBER = re.compile(r"^\d{2,4}(?:\.\d+)?$")


def _numeric_tokens(engine: dict) -> list[tuple[float, float, float, float, str]]:
    values = []
    for token in engine.get("tokens") or []:
        if not isinstance(token, dict):
            continue
        text = str(token.get("text") or "").strip()
        if not _NUMBER.fullmatch(text):
            continue
        value = float(text)
        try:
            confidence = float(token.get("confidence") or 0)
            x = float(token.get("center_x") or 0)
            y = float(token.get("center_y") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(number) for number in (value, confidence, x, y)):
            continue
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
    if len(set(width_values)) == 1:
        partial["W"] = width_values[0]
    if len(set(depth_values)) == 1:
        partial["D"] = depth_values[0]
    return partial


def _decorative_dimensions(text: str) -> set[float]:
    values = set()
    for match in re.finditer(r"字[宽高]\s*[:：]?\s*(\d{2,4}(?:\.\d+)?)", text or ""):
        values.add(float(match.group(1)))
    return values


def repair_recognition_result(item: dict, parser=None, *, native_text="", native_dimension_lines=None) -> dict:
    if not isinstance(item, dict) or item.get("error"):
        return item

    targets = [item, *(item.get("cabinet_candidates") or [])]
    cabinet_count = sum(isinstance(target, dict) for target in targets[1:])
    for target in targets:
        if not isinstance(target, dict):
            continue
        # Document-wide geometry cannot be attributed to several cabinets.
        geometry_partial = _landscape_partial_dimensions(target) if cabinet_count <= 1 else {}
        if target is not item and cabinet_count == 1 and not geometry_partial:
            geometry_partial = _landscape_partial_dimensions(item)
        raw_partial = target.get("partial_specification_dimensions") or {}
        partial = dict(raw_partial) if isinstance(raw_partial, dict) else {}
        raw_text = str(target.get("raw_text") or target.get("text") or "")
        decorative = _decorative_dimensions(raw_text)
        for key, value in list(partial.items()):
            try:
                if float(value) in decorative:
                    partial.pop(key)
            except (TypeError, ValueError):
                partial.pop(key)
        for key, value in geometry_partial.items():
            if key not in partial:
                partial[key] = value
        target["partial_specification_dimensions"] = partial
        if geometry_partial and not target.get("specification"):
            target["dimension_source"] = "rapidocr_token_geometry_partial"
        if partial and "H" not in partial and not target.get("specification"):
            warning = "已识别图纸宽度/深度；高度未形成可靠证据，请对照原图补充。"
            warnings = list(target.get("specification_warnings") or [])
            if warning not in warnings:
                warnings.append(warning)
            target["specification_warnings"] = warnings
            target["warnings"] = warnings
        region = target.get("source_region") or {}
        located = isinstance(region, dict) and any(region.get(key) is not None for key in ("x", "y", "left", "top", "bbox"))
        scoped_native = native_text if cabinet_count <= 1 and not located else ""
        reconcile_recognition_dimensions(target, parser, native_text=scoped_native)
        if cabinet_count <= 1 and not located and native_dimension_lines is not None:
            attach_dimension_line_suggestions(target, native_dimension_lines)
    return item


def _single_page_native_text(path: str) -> str:
    """Native text only, bounded to one physical PDF page. No OCR or network."""
    return inspect_single_page_pdf(path)["text"]


def install_recognition_repair(namespace: dict) -> None:
    tools = namespace["DrawingRecognitionTools"]
    if getattr(tools, "_recognition_repair_installed", False):
        return

    original_recognize_document = tools.recognize_document
    parser = namespace.get("parse_review_specification")

    def recognize_document_with_repair(cls, path: str) -> dict:
        result = original_recognize_document(path)
        native = inspect_single_page_pdf(path)
        return repair_recognition_result(result, parser, native_text=native["text"],
                                         native_dimension_lines=native["dimension_lines"])

    tools.recognize_document = classmethod(recognize_document_with_repair)
    tools._recognition_repair_installed = True
