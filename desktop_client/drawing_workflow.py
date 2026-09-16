"""V3 drawing/quote presentation state. Existing API and quote math are untouched."""
from pathlib import Path
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFrame, QHeaderView, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QSizePolicy, QStackedWidget, QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from freight_state import FreightState, billable_weight, money
from quote_drawing_preview import QuoteDrawingPreview, normalized_path, resolve_document

# Keep the recovered core's route IDs: 0 recognition, 1 quote, 2 notes, 3 list.
# Navigation order is independent of route IDs, so internal callers stay valid.
CABINET_SUMMARY_ROUTE = 4


class CabinetSummaryTable(QTableWidget):
    """Whole-row drag table that delegates data order to the shared model."""

    row_move_requested = Signal(int, int)

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self._drag_source_row = -1

    def startDrag(self, supported_actions):
        self._drag_source_row = self.currentRow()
        if self._drag_source_row < 0:
            return
        indexes = self.selectedIndexes()
        if not indexes:
            self._drag_source_row = -1
            return
        # QAbstractItemView.startDrag removes the source items after an
        # accepted MoveAction. The shared drawing list is already reordered
        # and the table is rebuilt in dropEvent, so that default cleanup would
        # clear a row from the freshly rebuilt table. Run QDrag directly and
        # leave all data movement to reorder_cabinets exactly once.
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(indexes))
        try:
            drag.exec(Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
        finally:
            self._drag_source_row = -1

    def dropEvent(self, event):
        source = self._drag_source_row
        self._drag_source_row = -1
        if source < 0 or source >= self.rowCount():
            event.ignore()
            return
        point = event.position().toPoint()
        index = self.indexAt(point)
        insert_at = self.rowCount()
        if index.isValid():
            insert_at = index.row()
            rect = self.visualRect(self.model().index(insert_at, 0))
            if point.y() > rect.center().y():
                insert_at += 1
        if insert_at > source:
            insert_at -= 1
        insert_at = max(0, min(insert_at, self.rowCount() - 1))
        if insert_at == source:
            event.acceptProposedAction()
            return
        self.row_move_requested.emit(source, insert_at)
        event.acceptProposedAction()


def drawing_key(item):
    if not isinstance(item, dict):
        return None
    return (str(item.get('candidate_id') or id(item)),
            normalized_path(item.get('source_path') or item.get('path')))


def sync_drawing(window):
    item = window._quote_drawing
    source, preview = resolve_document(item, window.recognized_documents)
    window.quote_drawing_preview.set_document(drawing_key(item), source, preview)


def show_preview(window):
    if not hasattr(window, 'quote_right_stack'):
        return
    sync_drawing(window)
    window.quote_right_stack.setCurrentIndex(0)
    window.quote_drawing_preview.canvas.finish_stroke()


def show_quote_result(window):
    if not hasattr(window, 'quote_right_stack'):
        return
    window.quote_drawing_preview.canvas.finish_stroke()
    window.quote_right_stack.setCurrentIndex(1)
    window.statusBar().showMessage('当前显示：双报价结果和历史价格', 3000)


def install_result_drawing_button(window, result_panel):
    """Add the drawing route without squeezing long calculation status text."""
    button = QPushButton('返回当前柜体图纸', result_panel)
    button.setObjectName('compactToolButton')
    button.setAccessibleName('返回当前柜体图纸')
    button.setToolTip('切换到当前柜体图纸，不重新计算或清空报价结果')
    button.setMinimumHeight(32)
    button.clicked.connect(lambda: show_preview(window))

    result_layout = result_panel.layout()
    header_layout = None
    if result_layout is not None and result_layout.count():
        header_layout = result_layout.itemAt(0).layout()
    if isinstance(header_layout, QHBoxLayout):
        # Keep the action beside the title. The recovered header originally
        # put its variable-length state badge in this same narrow row, which
        # clips failure details after adding the action. Give the state its own
        # full-width, wrapping row immediately below the header.
        header_layout.insertWidget(1, button, 0, Qt.AlignmentFlag.AlignTop)
        state = result_panel.findChild(QLabel, 'quoteResultState')
        if state is not None:
            header_layout.removeWidget(state)
            state.setWordWrap(True)
            state.setMinimumWidth(0)
            state.setMaximumWidth(16777215)
            state.setMinimumHeight(34)
            state.setMaximumHeight(16777215)
            state.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            state.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            result_layout.insertWidget(1, state)
            window.quote_result_state = state
    elif result_layout is not None:
        result_layout.insertWidget(0, button, 0, Qt.AlignmentFlag.AlignRight)
    window.return_to_drawing_button = button


def set_freight_value(window):
    with QSignalBlocker(window.freight_spin):
        window.freight_spin.setValue(float(window.freight_state.value))
    update_freight_mode(window)
    refresh_freight_amounts(window)


def refresh_freight_amounts(window):
    """Present the same input used by both existing total calculators."""
    text = f'{money(window.freight_spin.value()):.2f} 元'
    for name in ('formula_labels', 'quick_labels'):
        label = getattr(window, name, {}).get('freight')
        if label is not None:
            label.setText(text)


def update_freight_mode(window):
    automatic = window.freight_state.mode == 'AUTO'
    window.freight_label.setText('运费 · 自动' if automatic else '运费 · 人工')
    window.freight_auto_button.setVisible(not automatic)
    window.freight_spin.setToolTip(
        '填写每台柜体或每套并柜的运费；最终运费＝运费×柜型数量，且不参与折扣。\n'
        '自动运费＝服务最终计价材料重量×1元/kg；尚未取得重量时为0.00元。'
    )


def cabinet_quantity(item):
    """Read a positive whole-cabinet quantity from the shared drawing state."""
    if not isinstance(item, dict):
        return 1
    for key in ('quantity', 'cabinet_quantity', 'recognized_quantity', 'order_quantity'):
        try:
            value = int(float(item.get(key)))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 1


def sync_current_cabinet_quantity(window, value):
    item = getattr(window, '_quote_drawing', None)
    if not isinstance(item, dict):
        return
    quantity = max(1, int(value))
    if item.get('quantity') == quantity:
        return
    item['quantity'] = quantity
    refresh_cabinets(window)


def refresh_cabinets(window):
    if not hasattr(window, 'cabinet_summary_table'):
        return
    table = window.cabinet_summary_table
    selected = table.currentRow()
    selected_key = None
    if selected >= 0 and table.item(selected, 0) is not None:
        selected_key = table.item(selected, 0).data(Qt.ItemDataRole.UserRole)
    table.setRowCount(len(window.recognized_drawings))
    for row, item in enumerate(window.recognized_drawings):
        ready = window._drawing_ready(item)
        source = item.get('source_document_name') or Path(item.get('source_path') or item.get('path') or '').name
        values = (str(row + 1), item.get('name') or '未命名柜体', item.get('specification') or '待核验',
                  cabinet_quantity(item), source, '可报价' if ready else '待核验')
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))
        # Store only a stable key; resolve against the canonical recognition list.
        table.item(row, 0).setData(Qt.ItemDataRole.UserRole, drawing_key(item))
    selected_after = next((
        row for row in range(table.rowCount())
        if table.item(row, 0) is not None
        and table.item(row, 0).data(Qt.ItemDataRole.UserRole) == selected_key
    ), None)
    if selected_after is not None:
        table.selectRow(selected_after)
    elif 0 <= selected < table.rowCount():
        table.selectRow(selected)
    window.cabinet_summary_empty.setVisible(table.rowCount() == 0)


