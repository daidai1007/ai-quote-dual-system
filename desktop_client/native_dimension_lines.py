"""Native PDF view/dimension-line evidence, always for human review.

Design references: javvi51/edocr2 (region-first engineering drawing OCR), and
py-pdf/pypdf's documented text/operand visitors. This is an original adapter;
no eDOCr/TensorFlow model or third-party source is vendored or executed.
Numeric annotations are not measurements of pixels, and no scale is guessed.
"""
from __future__ import annotations

import math
from pathlib import Path
import re


_NUMBER = re.compile(r"^(\d{2,5}(?:\.\d+)?)\s*(?:mm|毫米)?$", re.IGNORECASE)
_FRONT = {"主视图", "正视图", "前视图", "FRONTVIEW", "FRONT"}
_SIDE = {"左视图", "右视图", "侧视图", "SIDEVIEW", "LEFTVIEW", "RIGHTVIEW", "SIDE"}
_MAX_SEGMENTS = 20000
_MAX_TOKENS = 2000
_MAX_RECTANGLES = 500


class EvidenceLimit(ValueError):
    pass


def _point(matrix, x, y):
    a, b, c, d, e, f = map(float, matrix)
    return a * x + c * y + e, b * x + d * y + f


def _orientation(line):
    x0, y0, x1, y1 = line
    if abs(y0 - y1) < .01 and abs(x1 - x0) > 1:
        return "horizontal"
    if abs(x0 - x1) < .01 and abs(y1 - y0) > 1:
        return "vertical"
    return None


