"""Conservative cabinet dimension evidence, independent of Qt and OCR engines.

The recovered core prices with (W, body-H, D), but displays W*D*H.  Parsing a
specification is never evidence of manual review.  Only format/axis fields are
copied from the core parser; its manual provenance and confidence are ignored.
"""
from __future__ import annotations

import math
import re


_NUMBER = r"\d+(?:\.\d+)?"
_VALUE_END = (r"(?!(?:,\d|\s*[+\-–—~～至/×xX*]|"
              r"\s+(?!(?:[WDHB]\s*[:：=]?\s*\d))[A-Za-z]|\s+(?:毫米|厘米|米|公分|公尺|英寸)))"
              r"(?=$|[\s,，;；:：()（）\]】]|(?:[WDHB]|宽度?|深度?|高度?|底座高?)\s*[:：=]?\s*\d)")
_TERM = rf"(?:{_NUMBER}|\(\s*{_NUMBER}(?:\s*\+\s*{_NUMBER})+\s*\))"
_SPEC = re.compile(rf"^({_TERM})\s*\*\s*({_NUMBER})\s*\*\s*({_TERM})$")
_AXIS = re.compile(
    rf"(?<![A-Za-z\u3400-\u9fff])"
    rf"(?P<label>柜体总高|箱体总高|柜体宽度|柜体深度|柜体高度|柜体宽|柜体深|柜体高|"
    rf"本体高度|本体高|总高度|总高|柜宽|柜深|柜高|总宽|总深|"
    rf"宽度|深度|高度|底座高度|底座高|底座|宽|深|高|W|D|H|B)"
    rf"\s*[:：=]?\s*(?P<value>{_NUMBER})\s*(?P<unit>mm|cm|毫米|厘米|米|m)?"
    rf"{_VALUE_END}", re.IGNORECASE,
)
_ORDER = re.compile(
    rf"(?<![A-Za-z0-9_\u3400-\u9fff])(?P<a>W|D|H|宽|深|高)\s*[*×x]\s*(?P<b>W|D|H|宽|深|高)"
    rf"\s*[*×x]\s*(?P<c>W|D|H|宽|深|高)\s*[)）\]】]?\s*[:：=]?\s*"
    rf"(?P<x>{_NUMBER})\s*[*×x]\s*(?P<y>{_NUMBER})\s*[*×x]\s*(?P<z>{_NUMBER})"
    rf"\s*(?P<unit>mm|cm|毫米|厘米|米|m)?{_VALUE_END}", re.IGNORECASE,
)
_DETAIL = re.compile(r"安装板|门板|开孔|孔距|孔径|螺纹|字宽|字高|字符|字体|零件|局部|净空")
_AXES = {"宽": "W", "深": "D", "高": "H"}
_COPY_FIELDS = ("specification", "dimensions", "height_kind", "height_terms_mm")


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and 0 < value <= 100000 else None


def _triple(values):
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return None
    result = tuple(_positive(value) for value in values)
    return result if all(value is not None for value in result) else None


def _parts(text):
    return [float(value) for value in text.strip().strip("()").split("+")]


