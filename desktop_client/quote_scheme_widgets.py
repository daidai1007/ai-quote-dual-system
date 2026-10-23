"""Scoped, reference-matched widgets for the quotation-scheme list.

No persistence, pricing or network operations belong in this module.
Metrics are logical pixels; Qt handles monitor DPI without bitmap scaling.
"""

from PySide6.QtCore import QDate, QEvent, QLocale, QPoint, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCalendarWidget, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QSpinBox, QTableWidget, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)
from ui_typography import AUXILIARY_PX, BODY_PX, FIELD_LABEL_PX, REGULAR_WEIGHT, TABLE_PX


PAGE_SIZES = (10, 20, 50, 100)
COLORS = {
    "background": "#FFFFFF", "text": "#27354B", "muted": "#8190A5",
    "primary": "#2563EB", "hover": "#1D4ED8", "border": "#DCE3ED",
    "grid": "#E7ECF3", "header": "#EEF3F8", "selection": "#E6F2FF",
}
METRICS = {
    "page_margin": 20, "section_gap": 16, "field_height": 40,
    "field_gap": 6, "filter_gap": 16, "action_gap": 10,
    "header_height": 48, "row_height": 60, "badge_height": 28,
    "badge_padding": 10, "badge_radius": 4, "page_button": 36,
    "full_actions_breakpoint": 1250, "footer_breakpoint": 1130,
}
FULL_COLUMN_WIDTHS = (166, 164, 206, 80, 112, 80, 98, 156, 228)
COMPACT_COLUMN_WIDTHS = (164, 124, 168, 74, 108, 76, 92, 150, 116)


# Approved compact action variant, based on the cost-page coefficient button.
# Apply locally so table links, document editing and unrelated pages keep their style.
LIGHT_ACTION = {
    'height': 28, 'font_size': 12, 'radius': 5, 'inset': 14, 'min_width': 64,
    'text': '#185FA5', 'background': '#E6F1FB', 'border': '#85B7EB',
    'hover': '#D9EBFC', 'hover_border': '#659FDC', 'pressed': '#CCE3F9',
    'disabled_text': '#98A8BA', 'disabled_background': '#F0F4F8',
    'disabled_border': '#D1DCE7', 'focus': '#2463BD',
}


def apply_light_action(control, equal_width_labels=()):
    """Keep the existing control, signals and name; change only its appearance."""
    c = LIGHT_ACTION
    kind = 'QComboBox' if isinstance(control, QComboBox) else 'QPushButton'
    control.setFixedHeight(c['height'])
    font = control.font(); font.setPixelSize(c['font_size']); control.setFont(font)
    label = control.currentText() if isinstance(control, QComboBox) else control.text()
    label_width = max(control.fontMetrics().horizontalAdvance(text) for text in (equal_width_labels or (label,)))
    control.setMinimumWidth(max(c['min_width'], label_width + 2*c['inset'] + 2))
    control.setStyleSheet(f"""
{kind} {{ color:{c['text']}; background:{c['background']}; border:1px solid {c['border']};
    border-radius:{c['radius']}px; padding:0 {c['inset']}px;
    min-height:{c['height']-2}px; max-height:{c['height']-2}px;
    font-size:{c['font_size']}px; font-weight:400; }}
{kind}:hover:enabled {{ background:{c['hover']}; border-color:{c['hover_border']}; }}
{kind}:pressed:enabled {{ background:{c['pressed']}; }}
{kind}:focus {{ border-color:{c['focus']}; }}
{kind}:disabled {{ color:{c['disabled_text']}; background:{c['disabled_background']};
    border-color:{c['disabled_border']}; }}
QComboBox {{ padding-right:28px; }}
QComboBox::drop-down {{ border:0; width:24px; }}
QComboBox::down-arrow {{ image:none; width:0; height:0; }}
""")
    return control


def light_purpose_style_sheet():
    c = LIGHT_ACTION
    return f"""color:{c['text']}; background:{c['background']};
border:1px solid {c['border']}; border-radius:{c['radius']}px;
padding:6px 10px; font-size:{c['font_size']}px;"""


