"""Presentation and interaction refinements for the V3 desktop workbench.

The recovered V3 core continues to own recognition, quote calculation,
database access, BOM data and workbook export.  This overlay changes layout,
visual hierarchy, accessible copy and state-gated navigation only.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QDoubleSpinBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QWidget,
)


WIDGET_MAX = 16_777_215

# Cold-rolled sheet metal, drawing ink and inspection marks.  Keep the palette
# compact so every state color has one stable meaning throughout the client.
STEEL_CANVAS = "#F4F6F8"
PAPER = "#FFFFFF"
GRAPHITE = "#20252B"
GRAPHITE_RAISED = "#2B3238"
STEEL_LINE = "#D5DBE2"
MUTED_INK = "#66727E"
BLUEPRINT = "#1769AA"
BLUEPRINT_PALE = "#EAF3FA"
INSPECTION_GREEN = "#2F855A"
INSPECTION_PALE = "#E8F5EE"
WARNING_AMBER = "#C98113"
WARNING_PALE = "#FFF5DF"


def _find(root: QWidget, widget_type, object_name: str):
    return root.findChild(widget_type, object_name)


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _money_formatter(namespace: dict):
    money = namespace.get("money")
    if callable(money):
        return money

    def fallback(value):
        if value is None:
            return "—"
        try:
            return f"{float(value):,.2f}"
        except Exception:
            return "—"

    return fallback


def _fixed_vertical(widget: QWidget | None, maximum: int) -> None:
    if widget is None:
        return
    policy = widget.sizePolicy()
    policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
    widget.setSizePolicy(policy)
    widget.setMaximumHeight(maximum)


def _configure_table(table: QTableWidget | None, minimum_height: int) -> None:
    if table is None:
        return
    table.setMinimumHeight(minimum_height)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    header = table.horizontalHeader() if hasattr(table, "horizontalHeader") else table.header()
    header.setStretchLastSection(True)


def _buttons_with_text(root: QWidget, captions: set[str]) -> list[QAbstractButton]:
    return [
        button
        for button in root.findChildren(QAbstractButton)
        if button.text().replace("&", "").strip() in captions
    ]


def _sync_recognition_action_state(window) -> None:
    """Expose candidate actions only after an operator selects evidence."""

    page = window.stack.widget(0)
    table = _find(page, QTableWidget, "candidateTable")
    if table is None:
        table = getattr(window, "drawing_list", None)
    has_selection = bool(
        isinstance(table, QTableWidget)
        and table.rowCount() > 0
        and table.currentRow() >= 0
    )
    for button in _buttons_with_text(page, {"复核类型", "新增拆分项", "合并", "排除"}):
        button.setProperty("uiRole", "candidateAction")
        button.setEnabled(has_selection)
        button.setToolTip(
            "对当前识别候选执行此操作"
            if has_selection
            else "请先在识别候选表中选择一项"
        )
        button.style().unpolish(button)
        button.style().polish(button)


def _sync_summary_action_state(window) -> None:
    """Keep list tools aligned with the current row selection."""

    page = window.stack.widget(3)
    table = getattr(window, "summary_table", None)
    has_rows = isinstance(table, QTableWidget) and table.rowCount() > 0
    has_selection = bool(has_rows and table.currentRow() >= 0)
    for button in _buttons_with_text(page, {"编辑", "删除", "上移", "下移"}):
        button.setProperty("uiRole", "listAction")
        button.setEnabled(has_selection)
        button.setToolTip("操作当前选中柜型" if has_selection else "请先选择一个柜型")
        button.style().unpolish(button)
        button.style().polish(button)

    empty_action = _find(page, QPushButton, "emptyStateAction")
    if empty_action is not None:
        empty_action.setVisible(not has_rows)


def _ensure_summary_empty_action(window, list_card: QFrame) -> None:
    if _find(list_card, QPushButton, "emptyStateAction") is not None:
        return
    empty_state = getattr(window, "summary_empty_label", None)
    layout = list_card.layout()
    if empty_state is None or layout is None:
        return

    action = QPushButton("去报价计算", list_card)
    action.setObjectName("emptyStateAction")
    action.setAccessibleName("去报价计算")
    action.setToolTip("打开报价计算，完成一个柜型后返回清单")
    action.clicked.connect(lambda: window.show_section(1))
    index = layout.indexOf(empty_state)
    layout.insertWidget(index + 1 if index >= 0 else layout.count(), action, 0, Qt.AlignmentFlag.AlignCenter)


def _configure_action_copy(window) -> None:
    roles = {
        "primaryQuoteAction": (
            "计算双报价",
            "使用当前柜体参数请求公式法和快速报价",
        ),
        "secondaryQuoteAction": (
            "加入报价清单",
            "两套报价完整后，将当前柜型加入报价清单",
        ),
        "primaryExportAction": (
            "导出正式双报价单",
            "确认清单并生成包含两套报价的 Excel 文件",
        ),
        "serviceRetryButton": (
            "重新连接报价服务",
            "重新检查报价 API 和产品目录",
        ),
    }
    for object_name, (accessible_name, tooltip) in roles.items():
        button = _find(window, QAbstractButton, object_name)
        if button is not None:
            button.setAccessibleName(accessible_name)
            button.setToolTip(tooltip)

    status = _find(window, QLabel, "serviceStatusBadge")
    if status is not None:
        status.setAccessibleName("报价服务状态")
        status.setToolTip("显示当前客户端与报价 API 的连接状态")


def _refresh_recognition_page(window) -> None:
    page = window.stack.widget(0)
    root = page.layout()
    root.setSpacing(8)

    splitter = _find(page, QSplitter, "workbenchSplitter")
    if splitter is None or splitter.count() < 3:
        return

    splitter.setHandleWidth(6)
    splitter.setChildrenCollapsible(False)
    left_panel, center_panel, right_panel = (
        splitter.widget(0),
        splitter.widget(1),
        splitter.widget(2),
    )
    left_panel.setMinimumWidth(228)
    left_panel.setMaximumWidth(264)
    center_panel.setMinimumWidth(520)
    right_panel.setMinimumWidth(348)
    right_panel.setMaximumWidth(420)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setStretchFactor(2, 0)
    splitter.setSizes([236, 700, 360])

    preview = getattr(window, "drawing_preview", None)
    if preview is not None:
        preview.setMinimumHeight(270)
        preview.setMaximumHeight(WIDGET_MAX)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    for label in center_panel.findChildren(QLabel):
        hint_text = label.text().replace(" ", "")
        if "滚轮缩放" in hint_text and "双击复位" in hint_text:
            label.setObjectName("drawingViewportHint")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(30)
            label.setMaximumHeight(30)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            break

    candidate_table = getattr(window, "drawing_list", None)
    _configure_table(candidate_table, 122)
    if candidate_table is not None:
        candidate_table.setMaximumHeight(168)
        if not getattr(candidate_table, "_layout_state_signal_connected", False):
            candidate_table.itemSelectionChanged.connect(
                lambda: _sync_recognition_action_state(window)
            )
            candidate_table._layout_state_signal_connected = True

    document_list = getattr(window, "document_list", None)
    _configure_table(document_list, 180)

    output_scroll = getattr(window, "output_form_scroll", None)
    if isinstance(output_scroll, QScrollArea):
        output_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        output_scroll.setWidgetResizable(True)

    banner = getattr(window, "batch_banner", None)
    if banner is not None:
        banner.setMinimumHeight(40)
        banner.setMaximumHeight(48)
        banner.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

    progress = getattr(window, "drawing_progress", None)
    if progress is not None:
        _force_hide_recognition_progress(window)
    _sync_recognition_action_state(window)


def _refresh_quote_page(window) -> None:
    page = window.stack.widget(1)
    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is None or workspace.count() < 2:
        return

    workspace.setChildrenCollapsible(False)
    workspace.setHandleWidth(8)
    input_panel, result_panel = workspace.widget(0), workspace.widget(1)
    input_panel.setMinimumWidth(570)
    result_panel.setMinimumWidth(520)
    result_panel.setMaximumWidth(680)
    workspace.setStretchFactor(0, 11)
    workspace.setStretchFactor(1, 9)
    workspace.setSizes([720, 600])

    for card_name in ("formulaCard", "quickCard"):
        card = _find(page, QFrame, card_name)
        if card is not None:
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    attachment_list = getattr(window, "attachment_list", None)
    if attachment_list is not None:
        attachment_list.setMaximumHeight(84)


def _refresh_summary_page(window) -> None:
    page = window.stack.widget(3)
    list_card = _find(page, QFrame, "summaryListCard")
    if list_card is None:
        return

    list_layout = list_card.layout()
    list_layout.setSpacing(9)

    title = _find(list_card, QLabel, "cardTitle")
    help_text = _find(list_card, QLabel, "tableHelp")
    _fixed_vertical(title, 32)
    _fixed_vertical(help_text, 32)

    empty_state = getattr(window, "summary_empty_label", None)
    if empty_state is not None:
        empty_state.setMinimumHeight(220)
        empty_state.setMaximumHeight(WIDGET_MAX)
        empty_state.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)

    table = getattr(window, "summary_table", None)
    _configure_table(table, 320)
    if table is not None:
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        if not getattr(table, "_layout_state_signal_connected", False):
            table.itemSelectionChanged.connect(lambda: _sync_summary_action_state(window))
            table._layout_state_signal_connected = True

    _ensure_summary_empty_action(window, list_card)
    _sync_summary_action_state(window)


def _ensure_labor_multiplier_field(window) -> None:
    """Ensure formula card exposes a human-editable labor multiplier."""

    stack = getattr(window, "stack", None)
    if stack is None or stack.count() <= 1:
        return
    page = stack.widget(1)
    card = _find(page, QFrame, "formulaCard")
    if card is None:
        return

    layout = card.layout()
    if layout is None:
        return

    multiplier = getattr(window, "labor_multiplier", None)
    if not isinstance(multiplier, QDoubleSpinBox):
        multiplier = _find(card, QDoubleSpinBox, "laborMultiplier")
    if not isinstance(multiplier, QDoubleSpinBox):
        multiplier = QDoubleSpinBox()
        multiplier.setObjectName("laborMultiplier")
        multiplier.setRange(0.01, 10)
        multiplier.setDecimals(2)
        multiplier.setSingleStep(0.05)
        multiplier.setValue(1.0)
        multiplier.setSuffix(" ×")
        window.labor_multiplier = multiplier
        try:
            multiplier.valueChanged.connect(window.refresh_discounted_totals)
        except Exception:
            pass

    multiplier.setObjectName("laborMultiplier")
    multiplier.setRange(0.01, 10.0)
    multiplier.setDecimals(2)
    multiplier.setSingleStep(0.05)
    if _safe_float(multiplier.value()) is None:
        multiplier.setValue(1.0)
    multiplier.setSuffix(" ×")
    multiplier.setFixedWidth(104)
    multiplier.setToolTip("调整后，人工成本和管理费用会立即重新计算")
    multiplier.setAccessibleName("人工成本折扣系数")
    window.labor_multiplier = multiplier
    if not getattr(multiplier, "_layout_refresh_signal_connected", False):
        multiplier.valueChanged.connect(window.refresh_discounted_totals)
        multiplier._layout_refresh_signal_connected = True

    if getattr(window, "_layout_labor_row_added", False):
        try:
            multiplier.setValue(_safe_float(multiplier.value()) or 1.0)
        except Exception:
            pass
        try:
            window.refresh_discounted_totals()
        except Exception:
            pass
        return

    row = QFrame(card)
    row.setObjectName("laborMultiplierRow")
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(8, 6, 8, 6)
    row_layout.setSpacing(8)
    label = QLabel("人工成本折扣系数", row)
    label.setObjectName("laborMultiplierLabel")
    label.setBuddy(multiplier)
    row_layout.addWidget(label)
    row_layout.addStretch(1)
    row_layout.addWidget(multiplier)
    if hasattr(layout, "insertWidget"):
        layout.insertWidget(1, row)
    else:
        layout.addWidget(row)

    window._layout_labor_row_added = True
    try:
        window.refresh_discounted_totals()
    except Exception:
        pass


def _patch_family_for_code(main_window) -> None:
    if getattr(main_window, "_layout_refresh_family_patched", False):
        return
    main_window._layout_refresh_family_patched = True


INDUSTRIAL_WORKBENCH_STYLE = f"""
QWidget#page {{
    background: {STEEL_CANVAS};
    color: {GRAPHITE};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei";
}}
QFrame#navPanel {{
    background: {GRAPHITE};
    border: 0;
    border-right: 1px solid #303840;
    border-radius: 0;
}}
QFrame#brandBlock {{ background: transparent; border: 0; }}
QLabel#brandMark {{
    background: {BLUEPRINT}; color: white; border: 0; border-radius: 7px;
    font-family: "Consolas"; font-weight: 700;
}}
QLabel#navTitle {{ color: white; font-weight: 700; }}
QLabel#navHint, QLabel#navSectionLabel, QLabel#navFooter {{ color: #AAB4BE; }}
QLabel#navHint {{
    font-family: "Consolas"; font-size: 8pt; letter-spacing: 0.3px;
}}
QPushButton#navButton {{
    color: #DCE2E7; background: transparent; border: 0;
    border-left: 3px solid transparent; border-radius: 6px;
    padding: 9px 10px; text-align: left;
}}
QPushButton#navButton:hover {{ background: {GRAPHITE_RAISED}; color: white; }}
QPushButton#navButton:checked {{
    background: {BLUEPRINT}; color: white; border-left: 3px solid #9CCBF0;
}}
#modernPageHeader, #commandBar {{
    background: {PAPER}; border: 1px solid {STEEL_LINE}; border-radius: 8px;
}}
QLabel#modernPageTitle, QLabel#workbenchTitle {{
    color: {GRAPHITE}; font-weight: 700;
}}
QLabel#modernPageSubtitle, QLabel#workbenchSubtitle, QLabel#cardSubtitle {{
    color: {MUTED_INK};
}}
QLabel#workbenchCounter {{
    background: #F8FAFB; border: 1px solid {STEEL_LINE}; border-radius: 6px;
    color: #45515D; padding: 6px 9px;
}}
QLabel#batchBanner {{
    background: {BLUEPRINT_PALE}; border: 1px solid #BED8EB;
    border-left: 4px solid {BLUEPRINT}; border-radius: 5px;
    color: #234A66; padding: 0 12px; font-weight: 600;
}}
#inputPanel, #evidencePanel, #outputPanel, #quoteInputCard,
#quoteResultsPanel, QFrame#summaryListCard {{
    background: {PAPER}; border: 1px solid {STEEL_LINE}; border-radius: 8px;
}}
#importDropZone {{
    background: #FAFBFC; border: 1px dashed #AEB9C3; border-radius: 7px;
}}
#reviewGateCard {{
    background: {WARNING_PALE}; border: 1px solid #ECD39A;
    border-left: 4px solid {WARNING_AMBER}; border-radius: 6px;
}}
QFrame#formulaCard {{
    background: {PAPER}; border: 1px solid {STEEL_LINE};
    border-left: 4px solid {BLUEPRINT}; border-radius: 7px;
}}
QFrame#quickCard {{
    background: {PAPER}; border: 1px solid {STEEL_LINE};
    border-left: 4px solid {INSPECTION_GREEN}; border-radius: 7px;
}}
QLabel#serviceStatusBadge[tone="success"] {{
    background: {INSPECTION_PALE}; color: #246B49;
    border: 1px solid #B7DDC8; border-radius: 6px;
}}
QLabel#serviceStatusBadge[tone="info"] {{
    background: {BLUEPRINT_PALE}; color: #24577B;
    border: 1px solid #BED8EB; border-radius: 6px;
}}
QLabel#serviceStatusBadge[tone="warning"], QLabel#serviceStatusBadge[tone="error"] {{
    background: {WARNING_PALE}; color: #855A08;
    border: 1px solid #ECD39A; border-radius: 6px;
}}
QLabel#dimensionCode {{
    background: {GRAPHITE}; color: white; border-radius: 5px;
    font-family: "Consolas"; font-weight: 700;
}}
QSpinBox, QDoubleSpinBox {{ font-family: "Consolas", "Microsoft YaHei UI"; }}
QPushButton#primaryQuoteAction, QPushButton#primaryAction,
QPushButton#primaryExportAction, QPushButton#importPrimaryAction,
QPushButton#emptyStateAction {{
    background: {BLUEPRINT}; color: white; border: 1px solid {BLUEPRINT};
    border-radius: 6px; font-weight: 700; padding: 8px 14px;
}}
QPushButton#primaryQuoteAction:hover, QPushButton#primaryAction:hover,
QPushButton#primaryExportAction:hover, QPushButton#importPrimaryAction:hover,
QPushButton#emptyStateAction:hover {{ background: #115787; border-color: #115787; }}
QPushButton#secondaryQuoteAction {{
    background: {BLUEPRINT_PALE}; color: #145681; border: 1px solid #B9D7EA;
    border-radius: 6px; font-weight: 700;
}}
QPushButton[uiRole="candidateAction"], QPushButton[uiRole="listAction"] {{
    background: {PAPER}; color: #34414D; border: 1px solid #BCC6CF;
    border-radius: 5px; padding: 6px 10px;
}}
QPushButton:disabled {{
    background: #EEF1F4; color: #9AA4AE; border-color: #D9DEE3;
}}
QPushButton:focus, QComboBox:focus, QLineEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTableWidget:focus {{
    border: 2px solid {BLUEPRINT};
}}
QSplitter#workbenchSplitter::handle:horizontal,
QSplitter#quoteWorkspace::handle:horizontal {{
    background: {STEEL_LINE}; margin: 8px 1px; border-radius: 2px;
}}
QFrame#summaryListCard {{ border-top: 3px solid {BLUEPRINT}; }}
QLabel#summaryEmptyState {{
    background: #FAFBFC; border: 1px dashed #B8C1CA;
    color: {MUTED_INK}; border-radius: 6px;
}}
QLabel#drawingViewportHint {{
    background: #FAFBFC; border: 1px solid {STEEL_LINE}; border-radius: 5px;
    color: {MUTED_INK}; padding: 0 10px;
}}
QTableWidget#summaryTable, QTableWidget#candidateTable, QTreeWidget#documentQueue {{
    gridline-color: #E2E6EA; selection-background-color: #DCECF7;
    selection-color: {GRAPHITE}; alternate-background-color: #FAFBFC;
}}
QHeaderView::section {{
    background: #EEF2F5; color: #44515D; border: 0;
    border-right: 1px solid {STEEL_LINE}; border-bottom: 1px solid {STEEL_LINE};
    padding: 7px; font-weight: 700;
}}
QProgressBar#drawingProgress {{
    min-height: 0; max-height: 0; border: 0; margin: 0; padding: 0;
    background: transparent; color: transparent;
}}
QProgressBar#drawingProgress::chunk {{ border: 0; background: transparent; }}
QFrame#laborMultiplierRow {{
    background: #F7F9FA; border: 1px solid {STEEL_LINE}; border-radius: 6px;
}}
QLabel#laborMultiplierLabel {{ color: #34414D; font-weight: 600; }}
QDoubleSpinBox#laborMultiplier {{ min-height: 28px; }}
"""


def apply_layout_refresh(window) -> None:
    """Apply the V3 workbench presentation without changing quote state."""

    nav = _find(window, QFrame, "navPanel")
    if nav is not None:
        nav.setFixedWidth(168)
        nav_hint = _find(nav, QLabel, "navHint")
        if nav_hint is not None:
            nav_hint.setText("QUOTE DESK")

    main_scroll = _find(window, QScrollArea, "mainScroll")
    if main_scroll is not None:
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    _refresh_recognition_page(window)
    _refresh_quote_page(window)
    _ensure_labor_multiplier_field(window)
    _refresh_summary_page(window)
    _configure_action_copy(window)
    window.setStyleSheet(window.styleSheet() + INDUSTRIAL_WORKBENCH_STYLE)


def _force_hide_recognition_progress(window) -> None:
    """Keep the redundant recognition progress strip out of the layout."""

    progress = getattr(window, "drawing_progress", None)
    if progress is None:
        return
    progress.setMinimumHeight(0)
    progress.setMaximumHeight(0)
    policy = progress.sizePolicy()
    policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
    progress.setSizePolicy(policy)
    QWidget.setVisible(progress, False)


def _show_selected_queue_document(window) -> None:
    """Keep the raw imported drawing visible while recognition is running."""

    document_list = getattr(window, "document_list", None)
    preview = getattr(window, "drawing_preview", None)
    if document_list is None or preview is None:
        return

    current = document_list.currentItem()
    if current is None and document_list.topLevelItemCount():
        current = document_list.topLevelItem(0)
    if current is None:
        return

    source_path = str(current.data(0, Qt.ItemDataRole.UserRole) or "")
    if not source_path or not Path(source_path).is_file():
        return
    if str(getattr(preview, "_source_path", "") or "") == source_path:
        return
    preview.set_source(source_path)


def _stabilize_preview_widget(preview) -> None:
    """Make the rendered pixmap survive the native Windows paint path."""

    label = getattr(preview, "image_label", None)
    if label is None:
        return
    if label.graphicsEffect() is not None:
        label.setGraphicsEffect(None)
    label.show()
    label.raise_()
    label.update()

    paper = getattr(preview, "paper", None)
    if paper is not None:
        paper.show()
        paper.update()

    canvas = getattr(preview, "canvas", None)
    if canvas is not None:
        canvas.viewport().update()
        canvas.update()


def _install_stable_preview(namespace: dict) -> None:
    preview_class = namespace.get("DrawingPreviewWidget")
    if preview_class is None or getattr(preview_class, "_stable_preview_installed", False):
        return

    original_set_source = preview_class.set_source
    original_render_image = preview_class._render_image

    def set_source_without_deleted_worker(self, source_path):
        worker = getattr(self, "_worker", None)
        if worker is not None:
            try:
                worker.isRunning()
            except RuntimeError:
                self._worker = None
        return original_set_source(self, source_path)

    def render_image_without_opacity_loss(self):
        original_render_image(self)
        _stabilize_preview_widget(self)
        QTimer.singleShot(0, lambda: _stabilize_preview_widget(self))

    def stable_flash(self):
        _stabilize_preview_widget(self)

    preview_class.set_source = set_source_without_deleted_worker
    preview_class._render_image = render_image_without_opacity_loss
    preview_class.flash = stable_flash
    preview_class._stable_preview_installed = True


def _patch_discounted_totals(namespace: dict, main_window) -> None:
    original_refresh = getattr(main_window, "refresh_discounted_totals", None)
    original_show_result = getattr(main_window, "show_result", None)
    if not callable(original_refresh) or getattr(main_window, "_layout_refresh_discount_patched", False):
        return

    money = _money_formatter(namespace)

    if callable(original_show_result):
        def show_result_with_formula_base(self, result):
            formula = result.get("formula_cost") if isinstance(result, dict) else None
            self._formula_base_result = dict(formula) if isinstance(formula, dict) else None
            original_show_result(self, result)
            if not isinstance(getattr(self, "current_result", None), dict):
                self._formula_base_result = None
                return
            self.refresh_discounted_totals()
        main_window.show_result = show_result_with_formula_base

    original_reset = getattr(main_window, "reset_current_cabinet", None)
    if callable(original_reset):
        def reset_current_cabinet_without_labor_base(self, *args, **kwargs):
            result = original_reset(self, *args, **kwargs)
            self._formula_base_result = None
            return result
        main_window.reset_current_cabinet = reset_current_cabinet_without_labor_base

    def refresh_discounted_totals_with_labor(self):
        current = getattr(self, "current_result", {}) or {}
        formula = current.get("formula")
        if not isinstance(formula, dict):
            return

        multiplier_widget = getattr(self, "labor_multiplier", None)
        multiplier = _safe_float(getattr(multiplier_widget, "value", lambda: None)())
        if multiplier is None:
            multiplier = 1.0

        labels = getattr(self, "formula_labels", {})
        if not isinstance(labels, dict):
            return

        base = getattr(self, "_formula_base_result", None)
        if not isinstance(base, dict):
            base = dict(formula)
            self._formula_base_result = dict(base)
        base_labor = _safe_float(base.get("labor_cost"))
        base_management = _safe_float(base.get("management_fee"))
        base_total = _safe_float(base.get("total_cost"))
        if base_labor is None or base_management is None or base_total is None:
            original_refresh(self)
            return

        labor = base_labor * multiplier
        management = labor * 0.13
        rendered = dict(base)
        rendered["labor_cost"] = labor
        rendered["management_fee"] = management
        rendered["total_cost"] = base_total - base_labor - base_management + labor + management

        self.current_result["formula"] = rendered
        original_refresh(self)

    main_window.refresh_discounted_totals = refresh_discounted_totals_with_labor

    original_add = getattr(main_window, "add_current_to_summary", None)
    if callable(original_add):
        def add_current_to_summary_with_labor_state(self):
            self.refresh_discounted_totals()
            base = getattr(self, "_formula_base_result", None)
            multiplier_widget = getattr(self, "labor_multiplier", None)
            multiplier = _safe_float(getattr(multiplier_widget, "value", lambda: 1.0)()) or 1.0
            before = len(getattr(self, "draft_items", []))
            result = original_add(self)
            items = getattr(self, "draft_items", [])
            if len(items) == before + 1:
                item = items[-1]
                if isinstance(base, dict):
                    item["formula_base"] = dict(base)
                item["labor_multiplier"] = multiplier
                self.refresh_summary()
            return result
        main_window.add_current_to_summary = add_current_to_summary_with_labor_state

    original_load = getattr(main_window, "load_draft_item", None)
    if callable(original_load):
        def load_draft_item_with_labor_state(self, item):
            base = item.get("formula_base") if isinstance(item, dict) else None
            if not isinstance(base, dict) and isinstance(item, dict):
                base = item.get("formula")
            self._formula_base_result = dict(base) if isinstance(base, dict) else None
            multiplier_widget = getattr(self, "labor_multiplier", None)
            if isinstance(multiplier_widget, QDoubleSpinBox):
                multiplier_widget.setValue(float(item.get("labor_multiplier", 1.0)))
            result = original_load(self, item)
            self._formula_base_result = dict(base) if isinstance(base, dict) else None
            self.refresh_discounted_totals()
            return result
        main_window.load_draft_item = load_draft_item_with_labor_state

    main_window._layout_refresh_discount_patched = True


def install_layout_refresh(namespace: dict) -> None:
    """Install the layout pass on an extracted or packaged V3 namespace."""

    main_window = namespace["MainWindow"]
    if getattr(main_window, "_layout_refresh_installed", False):
        return

    _install_stable_preview(namespace)
    _patch_family_for_code(main_window)
    _patch_discounted_totals(namespace, main_window)

    original_build_ui = main_window.build_ui
    original_refresh_document_list = main_window._refresh_document_list
    original_import_drawing_paths = main_window.import_drawing_paths
    original_recognition_progress = main_window.pdf_recognition_progress
    original_recognition_finished = main_window.pdf_recognition_finished
    original_refresh_summary = main_window.refresh_summary

    def build_ui_with_refresh(self):
        original_build_ui(self)
        apply_layout_refresh(self)

    def refresh_document_list_with_preview(self):
        original_refresh_document_list(self)
        _show_selected_queue_document(self)
        _sync_recognition_action_state(self)

    def import_drawing_paths_without_progress_strip(self, paths):
        try:
            return original_import_drawing_paths(self, paths)
        finally:
            _force_hide_recognition_progress(self)
            _sync_recognition_action_state(self)

    def recognition_progress_without_strip(self, index, total, name):
        try:
            return original_recognition_progress(self, index, total, name)
        finally:
            _force_hide_recognition_progress(self)
            _sync_recognition_action_state(self)

    def recognition_finished_without_strip(self, succeeded, failed, cancelled):
        try:
            return original_recognition_finished(self, succeeded, failed, cancelled)
        finally:
            _force_hide_recognition_progress(self)
            _sync_recognition_action_state(self)

    def refresh_summary_with_action_state(self):
        result = original_refresh_summary(self)
        _sync_summary_action_state(self)
        return result

    main_window.build_ui = build_ui_with_refresh
    main_window._refresh_document_list = refresh_document_list_with_preview
    main_window.import_drawing_paths = import_drawing_paths_without_progress_strip
    main_window.pdf_recognition_progress = recognition_progress_without_strip
    main_window.pdf_recognition_finished = recognition_finished_without_strip
    main_window.refresh_summary = refresh_summary_with_action_state
    main_window._layout_refresh_installed = True
