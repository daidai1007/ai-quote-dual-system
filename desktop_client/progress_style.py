"""Shared progress colours for every page and dynamically created dialog."""

PROGRESS_COLORS = dict(fill='#97C459', track='#EEF0F3', text='#1F3A6A')


def progress_color_style(selector='QProgressBar'):
    # State is conveyed by text/actions, never by a different fill colour.
    return (
        f"{selector} {{ border:0; background:{PROGRESS_COLORS['track']}; color:{PROGRESS_COLORS['text']}; }}\n"
        f"{selector}::chunk {{ border:0; background:{PROGRESS_COLORS['fill']}; }}\n"
    )


def install_progress_style():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None and not app.property('uniformGreenProgressInstalled'):
        app.setStyleSheet(app.styleSheet() + '\n' + progress_color_style())
        app.setProperty('uniformGreenProgressInstalled', True)