def page_style_sheet():
    c, m = COLORS, METRICS
    return f"""
QWidget#quoteSchemeCenterPage {{ background:{c['background']}; color:{c['text']}; font-size:{BODY_PX}px; }}
QWidget#quoteSchemeCenterPage QLabel {{ color:{c['text']}; font-size:{BODY_PX}px; background:transparent; border:0; padding:0; }}
QWidget#quoteSchemeCenterPage QLabel#quoteSchemeServerNotice {{ color:{c['muted']}; font-size:{AUXILIARY_PX}px; }}
QWidget#quoteSchemeCenterPage QFrame#quoteSchemeFilters {{ background:#FFFFFF; border:1px solid {c['border']}; border-radius:4px; }}
QWidget#quoteSchemeCenterPage QLabel#quoteSchemeFieldLabel {{ font-size:{FIELD_LABEL_PX}px; font-weight:{REGULAR_WEIGHT}; }}
QWidget#quoteSchemeCenterPage QLineEdit,
QWidget#quoteSchemeCenterPage QComboBox,
QWidget#quoteSchemeCenterPage QSpinBox {{ color:{c['text']}; background:#FFFFFF; border:1px solid {c['border']}; border-radius:4px; padding:0 10px; min-height:38px; max-height:38px; font-size:{BODY_PX}px; selection-background-color:{c['selection']}; selection-color:{c['text']}; }}
QWidget#quoteSchemeCenterPage QLineEdit:focus,
QWidget#quoteSchemeCenterPage QComboBox:focus,
QWidget#quoteSchemeCenterPage QSpinBox:focus {{ border-color:{c['primary']}; }}
QWidget#quoteSchemeCenterPage QComboBox {{ padding-right:24px; }}
QWidget#quoteSchemeCenterPage QComboBox::drop-down {{ border:0; width:22px; }}
QWidget#quoteSchemeCenterPage QComboBox::down-arrow {{ image:none; width:0; height:0; }}
QWidget#quoteSchemeCenterPage QSpinBox::up-button,
QWidget#quoteSchemeCenterPage QSpinBox::down-button {{ width:0; border:0; }}
QWidget#quoteSchemeCenterPage QPushButton#scheme2PrimaryAction {{ color:#FFFFFF; background:{c['primary']}; border:1px solid {c['primary']}; border-radius:5px; padding:0 14px; min-height:38px; max-height:38px; font-size:{BODY_PX}px; font-weight:500; }}
QWidget#quoteSchemeCenterPage QPushButton#scheme2PrimaryAction:hover {{ background:{c['hover']}; border-color:{c['hover']}; }}
QWidget#quoteSchemeCenterPage QPushButton#scheme2PrimaryAction:disabled {{ color:#FFFFFF; background:#AEC5EC; border-color:#AEC5EC; }}
QWidget#quoteSchemeCenterPage QPushButton#scheme2PrimaryAction:focus {{ border:2px solid #123A9B; }}
QWidget#quoteSchemeCenterPage QTableWidget#quoteSchemeTable {{ color:{c['text']}; background:#FFFFFF; alternate-background-color:#FFFFFF; border:1px solid {c['border']}; border-radius:3px; gridline-color:{c['grid']}; font-size:{TABLE_PX}px; selection-background-color:{c['selection']}; selection-color:{c['text']}; }}
QWidget#quoteSchemeCenterPage QTableWidget#quoteSchemeTable::item {{ padding:0 12px; border:0; }}
QWidget#quoteSchemeCenterPage QTableWidget#quoteSchemeTable::item:selected {{ background:{c['selection']}; color:{c['text']}; }}
QWidget#quoteSchemeCenterPage QTableWidget#quoteSchemeTable QHeaderView::section {{ color:{c['text']}; background:{c['header']}; border:0; border-right:1px solid {c['border']}; border-bottom:1px solid {c['border']}; padding:0 12px; min-height:{m['header_height']}px; font-size:{TABLE_PX}px; font-weight:600; }}
QWidget#quoteSchemeCenterPage QWidget#quoteSchemeRowActions {{ background:transparent; border:0; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemeRowLink,
QWidget#quoteSchemeCenterPage QToolButton#quoteSchemeMore {{ color:{c['primary']}; background:transparent; border:0; border-radius:3px; padding:0 2px; min-height:30px; max-height:30px; font-size:{TABLE_PX}px; font-weight:400; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemeRowLink:hover,
QWidget#quoteSchemeCenterPage QToolButton#quoteSchemeMore:hover {{ background:#D8E9FF; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemeRowLink:focus,
QWidget#quoteSchemeCenterPage QToolButton#quoteSchemeMore:focus {{ border:1px solid {c['primary']}; }}
QWidget#quoteSchemeCenterPage QToolButton#quoteSchemeMore {{ padding-right:12px; }}
QWidget#quoteSchemeCenterPage QToolButton#quoteSchemeMore::menu-indicator {{ subcontrol-position:right center; width:10px; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemePageButton {{ color:{c['text']}; background:#FFFFFF; border:1px solid {c['border']}; border-radius:4px; padding:0; min-height:34px; max-height:34px; min-width:34px; max-width:34px; font-size:{TABLE_PX}px; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemePageButton:checked {{ color:#FFFFFF; background:{c['primary']}; border-color:{c['primary']}; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemePageButton:hover {{ border-color:{c['primary']}; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemePageButton:disabled {{ color:#B7C0CD; background:#FAFBFD; }}
QWidget#quoteSchemeCenterPage QComboBox#quoteSchemePageSize {{ min-height:34px; max-height:34px; }}
QWidget#quoteSchemeCenterPage QSpinBox#quoteSchemePageJump {{ min-height:34px; max-height:34px; padding:0 6px; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemeOperatorButton {{ color:#64748B; background:transparent; border:0; padding:0 4px; min-height:30px; max-height:30px; font-size:{AUXILIARY_PX}px; font-weight:400; text-align:left; }}
QWidget#quoteSchemeCenterPage QPushButton#quoteSchemeOperatorButton:hover {{ color:{c['primary']}; }}
QWidget#quoteSchemeCenterPage QLabel#quoteSchemePageStatus {{ color:#64748B; font-size:{TABLE_PX}px; padding:24px; }}
QWidget#quoteSchemeCenterPage QLabel#quoteSchemePageStatus[state="error"] {{ color:#B42318; }}
QWidget#quoteSchemeCenterPage QLabel#quoteSchemeOperationStatus {{ color:#B42318; font-size:{AUXILIARY_PX}px; }}
QMenu#quoteSchemeCalendarPopup {{ background:#FFFFFF; border:1px solid {c['border']}; padding:8px; }}
"""


