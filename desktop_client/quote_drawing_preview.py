"""Read-only drawing renderer and document-coordinate session ink for Qt."""
from collections import OrderedDict
from math import ceil, hypot
from pathlib import Path
import subprocess
import tempfile

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
)
from pypdf import PdfReader

# Load the complete renderer before the recovered core installs its partial
# archive importer. Recognition continues to use the same ezdxf parser.
try:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
except ImportError:
    ezdxf = None

RENDER_EDGE = 3600
PDF_RENDER_STEP = 1200
PDF_MAX_RENDER_EDGE = 9600
PDF_DETAIL_DELAY_MS = 180
FIT_RENDER_OVERSAMPLE = 2.25
PDF_ZOOM_OVERSAMPLE = 1.75
CACHE_PIXEL_BUDGET = 80_000_000
VECTOR_DETAIL_SUFFIXES = {'.pdf', '.dxf', '.dwg'}
TOOL_HEIGHT = 34
SPACE = 8
COLORS = (('红色', '#d32f2f'), ('蓝色', '#1769aa'), ('黑色', '#20272e'), ('绿色', '#258450'))
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


def normalized_path(path):
    return str(Path(path).resolve()).casefold() if path else ''


def resolve_document(candidate, documents):
    """Follow explicit source/preview references only; never guess by filename."""
    if not candidate:
        return '', ''
    source = str(candidate.get('source_path') or candidate.get('path') or '')
    # PDF is already the vector-quality source.  Generated recognition previews
    # are often raster thumbnails and become visibly softer than WPS when zoomed.
    if source and Path(source).is_file() and Path(source).suffix.lower() == '.pdf':
        return source, source
    records = [candidate] + [d for d in documents if isinstance(d, dict) and source
                           and normalized_path(d.get('source_path') or d.get('path')) == normalized_path(source)]
    for record in records:
        for key in ('preview_path', 'converted_pdf_path', 'preview_pdf_path', 'preview_image_path'):
            preview = str(record.get(key) or '')
            if preview and Path(preview).is_file() and Path(preview).suffix.lower() in IMAGE_SUFFIXES | {'.pdf'}:
                return source, preview
    return source, source


class RenderWorker(QThread):
    rendered = Signal(int, object, int, str, int)
    failed = Signal(int, str)

    def __init__(self, serial, path, page, render_edge, pdftoppm, convert_dwg, parent):
        super().__init__(parent)
        self.serial, self.path, self.page = serial, path, page
        self.render_edge = render_edge
        self.pdftoppm, self.convert_dwg = pdftoppm, convert_dwg

    def run(self):
        try:
            path = Path(self.path)
            if not path.is_file():
                raise ValueError('源图纸不可用，请返回图纸识别检查文件。')
            count, kind = 1, '图片'
            with tempfile.TemporaryDirectory(prefix='quote-view-') as folder:
                if path.suffix.lower() == '.pdf':
                    count = len(PdfReader(str(path)).pages)
                    if not count or self.page >= count:
                        raise ValueError('PDF 页码不可用。')
                    if not self.pdftoppm or not Path(self.pdftoppm).is_file():
                        raise ValueError('缺少 PDF 预览组件，请修复客户端安装。')
                    prefix = str(Path(folder) / 'page')
                    run = subprocess.run([self.pdftoppm, '-f', str(self.page + 1), '-l', str(self.page + 1),
                                          '-singlefile', '-aa', 'yes', '-aaVector', 'yes',
                                          '-scale-to', str(self.render_edge), '-png', str(path), prefix],
                                         capture_output=True, timeout=60,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if run.returncode:
                        raise ValueError('PDF 渲染失败，请检查文件是否损坏或加密。')
                    image, kind = QImage(prefix + '.png'), 'PDF'
                elif path.suffix.lower() in {'.dxf', '.dwg'}:
                    if ezdxf is None:
                        raise ValueError('缺少 CAD 预览组件，请修复客户端安装。')
                    if path.suffix.lower() == '.dwg':
                        if not self.convert_dwg:
                            raise ValueError('未找到 DWG 转换组件，暂时无法预览。')
                        path = Path(self.convert_dwg(path, Path(folder)))
                    doc = ezdxf.readfile(str(path))
                    backend = svg.SVGBackend()
                    config = Configuration(background_policy=BackgroundPolicy.WHITE,
                                           color_policy=ColorPolicy.BLACK)
                    Frontend(RenderContext(doc), backend, config=config).draw_layout(doc.modelspace(), finalize=True)
                    content = backend.get_string(layout.Page(0, 0)).encode('utf-8')
                    renderer = QSvgRenderer(content)
                    if not renderer.isValid() or renderer.viewBoxF().isEmpty():
                        raise ValueError('CAD 模型空间没有可预览的图元。')
                    size = renderer.viewBoxF().size().toSize()
                    size.scale(QSize(self.render_edge, self.render_edge), Qt.AspectRatioMode.KeepAspectRatio)
                    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.white)
                    painter = QPainter(image)
                    painter.setRenderHints(
                        QPainter.RenderHint.Antialiasing
                        | QPainter.RenderHint.TextAntialiasing
                        | QPainter.RenderHint.SmoothPixmapTransform
                    )
                    renderer.render(painter)
                    painter.end()
                    kind = 'CAD 模型空间'
                elif path.suffix.lower() in IMAGE_SUFFIXES:
                    reader = QImageReader(str(path))
                    reader.setAutoTransform(True)
                    size = reader.size()
                    if max(size.width(), size.height()) > self.render_edge:
                        size.scale(QSize(self.render_edge, self.render_edge), Qt.AspectRatioMode.KeepAspectRatio)
                        reader.setScaledSize(size)
                    image = reader.read()
                else:
                    raise ValueError('当前格式没有可用的图纸预览。')
                if image.isNull():
                    raise ValueError('图纸读取失败，请检查源文件。')
                if not self.isInterruptionRequested():
                    self.rendered.emit(self.serial, image, count, kind, self.render_edge)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(self.serial, str(error))