def open_cabinet(window, for_quote):
    row = window.cabinet_summary_table.currentRow()
    if row < 0:
        return
    key = window.cabinet_summary_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
    index = next((i for i, item in enumerate(window.recognized_drawings) if drawing_key(item) == key), None)
    if index is None:
        refresh_cabinets(window)
        return
    window.drawing_list.selectRow(index)
    window.select_drawing_row(index)
    if for_quote and window._drawing_ready(window.active_drawing):
        window.use_selected_drawing()
    else:
        window.show_section(0)


def reorder_cabinets(window, source_row: int, target_row: int):
    drawings = getattr(window, 'recognized_drawings', None)
    if not isinstance(drawings, list) or not (0 <= source_row < len(drawings)):
        return
    target_row = max(0, min(int(target_row), len(drawings) - 1))
    if source_row == target_row:
        return
    moved = drawings.pop(source_row)
    drawings.insert(target_row, moved)
    refresh_recognition = getattr(window, '_refresh_document_list', None)
    if callable(refresh_recognition):
        refresh_recognition()
    refresh_cabinets(window)
    window.cabinet_summary_table.selectRow(target_row)
    window.statusBar().showMessage(
        f'柜体顺序已调整：{target_row + 1}. {moved.get("name") or "未命名柜体"}',
        3500,
    )


