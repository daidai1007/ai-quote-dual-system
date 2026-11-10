"""Opt-in local eDOCr2 dimension review for the Scheme 2 page worker."""

import atexit
import json
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock, Thread


_log = logging.getLogger("ai_quote.edocr2")
_lock = Lock()
_process = None
_replies = None


def _read_replies(pipe, replies):
    try:
        for line in pipe:
            replies.put(line)
    finally:
        replies.put(None)


@atexit.register
def _stop():
    global _process, _replies
    if _process is not None:
        if _process.poll() is None:
            _process.kill()
        _process.wait()
        _process.stdin.close()
        _process.stdout.close()
    _process = _replies = None


def review_dimensions(encoded, result, width, height, title_sizes=()):
    python = os.environ.get("AIQUOTE_EDOCR2_PYTHON")
    if not python:
        return None
    source = os.environ.get("AIQUOTE_EDOCR2_SOURCE")
    model = os.environ.get("AIQUOTE_EDOCR2_MODEL")
    if not source or not model:
        return {"status": "error", "reason": "missing_source_or_model"}
    if result.boxes is None or result.txts is None or result.scores is None:
        return {"status": "unavailable", "reason": "no_text_boxes"}
    tokens = [
        {"text": str(text), "score": float(score),
         "box": [[float(x) / width, float(y) / height] for x, y in box]}
        for box, text, score in zip(result.boxes, result.txts, result.scores)
    ]
    with _lock:
        try:
            return _request(python, source, model, encoded, tokens, title_sizes)
        except (OSError, ValueError, Empty, RuntimeError) as error:
            _stop()
            _log.warning("Local dimension review unavailable (%s)", type(error).__name__)
            return {"status": "error", "reason": type(error).__name__}


def _request(python, source, model, encoded, tokens, title_sizes):
    global _process, _replies
    if _process is None or _process.poll() is not None:
        _stop()
        runner = Path(__file__).with_name("edocr2_runner.py")
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        _process = subprocess.Popen(
            [python, "-I", "-u", str(runner), source, model],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        _replies = Queue()
        Thread(target=_read_replies, args=(_process.stdout, _replies), daemon=True).start()
    with TemporaryDirectory(prefix="edocr2-page-") as folder:
        image = Path(folder) / "page.png"
        image.write_bytes(encoded)
        _process.stdin.write(json.dumps({"image": str(image), "tokens": tokens, "title_sizes": title_sizes}) + "\n")
        _process.stdin.flush()
        line = _replies.get(timeout=60)
        if line is None:
            raise RuntimeError("eDOCr2 worker exited")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise ValueError("invalid eDOCr2 worker response")
        return response