def parse_dimension_specification(value, parser=None):
    """Return format/axis data only. Height used for pricing excludes base B."""
    text = str(value or "").strip()
    if not text:
        return None
    if parser is not None:
        try:
            parsed = parser(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if not isinstance(parsed, dict):
            return None
        dimensions = parsed.get("dimensions") or []
        whd = _triple(dimensions[0]) if dimensions else None
        if whd is None:
            return None
        result = {key: parsed[key] for key in _COPY_FIELDS if key in parsed}
        result["dimensions"] = [whd]
        return result
    text = re.sub(r"[×xX]", "*", text).replace("（", "(").replace("）", ")")
    match = _SPEC.fullmatch(text)
    if match is None:
        return None
    width_parts, depth, heights = _parts(match[1]), float(match[2]), _parts(match[3])
    # H+B has exactly two terms. More terms have no established height meaning.
    if len(heights) > 2 or not all(_positive(v) for v in (*width_parts, depth, *heights)):
        return None
    width, body = sum(width_parts), heights[0]
    if _triple((width, body, depth)) is None or _positive(sum(heights)) is None:
        return None
    width_text = f"{width:g}" if len(width_parts) == 1 else "(" + "+".join(f"{v:g}" for v in width_parts) + ")"
    height_text = f"{body:g}" if len(heights) == 1 else f"({body:g}+{heights[1]:g})"
    return {"specification": f"{width_text}*{depth:g}*{height_text}",
            "dimensions": [(width, body, depth)], "height_kind": "base" if len(heights) == 2 else "single",
            "height_terms_mm": heights if len(heights) == 2 else []}


def _axis_name(label):
    if label.upper() in {"W", "D", "H", "B"}:
        return label.upper()
    if "底座" in label:
        return "B"
    return next((axis for word, axis in _AXES.items() if word in label), None)


def explicit_axis_evidence(text):
    """Read named axes only; no order, largest-number or missing-axis guesses."""
    values = {axis: set() for axis in ("W", "D", "H", "B")}
    height_kinds = set()
    for line in str(text or "")[:200000].splitlines():
        if _DETAIL.search(line):
            continue
        # In 'W*D*H: 800*600*1800', H:800 is a header followed by W,
        # not a second height observation.
        axis_line = _ORDER.sub(" ", line)
        for match in _AXIS.finditer(axis_line):
            axis = _axis_name(match["label"])
            scale = {"cm": 10, "厘米": 10, "m": 1000, "米": 1000}.get((match["unit"] or "").lower(), 1)
            value = _positive(float(match["value"]) * scale)
            if value is None or axis is None:
                continue
            values[axis].add(value)
            if axis == "H":
                height_kinds.add("total" if "总" in match["label"] else "body" if "本体" in match["label"] else "unspecified")
        for match in _ORDER.finditer(line):
            order = [_axis_name(match[key]) for key in ("a", "b", "c")]
            if set(order) != {"W", "D", "H"}:
                continue
            scale = {"cm": 10, "厘米": 10, "m": 1000, "米": 1000}.get((match["unit"] or "").lower(), 1)
            for axis, key in zip(order, ("x", "y", "z")):
                value = _positive(float(match[key]) * scale)
                if value is not None:
                    values[axis].add(value)
            height_kinds.add("unspecified")
    partial = {axis: next(iter(found)) for axis, found in values.items() if len(found) == 1}
    conflicts = [axis for axis, found in values.items() if len(found) > 1]
    if "H" in partial and "B" in partial and height_kinds == {"total"} and partial["H"] > partial["B"]:
        partial["H"] -= partial["B"]
        height_kinds = {"body"}
    specification = None
    if not conflicts and all(axis in partial for axis in ("W", "D", "H")):
        width, depth, height = (partial[axis] for axis in ("W", "D", "H"))
        if "B" not in partial:
            specification = f"{width:g}*{depth:g}*{height:g}"
        elif height_kinds == {"body"}:
            specification = f"{width:g}*{depth:g}*({height:g}+{partial['B']:g})"
        elif height_kinds == {"total"} and height > partial["B"]:
            specification = f"{width:g}*{depth:g}*({height-partial['B']:g}+{partial['B']:g})"
            partial["H"] = height - partial["B"]
        # Unqualified H plus B has no reliable body/overall interpretation.
    return {"partial": partial, "conflicting_axes": conflicts, "specification": specification,
            "height_ambiguous": "B" in partial and height_kinds != {"body"}}


def reconcile_recognition_dimensions(record, parser=None, *, native_text=""):
    """Reconcile one candidate's own evidence; never copy a parent sheet's axes."""
    if not isinstance(record, dict) or record.get("error"):
        return record
    candidates = []

    def retain(parsed, origin):
        if parsed is not None:
            row = {key: parsed[key] for key in _COPY_FIELDS if key in parsed}
            row["origin"] = origin
            if row not in candidates:
                candidates.append(row)

    original_spec = str(record.get("specification") or "").strip()
    parsed_spec = parse_dimension_specification(original_spec, parser)
    retain(parsed_spec, "recognized_specification")
    native = explicit_axis_evidence(native_text)
    parsed_native = parse_dimension_specification(native["specification"], parser)
    legacy = []
    for values in record.get("dimensions") or []:
        whd = _triple(values)
        if whd is not None and whd not in legacy:
            legacy.append(whd)
    # A base-bearing specification is richer than its legacy WHD tuple.
    for width, height, depth in legacy:
        if not any(parsed and (width, height, depth) == tuple(parsed["dimensions"][0]) for parsed in (parsed_spec, parsed_native)):
            retain(parse_dimension_specification(f"{width:g}*{depth:g}*{height:g}", parser), "legacy_whd")
    retain(parsed_native, "pdf_native_explicit_axes")
    consensus = record.get("ocr_consensus")
    consensus = consensus if isinstance(consensus, dict) else {}
    base_evidence = record.get("ocr_base_evidence")
    base_evidence = base_evidence if isinstance(base_evidence, dict) else {}
    blocked = consensus.get("status") in {"conflict", "ambiguous"} or base_evidence.get("status") == "conflict"
    if blocked:
        engines = consensus.get("engine_candidates") or {}
        for engine, rows in engines.items() if isinstance(engines, dict) else []:
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    retain(parse_dimension_specification(row.get("specification"), parser), str(engine))
    stored_partial = record.get("partial_specification_dimensions") or {}
    partial = {axis: value for axis, raw in (stored_partial.items() if isinstance(stored_partial, dict) else [])
               if axis in {"W", "D", "H", "B"} and (value := _positive(raw)) is not None}
    # OCR text may help the user find a missing axis, but cannot by itself
    # bypass the core's independent-engine/quality gate.
    own_text = explicit_axis_evidence(record.get("raw_text") or record.get("text") or "")
    partial_conflicts = set(native["conflicting_axes"])
    for evidence in (own_text, native):
        partial_conflicts.update(evidence["conflicting_axes"])
        for axis, value in evidence["partial"].items():
            if axis in partial and partial[axis] != value:
                partial_conflicts.add(axis)
            else:
                partial[axis] = value
    for axis in partial_conflicts:
        partial.pop(axis, None)
    # Compare explicit per-axis counter-evidence with selected full sizes too.
    # H may only be compared after body/overall semantics are established.
    for evidence in (own_text, native):
        for row in candidates:
            width, body, depth = row["dimensions"][0]
            expected = {"W": width, "D": depth, "H": body}
            terms = row.get("height_terms_mm") or []
            if len(terms) == 2:
                expected["B"] = terms[1]
            for axis, value in evidence["partial"].items():
                if axis == "H" and evidence["height_ambiguous"]:
                    continue
                if axis in expected and value != expected[axis]:
                    partial_conflicts.add(axis)
    for axis in partial_conflicts:
        partial.pop(axis, None)
    signatures = {(tuple(row["dimensions"][0]), tuple(row.get("height_terms_mm") or [])) for row in candidates}
    unresolved_base = (any(evidence["height_ambiguous"] for evidence in (own_text, native))
                       and not any(len(row.get("height_terms_mm") or []) == 2 for row in candidates))
    if blocked or len(signatures) > 1 or partial_conflicts:
        status = "conflict"
    elif candidates and not (original_spec and parsed_spec is None):
        # Existing unresolved low-confidence WHD suggestions are not upgraded.
        review_only = record.get("specification_review_only") or record.get("review_only")
        weak = False
        confidence = record.get("specification_confidence")
        if confidence is not None:
            try:
                weak = weak or float(confidence) < 0.8 or not math.isfinite(float(confidence))
            except (TypeError, ValueError):
                weak = True
        if record.get("ocr_confirmation_required") or unresolved_base:
            status = "unverified"
        elif review_only or (weak and parsed_native is None):
            status = "partial"
        else:
            status = "recognized"
    else:
        status = "partial" if partial else "missing"
    result = {"schema_version": 1, "status": status, "candidates": candidates,
              "partial": partial, "conflicting_axes": sorted(partial_conflicts)}
    record["dimension_recognition"] = result
    record["dimension_review_required"] = status != "recognized"
    record["partial_specification_dimensions"] = partial
    if status == "recognized":
        chosen = next((row for row in candidates if row["origin"] == "recognized_specification"), candidates[0])
        for key in _COPY_FIELDS:
            if key in chosen:
                record[key] = chosen[key]
        if chosen["origin"] == "pdf_native_explicit_axes":
            record["dimension_source"] = chosen["origin"]
    else:
        # Keep rejected evidence above, never expose it as a selected size.
        record["specification"] = ""
        record["dimensions"] = []
    return record


def dimension_review_hint(record):
    evidence = record.get("dimension_recognition") or {}
    status = evidence.get("status")
    text = ("尺寸存在冲突，请对照原图填写宽*深*高。" if status == "conflict" else
            "尺寸正在识别；也可对照原图填写宽*深*高。" if status == "pending" else
            "尺寸候选尚未完成交叉核对，请对照原图填写宽*深*高。" if status == "unverified" else
            "尺寸尚未完整识别，请对照原图补充宽*深*高。")
    specifications = list(dict.fromkeys(
        row["specification"] + ("（尺寸线候选，待核对）" if row.get("units") == "mm" else "（尺寸线候选，单位待核）")
        if row.get("origin") == "pdf_native_dimension_lines_review" else row["specification"]
        for row in evidence.get("candidates", []) if row.get("specification")))
    if specifications:
        text += "\n候选：" + "；".join(specifications[:6])
    partial = evidence.get("partial") or {}
    if partial:
        text += "\n可核对：" + "，".join(f"{label}{partial[axis]:g} mm" for axis, label in (("W", "宽"), ("D", "深"), ("H", "高（含义待核）"), ("B", "底座")) if axis in partial)
    for note in evidence.get("review_notes", [])[:3]:
        text += "\n" + str(note)[:300]
    return text
