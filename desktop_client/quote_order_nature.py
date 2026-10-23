"""One classification for the current document and each immutable version."""
LABELS = {'INTERNAL': '内部', 'EXTERNAL': '外部', 'UNCLASSIFIED': '待分类'}


def normalize(value):
    return value if isinstance(value, str) and value in LABELS else 'UNCLASSIFIED'


def current(window):
    manager = getattr(window, 'quote_management', None)
    if manager is not None and manager.history_version is not None:
        versions = manager.state.get('versions') or []
        return normalize(versions[manager.history_version - 1].get('order_nature'))
    return normalize(getattr(window, '_quote_order_nature', None))


def label(window):
    return LABELS[current(window)]


def locked(window):
    manager = getattr(window, 'quote_management', None)
    return bool(getattr(window, '_quote_order_nature_locked', False) or
                (manager and any(v.get('sealed') and normalize(v.get('order_nature')) != 'UNCLASSIFIED'
                                for v in manager.state.get('versions', []))))


def require_selected(window):
    if current(window) == 'UNCLASSIFIED':
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(window, '请选择订单性质', '请在客户旁选择“内部”或“外部”，再打印或导出报价单。')
        return False
    return True