class _Collector:
    def __init__(self, page):
        self.page = page
        self.tokens, self.rectangles, self.segments = [], [], []
        self.pending_lines, self.pending_rectangles, self.path = [], [], []
        self.unsupported_form = False
        self.render_mode, self.render_stack, self.font_size = 0, [], 12
        self.plain_ascii_font = False
        self.ascii_values = set()

    def text(self, text, cm, tm, _font, size):
        if re.sub(r"\s+", "", str(text)) in self.ascii_values:
            return  # Prefer the exact show-operator matrix to a later flush.
        self._add_text(text, cm, tm, size, "text_visitor")

    def _add_text(self, text, cm, tm, size, source):
        if self.render_mode in {3, 7}:
            return
        value = str(text).strip()
        compact = re.sub(r"\s+", "", value).upper()
        if not (_NUMBER.fullmatch(value) or compact in _FRONT | _SIDE):
            return
        x, y = _point(cm, float(tm[4]), float(tm[5]))
        vx = float(tm[0]) * float(cm[0]) + float(tm[1]) * float(cm[2])
        vy = float(tm[0]) * float(cm[1]) + float(tm[1]) * float(cm[3])
        scale = math.hypot(vx, vy)
        if (not all(math.isfinite(v) for v in (x, y, scale, float(size))) or scale <= 0
                or not 1 <= abs(float(size)*scale) <= 100):
            return
        # Anchor, not an exact glyph box: PDF font widths/kerning vary.
        extent = len(value) * float(size) * scale * .5
        self.tokens.append({"text": value, "kind": "front" if compact in _FRONT else "side" if compact in _SIDE else "number",
            "x": x, "y": y, "center_x": x + vx / scale * extent / 2,
            "center_y": y + vy / scale * extent / 2, "font_size": abs(float(size) * scale), "source": source})
        if len(self.tokens) > _MAX_TOKENS:
            raise EvidenceLimit("native token budget exceeded")

    def _close(self):
        if len(self.path) > 1:
            self.pending_lines.append((*self.path[-1], *self.path[0]))
        if len(self.path) == 4:
            xs, ys = zip(*self.path)
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            corners = {(round(x0, 3), round(y0, 3)), (round(x1, 3), round(y0, 3)),
                       (round(x1, 3), round(y1, 3)), (round(x0, 3), round(y1, 3))}
            if {(round(x, 3), round(y, 3)) for x, y in self.path} == corners:
                self.pending_rectangles.append((x0, y0, x1, y1))
        self.path = []

    def operand(self, op, args, cm, _tm):
        if op == b"q":
            self.render_stack.append((self.render_mode, self.font_size, self.plain_ascii_font))
        elif op == b"Q":
            self.render_mode, self.font_size, self.plain_ascii_font = self.render_stack.pop() if self.render_stack else (0, 12, False)
        elif op == b"Tr":
            self.render_mode = int(args[0])
        elif op == b"Tf":
            self.font_size = float(args[1])
            self.plain_ascii_font = False
            try:
                font = self.page["/Resources"]["/Font"][args[0]].get_object()
                family = str(font.get("/BaseFont", "")).split("-")[0]
                self.plain_ascii_font = (font.get("/Subtype") == "/Type1"
                    and family in {"/Helvetica", "/Times", "/Courier"}
                    and font.get("/Encoding", "/StandardEncoding") in {"/StandardEncoding", "/WinAnsiEncoding", "/MacRomanEncoding"}
                    and "/ToUnicode" not in font)
            except (KeyError, TypeError, AttributeError):
                pass
        elif op in {b"Tj", b"TJ"} and self.plain_ascii_font:
            chunks = args[0] if op == b"TJ" else [args[0]]
            # ASCII dimension glyphs and English captions can be decoded at
            # the show operator. Unicode/CID text remains on the text visitor.
            decoded = []
            separated = False
            for chunk in chunks:
                if isinstance(chunk, (bytes, str)):
                    try:
                        value = chunk.decode("ascii") if isinstance(chunk, bytes) else str(chunk)
                        value.encode("ascii")
                    except (UnicodeError, AttributeError):
                        decoded = []
                        break
                    decoded.append(value)
                elif abs(float(chunk)) >= 500:
                    separated = True  # Large TJ spacing may separate annotations.
            value = "".join(decoded).strip()
            if not separated:
                self._add_text(value, cm, _tm, self.font_size, "show_operator_ascii")
            if value:
                self.ascii_values.add(re.sub(r"\s+", "", value))
        elif op == b"Do":
            objects = self.page.get("/Resources", {}).get("/XObject", {})
            try:
                if objects[args[0]].get_object().get("/Subtype") == "/Form":
                    self.unsupported_form = True
            except (KeyError, TypeError, AttributeError):
                self.unsupported_form = True
        elif op == b"m":
            self.path = [_point(cm, float(args[0]), float(args[1]))]
        elif op == b"l" and self.path:
            end = _point(cm, float(args[0]), float(args[1]))
            self.pending_lines.append((*self.path[-1], *end))
            self.path.append(end)
        elif op == b"re":
            x, y, width, height = map(float, args)
            points = [_point(cm, px, py) for px, py in ((x, y), (x+width, y), (x+width, y+height), (x, y+height))]
            self.path = points
            self.pending_lines.extend((*points[i], *points[i+1]) for i in range(3))
            self._close()
        elif op == b"h":
            self._close()
        elif op in {b"c", b"v", b"y"}:
            # Do not join a later line to the stale start of a curved path.
            self.path = []
        elif op in {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}:
            if op in {b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}:
                self._close()
            self.segments.extend(line for line in self.pending_lines if _orientation(line))
            self.rectangles.extend(self.pending_rectangles)
            self.pending_lines, self.pending_rectangles, self.path = [], [], []
            if len(self.segments) > _MAX_SEGMENTS or len(self.rectangles) > _MAX_RECTANGLES:
                raise EvidenceLimit("native geometry budget exceeded")
        elif op == b"n":
            # Unpainted clipping paths are not cabinet outlines.
            self.pending_lines, self.pending_rectangles, self.path = [], [], []
        if len(self.pending_lines) > _MAX_SEGMENTS or len(self.path) > _MAX_SEGMENTS:
            raise EvidenceLimit("pending native geometry budget exceeded")


