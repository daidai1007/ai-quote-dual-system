"""One visual system for Qt message boxes, forms and workbench dialogs.

Presentation only: keep Qt's button identities, defaults, escape handling,
signals, validation and existing business layouts intact.
"""
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QBoxLayout, QDialog, QDialogButtonBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QStyle, QToolButton,
)
from dropdown_style import POPUP_COLORS


DIALOG_COLORS = {
    **POPUP_COLORS, "text": "#2A3541", "title": "#1F3A6A",
    "header": "#F6F7F9", "border": "#D7DCE3", "hover_primary": "#1D4ED8",
    "focus": "#7DB6FF",
}
DIALOG_METRICS = {
    "font_px": 12, "title_px": 13, "radius": 14, "button_radius": 6, "button_height": 28,
    "button_width": 60, "button_inset": 10, "spacing": 8,
    "content_inset": 18, "header_height": 40, "close_size": 28,
}
PRIMARY_NAMES = {
    "historyOrderPrimary", "scheme2DimensionConfirm", "scheme2PrimaryAction",
    "scheme2CustomAttachmentConfirm",
}
SECONDARY_NAMES = {
    "historyOrderSecondary", "scheme2ConfirmReject", "scheme2DimensionCancel",
    "scheme2DiscountCancel", "scheme2AttachmentCancel", "scheme2CustomAttachmentCancel",
}
STANDARD_BUTTON_TEXT = {
    QMessageBox.StandardButton.Ok: "确定", QMessageBox.StandardButton.Yes: "确定",
    QMessageBox.StandardButton.No: "取消", QMessageBox.StandardButton.Cancel: "取消",
    QMessageBox.StandardButton.Close: "关闭", QMessageBox.StandardButton.Save: "保存",
    QMessageBox.StandardButton.Discard: "不保存", QMessageBox.StandardButton.Retry: "重试",
    QMessageBox.StandardButton.Abort: "中止", QMessageBox.StandardButton.Ignore: "忽略",
}


def button_style(role):
    c, m = DIALOG_COLORS, DIALOG_METRICS
    # The approved workbench uses blue affirmative buttons throughout. Danger
    # remains an explicit semantic role; do not change its safe default or icon.
    color, hover = c["primary"], c["hover_primary"]
    filled = role in ("primary", "danger")
    return f"""
QPushButton {{ font-family:"Microsoft YaHei UI","Microsoft YaHei";
    font-size:{m['font_px']}px; font-weight:500;
    min-height:{m['button_height']-2}px; max-height:{m['button_height']-2}px;
    min-width:{m['button_width']-2*m['button_inset']-2}px; padding:0 {m['button_inset']}px;
    border-radius:{m['button_radius']}px;
    color:{c['background'] if filled else c['text']};
    background:{color if filled else c['background']};
    border:1px solid {color if filled else c['border']}; }}
QPushButton:hover {{ background:{hover if filled else c['hover']}; }}
QPushButton:pressed {{ background:{hover if filled else c['selected']}; }}
QPushButton:focus {{ border:1px solid {c['focus']}; }}
QPushButton:disabled {{ color:{c['disabled']}; background:{c['scroll_track']}; border-color:{c['border']}; }}
"""


def dialog_style_sheet():
    c, m = DIALOG_COLORS, DIALOG_METRICS
    return f"""
QDialog[unifiedDialog="true"] {{ background:{c['background']}; color:{c['text']};
    font-family:"Microsoft YaHei UI","Microsoft YaHei"; font-size:{m['font_px']}px; }}
QDialog[unifiedDialog="true"][dialogOverlay="true"] {{ background:transparent; }}
QDialog[unifiedDialog="true"][dialogOverlay="false"] {{ border:1px solid {c['border']}; border-radius:{m['radius']}px; }}
QDialog[unifiedDialog="true"] QLabel {{ font-size:{m['font_px']}px; }}
QDialog[unifiedDialog="true"] QLineEdit,
QDialog[unifiedDialog="true"] QComboBox,
QDialog[unifiedDialog="true"] QSpinBox,
QDialog[unifiedDialog="true"] QDoubleSpinBox {{ font-size:{m['font_px']}px; }}
QDialog[unifiedDialog="true"] QPushButton {{ font-size:{m['font_px']}px; }}
QDialog#unifiedMessageDialog {{ border:1px solid {c['border']}; border-radius:{m['radius']}px; }}
QDialog#unifiedMessageDialog QLabel#qt_msgbox_label {{ font-size:{m['font_px']}px; padding:8px 0; }}
"""


