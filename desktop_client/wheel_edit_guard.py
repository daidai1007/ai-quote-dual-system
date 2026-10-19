"""Keep wheel gestures for scrolling, never for changing form values."""

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication,
    QComboBox, QScrollBar, QWidget,
)


def _value_control(widget):
    """Include child line edits, but not a combo's open list or scrollbars."""
    while isinstance(widget, QWidget):
        if isinstance(widget, (QAbstractScrollArea, QScrollBar)):
            return None
        if isinstance(widget, (QAbstractSpinBox, QComboBox, QAbstractSlider)):
            return widget
        widget = widget.parentWidget()
    return None


class WheelEditGuard(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        control = _value_control(watched)
        if control is None:
            return False

        # An application filter runs before widget-specific filters and native
        # wheel handlers, including focused and double-click-armed editors.
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                    event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                    event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                    event.source(), event.pointingDevice(),
                )
                QApplication.sendEvent(viewport, forwarded)
                break
            parent = parent.parentWidget()
        # Consume the original exactly once so it cannot change the input or
        # be delivered a second time to an enclosing scroll area.
        event.accept()
        return True


def install_wheel_edit_guard():
    """Install once per application; newly created dialogs need no opt-in."""
    app = QApplication.instance()
    if app is None:
        return None
    guard = getattr(app, "_wheel_edit_guard", None)
    if guard is None:
        guard = WheelEditGuard(app)
        app._wheel_edit_guard = guard
        app.installEventFilter(guard)
    return guard