class InkCanvas(QGraphicsView):
    changed = Signal()
    zoomed = Signal(float)
    selection_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setObjectName('drawingCanvas')
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(0, 200)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self.viewport().installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.ink_enabled = False
        self.select_enabled = False
        self.color, self.stroke_width = COLORS[0][1], 3
        self.strokes, self._items = [], []
        self._points, self._path_item = None, None
        self.selected_indices = set()
        self._selection_origin = self._selection_current = None
        self._selection_rect_item = self._selection_outline_item = None
        self._moving_selection = False
        self._move_origin = None
        self._move_before = {}
        self._history = []
        self._input_device = None
        self._touch_position = None
        self.fit_mode = True
        self.rotation_degrees = 0
        self.set_ink(False)

    def set_ink(self, enabled):
        self.set_tool('ink' if enabled else 'pan')

    def set_select(self, enabled):
        self.set_tool('select' if enabled else 'pan')

    def set_tool(self, mode):
        self.finish_stroke()
        self._finish_selection()
        self.ink_enabled = mode == 'ink'
        self.select_enabled = mode == 'select'
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag
            if mode in {'ink', 'select'} else QGraphicsView.DragMode.ScrollHandDrag
        )
        cursor = Qt.CursorShape.CrossCursor if mode in {'ink', 'select'} else Qt.CursorShape.OpenHandCursor
        self.viewport().setCursor(cursor)
        if mode != 'select':
            self.clear_selection()

    def set_image(self, image, strokes, rotation=0, logical_size=None, preserve_view=False):
        self.finish_stroke()
        self.clear_selection(remove_items=False)
        previous_transform = QTransform(self.transform())
        previous_scroll = (self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        previous_fit_mode = self.fit_mode
        self.scene().clear()
        self._items = []
        self.strokes = strokes
        self._history = []
        logical_width, logical_height = logical_size or (image.width(), image.height())
        pixmap_item = self.scene().addPixmap(QPixmap.fromImage(image))
        pixmap_item.setTransform(QTransform.fromScale(
            logical_width / image.width(), logical_height / image.height()))
        self.scene().setSceneRect(QRectF(0, 0, logical_width, logical_height))
        for stroke in strokes:
            self._items.append(self._draw(stroke))
        self.rotation_degrees = rotation % 360
        if preserve_view:
            self.setTransform(previous_transform)
            self.horizontalScrollBar().setValue(previous_scroll[0])
            self.verticalScrollBar().setValue(previous_scroll[1])
            self.fit_mode = previous_fit_mode
        else:
            self.resetTransform()
            self.rotate(self.rotation_degrees)
            self.fit()

    def current_scale(self):
        transform = self.transform()
        return hypot(transform.m11(), transform.m12())

    def set_rotation(self, degrees):
        self.finish_stroke()
        if self.scene().sceneRect().isEmpty():
            return
        self.rotation_degrees = degrees % 360
        self.resetTransform()
        self.rotate(self.rotation_degrees)
        self.fit()

    def _draw(self, stroke):
        path = self._stroke_path(stroke)
        item = self.scene().addPath(path, self._stroke_pen(stroke))
        item.setZValue(1)
        return item

    @staticmethod
    def _stroke_path(stroke):
        path = QPainterPath(QPointF(*stroke['points'][0]))
        for point in stroke['points'][1:]:
            path.lineTo(QPointF(*point))
        if len(stroke['points']) == 1:
            path.lineTo(path.currentPosition() + QPointF(.01, .01))
        return path

    @staticmethod
    def _stroke_pen(stroke):
        return QPen(QColor(stroke['color']), stroke['width'], Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def _refresh_item(self, index):
        if 0 <= index < len(self.strokes) and index < len(self._items):
            stroke = self.strokes[index]
            self._items[index].setPath(self._stroke_path(stroke))
            self._items[index].setPen(self._stroke_pen(stroke))

    def begin_stroke(self, position):
        point = self.mapToScene(position.toPoint())
        if not self.scene().sceneRect().contains(point) or not self.scene().items():
            return
        self._points = [(point.x(), point.y())]
        # Width is fixed in document coordinates once the stroke begins.
        self._stroke = {'color': self.color, 'width': self.stroke_width / self.current_scale(), 'points': self._points}
        self._path_item = self._draw(self._stroke)

    def move_stroke(self, position):
        if self._points is None:
            return
        point = self.mapToScene(position.toPoint())
        rect = self.scene().sceneRect()
        point.setX(min(rect.right(), max(rect.left(), point.x())))
        point.setY(min(rect.bottom(), max(rect.top(), point.y())))
        self._points.append((point.x(), point.y()))
        path = self._path_item.path()
        path.lineTo(point)
        self._path_item.setPath(path)

    def finish_stroke(self):
        if self._points is not None:
            self.strokes.append(self._stroke)
            self._items.append(self._path_item)
            self._history.append(('add', self._stroke))
            self._points, self._path_item = None, None
            self.changed.emit()

    def undo(self):
        self.finish_stroke()
        self.clear_selection()
        action = self._history.pop() if self._history else None
        if action and action[0] == 'add':
            stroke = action[1]
            index = next(
                (position for position, candidate in enumerate(self.strokes)
                 if candidate is stroke),
                None,
            )
            if index is not None:
                self.strokes.pop(index)
                self.scene().removeItem(self._items.pop(index))
        elif action and action[0] == 'move':
            for index, points in action[1].items():
                if 0 <= index < len(self.strokes):
                    self.strokes[index]['points'] = [tuple(point) for point in points]
                    self._refresh_item(index)
        elif action and action[0] == 'style':
            for index, color, width in action[1]:
                if 0 <= index < len(self.strokes):
                    self.strokes[index]['color'] = color
                    self.strokes[index]['width'] = width
                    self._refresh_item(index)
        elif action and action[0] == 'delete':
            for index, stroke in action[1]:
                self.strokes.insert(index, stroke)
                self._items.insert(index, self._draw(stroke))
        elif self.strokes:
            self.strokes.pop()
            self.scene().removeItem(self._items.pop())
        else:
            return
        self.changed.emit()

    def clear_ink(self):
        self.finish_stroke()
        self.clear_selection()
        self.strokes.clear()
        for item in self._items:
            self.scene().removeItem(item)
        self._items.clear()
        self._history.clear()
        self.changed.emit()

    def clear_selection(self, remove_items=True):
        had_selection = bool(self.selected_indices)
        if remove_items:
            for item in (self._selection_rect_item, self._selection_outline_item):
                if item is not None and item.scene() is self.scene():
                    self.scene().removeItem(item)
        self.selected_indices.clear()
        self._selection_origin = self._selection_current = None
        self._selection_rect_item = self._selection_outline_item = None
        self._moving_selection = False
        self._move_origin = None
        self._move_before = {}
        if had_selection:
            self.selection_changed.emit(False)

    def _selection_bounds(self):
        bounds = QRectF()
        for index in sorted(self.selected_indices):
            if 0 <= index < len(self._items):
                rect = self._items[index].sceneBoundingRect()
                bounds = rect if bounds.isNull() else bounds.united(rect)
        return bounds

    def _show_selection_outline(self):
        if self._selection_outline_item is not None and self._selection_outline_item.scene() is self.scene():
            self.scene().removeItem(self._selection_outline_item)
        bounds = self._selection_bounds()
        if bounds.isNull():
            self._selection_outline_item = None
            return
        pen = QPen(QColor('#1677c8'), 1 / max(self.current_scale(), .001), Qt.PenStyle.DashLine)
        self._selection_outline_item = self.scene().addRect(bounds.adjusted(-2, -2, 2, 2), pen)
        self._selection_outline_item.setZValue(3)

    def _begin_selection(self, position):
        point = self.mapToScene(position.toPoint())
        bounds = self._selection_bounds()
        if self.selected_indices and bounds.adjusted(-4, -4, 4, 4).contains(point):
            self._moving_selection = True
            self._move_origin = point
            self._move_before = {
                index: [tuple(value) for value in self.strokes[index]['points']]
                for index in self.selected_indices
                if 0 <= index < len(self.strokes)
            }
            return
        self.clear_selection()
        self._selection_origin = self._selection_current = point
        pen = QPen(QColor('#1677c8'), 1 / max(self.current_scale(), .001), Qt.PenStyle.DashLine)
        self._selection_rect_item = self.scene().addRect(QRectF(point, point), pen)
        self._selection_rect_item.setZValue(3)

    def _move_selection(self, position):
        point = self.mapToScene(position.toPoint())
        if self._moving_selection and self._move_origin is not None:
            delta = point - self._move_origin
            original_bounds = QRectF()
            for index, points in self._move_before.items():
                stroke_bounds = self._stroke_path({**self.strokes[index], 'points': points}).boundingRect()
                original_bounds = stroke_bounds if original_bounds.isNull() else original_bounds.united(stroke_bounds)
            scene_rect = self.scene().sceneRect()
            dx = min(scene_rect.right() - original_bounds.right(), max(scene_rect.left() - original_bounds.left(), delta.x()))
            dy = min(scene_rect.bottom() - original_bounds.bottom(), max(scene_rect.top() - original_bounds.top(), delta.y()))
            for index, points in self._move_before.items():
                self.strokes[index]['points'] = [(x + dx, y + dy) for x, y in points]
                self._refresh_item(index)
            self._show_selection_outline()
            return
        if self._selection_origin is None:
            return
        self._selection_current = point
        rect = QRectF(self._selection_origin, point).normalized()
        if self._selection_rect_item is not None:
            self._selection_rect_item.setRect(rect)

    def _finish_selection(self):
        if self._moving_selection:
            changed = any(
                index < len(self.strokes) and self.strokes[index]['points'] != points
                for index, points in self._move_before.items()
            )
            if changed:
                self._history.append(('move', self._move_before))
                self.changed.emit()
            self._moving_selection = False
            self._move_origin = None
            self._move_before = {}
            self._show_selection_outline()
            return
        if self._selection_origin is None:
            return
        rect = QRectF(self._selection_origin, self._selection_current).normalized()
        if self._selection_rect_item is not None and self._selection_rect_item.scene() is self.scene():
            self.scene().removeItem(self._selection_rect_item)
        self._selection_rect_item = None
        self.selected_indices = {
            index for index, item in enumerate(self._items)
            if rect.intersects(item.sceneBoundingRect())
        }
        self._selection_origin = self._selection_current = None
        self._show_selection_outline()
        self.selection_changed.emit(bool(self.selected_indices))

    def delete_selected(self):
        self.finish_stroke()
        if not self.selected_indices:
            return
        snapshots = [(index, self.strokes[index]) for index in sorted(self.selected_indices)]
        for index in sorted(self.selected_indices, reverse=True):
            self.strokes.pop(index)
            self.scene().removeItem(self._items.pop(index))
        self._history.append(('delete', snapshots))
        self.clear_selection()
        self.changed.emit()

    def apply_selection_style(self, color=None, screen_width=None):
        if not self.selected_indices:
            return
        before = []
        width = None if screen_width is None else screen_width / max(self.current_scale(), .001)
        for index in sorted(self.selected_indices):
            if not 0 <= index < len(self.strokes):
                continue
            stroke = self.strokes[index]
            before.append((index, stroke['color'], stroke['width']))
            if color is not None:
                stroke['color'] = color
            if width is not None:
                stroke['width'] = width
            self._refresh_item(index)
        if before:
            self._history.append(('style', before))
            self._show_selection_outline()
            self.changed.emit()

    def fit(self):
        self.fit_mode = True
        if not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoomed.emit(self.current_scale())

    def actual_size(self):
        if self.scene().sceneRect().isEmpty():
            return
        self.fit_mode = False
        self.resetTransform()
        self.rotate(self.rotation_degrees)
        physical_pixel_scale = 1 / max(self.viewport().devicePixelRatioF(), 1.0)
        self.scale(physical_pixel_scale, physical_pixel_scale)
        self.zoomed.emit(self.current_scale())

    def zoom(self, factor):
        scale = self.current_scale() * factor
        if .02 <= scale <= 16:
            self.fit_mode = False
            self.scale(factor, factor)
            self.zoomed.emit(scale)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit()

    def wheelEvent(self, event):
        delta = event.pixelDelta().y() or event.angleDelta().y()
        if delta:
            self.zoom(pow(1.0015, delta))
        event.accept()

    def mousePressEvent(self, event):
        if self.ink_enabled and event.button() == Qt.MouseButton.LeftButton:
            if self._input_device is None:
                self.begin_stroke(event.position())
            event.accept()
        elif self.select_enabled and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._begin_selection(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.ink_enabled:
            if self._input_device is None:
                self.move_stroke(event.position())
            event.accept()
        elif self.select_enabled:
            self._move_selection(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.ink_enabled:
            if self._input_device is None:
                self.finish_stroke()
            event.accept()
        elif self.select_enabled:
            self._finish_selection()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_indices:
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        kind = event.type()
        if (kind in (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease)
                and (self.ink_enabled or self.select_enabled)):
            if kind == QEvent.Type.TabletPress:
                self._input_device = 'pen'
                (self.begin_stroke if self.ink_enabled else self._begin_selection)(event.position())
            elif kind == QEvent.Type.TabletMove:
                (self.move_stroke if self.ink_enabled else self._move_selection)(event.position())
            else:
                (self.finish_stroke if self.ink_enabled else self._finish_selection)()
                self._input_device = None
            event.accept()
            return True
        if kind in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            if self._input_device == 'pen':
                event.accept()
                return True
            points = event.points()
            if kind == QEvent.Type.TouchBegin and points:
                self._input_device = 'touch'
                self._touch_position = points[0].position()
                if self.ink_enabled:
                    self.begin_stroke(self._touch_position)
                elif self.select_enabled:
                    self._begin_selection(self._touch_position)
            elif kind == QEvent.Type.TouchUpdate and points:
                position = points[0].position()
                if self.ink_enabled:
                    self.move_stroke(position)
                elif self.select_enabled:
                    self._move_selection(position)
                elif self._touch_position is not None:
                    delta = position - self._touch_position
                    self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
                    self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
                self._touch_position = position
            else:
                (self.finish_stroke if self.ink_enabled else self._finish_selection)()
                self._input_device, self._touch_position = None, None
            event.accept()
            return True
        return super().eventFilter(watched, event)


class QuoteDrawingPreview(QFrame):
    return_to_recognition = Signal()
    return_to_quote_result = Signal()

    def __init__(self, pdftoppm, convert_dwg, parent=None):
        super().__init__(parent)
        self.setObjectName('quoteResultsPanel')
        self.setMinimumWidth(0)
        self.pdftoppm, self.convert_dwg = pdftoppm, convert_dwg
        self.annotations, self.pages, self.rotations = {}, {}, {}
        self.render_edges, self.logical_sizes = {}, {}
        self.cache = OrderedDict()
        self._workers, self._render_context, self.serial = set(), {}, 0
        self.document_key, self.path, self.source = None, '', ''
        self.page, self.page_count = 0, 0
        self.current_render_edge, self.current_kind = RENDER_EDGE, ''
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(SPACE)
        title = QLabel('当前柜体图纸')
        title.setObjectName('cardTitle')
        box.addWidget(title)
        self.filename = QLabel('尚未关联图纸')
        self.filename.setObjectName('cardSubtitle')
        self.filename.setWordWrap(True)
        box.addWidget(self.filename)
        row = QHBoxLayout()
        self.previous = self.button('上一页', lambda: self.set_page(self.page - 1), row)
        self.counter = QLabel('0 / 0')
        row.addWidget(self.counter)
        self.next = self.button('下一页', lambda: self.set_page(self.page + 1), row)
        row.addStretch()
        self.rotate_left_button = self.button('左转', lambda: self.rotate_page(-90), row)
        self.rotate_left_button.setAccessibleName('图纸向左旋转90度')
        self.rotate_right_button = self.button('右转', lambda: self.rotate_page(90), row)
        self.rotate_right_button.setAccessibleName('图纸向右旋转90度')
        self.button('−', lambda: self.canvas.zoom(1 / 1.2), row).setAccessibleName('缩小图纸')
        self.button('+', lambda: self.canvas.zoom(1.2), row).setAccessibleName('放大图纸')
        self.button('1:1', lambda: self.canvas.actual_size(), row).setAccessibleName('图纸原始像素大小')
        self.button('适应窗口', lambda: self.canvas.fit(), row)
        box.addLayout(row)
        ink = QHBoxLayout()
        self.pen_button = self.button('手写笔', self.toggle_pen, ink)
        self.pen_button.setCheckable(True)
        self.select_button = self.button('框选', self.toggle_select, ink)
        self.select_button.setCheckable(True)
        self.select_button.setAccessibleName('框选编辑笔迹')
        self.color_combo = QComboBox()
        for name, value in COLORS:
            self.color_combo.addItem(name, value)
        self.color_combo.setAccessibleName('笔迹颜色')
        ink.addWidget(self.color_combo)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 16)
        self.width_spin.setValue(3)
        self.width_spin.setSuffix(' px')
        self.width_spin.setAccessibleName('笔画粗细')
        ink.addWidget(self.width_spin)
        self.undo_button = self.button('撤销', lambda: self.canvas.undo(), ink)
        self.delete_selection_button = self.button(
            '删除选中', lambda: self.canvas.delete_selected(), ink
        )
        self.clear_button = self.button('清除', lambda: self.canvas.clear_ink(), ink)
        ink.addStretch()
        box.addLayout(ink)
        self.canvas = InkCanvas(self)
        box.addWidget(self.canvas, 1)
        self.message = QLabel('暂无图纸，请返回图纸识别选择当前柜体。')
        self.message.setWordWrap(True)
        box.addWidget(self.message)
        bottom = QHBoxLayout()
        self.back = self.button('返回图纸识别', self.return_to_recognition.emit, bottom)
        self.back_to_quote = self.button(
            '返回报价计算', self.return_to_quote_result.emit, bottom
        )
        self.back_to_quote.setAccessibleName('返回双报价结果')
        self.back_to_quote.setToolTip('切换到双报价结果和历史价格，不重新计算')
        bottom.addStretch()
        box.addLayout(bottom)
        self.color_combo.currentIndexChanged.connect(self.change_color)
        self.width_spin.valueChanged.connect(self.change_width)
        self.canvas.changed.connect(self.update_tools)
        self.canvas.selection_changed.connect(self.update_tools)
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(PDF_DETAIL_DELAY_MS)
        self._detail_timer.timeout.connect(self.load_pdf_detail)
        self.canvas.zoomed.connect(lambda *_: self.schedule_pdf_detail())
        self.update_tools()

    @staticmethod
    def button(text, callback, row):
        button = QPushButton(text)
        button.setObjectName('compactToolButton')
        button.setMinimumHeight(TOOL_HEIGHT)
        button.clicked.connect(callback)
        row.addWidget(button)
        return button

    def toggle_pen(self):
        checked = self.pen_button.isChecked()
        if checked:
            self.select_button.blockSignals(True)
            self.select_button.setChecked(False)
            self.select_button.blockSignals(False)
            self.select_button.setText('框选')
        self.canvas.set_ink(checked)
        self.pen_button.setText('关闭手写' if checked else '手写笔')
        self.update_tools()

    def toggle_select(self):
        checked = self.select_button.isChecked()
        if checked:
            self.pen_button.blockSignals(True)
            self.pen_button.setChecked(False)
            self.pen_button.blockSignals(False)
            self.pen_button.setText('手写笔')
        self.canvas.set_select(checked)
        self.select_button.setText('关闭框选' if checked else '框选')
        self.update_tools()

    def change_color(self):
        color = self.color_combo.currentData()
        self.canvas.color = color
        if self.canvas.select_enabled:
            self.canvas.apply_selection_style(color=color)

    def change_width(self, width):
        self.canvas.stroke_width = width
        if self.canvas.select_enabled:
            self.canvas.apply_selection_style(screen_width=width)

    def rotate_page(self, degrees):
        if not self.canvas.isEnabled() or not self.document_key:
            return
        self.canvas.finish_stroke()
        key = (self.document_key, self.page)
        rotation = (self.rotations.get(key, 0) + degrees) % 360
        self.rotations[key] = rotation
        self.canvas.set_rotation(rotation)

    def update_tools(self):
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(self.page + 1 < self.page_count)
        drawing_ready = self.canvas.isEnabled() and self.page_count > 0
        self.rotate_left_button.setEnabled(drawing_ready)
        self.rotate_right_button.setEnabled(drawing_ready)
        self.pen_button.setEnabled(drawing_ready)
        self.select_button.setEnabled(drawing_ready)
        self.counter.setText(f'{self.page + 1} / {self.page_count}' if self.page_count else '0 / 0')
        self.undo_button.setEnabled(bool(self.canvas.strokes))
        self.delete_selection_button.setEnabled(bool(self.canvas.selected_indices))
        self.clear_button.setEnabled(bool(self.canvas.strokes))

    def set_document(self, key, source, path):
        identity = (key, normalized_path(source), normalized_path(path))
        if identity == self.document_key:
            return
        self.canvas.finish_stroke()
        self.document_key, self.source, self.path = identity, source, path
        self.page = self.pages.get(identity, 0)
        self.page_count = 0
        self.current_render_edge, self.current_kind = RENDER_EDGE, ''
        self.filename.setText(Path(source).name if source else '尚未关联图纸')
        self.load_page()

    def set_page(self, page):
        if 0 <= page < self.page_count and page != self.page:
            self.canvas.finish_stroke()
            self.page = page
            self.pages[self.document_key] = page
            self.load_page()

    def schedule_pdf_detail(self):
        if (self.canvas.isEnabled() and self.path
                and Path(self.path).suffix.lower() in VECTOR_DETAIL_SUFFIXES
                and not self.canvas.fit_mode):
            self._detail_timer.start()

    def load_pdf_detail(self):
        if (not self.canvas.isEnabled() or not self.path
                or Path(self.path).suffix.lower() not in VECTOR_DETAIL_SUFFIXES):
            return
        logical_edge = max(self.canvas.scene().sceneRect().width(),
                           self.canvas.scene().sceneRect().height())
        required = int(ceil(logical_edge * self.canvas.current_scale()
                            * self.canvas.viewport().devicePixelRatioF() * PDF_ZOOM_OVERSAMPLE))
        target = max(RENDER_EDGE, int(ceil(required / PDF_RENDER_STEP) * PDF_RENDER_STEP))
        target = min(PDF_MAX_RENDER_EDGE, target)
        if target > self.current_render_edge:
            self.load_page(target, preserve_view=True)

    def load_page(self, render_edge=None, preserve_view=False):
        self.serial += 1
        self.canvas.finish_stroke()
        page_key = (self.document_key, self.page)
        viewport = self.canvas.viewport()
        fit_required = int(ceil(
            max(viewport.width(), viewport.height())
            * viewport.devicePixelRatioF()
            * FIT_RENDER_OVERSAMPLE
        ))
        fit_edge = int(ceil(fit_required / PDF_RENDER_STEP) * PDF_RENDER_STEP)
        fit_edge = min(PDF_MAX_RENDER_EDGE, max(RENDER_EDGE, fit_edge))
        target_edge = int(render_edge or max(self.render_edges.get(page_key, RENDER_EDGE), fit_edge))
        target_edge = min(PDF_MAX_RENDER_EDGE, max(RENDER_EDGE, target_edge))
        self._render_context[self.serial] = (target_edge, preserve_view)
        if not preserve_view:
            self.canvas.scene().clear()
            self.canvas.strokes, self.canvas._items = [], []
            self.canvas.setEnabled(False)
            self.update_tools()
        if not self.path:
            self.message.setText('暂无图纸，请返回图纸识别选择当前柜体。')
            return
        if not preserve_view:
            self.message.setText('正在加载图纸…')
        key = (normalized_path(self.path), self.page, target_edge)
        if key in self.cache:
            self.ready(self.serial, *self.cache[key])
            return
        worker = RenderWorker(self.serial, self.path, self.page, target_edge,
                              self.pdftoppm, self.convert_dwg, self)
        self._workers.add(worker)
        worker.rendered.connect(self.ready)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda: (
            self._workers.discard(worker),
            self._render_context.pop(worker.serial, None),
            worker.deleteLater(),
        ))
        worker.start()

    def ready(self, serial, image, count, kind, render_edge):
        if serial != self.serial:
            return
        _, preserve_view = self._render_context.pop(serial, (render_edge, False))
        normalized = normalized_path(self.path)
        for old_key in tuple(self.cache):
            if old_key[:2] == (normalized, self.page) and old_key[2] != render_edge:
                self.cache.pop(old_key)
        key = (normalized, self.page, render_edge)
        self.cache[key] = (image, count, kind, render_edge)
        self.cache.move_to_end(key)
        while (len(self.cache) > 8
               or sum(value[0].width() * value[0].height()
                      for value in self.cache.values()) > CACHE_PIXEL_BUDGET):
            if len(self.cache) == 1:
                break
            self.cache.popitem(last=False)
        self.page_count = count
        page_key = (self.document_key, self.page)
        logical_size = self.logical_sizes.setdefault(page_key, (image.width(), image.height()))
        self.render_edges[page_key] = render_edge
        self.current_render_edge, self.current_kind = render_edge, kind
        strokes = self.annotations.setdefault(page_key, [])
        self.canvas.set_image(image, strokes, self.rotations.get(page_key, 0),
                              logical_size, preserve_view=preserve_view)
        self.canvas.setEnabled(True)
        detail = '，放大后自动提高清晰度' if Path(self.path).suffix.lower() in VECTOR_DETAIL_SUFFIXES else ''
        self.message.setText(
            f'{kind} · 支持左右旋转和滚轮缩放{detail}；框选笔迹后可移动、改颜色/粗细或删除；'
            '关闭手写和框选后拖动平移；标注仅保留在本次会话。'
        )
        self.update_tools()

    def failed(self, serial, message):
        if serial == self.serial:
            _, preserve_view = self._render_context.pop(serial, (RENDER_EDGE, False))
            if not preserve_view:
                self.page_count = 0
                self.message.setText(message)
            else:
                self.message.setText(f'高清重渲染失败，继续使用当前预览：{message}')
            self.update_tools()