def build_summary(window):
    page = QWidget()
    page.setObjectName('cabinetSummaryPage')
    box = QVBoxLayout(page)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(12)
    header = QFrame()
    header.setObjectName('commandBar')
    heading = QVBoxLayout(header)
    title = QLabel('柜体汇总')
    title.setObjectName('workbenchTitle')
    heading.addWidget(title)
    subtitle = QLabel('核对识别柜体；按住任意柜体行上下拖动可调整顺序')
    subtitle.setObjectName('workbenchSubtitle')
    heading.addWidget(subtitle)
    box.addWidget(header)
    panel = QFrame()
    panel.setObjectName('quoteResultsPanel')
    body = QVBoxLayout(panel)
    empty = QLabel('暂无识别柜体，请先返回图纸识别导入图纸。')
    empty.setWordWrap(True)
    body.addWidget(empty)
    table = CabinetSummaryTable(0, 6)
    table.setObjectName('cabinetSummaryTable')
    table.setHorizontalHeaderLabels(('序号', '柜体名称', '规格型号（W*D*H）', '数量', '来源图纸', '状态'))
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setDragEnabled(True)
    table.setAcceptDrops(True)
    table.viewport().setAcceptDrops(True)
    table.setDropIndicatorShown(True)
    table.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
    table.setDragDropOverwriteMode(False)
    table.setDefaultDropAction(Qt.DropAction.MoveAction)
    table.setAutoScroll(True)
    table.setToolTip('按住任意柜体行上下拖动，松开后保存当前会话中的柜体顺序')
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    table.setMinimumHeight(300)
    body.addWidget(table, 1)
    row = QHBoxLayout()
    for text, callback in (
        ('返回图纸识别', lambda: window.show_section(0)),
        ('核验选中柜体', lambda: open_cabinet(window, False)),
        ('进入报价计算', lambda: open_cabinet(window, True)),
    ):
        button = QPushButton(text)
        button.setObjectName('primaryAction' if text == '进入报价计算' else 'outlineAction')
        button.clicked.connect(callback)
        row.addWidget(button)
    body.addLayout(row)
    box.addWidget(panel, 1)
    window.cabinet_summary_table, window.cabinet_summary_empty = table, empty
    table.row_move_requested.connect(lambda source, target: reorder_cabinets(window, source, target))
    table.cellDoubleClicked.connect(lambda *_: open_cabinet(window, True))
    window.stack.addWidget(page)
    nav = window.nav_buttons[0].parentWidget()
    button = QPushButton('柜体汇总', nav)
    button.setObjectName('navButton')
    button.setCheckable(True)
    reference = window.nav_buttons[1]
    button.setFont(reference.font())
    button.setIcon(window.fluent_icon('\ue80f', QStyle.StandardPixmap.SP_DirIcon,
                                     color='#3A3A3C', checked_color='#FFFFFF'))
    button.setIconSize(reference.iconSize())
    button.setMinimumHeight(reference.minimumHeight())
    button.clicked.connect(lambda: window.show_section(CABINET_SUMMARY_ROUTE))
    nav.layout().insertWidget(nav.layout().indexOf(reference), button)
    routes = list(window.nav_routes)
    routes.insert(1, (CABINET_SUMMARY_ROUTE, '柜体汇总', '\ue80f', QStyle.StandardPixmap.SP_DirIcon))
    window.nav_routes = tuple(routes)
    window.nav_buttons.insert(1, button)
    refresh_cabinets(window)


