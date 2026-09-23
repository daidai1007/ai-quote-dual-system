import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import quote_drawing_preview as preview


assert preview.RENDER_EDGE >= 3600
assert preview.FIT_RENDER_OVERSAMPLE >= 2.25
assert preview.PDF_ZOOM_OVERSAMPLE >= 1.75
assert preview.PDF_MAX_RENDER_EDGE >= 9600

source = (ROOT / "desktop_client/quote_drawing_preview.py").read_text(encoding="utf-8")
assert "'-aa', 'yes', '-aaVector', 'yes'" in source
assert "QPainter.RenderHint.TextAntialiasing" in source

print("PASS: drawing preview uses enhanced initial, fit and zoom rendering quality")
