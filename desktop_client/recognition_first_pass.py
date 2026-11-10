"""Share the first OCR reading and its direction with the page preview."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Event
from unicodedata import normalize

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QTransform

from drawing_orientation import _text_scores, _clear_direction
from edocr2_review import review_dimensions
from recognition_dimensions import explicit_axis_evidence, parse_dimension_specification


_current_scan = ContextVar("current_drawing_page_scan", default=None)
_TITLE_SIZE = re.compile(
    r"^(?:规格|尺寸|备注)?[:：]?L(?P<length>\d{2,4})[X×*]"
    r"(?P<a>[WH])(?P<av>\d{2,4})[X×*](?P<b>[WH])(?P<bv>\d{2,4})"
    r"(?=$|[（(]|MM$|附图|附件)"
)
_TECH_SIZE = re.compile(
    r"^(?:\d[.、])?(?:尺寸[:：]?)?(?P<width_label>宽)?(?P<w>\d{2,4})[X×*]高(?P<h>\d{2,4})"
    r"(?:\+(?P<base>\d{2,4}))?[X×*](?:深(?P<d>\d{2,4})|(?P<tail>\d{2,4})深)"
    r"(?=$|[;；。]|MM$)"
)
_TITLE_HINT = re.compile(r"图号|表面处理|备注|drawing\s*no|remarks|surface\s*treatment", re.IGNORECASE)
_TITLE_ORDER = re.compile(
    r"^(?P<x>\d{2,4})[X×*](?P<y>\d{2,4})[X×*](?P<z>\d{2,4})"
    r"\((?P<a>[宽高深])[X×*]?(?P<b>[宽高深])[X×*]?(?P<c>[宽高深])\)$"
)


class PageScan:
    """One result channel per imported source page, confined to the session."""

    def __init__(self):
        self.ready = Event()
        self.rotation = None
        self.native_rotation = None
        self.mode = "native"
        self.native_text = ""
        self.reuse_path = None
        self.reading = None
        self.printed_sizes = ()
        self.primary_reads = 0
        self.detail_reads = 0
        self.edocr2 = None

    def publish(self, angle):
        self.rotation = angle
        self.ready.set()

    def wait_rotation(self, cancelled):
        while not cancelled():
            if self.ready.wait(.05):
                return self.rotation
        return None


@contextmanager
def page_scan_scope(scan):
    token = _current_scan.set(scan)
    try:
        yield
    finally:
        scan.ready.set()
        _current_scan.reset(token)


def current_page_scan():
    return _current_scan.get()


def _png(image):
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, "PNG")
    buffer.close()
    return bytes(encoded) if ok else None


def _oriented_reading(image, read_text, known_angle):
    """Try upright once first. Other directions are only for uncertain pages."""
    scores = {}
    best = None
    best_score = -1
    order = [known_angle] if known_angle is not None else [0, 270, 90, 180]
    for index, angle in enumerate(order):
        oriented = image.transformed(QTransform().rotate(angle)) if angle else image
        encoded = _png(oriented)
        result = read_text(encoded, lambda: False) if encoded else None
        if result is None:
            return None
        horizontal, total, terms = _text_scores(result)
        if known_angle is not None or (len(terms) >= 2 and horizontal >= 24 and horizontal >= .75 * total):
            return angle, encoded, result, oriented.width(), oriented.height()
        scores[angle] = horizontal + 8 * len(terms)
        if scores[angle] > best_score:
            best_score = scores[angle]
            best = (angle, encoded, result, oriented.width(), oriented.height())
        if index == 0 and image.width() < image.height() and total < 24:
            order[1:3] = (90, 270)
    return best if _clear_direction(scores, minimum=24) is not None else None


def _as_core_reading(result, width, height, contract):
    tokens = []
    if result.boxes is None or result.txts is None or result.scores is None:
        return None
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        text = str(text).strip()
        if not text:
            continue
        raw_points = [(float(x), float(y)) for x, y in box]
        if len(raw_points) != 4:
            continue
        points = tuple((x / width, y / height) for x, y in raw_points)
        tokens.append(contract["OCRToken"](
            text, float(score), sum(x for x, _ in points) / len(points),
            sum(y for _, y in points) / len(points), contract["_polygon_text_orientation"](raw_points), points))
    if not tokens:
        return None
    return contract["OCRReading"](
        contract["RAPIDOCR_ENGINE_NAME"], 0, "\n".join(token.text for token in tokens),
        sum(token.confidence for token in tokens) / len(tokens), len(tokens), tuple(tokens), width, height)


def _printed_sizes(tokens, *, title_crop=False):
    """Keep complete, explicitly labelled sizes as review evidence."""
    sizes = set()
    for token in tokens:
        if token.confidence < .80 or token.orientation != "horizontal":
            continue
        text = re.sub(r"\s+", "", normalize("NFKC", token.text)).upper()
        in_title = title_crop or (token.center_x >= .44 and token.center_y >= .73)
        match = _TITLE_SIZE.match(text) if in_title else None
        if match and match["a"] != match["b"]:
            axes = {match["a"]: int(match["av"]), match["b"]: int(match["bv"])}
            spec = f"{int(match['length'])}*{axes['W']}*{axes['H']}"
            if parse_dimension_specification(spec):
                sizes.add(spec)
        order = _TITLE_ORDER.fullmatch(text) if in_title else None
        if order and {order["a"], order["b"], order["c"]} == {"宽", "高", "深"}:
            axes = {order[label]: order[value] for label, value in zip("abc", "xyz")}
            spec = f"{axes['宽']}*{axes['深']}*{axes['高']}"
            if parse_dimension_specification(spec):
                sizes.add(spec)
        tech = _TECH_SIZE.match(text)
        if tech and (tech["width_label"] or tech["base"]):
            height = tech["h"]
            if tech["base"]:
                base = tech["base"]
                # Require a matching explicit base annotation in the same
                # reading before interpreting the plus term as a base.
                if not any(other.confidence >= .80 and re.search(
                    rf"(?:(?<!\d){base}\s*(?:mm|毫米)?\s*高[^\n]{{0,8}}底座|底座(?:高[度]?)?[:：]?\s*{base}(?!\d))",
                    other.text, re.IGNORECASE) for other in tokens):
                    continue
                height = f"({height}+{base})"
            spec = f"{tech['w']}*{tech['d'] or tech['tail']}*{height}"
            if parse_dimension_specification(spec):
                sizes.add(spec)
    return sizes


def _matches_view_dimensions(specification, view_values):
    parsed = parse_dimension_specification(specification)
    if not parsed:
        return False
    width, body, depth = parsed["dimensions"][0]
    heights = {body}
    if parsed["height_terms_mm"]:
        heights.add(sum(parsed["height_terms_mm"]))
    return (view_values.get("W", width) == width and view_values.get("D", depth) == depth
            and view_values.get("H", body) in heights)


def refine_pending_size_evidence(record, native_text, specifications, raster_evidence=None):
    """Prefer dimension lines tied to the cabinet outline over prose."""
    summary = record.get("dimension_recognition")
    if not isinstance(summary, dict):
        return
    line_evidence = record.get("native_dimension_lines") or {}
    view_values = {}
    if (line_evidence.get("policy") == "review_only_never_confirms_specification"
            and line_evidence.get("units") == "mm"
            and line_evidence.get("status") in {"candidate", "partial"}):
        view_values = line_evidence.get("partial") or {}
    view_spec = line_evidence.get("specification") if set(view_values) >= {"W", "D", "H"} else None
    view_origin = "pdf_native_dimension_lines_review"
    if raster_evidence and raster_evidence.get("status") == "candidate":
        raster_spec = raster_evidence["specification"]
        if line_evidence.get("status") != "conflict" and _matches_view_dimensions(raster_spec, view_values):
            view_values = raster_evidence["partial"]
            view_spec = raster_spec
            view_origin = "edocr2_outline_review"
    view_disagrees = bool(view_values and record.get("specification")
                          and not _matches_view_dimensions(record["specification"], view_values))
    if not record.get("dimension_review_required"):
        if len(specifications) < 2 and not view_disagrees:
            return
        record.update(specification="", dimensions=[], dimension_review_required=True)
    named = explicit_axis_evidence(native_text)["partial"]
    summary["partial"] = {
        **{axis: value for axis, value in (summary.get("partial") or {}).items() if named.get(axis) == value},
        **view_values,
    }
    if not specifications and not view_values:
        return
    candidates = summary.setdefault("candidates", [])
    for specification in specifications:
        row = dict(specification=specification, origin="pdf_title_ocr_review", review_only=True)
        if row not in candidates:
            candidates.append(row)
    if view_spec and not any(row.get("origin") == view_origin
                             and row.get("specification") == view_spec for row in candidates):
        candidates.append(dict(specification=view_spec, origin=view_origin, review_only=True,
                               units="mm" if view_origin == "pdf_native_dimension_lines_review" else "unverified"))
    notes = summary.setdefault("review_notes", [])
    distinct = {row["specification"] for row in candidates if row.get("specification")}
    matching = {spec for spec in distinct if view_values and _matches_view_dimensions(spec, view_values)}
    if view_disagrees or len(distinct) > 1:
        summary["status"] = "conflict"
    summary.pop("review_display_specification", None)
    if view_values:
        # Where a body/base expression already agrees with the view, keep
        # that interpretation. The line alone does not split the height.
        base_matches = {spec for spec in matching
                        if (parse_dimension_specification(spec) or {}).get("height_terms_mm")}
        if len(base_matches) == 1:
            summary["review_display_specification"] = next(iter(base_matches))
        elif view_spec:
            summary["review_display_specification"] = view_spec
        elif len(matching) == 1:
            summary["review_display_specification"] = next(iter(matching))
        note = "优先核对柜体外廓尺寸线标注，高度是否包含底座需对照原图。"
    elif summary.get("status") == "conflict":
        note = "图面有不同规格，请对照柜体外廓尺寸线核对。"
    else:
        note = "图面标注的规格候选，请核对宽、深、本体高及底座。"
        if len(distinct) == 1:
            summary["review_display_specification"] = specifications[0]
    if note not in notes:
        notes.insert(0, note)
    record["dimension_recognition"] = summary


def _has_red_ink(image):
    count = 0
    for y in range(0, image.height(), max(12, image.height() // 160)):
        for x in range(0, image.width(), max(12, image.width() // 160)):
            pixel = image.pixel(x, y)
            red, green, blue = (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
            if red > 120 and red > 1.35 * max(green, blue):
                count += 1
                if count > 20:
                    return True
    return False


def _first_pass_is_sufficient(scan, reading, details):
    # Preserve the existing independent-evidence requirement. Agreement with
    # an explicit native PDF specification can satisfy it. A lone OCR result
    # never changes the existing quote gate.
    if scan.native_rotation is None:
        return False
    native = explicit_axis_evidence(scan.native_text)
    native_spec = parse_dimension_specification(native["specification"])
    if not native_spec or not reading.mean_confidence or reading.mean_confidence < .9:
        return False
    evidence = details["ocr_engine_evidence"][reading.engine]
    candidates = evidence.get("specification_candidates") or []
    return len(candidates) == 1 and parse_dimension_specification(
        candidates[0].get("specification")) == native_spec


def install_first_pass(namespace):
    tools = namespace["DrawingRecognitionTools"]
    read_text = namespace.get("_read_local_ocr_for_orientation")
    contract = namespace.get("_rapidocr_reading_contract") or {}
    required = ("OCRReading", "OCRToken", "RAPIDOCR_ENGINE_NAME", "_polygon_text_orientation")
    if not callable(read_text) or not all(name in contract for name in required):
        return
    original_dual = tools._dual_ocr_page
    original_rapid = namespace["rapidocr_angle_readings"]
    original_requirements = tools._ocr_numbered_requirements_region
    original_views = tools._infer_dimensions_from_views

    def reuse_rapid(image_path, angles=(0, 90, 180, 270), *args, **kwargs):
        scan = _current_scan.get()
        if scan is not None and scan.reuse_path == str(image_path) and tuple(angles) == (0,):
            return {0: scan.reading}, None
        return original_rapid(image_path, angles, *args, **kwargs)

    def dual(cls, image_path, windows_angles=(0, 90, 180, 270)):
        scan = _current_scan.get()
        if scan is None:
            return original_dual(image_path, windows_angles)
        scan.mode = "legacy_review"
        primary = None
        def read_once(data, cancelled):
            scan.primary_reads += 1
            return read_text(data, cancelled)

        try:
            image = QImage.fromData(Path(image_path).read_bytes())
            if not image.isNull():
                primary = _oriented_reading(image, read_once, scan.rotation)
            if primary:
                angle, encoded, result, width, height = primary
                reading = _as_core_reading(result, width, height, contract)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError, ImportError):
            primary = None
        if primary is None:
            checked = original_dual(image_path, windows_angles)
            evidence = checked.get("ocr_engine_evidence", {}).get("windows_ocr_multi_orientation") or {}
            angle = evidence.get("angle")
            if scan.rotation is None and angle in (0, 90, 180, 270) and len(evidence.get("text") or "") >= 32:
                scan.publish(angle)
            else:
                scan.ready.set()
            return checked
        scan.publish(angle)
        if reading is None:
            return original_dual(image_path, windows_angles)
        title_sizes = _printed_sizes(reading.tokens)
        if not title_sizes and not scan.native_text.strip() and any(
            token.center_x >= .44 and token.center_y >= .73 and _TITLE_HINT.search(token.text)
            for token in reading.tokens
        ):
            # Read only the title rectangle at the source's rendered detail.
            oriented = QImage.fromData(encoded)
            left, top = int(oriented.width() * .44), int(oriented.height() * .73)
            crop = oriented.copy(left, top, oriented.width() - left, oriented.height() - top)
            try:
                image_data = _png(crop)
                if image_data:
                    scan.detail_reads += 1
                    detail = read_text(image_data, lambda: False)
                    cropped = _as_core_reading(detail, crop.width(), crop.height(), contract) if detail is not None else None
                    if cropped is not None:
                        title_sizes = _printed_sizes(cropped.tokens, title_crop=True)
            except (OSError, ValueError, TypeError, AttributeError, RuntimeError, ImportError):
                pass
        scan.printed_sizes = tuple(sorted(title_sizes))
        scan.edocr2 = review_dimensions(encoded, result, width, height, scan.printed_sizes)
        has_red = _has_red_ink(image)
        evidence = reading.audit_dict()
        evidence["dimension_text"] = reading.text
        details = dict(has_red=has_red, primary_engine=reading.engine, primary_text=reading.text,
                       ocr_engine_evidence={reading.engine: evidence},
                       recognition_engines=[reading.engine], recognition_engine_errors={})
        details = cls._refresh_ocr_consensus(details)
        # Keep red-ink/technical-note handling on the verification path for
        # raster pages. A native-and-raster match alone proves dimensions.
        sufficient = _first_pass_is_sufficient(scan, reading, details)
        if sufficient and not has_red and len(cls.extract_technical_requirements(reading.text).splitlines()) >= 5:
            scan.mode = "first_pass"
            return details
        with TemporaryDirectory(prefix="upright-drawing-") as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(encoded)
            scan.reuse_path, scan.reading = str(path), reading
            scan.mode = "oriented_review"
            try:
                checked = original_dual(str(path), (0,))
            finally:
                scan.reuse_path = scan.reading = None
        checked["source_page_rotation"] = angle
        checked["has_red"] = bool(checked.get("has_red") or has_red)
        return checked

    def requirements(cls, *args, **kwargs):
        scan = _current_scan.get()
        if scan is not None and scan.mode == "first_pass":
            return ""
        return original_requirements(*args, **kwargs)

    def views(cls, *args, **kwargs):
        scan = _current_scan.get()
        if scan is not None and scan.mode == "first_pass":
            return None
        return original_views(*args, **kwargs)

    namespace["rapidocr_angle_readings"] = reuse_rapid
    tools._dual_ocr_page = classmethod(dual)
    tools._ocr_numbered_requirements_region = classmethod(requirements)
    tools._infer_dimensions_from_views = classmethod(views)