def _labelled_views(rectangles, tokens, page_bounds):
    px0, py0, px1, py1 = page_bounds
    page_area = (px1-px0) * (py1-py0)
    views = []
    for label in (token for token in tokens if token["kind"] in {"front", "side"}):
        choices = []
        for box in set(rectangles):
            x0, y0, x1, y1 = box
            width, height = x1-x0, y1-y0
            if width < 20 or height < 20 or width*height > page_area*.75 or width*height < page_area*.003:
                continue
            if not (px0 <= x0 < x1 <= px1 and py0 <= y0 < y1 <= py1):
                continue
            gap = y0 - label["y"]
            if x0-5 <= label["x"] <= x1+5 and 0 <= gap <= min(60, height*.25):
                choices.append((gap / height, -width*height, box))
        if choices:
            choices.sort()
            if len(choices) > 1 and choices[0][:2] == choices[1][:2] and choices[0][2] != choices[1][2]:
                continue
            box = list(choices[0][2])
            if not any(view["kind"] == label["kind"] and view["box"] == box for view in views):
                views.append({"kind": label["kind"], "label": label["text"], "box": box})
    return views


def _dimension_spans(view, segments, orientation):
    x0, y0, x1, y1 = view["box"]
    low, high = (x0, x1) if orientation == "horizontal" else (y0, y1)
    outside_low, outside_high = (y0, y1) if orientation == "horizontal" else (x0, x1)
    span = high-low
    groups = {}
    for segment in segments:
        if _orientation(segment) != orientation:
            continue
        a, b, fixed = ((segment[0], segment[2], segment[1]) if orientation == "horizontal"
                       else (segment[1], segment[3], segment[0]))
        a, b = sorted((a, b))
        gap = outside_low-fixed if fixed < outside_low else fixed-outside_high if fixed > outside_high else 0
        if 3 <= gap <= min(90, span*.4) and a >= low-4 and b <= high+4:
            groups.setdefault(round(fixed, 1), []).append((a, b))
    results = []
    for fixed, intervals in groups.items():
        intervals.sort()
        merged = []
        for a, b in intervals:
            if merged and a-merged[-1][1] <= min(60, span*.25):
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for a, b in merged:
            tolerance = max(3, span*.025)
            if abs(a-low) <= tolerance and abs(b-high) <= tolerance:
                results.append((a, b, fixed))
    if len(results) > 64:
        raise EvidenceLimit("too many dimension spans for one view")
    return results


def associate_dimension_lines(rectangles, segments, tokens, page_bounds):
    """Require a labelled view, matching span endpoints and a nearby number."""
    views = _labelled_views(rectangles, tokens, page_bounds)
    observations = []
    for index, view in enumerate(views):
        for orientation in ("horizontal", "vertical"):
            axis = ("W" if view["kind"] == "front" else "D") if orientation == "horizontal" else "H"
            for low, high, fixed in _dimension_spans(view, segments, orientation):
                for token in tokens:
                    match = _NUMBER.fullmatch(token["text"]) if token["kind"] == "number" else None
                    if match is None:
                        continue
                    value = float(match[1])
                    along, across = ((token["center_x"], token["center_y"]) if orientation == "horizontal"
                                     else (token["center_y"], token["center_x"]))
                    if (10 <= value <= 20000 and abs(along-(low+high)/2) <= max(20, (high-low)*.3)
                            and abs(across-fixed) <= max(10, token["font_size"]*1.6)):
                        row = {"axis": axis, "value": value, "view": view["kind"], "view_index": index,
                               "view_label": view["label"], "view_box": view["box"],
                               "line": {"orientation": orientation, "start": low, "end": high, "offset": fixed},
                               "text": token["text"], "anchor": [token["x"], token["y"]], "token_source": token.get("source", "provided")}
                        if row not in observations:
                            observations.append(row)
    values = {axis: sorted({row["value"] for row in observations if row["axis"] == axis}) for axis in ("W", "D", "H")}
    partial = {axis: found[0] for axis, found in values.items() if len(found) == 1}
    conflicts = [axis for axis, found in values.items() if len(found) > 1]
    # Several labelled front/side views may belong to different products.
    ambiguous_views = any(sum(view["kind"] == kind for view in views) > 1 for kind in ("front", "side"))
    specification = None
    if not conflicts and not ambiguous_views and all(axis in partial for axis in ("W", "D", "H")):
        specification = f"{partial['W']:g}*{partial['D']:g}*{partial['H']:g}"
    return {"schema_version": 1, "policy": "review_only_never_confirms_specification",
            "status": "conflict" if conflicts or ambiguous_views else "candidate" if specification else "partial" if partial else "unavailable",
            "views": views, "observations": observations, "axis_values": values, "partial": partial,
            "specification": specification, "conflicting_axes": conflicts, "ambiguous_views": ambiguous_views,
            "height_interpretation": "body_or_overall_unverified", "coordinate_space": "pdf_user_space"}


