"""Isolated eDOCr2 dimension recognizer and raster outline association."""

from contextlib import redirect_stdout
from functools import lru_cache
from itertools import islice
import json
import os
from pathlib import Path
import re
import sys


_NUMBER = re.compile(r"[0-9]{2,5}(?:\.[0-9]{1,2})?")
_ORDINATE_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.[0-9]{1,2})?")
_ORDINATE_TOKEN = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,2})?|[0Oo][0oOfF]?")
_FRONT = re.compile(r"主视|正视|前视|front\s*view", re.I)
_SIDE = re.compile(r"左视|右视|侧视|side\s*view", re.I)


class _MlsdTiny:
    """Run NAVER's Apache-2.0 M-LSD Tiny TFLite release on CPU."""

    def __init__(self, model_path):
        import tensorflow as tf

        self.interpreter = tf.lite.Interpreter(model_content=Path(model_path).read_bytes(), num_threads=2)
        self.interpreter.allocate_tensors()
        self.input = self.interpreter.get_input_details()[0]
        self.outputs = self.interpreter.get_output_details()
        if list(self.input["shape"]) != [1, 512, 512, 4] or [tuple(t["shape"]) for t in self.outputs] != [
            (1, 200, 2), (1, 200), (1, 256, 256, 4),
        ]:
            raise ValueError("M-LSD Tiny 512 FP32 model expected")

    def lines(self, image):
        height, width = image.shape[:2]
        batch = np.ones((1, 512, 512, 4), np.float32)
        batch[0, :, :, :3] = cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA)
        self.interpreter.set_tensor(self.input["index"], batch)
        self.interpreter.invoke()
        centers, scores, offsets = [self.interpreter.get_tensor(output["index"])[0] for output in self.outputs]
        for (y, x), score in zip(centers, scores):
            if score < .10:
                continue
            ax, ay, bx, by = offsets[y, x]
            if (ax - bx)**2 + (ay - by)**2 < 16**2:
                continue
            yield ((x + ax) * width / 256, (y + ay) * height / 256,
                   (x + bx) * width / 256, (y + by) * height / 256)


