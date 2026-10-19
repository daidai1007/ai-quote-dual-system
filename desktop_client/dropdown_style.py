"""Application-wide combo popups matching the selection-page material list.

Only the open list is styled. Models, data, editors and signals stay intact.
"""
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPen
from PySide6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QCompleter, QLineEdit, QStyle, QStyledItemDelegate
from shiboken6 import isValid


POPUP_METRICS = {
    "row_height": 40, "text_inset": 14, "vertical_inset": 8,
    "font_px": 13, "radius": 6, "visible_rows": 8,
    "checkbox_size": 15, "checkbox_text_inset": 40, "icon_size": 16,
    "scrollbar_extent": 20, "scrollbar_handle": 40,
}
POPUP_COLORS = {
    "background": "#FFFFFF", "text": "#1C1C1E", "border": "#B8BEC7",
    "selected": "#E6F1FB", "selected_text": "#185FA5", "hover": "#F5F9FF",
    "disabled": "#8A8A86", "separator": "#D7DCE3", "primary": "#2563EB",
    "checkbox_border": "#98A2B3", "scroll_track": "#EEF0F3", "scroll_handle": "#A8B5C5",
    "scroll_hover": "#6E91BF",
}


def popup_style_sheet():
    c, m = POPUP_COLORS, POPUP_METRICS
    return f"""
QAbstractItemView {{ background:{c['background']}; color:{c['text']};
    border:1px solid {c['border']}; border-radius:{m['radius']}px;
    outline:0; padding:0; font-size:{m['font_px']}px;
    selection-background-color:{c['selected']}; selection-color:{c['selected_text']}; }}
QAbstractItemView::item {{ min-height:{m['row_height']}px; padding:0; border:0; }}
QScrollBar:vertical {{ background:{c['scroll_track']}; width:{m['scrollbar_extent']}px; margin:0; border:0; }}
QScrollBar:horizontal {{ background:{c['scroll_track']}; height:{m['scrollbar_extent']}px; margin:0; border:0; }}
QScrollBar::handle:vertical {{ background:{c['scroll_handle']}; min-height:{m['scrollbar_handle']}px; border-radius:{m['radius']}px; }}
QScrollBar::handle:horizontal {{ background:{c['scroll_handle']}; min-width:{m['scrollbar_handle']}px; border-radius:{m['radius']}px; }}
QScrollBar::handle:hover {{ background:{c['scroll_hover']}; }}
QScrollBar::handle:pressed {{ background:{c['primary']}; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:{c['scroll_track']}; }}
QAbstractScrollArea::corner {{ background:{c['scroll_track']}; border:0; }}
"""