class _DialogHeader(QFrame):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)


def _add_header(dialog):
    """Add chrome without replacing Qt's message/button/detail machinery."""
    if getattr(dialog, "_unified_dialog_header", None) is not None:
        return
    layout = dialog.layout()
    if not isinstance(layout, (QGridLayout, QBoxLayout)):
        return
    c, m = DIALOG_COLORS, DIALOG_METRICS
    header = _DialogHeader(dialog)
    header.setObjectName("unifiedDialogHeader")
    row = QHBoxLayout(header)
    row.setContentsMargins(m['content_inset'], 0, 6, 0)
    title = QLabel(dialog.windowTitle(), header)
    title.setObjectName("unifiedDialogTitle")
    title.setTextFormat(Qt.TextFormat.PlainText)
    dialog.windowTitleChanged.connect(title.setText)
    close = QToolButton(header)
    close.setObjectName("unifiedDialogClose")
    close.setText("×")
    close.setAccessibleName("关闭弹窗")
    close.setToolTip("关闭")
    close.setFixedSize(m['close_size'], m['close_size'])
    close.clicked.connect(dialog.close)
    row.addWidget(title, 1)
    row.addWidget(close)
    header.setMinimumHeight(m['header_height'])
    if isinstance(layout, QGridLayout):
        # Save positions before removing items: removal changes item indices.
        entries = [(layout.itemAt(i), layout.getItemPosition(i)) for i in range(layout.count())]
        columns = max(1, layout.columnCount())
        for _ in entries:
            layout.takeAt(0)
        for item, (r, col, rs, cs) in entries:
            layout.addItem(item, r + 1, col, rs, cs)
        layout.addWidget(header, 0, 0, 1, columns)
    else:
        layout.insertWidget(0, header)
    dialog._unified_dialog_header = header
    _style_chrome(header, "header")
    _style_chrome(title, "title")
    _style_chrome(close, "close")


def _style_chrome(widget, role):
    c, m = DIALOG_COLORS, DIALOG_METRICS
    rules = {
        "shell": f"background:{c['background']}; border:1px solid {c['border']}; border-radius:{m['radius']}px;",
        "header": f"background:{c['header']}; border:0; border-bottom:1px solid {c['border']}; min-height:{m['header_height']}px;",
        "title": f"background:transparent; border:0; color:{c['title']}; font-size:{m['title_px']}px; font-weight:600;",
        "close": f"background:transparent; border:0; color:{c['disabled']}; font-size:18px; padding:0;",
    }
    # QLabel also inherits QFrame. An unscoped QFrame rule here would draw
    # borders around every descendant label and erase the blue price preview.
    widget.setStyleSheet(f"QWidget#{widget.objectName()} {{ {rules[role]} }}")