def _axis_segments(ink, minimum):
    # One-dimensional morphology preserves the endpoints of long painted lines.
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    lines = cv2.morphologyEx(joined, cv2.MORPH_OPEN, np.ones((1, minimum), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(lines)
    return [(x, x + w - 1, y + (h - 1) / 2) for x, y, w, h, _ in stats[1:]
            if w >= minimum and h <= 9]


def _outlines(horizontal, vertical, width, height, *, projections=False):
    min_height = height * .13
    vertical = [line for line in vertical if min_height <= line[1] - line[0] <= height * .65]
    if len(vertical) > (210 if projections else 140):
        return []
    boxes = []
    for i, (top, bottom, left) in enumerate(vertical):
        for y0, y1, right in vertical[i + 1:]:
            x0, x1 = sorted((left, right))
            if not width * .045 <= x1 - x0 <= width * .48:
                continue
            start, end = max(top, y0), min(bottom, y1)
            if end - start < min_height - (height * .01):
                continue
            tolerance = max(5, (end - start) * .03)
            edges = [y for a, b, y in horizontal if start - tolerance <= y <= end + tolerance
                     and a <= x0 + 5 and b >= x1 - 5
                     and min(abs(a - x0), abs(b - x1), abs(y - start), abs(y - end)) <= tolerance]
            if len(edges) < 2:
                continue
            tops, bottoms = [min(edges)], [max(edges)]
            if projections:
                # Extension lines may run past a cabinet edge to a parallel
                # dimension line. Keep nearby closed projections as well.
                inset = min(54, (max(edges) - min(edges)) * .15)
                tops = sorted({y for y in edges if y <= min(edges) + inset})[:5]
                bottoms = sorted({y for y in edges if y >= max(edges) - inset}, reverse=True)[:5]
            for upper in tops:
                for lower in bottoms:
                    if lower - upper < min_height:
                        continue
                    box = (x0, upper, x1, lower)
                    if not any(max(abs(a - b) for a, b in zip(box, other)) <= 5 for other in boxes):
                        boxes.append(box)
    return boxes if len(boxes) <= (260 if projections else 100) else []


def _same_height(a, b):
    tolerance = max(6, (a[3] - a[1]) * .03)
    return abs(a[1] - b[1]) <= tolerance and abs(a[3] - b[3]) <= tolerance


def _view_pairs(boxes, labels):
    def view_label(box, pattern):
        x0, _, x1, bottom = box
        return any(pattern.search(label) and x0 <= x <= x1 and -1 <= y - bottom <= 33
                   for x, y, label in labels)

    fronts = [box for box in boxes if view_label(box, _FRONT)]
    sides = [box for box in boxes if view_label(box, _SIDE)]
    pairs = [(front, side) for front in fronts for side in sides if _same_height(front, side)
             and (front[0] >= side[2] - 5 or side[0] >= front[2] - 5)]
    if pairs:
        return pairs
    # A central front view flanked by equal-width, aligned side views can also
    # establish the axes when a scan has no view captions.
    for front in boxes:
        for left in boxes:
            side_width = left[2] - left[0]
            if left[2] >= front[0] or front[2] - front[0] < 1.45 * side_width or not _same_height(front, left):
                continue
            for right in boxes:
                if (right[0] > front[2] and _same_height(front, right)
                        and abs(right[2] - right[0] - side_width) <= .06 * side_width):
                    pairs.extend(((front, left), (front, right)))
    return pairs


def _projection_pairs(boxes, labels, width, height):
    main = [box for box in boxes if box[3] - box[1] >= height * .13]
    pairs = set(_view_pairs(main, labels))
    # A repeated wide projection on both sides of a narrow one can be the
    # front and rear, with the depth view between them. Allow either ordering.
    for front in main:
        front_width = front[2] - front[0]
        for side in main:
            side_width = side[2] - side[0]
            if front_width < 1.35 * side_width or not _same_height(front, side):
                continue
            if not 0 < max(side[0] - front[2], front[0] - side[2]) <= width * .16:
                continue
            for other in main:
                if not _same_height(front, other):
                    continue
                other_width = other[2] - other[0]
                if ((front[2] < side[0] and 0 < other[0] - side[2] <= width * .16)
                        or (side[2] < front[0] and 0 < side[0] - other[2] <= width * .16)):
                    if abs(other_width - front_width) <= .07 * front_width:
                        pairs.add((front, side))
                if ((front[2] < side[0] and 0 < front[0] - other[2] <= width * .16)
                        or (side[2] < front[0] and 0 < other[0] - front[2] <= width * .16)):
                    if abs(other_width - side_width) <= .07 * side_width:
                        pairs.add((front, side))
    return sorted(pairs) if len(pairs) <= 220 else []


def _ink_supported_lines(image, detector, horizontal, vertical, *, tiled=False):
    """Accept model segments only where the rendered page contains a stroke."""
    height, width = image.shape[:2]
    ink = image.min(axis=2) < 226
    added = ([], [])
    if tiled:
        tile_width, tile_height = round(width * .63), round(height * .63)
        regions = ((x, y, x + tile_width, y + tile_height)
                   for x in (0, width - tile_width) for y in (0, height - tile_height))
    else:
        regions = [(0, 0, width, height)]
    candidates = ((x + left, y + top, xx + left, yy + top) for left, top, right, bottom in regions
                  for x, y, xx, yy in detector.lines(image[top:bottom, left:right]))
    for x0, y0, x1, y1 in candidates:
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        is_vertical = bool(dy > dx)
        span, slope = (dy, dx) if is_vertical else (dx, dy)
        page_axis = height if is_vertical else width
        if not max(30, page_axis * .035) <= span <= page_axis * .66 or slope > max(3, span * .035):
            continue
        mask = ink.T if is_vertical else ink
        low, high = sorted((y0, y1) if is_vertical else (x0, x1))
        start, end = max(0, round(low)), min(mask.shape[1] - 1, round(high))
        center = round((x0 + x1) / 2 if is_vertical else (y0 + y1) / 2)
        first, last = max(0, center - 8), min(mask.shape[0], center + 9)
        if first >= last or start >= end:
            continue
        support = mask[first:last, start:end + 1]
        best = int(np.argmax(np.count_nonzero(support, axis=1)))
        row = support[best]
        outer = max(5, row.size // 10)
        if row.mean() < .60 or min(row[:outer].mean(), row[-outer:].mean()) < .25:
            continue
        points = np.flatnonzero(row)
        line = (start + int(points[0]), start + int(points[-1]), float(first + best))
        existing = vertical if is_vertical else horizontal
        pool = added[is_vertical]
        if not any(abs(line[0] - a) <= 8 and abs(line[1] - b) <= 8 and abs(line[2] - c) <= 3
                   for segments in (existing, pool) for a, b, c in segments):
            pool.append(line)
    return added


def _anchored_lines(box, lines, axis, *, supplemental=False):
    x0, y0, x1, y1 = box
    if axis == "H":
        low, high, inner_low, inner_high = y0, y1, x0, x1
    else:
        low, high, inner_low, inner_high = x0, x1, y0, y1
    tolerance = max(11 if supplemental else 8, .028 * (high - low))
    return [(start, end, offset) for start, end, offset in lines
            if abs(start - low) <= tolerance and abs(end - high) <= tolerance
            and 3 <= max(inner_low - offset, offset - inner_high) <= 110]


def _label_crop(gray, line, vertical, scale):
    start, end, offset = line
    if vertical:
        gray = gray.T
    half = max(16, min(45, (end - start) * .12))
    center = (start + end) / 2
    left, right = max(0, round((center - half) * scale)), min(gray.shape[1], round((center + half) * scale))
    top, bottom = max(0, round((offset - 16) * scale)), min(gray.shape[0], round((offset - 1) * scale))
    if bottom - top < 5 or right <= left:
        return None
    band = gray[top:bottom, left:right]
    if vertical:
        band = cv2.flip(band, 1)
    mask = np.uint8(band < 205)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    glyphs = [(x, y, w, h) for x, y, w, h, area in stats[1:count]
              if 1.5 * scale <= w <= 16 * scale and 3 * scale <= h <= 14 * scale and area >= 6 * scale]
    if not 2 <= len(glyphs) <= 6:
        return None
    x0, y0 = min(row[0] for row in glyphs), min(row[1] for row in glyphs)
    x1, y1 = max(x + w for x, y, w, h in glyphs), max(y + h for x, y, w, h in glyphs)
    if y1 - y0 > 15 * scale or x1 - x0 > .8 * (right - left):
        return None
    return {"center": (float(offset), float(center)) if vertical else (float(center), float(offset)),
            "vertical": vertical, "text": "", "crop": band[y0:y1, x0:x1]}


def _matching_reads(lines, reads, vertical, gray, fallback, scale):
    found = []
    for start, end, offset in set(lines):
        matches = []
        line = [int(start), int(end), round(float(offset), 1)]
        for token in reads:
            x, y = token["center"]
            along, across = (y, x) if vertical else (x, y)
            distance = abs(across - offset)
            if (token["vertical"] == vertical and distance <= min(21, max(9, token["thickness"] * 1.25))
                    and abs(along - (start + end) / 2) <= .18 * (end - start)):
                matches.append((distance, token))
        if matches:
            nearest = min(distance for distance, _ in matches)
            found.extend((token, line) for distance, token in matches if distance <= nearest + 2)
        else:
            key = (start, end, offset, vertical)
            if key not in fallback:
                fallback[key] = _label_crop(gray, key[:3], vertical, scale)
            if fallback[key] is not None:
                found.append((fallback[key], line))
    return found


def _numeric_crops(gray, tokens, width, height):
    source_height, source_width = gray.shape
    for token in tokens:
        if token["score"] < .55 or not _NUMBER.fullmatch(token["text"].strip()):
            continue
        points = np.asarray(token["box"]) * [width, height]
        lo, hi = points.min(axis=0), points.max(axis=0)
        w, h = hi - lo
        if min(w, h) < 3 or max(w, h) > .1 * width:
            continue
        vertical = h > 1.3 * w
        scale = np.array([source_width / width, source_height / height])
        x0, y0 = np.maximum((lo * scale).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(hi * scale).astype(int) + 1, [source_width, source_height])
        # Keep the polygon tight so a neighboring arrow or dimension line
        # does not become part of the number sent to eDOCr2.
        band = gray[y0:y1, x0:x1]
        crop = cv2.rotate(band, cv2.ROTATE_90_CLOCKWISE) if vertical else band
        yield {"center": ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2),
               "vertical": vertical, "thickness": min(w, h), "text": token["text"], "crop": crop,
               "score": token["score"]}


def _recognize(recognizer, crops, *, original_crop=False):
    if not crops:
        return []
    samples = []
    for crop in crops:
        image = crop["crop"]
        if not original_crop:
            cleaned = _clean_number(image)
            if cleaned is not None:
                image = cleaned
            margin = 2 if crop["text"] else 5
            image = cv2.copyMakeBorder(image, margin, margin, margin, margin, cv2.BORDER_CONSTANT, value=255)
        scale = min(200 / image.shape[1], 31 / image.shape[0])
        size = tuple(max(1, round(side * scale)) for side in image.shape[::-1])
        resized = cv2.resize(image, size)
        padded = np.zeros((31, 200), np.uint8)
        padded[:size[1], :size[0]] = resized
        samples.append(padded)
    batch = np.array(samples, dtype=np.float32)[..., None] / 255
    readings = []
    for offset in range(0, len(batch), 16):
        for probabilities in np.asarray(recognizer.model(batch[offset:offset + 16], training=False)):
            chars, scores = [], []
            previous = recognizer.blank_label_idx
            for label, distribution in zip(probabilities.argmax(axis=-1), probabilities):
                if label != previous and label != recognizer.blank_label_idx:
                    chars.append(recognizer.alphabet[label])
                    scores.append(float(distribution[label]))
                previous = label
            readings.append(("".join(chars), min(scores, default=0)))
    return readings


def _clean_number(image):
    # RapidOCR boxes occasionally include the horizontal rule under the text.
    # Strip continuous rules before presenting the printed glyphs to eDOCr2.
    _, ink = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink[np.count_nonzero(ink, axis=1) >= ink.shape[1] * .74] = 0
    for index in np.flatnonzero(np.count_nonzero(ink, axis=0) >= ink.shape[0] * .76):
        if index <= ink.shape[1] * .12 or index >= ink.shape[1] * .88:
            ink[:, index] = 0
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink)
    glyphs = [idx for idx, (x, y, w, h, area) in enumerate(stats[1:], 1)
              if h >= 3 and w <= .8 * ink.shape[1] and area >= 3]
    if not glyphs:
        return None
    ink = np.uint8(np.isin(labels, glyphs)) * 255
    x, y, width, height = cv2.boundingRect(ink)
    return 255 - ink[y:y + height, x:x + width]


def _find_proposals(pairs, horizontal, vertical, crops, source_gray, scale, *, supplemental=False):
    fallback = {}
    proposals = []
    sides_by_front = {}
    for front, side in pairs:
        sides_by_front.setdefault(front, set()).add(side)
    for front, side in pairs:
        aligned = sorted(sides_by_front[front])
        choices = {}
        for axis, outlines, lines in (("W", (front,), horizontal), ("D", (side,), horizontal),
                                       ("H", (front, *aligned), vertical)):
            spans = [span for box in outlines
                     for span in _anchored_lines(box, lines, axis, supplemental=supplemental)]
            choices[axis] = _matching_reads(spans, crops, axis == "H", source_gray, fallback, scale)
        if all(choices.values()):
            proposals.append(choices)
    return proposals


def _covers(lines, start, end, offset, tolerance=5):
    return any(a <= start + tolerance and b >= end - tolerance and abs(c - offset) <= tolerance
               for a, b, c in lines)


def _projected_plan_links(pairs, boxes, horizontal, vertical, height):
    """Link a front view to a plan whose marked depth matches the side projection."""
    seen = set()
    for (x0, y0, x1, y1), side in pairs:
        depth = side[2] - side[0]
        width = x1 - x0
        # Printed extension lines can make a front outline look too wide.
        # A separately closed plan can supply the exact shared lateral edges.
        widths = {(x0, x1)}
        for left, top, right, bottom in boxes:
            if (8 <= max(y0 - bottom, top - y1) <= .26 * height
                    and abs(left - x0) <= .09 * width and abs(right - x1) <= .09 * width
                    and abs(bottom - top - depth) <= max(8, .07 * depth)):
                widths.add((left, right))
        for left, right in sorted(widths):
            if not (all(_covers(horizontal, left, right, y) for y in (y0, y1))
                    and all(_covers(vertical, y0, y1, x) for x in (left, right))):
                continue
            for start, end, offset in vertical:
                if not (8 <= max(y0 - end, start - y1) <= .26 * height
                        and abs(end - start - depth) <= max(8, .07 * depth)
                        and 4 <= max(left - offset, offset - right) <= 95):
                    continue
                # Both extension strokes must reach the depth dimension line.
                if not (all(_covers(horizontal, min(left, offset), max(right, offset), y)
                            for y in (start, end))
                        and all(_covers(vertical, start, end, x) for x in (left, right))):
                    continue
                link = (tuple(map(float, (left, y0, right, y1))),
                        tuple(map(float, (left, start, right, end))), tuple(map(float, (start, end, offset))))
                if link not in seen:
                    seen.add(link)
                    yield link


def _measure_band(gray, line, vertical, scale, *, compact=False):
    start, end, offset = line
    center = (start + end) / 2
    half = 12 if compact else max(18, min(30, (end - start) * .09))
    if vertical:
        gray = gray.T
    x0, x1 = max(0, round((center - half) * scale)), round((center + half) * scale)
    y0 = max(0, round((offset - (14 if compact else 18)) * scale))
    y1 = round((offset - (0 if compact else 2)) * scale)
    band = gray[y0:y1, x0:x1]
    if not band.size:
        return None
    return cv2.flip(band, 1) if vertical else band


def _read_dimension_crops(recognizer, images):
    crops = [{"crop": image, "text": ""} for image in images]
    cleaned = _recognize(recognizer, crops)
    original = _recognize(recognizer, crops, original_crop=True)
    return [{float(text) for text, score in (first, second)
             if _ORDINATE_NUMBER.fullmatch(text) and score >= .80 and float(text) <= 20000}
            for first, second in zip(cleaned, original, strict=True)]


def _annotated_base(get_recognizer, gray, source_gray, scale, tokens, crops, horizontal, vertical, title_sizes):
    """Split a marked plinth only after verifying the outline and printed heights."""
    if len(title_sizes) != 1 or not any("底托" in token["text"] or "底座" in token["text"] for token in tokens):
        return None
    parts = title_sizes[0].split("*")
    if len(parts) != 3 or not all(_ORDINATE_NUMBER.fullmatch(value) for value in parts):
        return None
    width, depth, total = map(float, parts)
    if min(width, depth, total) < 20:
        return None
    faint_ink = np.uint8(gray < 238) * 255
    horizontal_marks = horizontal + _axis_segments(faint_ink, 30)
    vertical_marks = vertical + _axis_segments(faint_ink.T.copy(), 30)

    def fits(pixels, expected, tolerance=.045):
        return abs(pixels - expected) <= max(4, tolerance * expected)

    @lru_cache(maxsize=48)
    def read_vertical(line, compact=False):
        band = _measure_band(source_gray, line, True, scale)
        matched = _matching_reads([line], crops, True, source_gray, {}, scale)
        images = [token["crop"] for token, _ in matched]
        if band is not None:
            images.append(band)
        if compact:
            band = _measure_band(source_gray, line, True, scale, compact=True)
            if band is not None:
                images.append(band)
        images += [cv2.rotate(crop, cv2.ROTATE_180) for crop in images]
        return set().union(*_read_dimension_crops(get_recognizer(), images)) if images else set()

    def has_width(view, value):
        left, right, top, bottom = view
        spans = [line for line in horizontal_marks if abs(line[0] - left) <= 9 and abs(line[1] - right) <= 9
                 and top - 90 <= line[2] <= bottom + 90]
        return any(token.get("score", 0) >= .9 and float(token["text"]) == value
                   for token, _ in _matching_reads(spans, crops, False, source_gray, {}, scale)
                   if _NUMBER.fullmatch(token["text"]))

    values = {}
    for left, right, top in horizontal:
        pixels_per_mm = (right - left) / width
        for a, b, bottom in horizontal:
            if abs(a - left) > 5 or abs(b - right) > 5 or not fits(bottom - top, total * pixels_per_mm):
                continue
            if not all(_covers(vertical, top, bottom, edge) for edge in (left, right)):
                continue
            aligned = [(a, b, y, bottom) for a, b, y in horizontal if abs(y - top) <= 6
                       and (fits(b - a, width * pixels_per_mm) or fits(b - a, depth * pixels_per_mm))
                       and _covers(horizontal, a, b, bottom)
                       and all(_covers(vertical, top, bottom, edge) for edge in (a, b))]
            if not all(any(fits(view[1] - view[0], value * pixels_per_mm) and has_width(view, value)
                           for view in aligned) for value in (width, depth)):
                continue
            for a, b, divider in horizontal:
                base_span = bottom - divider
                if not (.025 * (bottom - top) <= base_span <= .18 * (bottom - top)
                        and abs(a - left) <= 6 and abs(b - right) <= 6):
                    continue
                for start, end, offset in vertical:
                    if not (start <= divider + 3 and bottom - 3 <= end <= bottom + 12
                            and end - start <= 3.4 * base_span
                            and 5 < abs(offset - right) <= .25 * (right - left)):
                        continue
                    bands = [(divider, bottom, offset), (divider - 2.5 * base_span, divider, offset)]
                    base_values = set().union(*(read_vertical(line, compact=True) for line in bands))
                    for base in base_values:
                        if not (20 <= base < total and fits(base_span, base * pixels_per_mm, .16)):
                            continue
                        body = total - base
                        for high, low, ruler in vertical_marks:
                            if abs(high - top) > 9 or not any(4 < max(a - ruler, ruler - b) <= 110
                                                              for a, b, _, _ in aligned):
                                continue
                            expected = total if abs(low - bottom) <= 8 else body if abs(low - divider) <= 8 else None
                            if expected is not None and expected in read_vertical((high, low, ruler)):
                                values[(body, base)] = {"base_span": [float(divider), float(bottom), float(offset)],
                                                        "height_span": [float(high), float(low), float(ruler)],
                                                        "printed_height": expected}
    if len(values) != 1:
        return None
    (body, base), evidence = next(iter(values.items()))
    return {"status": "candidate", "reason": "annotated_base_split", "dimension_layout": "separate_base",
            "partial": {"W": width, "D": depth, "H": body, "B": base},
            "specification": f"{width:g}*{depth:g}*({body:g}+{base:g})", "base_evidence": evidence,
            "height_interpretation": "separately_annotated_body_and_base"}


def _linked_ordinates(source_gray, ink, tokens, ruler, *, horizontal, recognizer):
    """Read a zero-based coordinate series with printed leaders on one ruler."""
    start, end, offset = ruler
    span = end - start
    along_limit = max(12, .02 * span)
    height, width = ink.shape
    source_height, source_width = source_gray.shape
    strokes = ink.T if horizontal else ink
    picks = []
    for token in tokens:
        text = token["text"].strip()
        if token["score"] < .5 or not _ORDINATE_TOKEN.fullmatch(text):
            continue
        box = np.asarray(token["box"])
        points = box * [width, height]
        x, y = points.mean(axis=0)
        along, across = (x, y) if horizontal else (y, x)
        if not (start - along_limit <= along <= end + along_limit and 2 <= offset - across <= 34):
            continue
        low, high = max(0, round(along) - 7), round(along) + 8
        edge = round(offset)
        leader = strokes[low:high, edge + 1:edge + 17]
        if not leader.size or leader.mean(axis=1).max() < .60:
            continue
        x0, y0 = np.maximum(np.floor(box.min(axis=0) * [source_width, source_height]).astype(int), 0)
        x1, y1 = np.ceil(box.max(axis=0) * [source_width, source_height]).astype(int)
        crop = source_gray[y0:y1 + 1, x0:x1 + 1]
        if not crop.size:
            continue
        # Remove a leader that lies on the edge of a horizontal text box.
        if not horizontal:
            crop = crop[:, :max(1, round(crop.shape[1] * .88))]
        else:
            crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
        picks.append((float(along), [float(x), float(y)], text, crop))
    if not 4 <= len(picks) <= 30:
        return []
    reads = _read_dimension_crops(recognizer, [row[3] for row in picks])
    zeroes = [row for row, values in zip(picks, reads, strict=True)
              if abs(row[0] - start) <= along_limit and 0 in values]
    if not zeroes:
        return []
    options = []
    for row, values in zip(picks, reads, strict=True):
        if abs(row[0] - end) > along_limit:
            continue
        for value in sorted(values):
            if value < 20:
                continue
            ratio = span / value
            marks = []
            for other, read in zip(picks, reads, strict=True):
                close = [coordinate for coordinate in read if 0 < coordinate < value and
                         abs(other[0] - start - coordinate * ratio) <= max(18, .06 * span)]
                if len(close) == 1:
                    marks.append(close[0])
            if marks and max(marks) - min(marks) >= .10 * value:
                options.append((value, {"span": list(ruler), "center": row[1], "primary_text": row[2],
                                        "coordinate_origin": zeroes[0][1], "interior_coordinates": sorted(set(marks)),
                                        "orientation": "horizontal" if horizontal else "vertical"}))
    return options


def _projected_dimensions(get_recognizer, gray, source_gray, scale, tokens, crops, pairs, boxes, horizontal, vertical):
    height, width = gray.shape
    ink = gray < 225
    # Thin ordinate rules may be absent from the original line mask.
    horizontal = horizontal + _axis_segments(np.uint8(ink) * 255, max(30, int(width * .035)))
    vertical = vertical + _axis_segments(np.uint8(ink.T) * 255, max(30, int(height * .045)))
    links = list(islice(_projected_plan_links(pairs, boxes, horizontal, vertical, height), 13))
    if not 0 < len(links) <= 12:
        return None
    recognizer = get_recognizer()

    @lru_cache(maxsize=48)
    def measure(line, vertical):
        matched = _matching_reads([line], crops, vertical, source_gray, {}, scale)
        labels = [crop for crop, _ in matched]
        fallback = _label_crop(source_gray, line, vertical, scale)
        band = _measure_band(source_gray, line, vertical, scale)
        if fallback is not None:
            labels.append(fallback)
        if band is not None:
            start, end, offset = line
            center = (start + end) / 2
            labels.append({"crop": band, "center": (offset, center) if vertical else (center, offset), "text": ""})
        attempts = [(label, label["crop"]) for label in labels]
        if vertical:
            attempts.extend((label, cv2.rotate(label["crop"], cv2.ROTATE_180)) for label in labels)
        reads = _read_dimension_crops(recognizer, [image for _, image in attempts])
        options = {}
        for (label, _), values in zip(attempts, reads, strict=True):
            # Only an exact, strong first-pass numeral can supplement a crop
            # read. It must still agree with the scale of the other two spans.
            if label.get("score", 0) >= .96 and _ORDINATE_NUMBER.fullmatch(label["text"]):
                values.add(float(label["text"]))
            for value in sorted(values):
                if 20 <= value <= 20000:
                    options[value] = {"span": list(line), "center": list(label["center"]),
                                      "primary_text": label["text"],
                                      "orientation": "vertical" if vertical else "horizontal"}
        return list(options.items())

    @lru_cache(maxsize=24)
    def coordinates(line, horizontal):
        return _linked_ordinates(source_gray, ink, tokens, line, horizontal=horizontal,
                                 recognizer=recognizer)

    results = {}
    for front, plan, depth in links:
        widths = {tuple(map(float, line)) for line in _anchored_lines(plan, horizontal, "W")}
        heights = {tuple(map(float, line)) for line in _anchored_lines(front, vertical, "H")}
        rulers = {tuple(map(float, line)) for line in _anchored_lines(front, horizontal, "W") if line[2] < front[1]}
        if not heights or len(widths | heights | rulers) > 16:
            continue
        depths = measure(depth, True)
        if not depths:
            continue
        plan_widths = [option for line in sorted(widths) for option in measure(line, False)]
        ordinate_widths = [option for line in sorted(rulers) for option in coordinates(line, True)]
        for layout, width_options, height_options in (
            ("plan_and_elevation", plan_widths,
             [option for line in sorted(heights) for option in measure(line, True)] if plan_widths else ()),
            ("zero_based_ordinate", ordinate_widths,
             [option for line in sorted(heights) if line[2] < front[0]
              for option in coordinates(line, False)] if ordinate_widths else ()),
        ):
            for w, wr in width_options:
                for d, dr in depths:
                    for h, hr in height_options:
                        rows = (("W", w, wr), ("D", d, dr), ("H", h, hr))
                        ratios = [(row["span"][1] - row["span"][0]) / value for _, value, row in rows]
                        if min(ratios) > 0 and max(ratios) <= 1.09 * min(ratios):
                            results[(w, d, h)] = (layout, [{"axis": axis, **row} for axis, _, row in rows])
    if len(results) != 1:
        return None
    triple, (layout, observations) = next(iter(results.items()))
    return {"status": "candidate", "reason": "linked_projected_dimensions", "dimension_layout": layout,
            "partial": dict(zip(("W", "D", "H"), triple)), "specification": "*".join(f"{n:g}" for n in triple),
            "observations": observations, "raster_size": [width, height],
            "height_interpretation": "body_or_overall_unverified"}


def _consistent_spans(proposals, numbers):
    results = {}
    for choice in proposals:
        axes = {axis: [(value, line, token) for token, line in matches
                       for value in numbers.get(id(token), ())] for axis, matches in choice.items()}
        for w, dw, wt in axes["W"]:
            for d, dd, dt in axes["D"]:
                for h, dh, ht in axes["H"]:
                    ratios = [(line[1] - line[0]) / value for line, value in ((dw, w), (dd, d), (dh, h))]
                    if min(ratios) > 0 and max(ratios) <= 1.09 * min(ratios):
                        results[(w, d, h)] = (("W", dw, wt), ("D", dd, dt), ("H", dh, ht))
    return results


def _review(get_recognizer, image, tokens, get_line_detector=None, title_sizes=()):
    height, width = image.shape[:2]
    source_gray = image.min(axis=2)
    scale = max(1, width / 1600)
    if scale > 1:
        width, height = round(width / scale), round(height / scale)
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    gray = image.min(axis=2)
    ink = np.uint8(gray < 195) * 255
    horizontal = _axis_segments(ink, max(30, int(width * .035)))
    vertical = _axis_segments(ink.T.copy(), max(30, int(height * .045)))
    boxes = _outlines(horizontal, vertical, width, height)
    b, g, r = image.astype(np.int16).transpose(2, 0, 1)
    dimension_ink = np.uint8((g > r + 35) & (g > b + 35)) * 255
    if cv2.countNonZero(dimension_ink):
        horizontal = horizontal + _axis_segments(dimension_ink, max(30, int(width * .035)))
        vertical = vertical + _axis_segments(dimension_ink.T.copy(), max(30, int(height * .045)))
    labels = [(float(x * width), float(y * height), token["text"])
              for token in tokens if token["score"] >= .68
              for x, y in [np.mean(token["box"], axis=0)]]
    pairs = _view_pairs(boxes, labels)
    crops = list(_numeric_crops(source_gray, tokens, width, height))
    proposals = _find_proposals(pairs, horizontal, vertical, crops, source_gray, scale)
    mlsd = {}
    if not proposals and get_line_detector is not None and title_sizes:
        base = _annotated_base(get_recognizer, gray, source_gray, scale, tokens, crops, horizontal, vertical, title_sizes)
        if base is not None:
            return base
    if not proposals and get_line_detector is not None:
        try:
            detector = get_line_detector()
            mlsd = {"mlsd": {"status": "ran", "segments": 0, "tiled": False}}
            for tiled in (False, True):
                added_h, added_v = _ink_supported_lines(image, detector, horizontal, vertical, tiled=tiled)
                mlsd["mlsd"]["segments"] += len(added_h) + len(added_v)
                mlsd["mlsd"]["tiled"] = tiled
                if not (added_h or added_v):
                    continue
                horizontal, vertical = horizontal + added_h, vertical + added_v
                boxes = _outlines(horizontal, vertical, width, height, projections=True)
                pairs = _projection_pairs(boxes, labels, width, height)
                proposals = _find_proposals(pairs, horizontal, vertical, crops, source_gray, scale, supplemental=True)
                if proposals:
                    break
        except (OSError, ValueError, RuntimeError, ImportError, cv2.error) as error:
            mlsd = {"mlsd": {"status": "error", "reason": type(error).__name__}}
    if not proposals:
        if pairs and mlsd.get("mlsd", {}).get("status") == "ran":
            projected = _projected_dimensions(get_recognizer, gray, source_gray, scale, tokens, crops,
                                              pairs, boxes, horizontal, vertical)
            if projected is not None:
                return {**projected, **mlsd, "pairs": len(pairs)}
        return {"status": "unavailable", "reason": "no_complete_outline_spans", "pairs": len(pairs), "crops": 0, **mlsd}
    all_spans = {axis: {tuple(line) for proposal in proposals for _, line in proposal[axis]}
                 for axis in ("W", "D", "H")}
    for proposal in proposals:
        for axis in ("W", "D", "H"):
            # Inner chains on an aligned outline must not stand in for the
            # measured envelope when a containing span is visible.
            proposal[axis] = [(token, line) for token, line in proposal[axis]
                              if not any(a <= line[0] + 2 and b >= line[1] - 2
                                         and b - a >= (line[1] - line[0]) * 1.035
                                         and abs(offset - line[2]) <= .13 * (b - a)
                                         for a, b, offset in all_spans[axis])]
    proposals = [proposal for proposal in proposals if all(proposal.values())]
    if not proposals:
        return {"status": "unavailable", "reason": "no_complete_outer_spans", "pairs": len(pairs), "crops": 0, **mlsd}
    selected = {id(token): token for choice in proposals for matches in choice.values() for token, _ in matches}
    if len(selected) > 36:
        return {"status": "unavailable", "reason": "ambiguous_outline_spans", "pairs": len(pairs), "crops": 0, **mlsd}
    attempts = []
    for token in selected.values():
        attempts.append(token)
        if token["vertical"]:
            attempts.append({**token, "crop": cv2.rotate(token["crop"], cv2.ROTATE_180), "original": token})
    numbers = {}
    recognizer = get_recognizer()

    def store_reads(batch, *, original_crop=False):
        for token, (text, score) in zip(batch, _recognize(recognizer, batch, original_crop=original_crop)):
            if _NUMBER.fullmatch(text) and score >= .76 and 20 <= float(text) <= 20000:
                numbers.setdefault(id(token.get("original", token)), set()).add(float(text))

    store_reads(attempts)
    if mlsd:
        unread = [token for token in attempts if id(token.get("original", token)) not in numbers]
        store_reads(unread, original_crop=True)
    results = _consistent_spans(proposals, numbers)
    if not results and mlsd.get("mlsd", {}).get("status") == "ran":
        for token, values in zip(attempts, _read_dimension_crops(recognizer, [row["crop"] for row in attempts]), strict=True):
            numbers.setdefault(id(token.get("original", token)), set()).update(n for n in values if n >= 20)
        results = _consistent_spans(proposals, numbers)
    evidence = {"status": "ambiguous" if results else "unavailable", "reason": "outline_dimension_consistency",
                "pairs": len(pairs), "crops": len(attempts),
                "alternatives": ["*".join(f"{value:g}" for value in triple) for triple in sorted(results)], **mlsd}
    if len(results) == 1:
        triple, supports = next(iter(results.items()))
        evidence.update(status="candidate", partial=dict(zip(("W", "D", "H"), triple)),
                        specification="*".join(f"{value:g}" for value in triple),
                        observations=[{"axis": axis, "span": line, "center": list(token["center"]),
                                       "orientation": "vertical" if token["vertical"] else "horizontal",
                                       "primary_text": token["text"]} for axis, line, token in supports],
                        raster_size=[width, height], height_interpretation="body_or_overall_unverified")
    return evidence


def main():
    global cv2, np
    reply = sys.stdout
    with redirect_stdout(sys.stderr):
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        os.environ.setdefault("TF_NUM_INTRAOP_THREADS", "2")
        os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
        sys.path.insert(0, str(Path(sys.argv[1]).resolve(strict=True)))
        import cv2
        import numpy as np
        weights = Path(sys.argv[2]).resolve(strict=True)
        line_model = os.environ.get("AIQUOTE_MLSD_TINY_MODEL")

        @lru_cache(maxsize=1)
        def get_line_detector():
            return _MlsdTiny(line_model)

        @lru_cache(maxsize=1)
        def get_recognizer():
            from edocr2.keras_ocr.recognition import Recognizer

            alphabet = weights.with_suffix(".txt").read_text(encoding="utf-8").strip()
            model = Recognizer(alphabet=alphabet, weights=None)
            model.model.load_weights(str(weights))
            return model

        for line in sys.stdin:
            try:
                request = json.loads(line)
                image = cv2.imdecode(np.fromfile(request["image"], dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("unreadable page image")
                result = _review(get_recognizer, image, request["tokens"], get_line_detector if line_model else None,
                                 request.get("title_sizes", ()))
            except (OSError, ValueError, RuntimeError, TypeError, KeyError, ImportError, cv2.error) as error:
                result = {"status": "error", "reason": type(error).__name__}
            print(json.dumps(result), file=reply, flush=True)


if __name__ == "__main__":
    main()
