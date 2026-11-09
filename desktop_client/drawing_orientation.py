"""Determine a clockwise view correction relative to the rendered page."""
from pathlib import Path
import re
from threading import Lock

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QTransform


_ANGLES = (0, 90, 180, 270)
_PROBE_EDGE = 1800
_TITLE_TERMS = re.compile(
    r"技术要求|表面处理|图纸编号|物料编码|产品名称|图号|电气柜|设计|审核|比例|接地|"
    r"technicalrequirements|drawingno|surfacefinish|revision|designedby|frontview|sideview",
    re.IGNORECASE,
)
_LOCAL_MODELS = (
    "PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)


def _clear_direction(scores, minimum):
    ranked = sorted(scores, key=scores.get, reverse=True)
    if scores[ranked[0]] >= minimum and scores[ranked[0]] >= 1.6 * scores[ranked[1]]:
        return ranked[0]
    return None


def pdf_view_rotation(page):
    """Account for /Rotate, which Poppler already applies when rendering."""
    hidden_text = False

    def check_render_mode(operator, args, *_):
        nonlocal hidden_text
        if operator == b"Tr" and args[0] in (3, 7):
            hidden_text = True

    scores = {}
    for angle in _ANGLES:
        content = page.extract_text(orientations=(angle,), visitor_operand_before=check_render_mode) or ""
        if hidden_text:
            return None  # An invisible OCR layer may disagree with the visible scan.
        # Dimension numbers and grid references alone are not a direction cue.
        words = re.findall(r"[^\W\d_]{2,}", content)
        scores[(angle - page.rotation) % 360] = sum(min(len(word), 32) for word in words)
    return _clear_direction(scores, minimum=16)


def _text_scores(result):
    horizontal = total = 0.0
    title_terms = set()
    if result.boxes is None or result.txts is None or result.scores is None:
        return horizontal, total, title_terms
    for box, text, confidence in zip(result.boxes, result.txts, result.scores):
        letters = sum(char.isalpha() for char in text)
        if confidence < .78 or letters < 2:
            continue
        weight = min(letters, 24) * confidence
        total += weight
        xs, ys = zip(*box)
        if max(xs) - min(xs) >= 1.4 * (max(ys) - min(ys)):
            horizontal += weight
            title_terms.update(_TITLE_TERMS.findall(re.sub(r"\s+", "", text).lower()))
    return horizontal, total, title_terms


def raster_view_rotation(image, read_text, cancelled):
    """Compare readable horizontal text on a bounded, local raster probe."""
    if max(image.width(), image.height()) > _PROBE_EDGE:
        image = image.scaled(QSize(_PROBE_EDGE, _PROBE_EDGE), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    scores = {}
    for angle in _ANGLES:
        if cancelled():
            return None
        rotated = image.transformed(QTransform().rotate(angle)) if angle else image
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not rotated.save(buffer, "PNG"):
            return None
        buffer.close()
        result = read_text(bytes(encoded))
        if result is None:
            return None
        horizontal, total, title_terms = _text_scores(result)
        scores[angle] = horizontal + 8 * len(title_terms)
        if angle == 0 and len(title_terms) >= 2 and horizontal >= 24 and horizontal >= .75 * total:
            return 0
    return _clear_direction(scores, minimum=24)


def install_raster_orientation_probe(namespace):
    """Reuse the shipped OCR engine and serialize its mutable inference settings."""
    read_angles = namespace.get("rapidocr_angle_readings")
    load_engine = getattr(read_angles, "__globals__", {}).get("_load_rapidocr_engine")
    if not callable(load_engine):
        return None
    inference_lock = Lock()

    def read_recognition_angles(*args, **kwargs):
        with inference_lock:
            return read_angles(*args, **kwargs)

    namespace["rapidocr_angle_readings"] = read_recognition_angles

    def probe(image, cancelled):
        import rapidocr

        model_dir = Path(rapidocr.__file__).with_name("models")
        if not all((model_dir / name).is_file() for name in _LOCAL_MODELS):
            return None

        def read_text(data):
            with inference_lock:
                if cancelled():
                    return None
                engine, _ = load_engine()
                if not isinstance(engine, rapidocr.RapidOCR):
                    return None
                previous = engine.use_cls
                try:
                    # Keep the direction signal. The line classifier otherwise
                    # turns upside-down crops before text recognition.
                    return engine(data, use_cls=False)
                finally:
                    engine.use_cls = previous

        return raster_view_rotation(image, read_text, cancelled)

    return probe