class ComboPopupDelegate(QStyledItemDelegate):
    def __init__(self, combo, separator_index=-1, view=None):
        super().__init__(view if view is not None else combo.view())
        # The combo owns its popup/delegate. Do not keep the combo alive through
        # a Python cycle during repeated dialog/window destruction.
        self._combo_ref = weakref.ref(combo)
        self.separator_index = separator_index
        self.setObjectName("scheme2DropdownItemDelegate")

    @property
    def combo(self):
        return self._combo_ref()

    def sizeHint(self, option, index):
        metrics = QFontMetrics(option.font)
        inset = POPUP_METRICS['checkbox_text_inset'] if hasattr(self.combo, 'is_row_selected') else POPUP_METRICS['text_inset']
        width = metrics.horizontalAdvance(str(index.data(Qt.ItemDataRole.DisplayRole) or '')) + inset + POPUP_METRICS['text_inset']
        return QSize(max(120, width), max(POPUP_METRICS['row_height'], metrics.height() + 2 * POPUP_METRICS['vertical_inset']))

    @staticmethod
    def checkbox_rect(rect):
        size = POPUP_METRICS['checkbox_size']
        return QRect(rect.left() + POPUP_METRICS['text_inset'], rect.center().y() - size // 2, size, size)

    def paint(self, painter, option, index):
        c, m = POPUP_COLORS, POPUP_METRICS
        painter.save()
        rect = option.rect
        placeholder = self.combo.property('schemePlaceholderIndex')
        placeholder = int(placeholder) if placeholder is not None else -1
        if isinstance(self.combo, QCompleter):
            chosen = bool(option.state & QStyle.StateFlag.State_Selected)
        elif hasattr(self.combo, 'is_row_selected'):
            chosen = self.combo.is_row_selected(index.row())
        elif index.model() is not self.combo.model():
            chosen = str(index.data() or '') == self.combo.currentText()
        else:
            chosen = index.row() == self.combo.currentIndex() and index.row() != placeholder
        hovered = bool(option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected))
        painter.fillRect(rect, QColor(c['selected'] if chosen else c['hover'] if hovered else c['background']))
        if index.row() == self.separator_index:
            painter.setPen(QColor(c['separator']))
            painter.drawLine(rect.topLeft(), rect.topRight())
        shows_checkbox = hasattr(self.combo, 'is_row_selected') and index.row() > 0
        text_inset = m['checkbox_text_inset'] if shows_checkbox else m['text_inset']
        if shows_checkbox:
            check_rect = self.checkbox_rect(rect)
            painter.setPen(QPen(QColor(c['primary'] if chosen else c['checkbox_border']), 1))
            painter.setBrush(QColor(c['primary'] if chosen else c['background']))
            painter.drawRoundedRect(check_rect, 2, 2)
            if chosen:
                painter.setPen(QPen(QColor(c['background']), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                y = check_rect.center().y()
                painter.drawLine(QPoint(check_rect.left()+3,y), QPoint(check_rect.left()+6,y+3))
                painter.drawLine(QPoint(check_rect.left()+6,y+3), QPoint(check_rect.right()-2,y-4))
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull() and not shows_checkbox:
            size = m['icon_size']
            icon.paint(painter, QRect(rect.left()+text_inset, rect.center().y()-size//2, size, size))
            text_inset += size + m['vertical_inset']
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        painter.setPen(QColor(c['disabled'] if not enabled else c['selected_text'] if chosen or index.row() == self.separator_index else c['text']))
        painter.setFont(option.font)
        text_rect = rect.adjusted(text_inset, 0, -m['text_inset'], 0)
        text = QFontMetrics(option.font).elidedText(str(index.data() or ''), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


def style_popup(combo, view):
    """Style a combo or completer list without changing its model or editor."""
    if not isValid(combo) or not isValid(view) or getattr(combo, '_styling_combo_popup', False):
        return
    combo._styling_combo_popup = True
    try:
        if not view.objectName():
            view.setObjectName('unifiedComboDropdown')
        view.setProperty('unifiedComboPopup', True)
        view.setMouseTracking(True)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        style = popup_style_sheet()
        if view.styleSheet() != style:
            view.setStyleSheet(style)
        if not isinstance(view.itemDelegate(), ComboPopupDelegate) or view.itemDelegate().combo is not combo:
            delegate = ComboPopupDelegate(combo, view=view)
            view.setItemDelegate(delegate)
        is_completion = isinstance(combo, QCompleter)
        field = combo.widget() if is_completion else combo
        count = view.model().rowCount() if is_completion else combo.count()
        combo.setMaxVisibleItems(min(POPUP_METRICS['visible_rows'], max(1, count)))
        screen = field.screen() if field is not None else None
        available = screen.availableGeometry().width() if screen is not None else 1920
        # Keep the existing field geometry. Only the open list may grow to fit.
        font = QFontMetrics(view.font())
        texts = (str(view.model().index(i, combo.completionColumn()).data() or '') for i in range(count)) if is_completion else (combo.itemText(i) for i in range(count))
        content_width = max((font.horizontalAdvance(text) for text in texts), default=0)
        minimum = min(max(field.width() if field is not None else 0,
                          content_width + 2 * POPUP_METRICS['text_inset'] + POPUP_METRICS['scrollbar_extent']),
                      max(1, available - 2 * POPUP_METRICS['text_inset']))
        view.setMinimumWidth(minimum)
    finally:
        combo._styling_combo_popup = False


def style_combo(combo):
    style_popup(combo, combo.view())
    completer = combo.completer()
    if completer is not None and completer.completionMode() != QCompleter.CompletionMode.InlineCompletion:
        style_popup(completer, completer.popup())


class ComboPopupStyleFilter(QObject):
    def eventFilter(self, watched, event):
        # A combo can still be under construction when it is polished. Wait
        # until Show before asking Qt to create its lazily allocated popup.
        if event.type() != QEvent.Type.Show:
            return False
        if isinstance(watched, QComboBox):
            style_combo(watched)
        elif isinstance(watched, QLineEdit) and not isinstance(watched.parentWidget(), QComboBox):
            completer = watched.completer()
            if completer is not None and completer.completionMode() != QCompleter.CompletionMode.InlineCompletion:
                style_popup(completer, completer.popup())
        elif isinstance(watched, QAbstractItemView):
            parent = watched.parentWidget()
            while parent is not None:
                if isinstance(parent, QComboBox) and parent.view() is watched:
                    style_popup(parent, watched)
                    return False
                parent = parent.parentWidget()
            # This also covers completion popups whose window has no combo parent.
            for widget in QApplication.allWidgets():
                if not isinstance(widget, (QComboBox, QLineEdit)):
                    continue
                if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), QComboBox):
                    continue
                completer = widget.completer()
                if (completer is not None and completer.completionMode() != QCompleter.CompletionMode.InlineCompletion
                        and completer.popup() is watched):
                    style_popup(completer, watched)
                    break
        return False


def install_combo_popup_style():
    app = QApplication.instance()
    if app is None:
        return None
    guard = getattr(app, '_combo_popup_style_filter', None)
    if guard is None:
        guard = ComboPopupStyleFilter(app)
        app._combo_popup_style_filter = guard
        app.installEventFilter(guard)
        for widget in QApplication.allWidgets():
            if isinstance(widget, QComboBox) and widget.isVisible():
                style_combo(widget)
    return guard