class SchemePage(QWidget):
    resized = Signal()

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class QueryLineEdit(QLineEdit):
    def event(self, event):
        # The workbench has a global Return shortcut for adding quote lines.
        # Filter entry must own Return while it has keyboard focus.
        if event.type() == QEvent.Type.ShortcutOverride and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter,
        ):
            event.accept()
            return True
        return super().event(event)


class PageJump(QSpinBox):
    submitted = Signal()

    def __init__(self):
        super().__init__()
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter,
        ):
            event.accept()
            if event.type() == QEvent.Type.KeyPress:
                self.interpretText()
                self.submitted.emit()
            return True
        return super().eventFilter(watched, event)

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter,
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.interpretText()
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SchemeComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(COLORS['muted']), 1.4))
        x, y = self.width() - 15, self.height() / 2
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))
        painter.end()


class ServerNotice(QLabel):
    def __init__(self):
        super().__init__('数据保存于服务器')
        self.setContentsMargins(26, 0, 0, 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(0, (self.height() - 18) / 2)
        painter.setPen(QPen(QColor(COLORS['muted']), 1.3))
        path = QPainterPath(QPointF(5, 14))
        path.cubicTo(0, 14, 0, 7, 5, 7)
        path.cubicTo(5, 0, 14, 0, 15, 7)
        path.cubicTo(21, 7, 21, 14, 15, 14)
        path.lineTo(5, 14)
        painter.drawPath(path)
        painter.drawLine(10, 12, 10, 6)
        painter.drawLine(10, 6, 7, 9)
        painter.drawLine(10, 6, 13, 9)
        painter.end()


def filter_field(label, editor, name):
    host = QWidget()
    host.setObjectName(name)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(METRICS['field_gap'])
    caption = QLabel(label)
    caption.setObjectName('quoteSchemeFieldLabel')
    if isinstance(editor, QWidget):
        caption.setBuddy(editor)
        layout.addWidget(caption)
        layout.addWidget(editor)
    else:
        layout.addWidget(caption)
        layout.addLayout(editor)
    return host


def _calendar_icon():
    icon = QIcon()
    for ratio in (1, 2, 3, 4):
        pixmap = QPixmap(16 * ratio, 16 * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(COLORS['muted']), 1.3))
        painter.drawRoundedRect(QRectF(2, 3, 12, 11), 1, 1)
        painter.drawLine(2, 6, 14, 6)
        painter.drawLine(5, 1, 5, 4)
        painter.drawLine(11, 1, 11, 4)
        for x in (5, 8, 11):
            for y in (9, 12):
                painter.drawPoint(x, y)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class DateFilter(QueryLineEdit):
    """Optional ISO date input: blank stays blank; selecting a day is explicit."""

    def __init__(self, name, accessible_name):
        super().__init__()
        self.setObjectName(name)
        self.setPlaceholderText('请选择日期')
        self.setAccessibleName(accessible_name)
        self.setMinimumWidth(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        action = self.addAction(_calendar_icon(), QLineEdit.ActionPosition.TrailingPosition)
        action.setText('选择日期')
        self.calendar_popup = QMenu(self)
        self.calendar_popup.setObjectName('quoteSchemeCalendarPopup')
        self.calendar = QCalendarWidget()
        self.calendar.setLocale(QLocale('zh_CN'))
        self.calendar.setGridVisible(False)
        widget_action = QWidgetAction(self.calendar_popup)
        widget_action.setDefaultWidget(self.calendar)
        self.calendar_popup.addAction(widget_action)
        self.calendar.clicked.connect(self._selected)
        action.triggered.connect(self._show_calendar)

    def _show_calendar(self):
        parsed = QDate.fromString(self.text().strip(), 'yyyy-MM-dd')
        self.calendar.setSelectedDate(parsed if parsed.isValid() else QDate.currentDate())
        self.calendar_popup.popup(self.mapToGlobal(QPoint(0, self.height())))

    def _selected(self, selected):
        self.setText(selected.toString('yyyy-MM-dd'))
        self.calendar_popup.hide()


class StatusBadgeDelegate(QStyledItemDelegate):
    def __init__(self, labels, colors, parent):
        super().__init__(parent)
        self.labels, self.colors = labels, colors

    def paint(self, painter, option, index):
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ''
        style = base.widget.style() if base.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, base, painter, base.widget)
        code = str(index.data(Qt.ItemDataRole.UserRole) or '')
        label = self.labels.get(code, str(index.data() or '—'))
        background, foreground = self.colors.get(code, self.colors['DRAFT'])
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(base.font)
        width = painter.fontMetrics().horizontalAdvance(label) + 2 * METRICS['badge_padding']
        height = min(METRICS['badge_height'], option.rect.height() - 8)
        rect = QRectF(option.rect.center().x() - width / 2,
                      option.rect.center().y() - height / 2, width, height)
        painter.setPen(QPen(QColor(background).darker(112)))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, METRICS['badge_radius'], METRICS['badge_radius'])
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()


class SchemeTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 9)
        self.compact_actions = False
        self.state_label = None
        self.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.fit_columns)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns()

    def fit_columns(self):
        width = self.viewport().width()
        compact = width < METRICS['full_actions_breakpoint']
        columns = list(COMPACT_COLUMN_WIDTHS if compact else FULL_COLUMN_WIDTHS)
        columns[0] = max(columns[0], self.fontMetrics().horizontalAdvance('BJ-20261019-999999') + 32)
        extra = max(0, width - sum(columns))
        columns[1] += extra // 3
        columns[2] += extra - extra // 3
        for index, value in enumerate(columns):
            if self.columnWidth(index) != value:
                self.setColumnWidth(index, value)
        self.compact_actions = compact
        for row in range(self.rowCount()):
            actions = self.cellWidget(row, 8)
            if isinstance(actions, RowActions):
                actions.set_compact(compact)
        if self.state_label is not None:
            self.state_label.setGeometry(self.viewport().rect())
            self.state_label.raise_()


class RowActions(QWidget):
    """At most three direct actions, with the rest in one keyboard-usable menu."""

    def __init__(self, actions, primary_labels):
        super().__init__()
        self.setObjectName('quoteSchemeRowActions')
        self.actions = list(actions)
        self.primary_labels = set(primary_labels)
        self._compact = None
        self.buttons = {}
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(10, 0, 8, 0)
        self.row_layout.setSpacing(8)
        for label, callback in self.actions:
            if label in self.primary_labels:
                button = QPushButton(label)
                button.setFlat(True)
                button.setObjectName('quoteSchemeRowLink')
                button.clicked.connect(callback)
                self.row_layout.addWidget(button)
                self.buttons[label] = button
        self.more = QToolButton()
        self.more.setText('更多')
        self.more.setObjectName('quoteSchemeMore')
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setAccessibleName('更多方案操作')
        self.menu = QMenu(self.more)
        self.more.setMenu(self.menu)
        self.row_layout.addWidget(self.more)
        self.row_layout.addStretch(1)
        self.set_compact(False)

    def set_compact(self, compact):
        if self._compact is compact:
            return
        self._compact = compact
        self.menu.clear()
        for label, callback in self.actions:
            visible = label in self.buttons and (label == '打开' or not compact)
            if label in self.buttons:
                self.buttons[label].setVisible(visible)
            if not visible:
                self.menu.addAction(label, callback)
        self.more.setVisible(not self.menu.isEmpty())
