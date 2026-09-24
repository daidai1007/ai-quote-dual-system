import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from desktop_client.quote_drawing_preview import DEFAULT_READABLE_ZOOM, InkCanvas


app = QApplication.instance() or QApplication([])
canvas = InkCanvas()
canvas.resize(600, 400)
canvas.show()
app.processEvents()
image = QImage(1200, 1800, QImage.Format.Format_RGB32)
image.fill(0xFFFFFFFF)
canvas.set_image(image, [])
readable_scale = canvas.current_scale()
canvas.fit_exact()
exact_scale = canvas.current_scale()

assert DEFAULT_READABLE_ZOOM == 1.30
assert readable_scale >= exact_scale * 1.29
assert canvas.fit_zoom == 1.0
print("DRAWING_DEFAULT_READABILITY=PASS")