def install_drawing_workflow(namespace):
    cls = namespace['MainWindow']
    if getattr(cls, '_drawing_workflow_installed', False):
        return
    cls._drawing_workflow_installed = True
    original_init = cls.__init__

    def init(window, *args, **kwargs):
        window._quote_drawing = None
        window._drawing_generation = 0
        window._draft_drawing_refs = {}
        window._freight_restoring = False
        window.freight_state = FreightState()
        original_init(window, *args, **kwargs)
        window._drawing_ready = namespace['drawing_candidate_ready_for_quote']
        build_summary(window)
        workspace = window.stack.widget(1).findChild(QSplitter, 'quoteWorkspace')
        result_panel = workspace.widget(1)
        window.quote_right_stack = QStackedWidget()
        window.quote_right_stack.setObjectName('quoteDrawingResultStack')
        window.quote_right_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        workspace.replaceWidget(1, window.quote_right_stack)
        install_result_drawing_button(window, result_panel)
        preview = QuoteDrawingPreview(window.drawing_preview._pdftoppm_path,
                                      namespace['DrawingRecognitionTools']._convert_dwg_to_dxf)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview.return_to_recognition.connect(lambda: window.show_section(0))
        preview.return_to_quote_result.connect(lambda: show_quote_result(window))
        window.quote_drawing_preview = preview
        window.quote_right_stack.addWidget(preview)
        window.quote_right_stack.addWidget(result_panel)
        window.freight_auto_button = QPushButton('按重量重新计算')
        window.freight_auto_button.setObjectName('compactToolButton')
        window.freight_field_block.layout().addWidget(window.freight_auto_button)

        def manual(value):
            if not window._freight_restoring:
                window.freight_state.manual(value)
                update_freight_mode(window)
                refresh_freight_amounts(window)

        def automatic():
            window.freight_state.automatic()
            set_freight_value(window)
            # Freight is a client line charge; repricing it never calls the API.
            if window.current_result:
                window.current_result['input_signature'] = window.quote_input_signature()
            window.refresh_discounted_totals()

        window.freight_spin.valueChanged.connect(manual)
        # textEdited captures deliberate entry of the current value as MANUAL too.
        window.freight_spin.lineEdit().textEdited.connect(lambda *_: manual(window.freight_spin.value()))
        window.freight_auto_button.clicked.connect(automatic)
        window.quantity_spin.valueChanged.connect(
            lambda value: sync_current_cabinet_quantity(window, value)
        )
        set_freight_value(window)
        show_preview(window)

    cls.__init__ = init

    original_refresh_totals = cls.refresh_discounted_totals

    def refresh_totals(window):
        result = original_refresh_totals(window)
        if hasattr(window, 'freight_spin'):
            refresh_freight_amounts(window)
        return result

    cls.refresh_discounted_totals = refresh_totals
    original_section = cls.show_section

    def section(window, index):
        if hasattr(window, 'quote_right_stack'):
            if index == 1:
                window.active_drawing = window._quote_drawing
                sync_drawing(window)
            elif index == CABINET_SUMMARY_ROUTE:
                refresh_cabinets(window)
        result = original_section(window, index)
        if index == CABINET_SUMMARY_ROUTE:
            window.statusBar().showMessage('当前模块：柜体汇总')
        return result

    cls.show_section = section
    original_use = cls.use_selected_drawing

    def use(window):
        item = window.active_drawing
        if not namespace['drawing_candidate_ready_for_quote'](item or {}):
            return original_use(window)
        if drawing_key(item) == drawing_key(window._quote_drawing):
            window.show_section(1)
            show_preview(window)
            return
        window._quote_drawing = item
        window._drawing_generation += 1
        window.freight_state.reset()
        if hasattr(window, 'freight_auto_button'):
            set_freight_value(window)
        window.clear_quote_result()
        result = original_use(window)
        window.quantity_spin.setValue(cabinet_quantity(item))
        show_preview(window)
        return result

    cls.use_selected_drawing = use
    original_apply = cls._apply_confirmed_drawing_to_quote

    def apply(window, item):
        if drawing_key(item) != drawing_key(window._quote_drawing):
            window._drawing_generation += 1
            window.freight_state.reset()
        window._quote_drawing = item
        result = original_apply(window, item)
        window.quantity_spin.setValue(cabinet_quantity(item))
        show_preview(window)
        return result

    cls._apply_confirmed_drawing_to_quote = apply
    original_signature = cls.quote_input_signature

    def signature(window):
        return tuple(original_signature(window)) + (('drawing_session', window._drawing_generation),)

    cls.quote_input_signature = signature
    original_show = cls.show_result

    def show_result(window, payload, *args, **kwargs):
        previous = window.current_result
        result = original_show(window, payload, *args, **kwargs)
        current = window.current_result
        if current is not None and current is not previous:
            window.freight_state.update_weight(billable_weight(payload))
            if hasattr(window, 'quote_right_stack'):
                set_freight_value(window)
                current['input_signature'] = window.quote_input_signature()
                window.refresh_discounted_totals()
                window.quote_drawing_preview.canvas.finish_stroke()
                window.quote_right_stack.setCurrentIndex(1)
        else:
            show_preview(window)
        return result

    cls.show_result = show_result
    original_calculate = cls.calculate

    def calculate(window):
        if getattr(window, 'quote_calculation_in_progress', False):
            return original_calculate(window)
        # The result panel owns the calculation progress and error state.
        # Reveal it as soon as the operator clicks the primary action; a
        # failed request is still routed back to the drawing by error().
        show_quote_result(window)
        return original_calculate(window)

    cls.calculate = calculate
    original_error = cls.show_error

    def error(window, message):
        show_preview(window)
        if hasattr(window, 'quote_drawing_preview'):
            window.quote_drawing_preview.message.setText(str(message))
        return original_error(window, message)

    cls.show_error = error
    original_clear = cls.clear_quote_result

    def clear(window, *args, **kwargs):
        result = original_clear(window, *args, **kwargs)
        if not window._freight_restoring:
            window.freight_state.update_weight(None)
            if hasattr(window, 'freight_auto_button'):
                set_freight_value(window)
        show_preview(window)
        return result

    cls.clear_quote_result = clear
    original_reset = cls.reset_current_cabinet

    def reset(window, *args, **kwargs):
        window._drawing_generation += 1
        window._quote_drawing = None
        window._freight_restoring = True
        try:
            result = original_reset(window, *args, **kwargs)
        finally:
            window._freight_restoring = False
        window.freight_state.reset()
        if hasattr(window, 'freight_auto_button'):
            set_freight_value(window)
        show_preview(window)
        return result

    cls.reset_current_cabinet = reset
    original_add = cls.add_current_to_summary

    def add(window, *args, **kwargs):
        count, drawing = len(window.draft_items), window._quote_drawing
        freight = FreightState(window.freight_state.mode, window.freight_state.weight, window.freight_state.value)
        result = original_add(window, *args, **kwargs)
        if len(window.draft_items) > count:
            window._draft_drawing_refs[id(window.draft_items[-1])] = (drawing, freight)
        return result

    cls.add_current_to_summary = add
    original_load = cls.load_draft_item

    def load(window, item):
        drawing, freight = window._draft_drawing_refs.get(id(item), (None, None))
        if drawing is None:
            drawing = next((d for d in window.recognized_drawings if d.get('candidate_id')
                            and d.get('candidate_id') == item.get('source_candidate_id')), None)
        window._quote_drawing = drawing
        window._drawing_generation += 1
        window._freight_restoring = True
        try:
            result = original_load(window, item)
        finally:
            window._freight_restoring = False
        window.active_drawing = drawing
        if freight:
            window.freight_state = FreightState(freight.mode, freight.weight, freight.value)
        else:
            window.freight_state = FreightState()
            if 'freight_fee' in item or 'freight' in item:
                window.freight_state.manual(item.get('freight_fee', item.get('freight', 0)))
        set_freight_value(window)
        show_preview(window)
        return result

    cls.load_draft_item = load
    original_review = cls.complete_inline_review

    def review(window):
        result = original_review(window)
        refresh_cabinets(window)
        return result

    cls.complete_inline_review = review
    original_close = cls.closeEvent

    def close(window, event):
        preview = getattr(window, 'quote_drawing_preview', None)
        if preview and preview._workers:
            for worker in tuple(preview._workers):
                worker.requestInterruption()
            window.statusBar().showMessage('正在结束图纸预览，请稍后关闭。')
            event.ignore()
            return
        return original_close(window, event)

    cls.closeEvent = close