def style_dialog(dialog):
    if getattr(dialog, "_styling_unified_dialog", False) or dialog.layout() is None:
        return
    dialog._styling_unified_dialog = True
    try:
        overlay = bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        first = not dialog.property("unifiedDialog")
        dialog.setProperty("unifiedDialog", True)
        if first:
            dialog.setProperty("dialogOverlay", overlay)
            if isinstance(dialog, QMessageBox):
                dialog.setObjectName("unifiedMessageDialog")
            dialog.setStyleSheet(dialog.styleSheet() + dialog_style_sheet())
        if isinstance(dialog, QMessageBox):
            if first:
                dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
                layout = dialog.layout()
                inset = DIALOG_METRICS['content_inset']
                layout.setContentsMargins(inset, 0, inset, inset)
                layout.setHorizontalSpacing(DIALOG_METRICS['spacing'])
                layout.setVerticalSpacing(DIALOG_METRICS['spacing'])
            _add_header(dialog)
            label = dialog.findChild(QLabel, "qt_msgbox_label")
            if label is not None:
                label.setWordWrap(True)
        elif not overlay:
            # File and input dialogs use the same Qt chrome, not an unstyleable
            # native window. Keep their original fields, modes and return values.
            dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            _add_header(dialog)
        for widget in dialog.findChildren(QFrame):
            if widget.window() is not dialog:
                continue
            name = widget.objectName()
            if name.endswith("Shell") or name == "historyOrderCard":
                _style_chrome(widget, "shell")
            elif name.endswith(("TitleBar", "Header")):
                _style_chrome(widget, "header")
        for widget in dialog.findChildren(QLabel):
            if widget.window() is dialog and widget.objectName().endswith("Title"):
                _style_chrome(widget, "title")
            elif widget.window() is dialog and widget.objectName() in ('scheme2ConfirmWarningIcon', 'historyOrderInfoIcon'):
                icon = (QStyle.StandardPixmap.SP_MessageBoxWarning if widget.objectName() == 'scheme2ConfirmWarningIcon'
                        else QStyle.StandardPixmap.SP_MessageBoxInformation)
                widget.setPixmap(dialog.style().standardIcon(icon).pixmap(28, 28))
        for widget in dialog.findChildren(QAbstractButton):
            if widget.window() is not dialog:
                continue
            name = widget.objectName()
            if name.endswith("Close"):
                _style_chrome(widget, "close")
        for box in dialog.findChildren(QDialogButtonBox):
            if box.window() is not dialog:
                continue
            for button in box.buttons():
                if isinstance(dialog, QMessageBox):
                    standard = dialog.standardButton(button)
                    if standard in STANDARD_BUTTON_TEXT:
                        button.setText(STANDARD_BUTTON_TEXT[standard])
                role = box.buttonRole(button)
                style = "secondary"
                if role in (QDialogButtonBox.ButtonRole.AcceptRole, QDialogButtonBox.ButtonRole.YesRole):
                    style = "primary"
                    if any(word in dialog.windowTitle() for word in ("作废", "删除", "清空", "放弃")):
                        style = "danger"
                elif role == QDialogButtonBox.ButtonRole.DestructiveRole:
                    style = "danger"
                button.setProperty("dialogActionRole", style)
                button.setStyleSheet(button_style(style))
            box.layout().setSpacing(DIALOG_METRICS['spacing'])
        for button in dialog.findChildren(QPushButton):
            if button.window() is not dialog:
                continue
            name = button.objectName()
            role = ("danger" if name == "scheme2ConfirmDanger" else
                    "primary" if name in PRIMARY_NAMES else
                    "secondary" if name in SECONDARY_NAMES else None)
            if role is not None:
                button.setProperty("dialogActionRole", role)
                button.setStyleSheet(button_style(role))
    finally:
        dialog._styling_unified_dialog = False


class DialogStyleFilter(QObject):
    def eventFilter(self, watched, event):
        # QFileDialog can polish a temporary QDialog wrapper while its C++
        # constructor is still building/replacing its layout. Wait for Show.
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
            visible = watched.isVisible()
            style_dialog(watched)
            if visible and not watched.isVisible():
                # Changing native chrome hides an already showing QWidget.
                # Queue one owned timer; deletion cancels the pending re-show.
                timer = QTimer(watched)
                timer.setSingleShot(True)
                timer.timeout.connect(watched.show)
                timer.timeout.connect(timer.deleteLater)
                timer.start(0)
        return False


def install_dialog_style():
    app = QApplication.instance()
    if app is None:
        return None
    guard = getattr(app, "_unified_dialog_style_filter", None)
    if guard is None:
        # Must be set before QFileDialog creates its platform helper. Static
        # QMessageBox calls from the recovered core are also covered by Qt.
        app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
        guard = DialogStyleFilter(app)
        app._unified_dialog_style_filter = guard
        app.installEventFilter(guard)
    return guard