def inspect_single_page_pdf(path):
    """Read text and painted vector paths; never rasterize, OCR or download."""
    result = {"text": "", "dimension_lines": {"status": "unavailable", "policy": "review_only_never_confirms_specification"}}
    if Path(path).suffix.lower() != ".pdf":
        return result
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        try:
            if len(reader.pages) != 1:
                return result
            page = reader.pages[0]
            collector = _Collector(page)
            try:
                text = page.extract_text(visitor_operand_before=collector.operand, visitor_text=collector.text) or ""
            except Exception as error:
                # A visitor failure must not remove the existing native-text route.
                result["text"] = (page.extract_text() or "")[:200000]
                result["dimension_lines"]["reason"] = type(error).__name__
                return result
            result["text"] = text[:200000]
            if collector.unsupported_form or page.rotation or float(page.get("/UserUnit", 1)) != 1:
                result["dimension_lines"]["reason"] = "complex_form_rotation_or_user_unit"
                return result
            bounds = tuple(map(float, page.cropbox))
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                return result
            evidence = associate_dimension_lines(collector.rectangles, collector.segments, collector.tokens, bounds)
            unit_values = {value.lower() for value in re.findall(r"(?:单位|UNITS?)\s*[:：=]?\s*(mm|cm|m|毫米|厘米|米)(?![A-Za-z0-9²])", text, re.IGNORECASE)}
            evidence["units"] = "mm" if unit_values and unit_values <= {"mm", "毫米"} else "unverified"
            result["dimension_lines"] = evidence
            return result
        finally:
            reader.close()
    except Exception as error:
        # Optional geometry must not fail an otherwise supported source import.
        result["dimension_lines"]["reason"] = type(error).__name__
        return result


def attach_dimension_line_suggestions(record, evidence):
    """Add auditable fallback clues without changing formal sizes or gates."""
    if not isinstance(evidence, dict) or evidence.get("policy") != "review_only_never_confirms_specification":
        return
    record["native_dimension_lines"] = evidence
    if not record.get("dimension_review_required") or evidence.get("status") not in {"candidate", "partial", "conflict"}:
        return
    summary = record.get("dimension_recognition") or {}
    notes = list(summary.get("review_notes") or [])
    note = "已关联图中视图与尺寸线；请核对标注单位，以及高度是否包含底座。"
    if note not in notes:
        notes.append(note)
    readings = []
    for axis, label in (("W", "宽"), ("D", "深"), ("H", "高（本体/总高待核）")):
        values = evidence.get("axis_values", {}).get(axis) or []
        if values:
            readings.append(label + "/".join(f"{value:g}" for value in values[:6]))
    if readings:
        reading_note = "尺寸线标注：" + "，".join(readings)
        if reading_note not in notes:
            notes.append(reading_note)
    summary["review_notes"] = notes
    specification = evidence.get("specification")
    if specification:
        row = {"specification": specification, "origin": "pdf_native_dimension_lines_review", "review_only": True,
               "height_interpretation": "body_or_overall_unverified", "units": evidence.get("units", "unverified")}
        rows = list(summary.get("candidates") or [])
        if row not in rows:
            rows.append(row)
        summary["candidates"] = rows
    # Numeric positions alone never establish mm, H+B or a formal size.
    if evidence.get("units") == "mm" and evidence.get("status") != "conflict":
        partial = dict(summary.get("partial") or {})
        for axis, value in evidence.get("partial", {}).items():
            if axis not in partial:
                partial[axis] = value
        summary["partial"] = partial
    record["dimension_recognition"] = summary
