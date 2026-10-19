"""Server-backed quotation scheme centre for the recovered desktop client."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QDate, QDateTime, QTimer, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QInputDialog, QLineEdit, QMessageBox, QPushButton,
    QTableWidgetItem, QVBoxLayout, QSizePolicy, QWidget,
)

from quote_scheme_widgets import (
    DateFilter, METRICS, PAGE_SIZES, PageJump, QueryLineEdit, RowActions,
    SchemeComboBox, SchemePage, SchemeTable, ServerNotice, StatusBadgeDelegate,
    filter_field, page_style_sheet,
)


SCHEME_ROUTE = 6
CLIENT_VERSION = "2026.10.19.02"
STATUS_TEXT = {
    "DRAFT": "草稿", "QUOTED": "已报价", "REVISING": "修订中",
    "ARCHIVED": "已归档", "VOID": "已作废",
}
STATUS_COLORS = {
    "DRAFT": ("#F3F4F6", "#4B5563"), "QUOTED": ("#EAF3DE", "#237804"),
    "REVISING": ("#FFF4E5", "#B45309"), "ARCHIVED": ("#EAF2FF", "#185FA5"),
    "VOID": ("#FDECEC", "#B42318"),
}

# Existing server summaries join product + dimensions with a space, and
# separate quote lines with semicolons. Strip only a trailing dimension
# expression, never split product names on spaces or remove model digits.
_PRODUCT_DIMENSIONS = re.compile(
    r"\s+\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米)?"
    r"(?:\s*[×xX*＊]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米)?)+\s*$",
    re.IGNORECASE,
)


def _display_products(summary):
    products = []
    for label in re.split(r"[；;]", str(summary or "")):
        product = _PRODUCT_DIMENSIONS.sub("", label.strip()).strip()
        if product and product not in products:
            products.append(product)
    return "；".join(products)


class QuoteSchemeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, method, url, headers, payload=None, parent=None):
        super().__init__(parent)
        self.method, self.url, self.headers = method, url, dict(headers or {})
        self.payload = deepcopy(payload)

    def run(self):
        try:
            data = None if self.payload is None else json.dumps(
                self.payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            headers = {**self.headers, "Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = "application/json; charset=utf-8"
            request = urllib.request.Request(self.url, data=data, headers=headers, method=self.method)
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
            self.succeeded.emit(json.loads(raw or "{}"))
        except urllib.error.HTTPError as error:
            try:
                body = json.loads(error.read().decode("utf-8"))
                message = str(body.get("message") or body.get("error") or error.reason)
            except Exception:
                message = str(error.reason or error)
            self.failed.emit(message)
        except Exception as error:
            self.failed.emit(str(error))


def _base_url(window):
    return str(window.base_url()).rstrip("/")


def _headers(window):
    factory = getattr(window, "_quote_scheme_headers_factory", None)
    return factory() if callable(factory) else {}


def _snapshot(window):
    from scheme2_ui import _order_workspace_payload, _row_values
    payload = _order_workspace_payload(window)
    items = list(payload.get("draft_items") or [])
    products = []
    quoted_amount = 0.0
    for item in items:
        values = _row_values(item)
        quoted_amount += float(values[16] or 0)
        product = str(item.get("product_name") or item.get("product_code") or item.get("name") or "").strip()
        specification = str(item.get("specification") or item.get("model_code") or "").strip()
        label = " ".join(value for value in (product, specification) if value)
        if label and label not in products:
            products.append(label)
    quote_date = str(getattr(window, "_quote_scheme_quote_date", "") or date.today().isoformat())
    payload["quote_scheme_schema_version"] = 1
    payload["client_version"] = CLIENT_VERSION
    payload["active_route"] = int(window.stack.currentIndex())
    payload["scheme_summary"] = {
        "company": str(payload.get("company") or "").strip(),
        "product_summary": "；".join(products[:3]),
        "quoted_amount": round(quoted_amount, 2),
    }
    payload["document"] = {
        "scheme_no": str(getattr(window, "_quote_scheme_id", "") or ""),
        "version_no": int(getattr(window, "_quote_scheme_business_version", 1) or 1),
        "quote_date": quote_date,
        "client_version": CLIENT_VERSION,
    }
    return payload


def _operator_name(window, prompt=False):
    editor = getattr(window, "quote_scheme_operator_name", None)
    value = editor.text().strip() if isinstance(editor, QLineEdit) else ""
    if not value and prompt:
        value, accepted = QInputDialog.getText(
            window, "填写创建人", "请输入当前操作人员姓名：", QLineEdit.EchoMode.Normal,
        )
        value = value.strip() if accepted else ""
        if value and isinstance(editor, QLineEdit):
            editor.setText(value)
    return value[:100]


def _require_operator(window, prompt=False):
    value = _operator_name(window, prompt)
    if value:
        return value
    _set_state(window, "请先在报价方案中心填写当前操作人姓名。", "error")
    return ""


def _set_state(window, text, kind="normal"):
    label = window.quote_scheme_save_status
    label.setText(text)
    # Keep idle workspace hints in the scheme centre, not in the sidebar.
    # Save progress and failures remain visible even before a number exists.
    label.setVisible(bool(text) and (bool(window._quote_scheme_id) or kind in ("busy", "error")))
    colors = {"normal": "#4B5563", "busy": "#185FA5", "ok": "#237804", "error": "#B42318"}
    label.setStyleSheet(f"color:{colors[kind]};font-size:12px;padding:4px 2px;")
    window.quote_scheme_page_status.setText(text)
    window.quote_scheme_page_status.setVisible(
        kind == "error" and window.quote_scheme_table.rowCount() == 0
    )
    operation_status = getattr(window, "quote_scheme_operation_status", None)
    if operation_status is not None:
        operation_status.setText(text)
        operation_status.setVisible(kind == "error" and window.quote_scheme_table.rowCount() > 0)


def _run(window, method, path, payload, success, failure=None):
    worker = QuoteSchemeWorker(method, _base_url(window) + path, _headers(window), payload, window)
    window._quote_scheme_workers.add(worker)

    def done():
        window._quote_scheme_workers.discard(worker)
        worker.deleteLater()

    worker.succeeded.connect(success)
    worker.failed.connect(failure or (lambda message: _set_state(window, f"保存失败：{message}", "error")))
    worker.finished.connect(done)
    worker.start()
    return worker


def _field(placeholder, name):
    editor = QueryLineEdit()
    editor.setObjectName(name)
    editor.setPlaceholderText(placeholder)
    editor.setClearButtonEnabled(True)
    editor.setMinimumHeight(34)
    return editor


class _FilterActionButton(QPushButton):
    LABELS = ("查询", "重置", "新建方案")

    def sizeHint(self):
        hint = super().sizeHint()
        metrics = self.fontMetrics()
        label_width = max(metrics.horizontalAdvance(text) for text in self.LABELS)
        hint.setWidth(hint.width() + max(0, label_width - metrics.horizontalAdvance(self.text())))
        return hint

    def minimumSizeHint(self):
        return self.sizeHint()


def _edit_operator(window):
    value, accepted = QInputDialog.getText(
        window, "当前操作人", "请输入当前操作人员姓名（自填）：",
        QLineEdit.EchoMode.Normal, window.quote_scheme_operator_name.text(),
    )
    if accepted:
        window.quote_scheme_operator_name.setText(value.strip()[:100])


def _update_operator_button(window):
    value = window.quote_scheme_operator_name.text().strip()
    button = window.quote_scheme_operator_button
    button.setText("操作人：" + (value if len(value) <= 8 else value[:7] + "…") if value else "填写操作人")
    button.setToolTip("当前操作人（自填）：" + (value or "未填写") + "；用于创建和修改记录，不作为登录身份。")


def _layout_footer(window):
    compact = window.quote_scheme_page.width() < METRICS["footer_breakpoint"]
    if getattr(window, "_quote_scheme_footer_compact", None) == compact:
        return
    window._quote_scheme_footer_compact = compact
    grid = window.quote_scheme_footer_grid
    left, right = window.quote_scheme_footer_info, window.quote_scheme_footer_pages
    grid.removeWidget(left)
    grid.removeWidget(right)
    if compact:
        grid.addWidget(left, 0, 0, 1, 2)
        grid.addWidget(right, 1, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
    else:
        grid.addWidget(left, 0, 0)
        grid.addWidget(right, 0, 1, Qt.AlignmentFlag.AlignRight)


def _page_jump(window):
    _load_list(window, window.quote_scheme_page_jump.value())


def _update_page_buttons(window, page, pages):
    layout = window.quote_scheme_number_layout
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
    first = max(1, min(page - 2, pages - 4))
    for number in range(first, min(pages, first + 4) + 1):
        button = QPushButton(str(number))
        button.setObjectName("quoteSchemePageButton")
        button.setCheckable(True)
        button.setChecked(number == page)
        button.setAccessibleName(f"第 {number} 页")
        button.clicked.connect(lambda _checked=False, target=number: _load_list(window, target))
        layout.addWidget(button)
    window.quote_scheme_page_jump.setRange(1, pages)
    window.quote_scheme_page_jump.setValue(page)


def _build_page(window):
    page = SchemePage()
    page.setObjectName("quoteSchemeCenterPage")
    page.setStyleSheet(page_style_sheet())
    window.quote_scheme_page = page
    root = QVBoxLayout(page)
    margin = METRICS["page_margin"]
    root.setContentsMargins(margin, margin, margin, margin)
    root.setSpacing(METRICS["section_gap"])

    heading = QHBoxLayout()
    title = QLabel("报价方案中心")
    title.setObjectName("quoteSchemeTitle")
    # Match the actual current quote-page title after its shared font scaling,
    # rather than maintaining a separate large-title type scale on this page.
    reference_title = window.scheme2_quote_page.findChild(QLabel, "scheme2PageTitle")
    reference_title.ensurePolished()
    title_font = reference_title.font()
    title.setFont(title_font)
    size = (f"{title_font.pixelSize()}px" if title_font.pixelSize() > 0
            else f"{title_font.pointSizeF():g}pt")
    color = reference_title.palette().color(reference_title.foregroundRole()).name()
    title.setStyleSheet(f"font-size:{size};font-weight:{int(title_font.weight())};color:{color};")
    server = ServerNotice()
    server.setObjectName("quoteSchemeServerNotice")
    heading.addWidget(title)
    heading.addStretch(1)
    heading.addWidget(server)
    root.addLayout(heading)

    # Keep one session-scoped operator value; entry moves to a quiet footer
    # control instead of competing with the reference title/server notice.
    operator_name = _field("填写姓名", "quoteSchemeOperatorName")
    operator_name.setParent(page)
    operator_name.setToolTip("该姓名由操作人员自填，用于方案显示、审计和搜索；当前阶段不作为登录身份。")
    operator_name.hide()
    window.quote_scheme_operator_name = operator_name

    filters = QFrame()
    filters.setObjectName("quoteSchemeFilters")
    grid = QGridLayout(filters)
    grid.setContentsMargins(16, 14, 16, 16)
    grid.setHorizontalSpacing(METRICS["filter_gap"])
    grid.setVerticalSpacing(16)
    window.quote_scheme_filters = {
        "scheme_no": _field("请输入方案编号", "quoteSchemeNumberFilter"),
        "company": _field("请输入下单公司", "quoteSchemeCompanyFilter"),
        "product": _field("请输入产品名称", "quoteSchemeProductFilter"),
        "creator": _field("请输入创建人", "quoteSchemeCreatorFilter"),
        "updated_from": DateFilter("quoteSchemeUpdatedFrom", "更新时间开始日期"),
        "updated_to": DateFilter("quoteSchemeUpdatedTo", "更新时间结束日期"),
    }
    for key, editor in window.quote_scheme_filters.items():
        editor.setMinimumWidth(0 if key not in ("updated_from", "updated_to") else 96)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor.returnPressed.connect(lambda: _load_list(window, 1))
    status = SchemeComboBox()
    status.setObjectName("quoteSchemeStatusFilter")
    status.addItem("全部", "")
    for code, label in STATUS_TEXT.items():
        status.addItem(label, code)
    window.quote_scheme_status_filter = status
    for column, (label, key) in enumerate((
        ("方案编号", "scheme_no"), ("下单公司", "company"), ("产品", "product"),
    )):
        field = filter_field(label, window.quote_scheme_filters[key], "quoteSchemeField_" + key)
        grid.addWidget(field, 0, column)
    grid.addWidget(filter_field("状态", status, "quoteSchemeField_status"), 1, 0)
    grid.addWidget(filter_field("创建人", window.quote_scheme_filters["creator"],
                               "quoteSchemeField_creator"), 1, 1)
    dates = QHBoxLayout()
    dates.setContentsMargins(0, 0, 0, 0)
    dates.setSpacing(8)
    dates.addWidget(window.quote_scheme_filters["updated_from"], 1)
    dates.addWidget(QLabel("-"))
    dates.addWidget(window.quote_scheme_filters["updated_to"], 1)
    grid.addWidget(filter_field("更新时间", dates, "quoteSchemeField_updated"), 1, 2)
    query, reset, create = (_FilterActionButton(text) for text in _FilterActionButton.LABELS)
    window.quote_scheme_query, window.quote_scheme_reset = query, reset
    window.quote_scheme_create = create
    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(METRICS["action_gap"])
    for button in (query, reset, create):
        button.setObjectName("scheme2PrimaryAction")
        actions.addWidget(button, 1)
    grid.addLayout(actions, 1, 3, Qt.AlignmentFlag.AlignBottom)
    for column, stretch in enumerate((10, 10, 16, 12)):
        grid.setColumnStretch(column, stretch)
    window.quote_scheme_filter_grid = grid
    root.addWidget(filters)

    table = SchemeTable()
    table.setObjectName("quoteSchemeTable")
    table.setHorizontalHeaderLabels([
        "方案编号", "下单公司", "产品", "状态", "报价金额",
        "创建人", "最后修改人", "更新时间", "操作",
    ])
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(METRICS["row_height"])
    table.verticalHeader().setMinimumSectionSize(METRICS["row_height"])
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(60)
    header.setFixedHeight(METRICS["header_height"])
    table.setItemDelegateForColumn(3, StatusBadgeDelegate(STATUS_TEXT, STATUS_COLORS, table))
    root.addWidget(table, 1)
    window.quote_scheme_table = table

    status_line = QLabel("正在准备报价方案列表…", table.viewport())
    status_line.setObjectName("quoteSchemePageStatus")
    status_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_line.setWordWrap(True)
    status_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    table.state_label = status_line
    window.quote_scheme_page_status = status_line

    operation_status = QLabel()
    operation_status.setObjectName("quoteSchemeOperationStatus")
    operation_status.setWordWrap(True)
    operation_status.hide()
    root.addWidget(operation_status)
    window.quote_scheme_operation_status = operation_status

    footer_info = QWidget()
    info_layout = QHBoxLayout(footer_info)
    info_layout.setContentsMargins(0, 0, 0, 0)
    info_layout.setSpacing(16)
    count = QLabel("共 0 条记录")
    selected = QLabel("已选择 0 条")
    info_layout.addWidget(count)
    info_layout.addWidget(selected)
    operator_button = QPushButton("填写操作人")
    operator_button.setObjectName("quoteSchemeOperatorButton")
    operator_button.clicked.connect(lambda: _edit_operator(window))
    info_layout.addWidget(operator_button)
    info_layout.addStretch(1)
    window.quote_scheme_operator_button = operator_button
    operator_name.textChanged.connect(lambda _text: _update_operator_button(window))
    _update_operator_button(window)

    footer_pages = QWidget()
    pagination = QHBoxLayout(footer_pages)
    pagination.setContentsMargins(0, 0, 0, 0)
    pagination.setSpacing(8)
    page_size = SchemeComboBox()
    page_size.setObjectName("quoteSchemePageSize")
    page_size.setAccessibleName("每页条数")
    for size in PAGE_SIZES:
        page_size.addItem(f"{size} 条/页", size)
    previous, following = QPushButton("‹"), QPushButton("›")
    for button, label in ((previous, "上一页"), (following, "下一页")):
        button.setObjectName("quoteSchemePageButton")
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setEnabled(False)
    number_host = QWidget()
    number_layout = QHBoxLayout(number_host)
    number_layout.setContentsMargins(0, 0, 0, 0)
    number_layout.setSpacing(8)
    page_label = QLabel("第 1 / 1 页", page)
    page_label.hide()  # Accessible/internal text retained beside numbered controls.
    jump = PageJump()
    jump.setObjectName("quoteSchemePageJump")
    jump.setAccessibleName("前往页码")
    jump.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    jump.setAlignment(Qt.AlignmentFlag.AlignCenter)
    jump.setRange(1, 1)
    jump.setFixedWidth(58)
    pagination.addWidget(page_size)
    pagination.addSpacing(8)
    pagination.addWidget(previous)
    pagination.addWidget(number_host)
    pagination.addWidget(following)
    pagination.addSpacing(12)
    pagination.addWidget(QLabel("前往"))
    pagination.addWidget(jump)
    pagination.addWidget(QLabel("页"))
    footer_grid = QGridLayout()
    footer_grid.setContentsMargins(0, 0, 0, 0)
    footer_grid.setHorizontalSpacing(16)
    footer_grid.setVerticalSpacing(10)
    footer_grid.setColumnStretch(0, 1)
    root.addLayout(footer_grid)
    window.quote_scheme_count, window.quote_scheme_selected = count, selected
    window.quote_scheme_page_size, window.quote_scheme_prev = page_size, previous
    window.quote_scheme_next, window.quote_scheme_page_label = following, page_label
    window.quote_scheme_page_jump = jump
    window.quote_scheme_number_layout = number_layout
    window.quote_scheme_footer_grid = footer_grid
    window.quote_scheme_footer_info, window.quote_scheme_footer_pages = footer_info, footer_pages
    page.resized.connect(lambda: _layout_footer(window))
    _layout_footer(window)
    _update_page_buttons(window, 1, 1)

    query.clicked.connect(lambda: _load_list(window, 1))
    reset.clicked.connect(lambda: _reset_filters(window))
    create.clicked.connect(lambda: _new_scheme(window))
    previous.clicked.connect(lambda: _load_list(window, max(1, window._quote_scheme_page - 1)))
    following.clicked.connect(lambda: _load_list(window, window._quote_scheme_page + 1))
    page_size.currentIndexChanged.connect(lambda _index: _load_list(window, 1))
    jump.submitted.connect(lambda: _page_jump(window))
    table.itemSelectionChanged.connect(
        lambda: selected.setText(f"已选择 {len(table.selectionModel().selectedRows())} 条")
    )
    table.itemDoubleClicked.connect(lambda *_: _open_selected_row(window))
    return page


def _reset_filters(window):
    for editor in window.quote_scheme_filters.values(): editor.clear()
    window.quote_scheme_status_filter.setCurrentIndex(0)
    _load_list(window, 1)


def _filters(window, page):
    values = {key: editor.text().strip() for key, editor in window.quote_scheme_filters.items()}
    for key in ("updated_from", "updated_to"):
        if values[key] and (not QDate.fromString(values[key], "yyyy-MM-dd").isValid()
                            or len(values[key]) != 10):
            raise ValueError("更新时间请输入 YYYY-MM-DD 格式的有效日期，或通过日历选择。")
    if values["updated_from"] and values["updated_to"] and values["updated_from"] > values["updated_to"]:
        raise ValueError("开始日期不能晚于结束日期，请重新选择更新时间范围。")
    values.update(status=str(window.quote_scheme_status_filter.currentData() or ""), page=page,
                  page_size=int(window.quote_scheme_page_size.currentData() or PAGE_SIZES[0]))
    return {key: value for key, value in values.items() if value not in ("", None)}


def _list_state(window, text="", kind="normal"):
    label = window.quote_scheme_page_status
    label.setText(text)
    label.setProperty("state", kind)
    label.style().unpolish(label)
    label.style().polish(label)
    label.setVisible(bool(text))
    window.quote_scheme_table.fit_columns()


def _set_list_busy(window, busy):
    window.quote_scheme_query.setEnabled(not busy)
    window.quote_scheme_reset.setEnabled(not busy)
    window.quote_scheme_footer_pages.setEnabled(not busy)


def _load_list(window, page=1):
    if getattr(window, "_quote_scheme_list_worker", None) is not None:
        return
    try:
        params = _filters(window, page)
    except ValueError as error:
        window.quote_scheme_table.setRowCount(0)
        window.quote_scheme_count.setText("记录数：未查询")
        window.quote_scheme_prev.setEnabled(False)
        window.quote_scheme_next.setEnabled(False)
        _list_state(window, str(error), "error")
        return
    _set_list_busy(window, True)
    window.quote_scheme_table.setRowCount(0)
    _list_state(window, "正在加载报价方案…", "busy")
    path = "/api/quote-schemes?" + urllib.parse.urlencode(params)
    worker = _run(window, "GET", path, None, lambda result: _list_loaded(window, result),
                  lambda message: _list_failed(window, message))
    window._quote_scheme_list_worker = worker
    worker.finished.connect(lambda: setattr(window, "_quote_scheme_list_worker", None))


def _list_failed(window, message):
    window.quote_scheme_table.setRowCount(0)
    _set_list_busy(window, False)
    _list_state(window, "报价方案加载失败，请点击“查询”重试；仍失败请联系管理员。", "error")
    window.quote_scheme_page_status.setToolTip(str(message))
    window.quote_scheme_count.setText("记录数：加载失败")
    window.quote_scheme_prev.setEnabled(False)
    window.quote_scheme_next.setEnabled(False)


def _item(text, align=None):
    value = QTableWidgetItem(str(text if text not in (None, "") else "—"))
    value.setToolTip(value.text())
    if align is not None:
        value.setTextAlignment(align)
    return value


def _display_updated_at(value):
    # Keep the existing server-time semantics (also used by API date filters).
    # The reference layout omits seconds; the full value stays in the tooltip.
    return str(value or "").replace("T", " ")[:16]


def _list_loaded(window, result):
    table = window.quote_scheme_table
    rows = list(result.get("items") or [])
    table.setRowCount(len(rows))
    for row, scheme in enumerate(rows):
        scheme_no = str(scheme.get("scheme_no") or "")
        status = str(scheme.get("status") or "DRAFT")
        amount = scheme.get("quoted_amount")
        values = [
            scheme_no, scheme.get("company_name"), _display_products(scheme.get("product_summary")),
            STATUS_TEXT.get(status, status),
            "—" if amount is None else f"¥ {float(amount):,.2f}",
            scheme.get("creator_name"), scheme.get("last_editor_name"),
            _display_updated_at(scheme.get("updated_at")),
        ]
        for column, value in enumerate(values):
            alignment = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignRight if column == 4 else Qt.AlignmentFlag.AlignLeft
            )
            table.setItem(row, column, _item(value, alignment))
        table.item(row, 7).setToolTip(str(scheme.get("updated_at") or "—"))
        table.item(row, 3).setData(Qt.ItemDataRole.UserRole, status)
        table.setCellWidget(row, 8, _row_actions(window, scheme))
        table.item(row, 0).setData(Qt.ItemDataRole.UserRole, deepcopy(scheme))
    total = int(result.get("total") or 0)
    page = int(result.get("page") or 1)
    size = int(result.get("page_size") or window.quote_scheme_page_size.currentData() or PAGE_SIZES[0])
    pages = max(1, (total + size - 1) // size)
    window._quote_scheme_page = page
    window._quote_scheme_pages = pages
    window.quote_scheme_count.setText(f"共 {total} 条记录")
    window.quote_scheme_page_label.setText(f"第 {page} / {pages} 页")
    size_index = window.quote_scheme_page_size.findData(size)
    if size_index >= 0:
        window.quote_scheme_page_size.blockSignals(True)
        window.quote_scheme_page_size.setCurrentIndex(size_index)
        window.quote_scheme_page_size.blockSignals(False)
    _update_page_buttons(window, page, pages)
    window.quote_scheme_prev.setEnabled(page > 1)
    window.quote_scheme_next.setEnabled(page < pages)
    _set_list_busy(window, False)
    window.quote_scheme_page_status.setToolTip("")
    _list_state(window, "" if rows else "暂无报价方案\n可调整查询条件，或点击“新建方案”开始。")
    table.fit_columns()


def _row_actions(window, scheme):
    status = str(scheme.get("status") or "DRAFT")
    scheme_no = scheme["scheme_no"]
    actions = [("打开", lambda _checked=False: _open_scheme(window, scheme_no))]
    if status in ("QUOTED", "ARCHIVED"):
        actions.extend([
            ("打印", lambda _checked=False: _open_scheme(window, scheme_no, 2, "print")),
            ("导出", lambda _checked=False: _open_scheme(window, scheme_no, 2, "export")),
        ])
    actions.append(("复制", lambda _checked=False: _scheme_action(window, scheme, "copy")))
    if status == "QUOTED":
        actions.append(("修订", lambda _checked=False: _scheme_action(window, scheme, "revision")))
        actions.append(("归档", lambda _checked=False: _confirm_transition(window, scheme, "archive")))
    elif status == "REVISING":
        actions.append(("修订", lambda _checked=False: _open_scheme(window, scheme_no)))
    elif status == "ARCHIVED":
        actions.append(("恢复", lambda _checked=False: _confirm_transition(window, scheme, "restore")))
    if status != "VOID":
        actions.append(("作废", lambda _checked=False: _confirm_transition(window, scheme, "void")))
    if status == "DRAFT" and not scheme.get("has_successful_export"):
        actions.append(("删除未使用草稿", lambda _checked=False: _confirm_delete(window, scheme)))
    primary = {
        "DRAFT": ("打开", "复制"), "QUOTED": ("打开", "打印", "导出"),
        "REVISING": ("打开", "修订"), "ARCHIVED": ("打开", "导出"), "VOID": ("打开",),
    }.get(status, ("打开",))
    return RowActions(actions, primary)


def _selected_scheme(window):
    rows = window.quote_scheme_table.selectionModel().selectedRows()
    return window.quote_scheme_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None


def _open_selected_row(window):
    scheme = _selected_scheme(window)
    if scheme: _open_scheme(window, scheme["scheme_no"])


def _open_scheme(window, scheme_no, route=3, after_open=None):
    busy = getattr(window, "_quote_scheme_save_worker", None)
    if busy is not None and busy.isRunning():
        QMessageBox.information(window, "方案保存中", "请等待当前方案保存完成后再打开其他方案。")
        return
    _set_state(window, "正在从服务器恢复方案…", "busy")
    _run(window, "GET", "/api/quote-schemes/" + urllib.parse.quote(scheme_no), None,
         lambda result: _apply_opened_scheme(window, result, route, after_open),
         lambda message: _set_state(window, f"打开失败：{message}", "error"))


def _apply_read_only(window, read_only):
    window._quote_scheme_read_only = bool(read_only)
    if hasattr(window, "summary_table"):
        window.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers if read_only else QAbstractItemView.EditTrigger.DoubleClicked)
    if hasattr(window, "scheme2_quote_preview"):
        window.scheme2_quote_preview.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers if read_only
            else QAbstractItemView.EditTrigger.DoubleClicked
        )
    for control in getattr(window, "scheme2_cost_controls", {}).values(): control.setEnabled(not read_only)
    for button in getattr(window, "scheme2_cost_action_buttons", []):
        if button.text() not in ("返回", "生成报价单"): button.setEnabled(not read_only)
    if hasattr(window, "scheme2_add_button"): window.scheme2_add_button.setEnabled(not read_only)
    if hasattr(window, "scheme2_company"): window.scheme2_company.setEnabled(not read_only)
    for name in (
        "scheme2_name_edit", "quote_spec_edit", "product_combo", "quantity_spin",
        "cabinet_body_thickness_spin", "material_combo", "coating_combo",
        "scheme2_color_combo", "single_door_combo", "double_door_combo", "notes_text",
    ):
        control = getattr(window, name, None)
        if control is not None:
            control.setEnabled(not read_only)
    for name in ("scheme2_attachment_field", "scheme2_attachment_button"):
        attachment_host = getattr(window, name, None)
        if attachment_host is not None:
            attachment_host.setEnabled(not read_only)


def _apply_opened_scheme(window, result, route=3, after_open=None):
    from scheme2_ui import _apply_order_workspace_payload
    snapshot = deepcopy(result.get("snapshot") or {})
    window._quote_scheme_loading = True
    try:
        window._quote_scheme_id = str(result.get("scheme_no") or "")
        window._quote_scheme_version = int(result.get("lock_version") or 1)
        window._quote_scheme_business_version = int(result.get("version_no") or 1)
        window._quote_scheme_status = str(result.get("status") or "DRAFT")
        document = snapshot.get("document") if isinstance(snapshot.get("document"), dict) else {}
        window._quote_scheme_quote_date = str(document.get("quote_date") or str(result.get("created_at") or "")[:10] or date.today().isoformat())
        _apply_order_workspace_payload(window, snapshot, f"已从服务器恢复：{window._quote_scheme_id}")
        _apply_read_only(window, window._quote_scheme_status in ("QUOTED", "ARCHIVED", "VOID"))
        window.show_section(route)
        window._quote_scheme_dirty_seq = 0
        window._quote_scheme_saved_seq = 0
        window._quote_scheme_save_pending = False
        window._quote_scheme_last_save_failed = False
    finally:
        window._quote_scheme_loading = False
    _set_state(window, f"{window._quote_scheme_id} · 已保存 {str(result.get('updated_at') or '')[:19]}", "ok")
    if after_open == "print":
        QTimer.singleShot(0, lambda: window.scheme2_quote_print.click())
    elif after_open == "export":
        QTimer.singleShot(0, lambda: window.scheme2_quote_export.click())


def _new_scheme(window):
    busy = getattr(window, "_quote_scheme_save_worker", None) or getattr(window, "_quote_scheme_create_worker", None)
    if busy is not None and busy.isRunning():
        QMessageBox.information(window, "方案保存中", "请等待当前方案保存完成后再新建方案。")
        return
    if window._quote_scheme_id or getattr(window, "draft_items", []):
        answer = QMessageBox.question(window, "新建方案", "将清空当前工作区并开始新方案。是否继续？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
    window._quote_scheme_id = ""; window._quote_scheme_version = 0; window._quote_scheme_status = ""
    window._quote_scheme_business_version = 1
    window._quote_scheme_quote_date = date.today().isoformat()
    window._quote_scheme_dirty_seq = 0; window._quote_scheme_saved_seq = 0
    window._quote_scheme_save_pending = False; window._quote_scheme_last_save_failed = False
    window.draft_items = []
    _apply_read_only(window, False)
    window.refresh_summary(); window.show_section(1)
    _set_state(window, "新方案尚未生成编号；首次加入报价清单后由服务器编号。")


def _ensure_created(window):
    if window._quote_scheme_id or window._quote_scheme_create_worker is not None or not getattr(window, "draft_items", []): return
    operator_name = _require_operator(window, True)
    if not operator_name:
        window._quote_scheme_last_save_failed = True
        return
    _set_state(window, "正在创建草稿并生成方案编号…", "busy")
    worker = _run(window, "POST", "/api/quote-schemes", {"snapshot": _snapshot(window), "operator_name": operator_name},
                  lambda result: _created(window, result),
                  lambda message: _create_failed(window, message))
    window._quote_scheme_create_worker = worker
    worker.finished.connect(lambda: setattr(window, "_quote_scheme_create_worker", None))


def _created(window, result):
    window._quote_scheme_id = str(result.get("scheme_no") or "")
    window._quote_scheme_version = int(result.get("lock_version") or 1)
    window._quote_scheme_business_version = int(result.get("version_no") or 1)
    window._quote_scheme_status = str(result.get("status") or "DRAFT")
    window._quote_scheme_quote_date = str(result.get("created_at") or date.today().isoformat())[:10]
    window._quote_scheme_last_save_failed = False
    _set_state(window, f"{window._quote_scheme_id} · 已保存", "ok")
    _schedule_save(window)


def _create_failed(window, message):
    window._quote_scheme_last_save_failed = True
    _set_state(window, f"草稿创建失败：{message}。当前内容尚未保存到服务器。", "error")


def _schedule_save(window):
    if getattr(window, "_quote_scheme_loading", False) or getattr(window, "_quote_scheme_read_only", False): return
    if not window._quote_scheme_id: return
    window._quote_scheme_dirty_seq += 1
    if window._quote_scheme_save_worker is not None:
        window._quote_scheme_save_pending = True
    window._quote_scheme_save_timer.start(500)
    _set_state(window, f"{window._quote_scheme_id} · 等待自动保存", "busy")


def _save(window):
    if not window._quote_scheme_id: return
    if window._quote_scheme_save_worker is not None:
        window._quote_scheme_save_pending = True
        return
    operator_name = _require_operator(window, False)
    if not operator_name:
        window._quote_scheme_last_save_failed = True
        return
    scheme_no = window._quote_scheme_id
    sequence = window._quote_scheme_dirty_seq
    _set_state(window, f"{window._quote_scheme_id} · 保存中…", "busy")
    payload = {"expected_version": window._quote_scheme_version, "snapshot": _snapshot(window),
               "operator_name": operator_name}
    worker = _run(window, "PUT", "/api/quote-schemes/" + urllib.parse.quote(window._quote_scheme_id), payload,
                  lambda result: _saved(window, result, scheme_no, sequence),
                  lambda message: _save_failed(window, message, scheme_no))
    window._quote_scheme_save_worker = worker
    worker.finished.connect(lambda: _save_finished(window, worker, scheme_no, sequence))


def _saved(window, result, scheme_no=None, sequence=None):
    if scheme_no is not None and window._quote_scheme_id != scheme_no:
        return
    window._quote_scheme_version = int(result.get("lock_version") or window._quote_scheme_version)
    if sequence is not None:
        window._quote_scheme_saved_seq = max(window._quote_scheme_saved_seq, int(sequence))
    window._quote_scheme_last_save_failed = False
    stamp = str(result.get("updated_at") or QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))[:19].replace("T", " ")
    _set_state(window, f"{window._quote_scheme_id} · 已保存 {stamp}", "ok")


def _save_failed(window, message, scheme_no=None):
    if scheme_no is not None and window._quote_scheme_id != scheme_no:
        return
    window._quote_scheme_last_save_failed = True
    _set_state(window, f"保存失败：{message}。请重试，关闭前不会把本地状态冒充为已保存。", "error")


def _save_finished(window, worker, scheme_no, sequence):
    if window._quote_scheme_save_worker is worker:
        window._quote_scheme_save_worker = None
    if window._quote_scheme_id != scheme_no:
        return
    needs_save = window._quote_scheme_save_pending or window._quote_scheme_dirty_seq > max(
        window._quote_scheme_saved_seq, int(sequence),
    )
    window._quote_scheme_save_pending = False
    if needs_save and not window._quote_scheme_last_save_failed:
        QTimer.singleShot(0, lambda: _save(window))


def _scheme_action(window, scheme, action):
    operator_name = _require_operator(window, True)
    if not operator_name:
        return
    _set_state(window, "正在创建新方案…", "busy")
    path = f"/api/quote-schemes/{urllib.parse.quote(scheme['scheme_no'])}/{action}"
    payload = {"expected_version": scheme["lock_version"], "operator_name": operator_name}
    _run(window, "POST", path, payload, lambda result: _open_scheme(window, result["scheme_no"], 1 if action == "copy" else 3),
         lambda message: _set_state(window, f"操作失败：{message}", "error"))


def _confirm_transition(window, scheme, action):
    labels = {"archive":"归档", "restore":"恢复", "void":"作废"}
    label = labels[action]
    answer = QMessageBox.question(window, label, f"确认{label}方案 {scheme['scheme_no']}？该操作将记录审计信息。",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    if answer != QMessageBox.StandardButton.Yes: return
    operator_name = _require_operator(window, True)
    if not operator_name:
        return
    path = f"/api/quote-schemes/{urllib.parse.quote(scheme['scheme_no'])}/{action}"
    _run(window, "POST", path, {"expected_version": scheme["lock_version"], "operator_name": operator_name},
         lambda _r: _load_list(window, window._quote_scheme_page))


def _confirm_delete(window, scheme):
    answer = QMessageBox.question(window, "删除未使用草稿", f"仅未导出过的草稿允许删除。确认删除 {scheme['scheme_no']}？",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    if answer != QMessageBox.StandardButton.Yes: return
    operator_name = _require_operator(window, True)
    if not operator_name:
        return
    path = f"/api/quote-schemes/{urllib.parse.quote(scheme['scheme_no'])}?" + urllib.parse.urlencode({
        "expected_version": scheme["lock_version"], "operator_name": operator_name,
    })
    _run(window, "DELETE", path, None, lambda _r: _load_list(window, window._quote_scheme_page))


def _record_export(window, succeeded, kind="XLSX"):
    if not window._quote_scheme_id: return
    operator_name = _require_operator(window, False)
    if not operator_name:
        window._quote_scheme_last_save_failed = True
        return
    path = f"/api/quote-schemes/{urllib.parse.quote(window._quote_scheme_id)}/export-result"
    payload = {"kind":kind, "succeeded":bool(succeeded), "expected_version":window._quote_scheme_version,
               "operator_name":operator_name, "detail":{"client_version":CLIENT_VERSION}}
    if succeeded: payload["snapshot"] = _snapshot(window)
    _run(window, "POST", path, payload,
         lambda result: _export_recorded(window, result) if succeeded else None,
         lambda message: _set_state(window, f"导出结果登记失败：{message}", "error"))


def _export_recorded(window, result):
    window._quote_scheme_status = str(result.get("status") or window._quote_scheme_status)
    window._quote_scheme_version = int(result.get("lock_version") or window._quote_scheme_version)
    _apply_read_only(window, window._quote_scheme_status in ("QUOTED", "ARCHIVED", "VOID"))
    _set_state(window, f"{window._quote_scheme_id} · 已报价并保存导出记录", "ok")


def install_quote_scheme_center(namespace):
    cls = namespace["MainWindow"]
    if getattr(cls, "_quote_scheme_center_installed", False): return
    cls._quote_scheme_center_installed = True
    original_init, original_section = cls.__init__, cls.show_section
    original_refresh, original_add, original_close = cls.refresh_summary, cls.add_current_to_summary, cls.closeEvent

    def init(window, *args, **kwargs):
        original_init(window, *args, **kwargs)
        window.setWindowTitle(f"AI 双报价系统 · {CLIENT_VERSION}")
        window._quote_scheme_headers_factory = namespace.get("api_headers")
        window._quote_scheme_id = ""; window._quote_scheme_version = 0; window._quote_scheme_status = ""
        window._quote_scheme_business_version = 1; window._quote_scheme_quote_date = date.today().isoformat()
        window._quote_scheme_workers = set(); window._quote_scheme_list_worker = None
        window._quote_scheme_create_worker = None; window._quote_scheme_save_worker = None
        window._quote_scheme_last_save_failed = False; window._quote_scheme_loading = False
        window._quote_scheme_dirty_seq = 0; window._quote_scheme_saved_seq = 0
        window._quote_scheme_save_pending = False
        window._quote_scheme_page = 1; window._quote_scheme_read_only = False
        window._quote_scheme_save_timer = QTimer(window); window._quote_scheme_save_timer.setSingleShot(True)
        window._quote_scheme_save_timer.timeout.connect(lambda: _save(window))
        window.stack.addWidget(_build_page(window))
        nav = window.scheme2_nav; layout = nav.layout()
        button = QPushButton("报价方案"); button.setObjectName("navButton"); button.setCheckable(True); button.setFixedHeight(28)
        button.clicked.connect(lambda: window.show_section(SCHEME_ROUTE))
        # Keep the established workflow order from the approved V0 sidebar:
        # selection -> cost -> quote sheet -> quote schemes.
        insert_at = max(1, layout.indexOf(window.nav_buttons[-1]) + 1)
        layout.insertWidget(insert_at, button)
        window.quote_scheme_nav_button = button
        window.nav_buttons.append(button)
        window.nav_routes = (
            (1, "选型配置", "", None),
            (3, "成本计算", "", None),
            (2, "报价单", "", None),
            (SCHEME_ROUTE, "报价方案", "", None),
        )
        window.quote_scheme_save_status = QLabel()
        window.quote_scheme_save_status.setWordWrap(True)
        window.quote_scheme_save_status.hide()
        service = getattr(window, "scheme2_service_status", None)
        layout.insertWidget(max(0, layout.indexOf(service)), window.quote_scheme_save_status)
        for control in (
            getattr(window, "scheme2_company", None), getattr(window, "scheme2_name_edit", None),
            getattr(window, "quote_spec_edit", None), getattr(window, "quantity_spin", None),
            getattr(window, "cabinet_body_thickness_spin", None), getattr(window, "product_combo", None),
            getattr(window, "material_combo", None), getattr(window, "coating_combo", None),
            getattr(window, "scheme2_color_combo", None), getattr(window, "single_door_combo", None),
            getattr(window, "double_door_combo", None), getattr(window, "notes_text", None),
        ):
            signal = (getattr(control, "textChanged", None) or getattr(control, "currentTextChanged", None)
                      or getattr(control, "valueChanged", None))
            if signal is not None: signal.connect(lambda *_: _schedule_save(window))
        success = window.export_succeeded
        def export_succeeded(owner, *items, **named):
            result = success(*items, **named)
            _record_export(window, True)
            return result
        window.export_succeeded = export_succeeded.__get__(window, type(window))
        window.quote_scheme_print_succeeded = lambda: _record_export(window, True, "PRINT")
        for name in ("export_failed", "persistence_failed", "finalization_failed"):
            prior = getattr(window, name, None)
            if callable(prior):
                def failed(owner, message, callback=prior):
                    result = callback(message); _record_export(window, False); return result
                setattr(window, name, failed.__get__(window, type(window)))
        prior_move = getattr(window, "move_selected_item", None)
        if callable(prior_move):
            def guarded_move(delta):
                if not window._quote_scheme_read_only:
                    return prior_move(delta)
                return None
            window.move_selected_item = guarded_move

    def section(window, index):
        if index == SCHEME_ROUTE:
            window.stack.setCurrentIndex(SCHEME_ROUTE)
            for button in window.nav_buttons: button.setChecked(button is window.quote_scheme_nav_button)
            # This route previously skipped the current workbench layout pass,
            # leaving the selection page's "加入报价清单" dock visible here.
            from scheme2_ui import _apply_responsive
            _apply_responsive(window)
            QTimer.singleShot(0, lambda: _apply_responsive(window))
            _load_list(window, window._quote_scheme_page)
            return
        result = original_section(window, index)
        if hasattr(window, "quote_scheme_nav_button"): window.quote_scheme_nav_button.setChecked(False)
        return result

    def refresh(window):
        result = original_refresh(window)
        if hasattr(window, "_quote_scheme_save_timer"): _schedule_save(window)
        return result

    def add(window, *args, **kwargs):
        before = len(getattr(window, "draft_items", []))
        result = original_add(window, *args, **kwargs)
        if len(getattr(window, "draft_items", [])) > before: QTimer.singleShot(0, lambda: _ensure_created(window))
        return result

    def close(window, event):
        if window._quote_scheme_save_timer.isActive() and window._quote_scheme_id:
            window._quote_scheme_save_timer.stop(); _save(window)
        busy = window._quote_scheme_save_worker or window._quote_scheme_create_worker
        if busy is not None and busy.isRunning():
            QMessageBox.information(window, "方案保存中", "请等待当前报价方案保存请求完成后再关闭客户端。")
            event.ignore(); return
        if window._quote_scheme_last_save_failed and window._quote_scheme_id:
            answer = QMessageBox.warning(window, "报价方案尚未保存", "最近一次服务器保存失败，关闭将丢失未保存修改。仍要关闭吗？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: event.ignore(); return
        if window._quote_scheme_id and window._quote_scheme_dirty_seq > window._quote_scheme_saved_seq:
            QMessageBox.warning(window, "报价方案尚未保存", "仍有修改尚未保存到服务器，请等待保存完成后再关闭。")
            event.ignore(); return
        return original_close(window, event)

    cls.__init__, cls.show_section = init, section
    cls.refresh_summary, cls.add_current_to_summary, cls.closeEvent = refresh, add, close

