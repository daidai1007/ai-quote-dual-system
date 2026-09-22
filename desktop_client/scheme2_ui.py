"""Install the approved ``界面方案2`` presentation over the recovered V3 core.

The overlay deliberately keeps the core quote, attachment, confirmation and
export objects alive.  It changes their presentation and stores new row-local
editing state inside the existing draft-item JSON snapshots.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QPoint, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


OPTION_ROUTE = 1
COST_ROUTE = 3
DETAIL_ROUTE = 5
HEADERS = (
    "序号", "名称", "产品", "尺寸", "材料成本", "辅材成本", "人工成本",
    "附件成本", "喷涂费用", "管理费用", "运费", "数量", "成本单价",
    "面价", "已选附件", "成本明细",
)
MONEY_COLUMNS = frozenset(range(4, 14))
EDITABLE_COLUMNS = frozenset((10, 11))
ROLE_ROW = int(Qt.ItemDataRole.UserRole)


def _number(value, fallback=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result


def _money(value):
    return f"{_number(value):,.2f}"


def _formula(item):
    value = item.get("formula") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else {}


def _quick(item):
    value = item.get("quick") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else {}


def _attachment_amount(row):
    price = row.get("unit_price_override", row.get("matched_price", 0))
    sign = -1 if int(_number(row.get("attachment_price_sign", 1), 1)) == -1 else 1
    return max(0, int(_number(row.get("quantity", 1), 1))) * abs(_number(price)) * sign


def _attachment_total(item):
    return sum(_attachment_amount(row) for row in item.get("attachments", []) if isinstance(row, dict))


def _row_values(item):
    formula = _formula(item)
    quick = _quick(item)
    quantity = max(1, int(_number(item.get("quantity", 1), 1)))
    freight = max(0.0, _number(item.get("freight_fee", item.get("freight", 0))))
    formula_unit = _number(formula.get("total_cost")) + freight
    face_base = _number(quick.get("total_cost")) + freight
    face = face_base * _number(item.get("quick_discount", 1), 1)
    specification = str(item.get("specification") or item.get("model_code") or "—")
    name = str(item.get("name") or item.get("model_code") or "未命名")
    product = str(item.get("product_name") or item.get("product_code") or "—")
    attachments = [row for row in item.get("attachments", []) if isinstance(row, dict)]
    return (
        "", name, product, specification,
        _number(formula.get("material_cost")),
        _number(formula.get("auxiliary_cost")),
        _number(formula.get("labor_cost")),
        _number(formula.get("attachment_fee"), _attachment_total(item)),
        _number(formula.get("spray_cost")),
        _number(formula.get("management_fee")),
        freight, quantity, formula_unit, face,
        f"{len(attachments)} 项 ›", "明细 ›",
    )


def _replace_component(item, key, value):
    formula = _formula(item)
    old = _number(formula.get(key))
    formula[key] = round(max(0.0, value), 2)
    formula["total_cost"] = round(max(0.0, _number(formula.get("total_cost")) - old + formula[key]), 2)


def _selected_row(window):
    table = getattr(window, "summary_table", None)
    if not isinstance(table, QTableWidget):
        return -1
    rows = table.selectionModel().selectedRows()
    if rows:
        return rows[0].row()
    return table.currentRow()


def _selected_item(window):
    row = _selected_row(window)
    items = getattr(window, "draft_items", [])
    return items[row] if 0 <= row < len(items) else None


def _field(label, control):
    box = QFrame()
    box.setObjectName("scheme2Field")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    text = QLabel(label)
    text.setObjectName("scheme2FieldLabel")
    layout.addWidget(text)
    layout.addWidget(control)
    return box


def _price_spin(value=0.0):
    control = QDoubleSpinBox()
    control.setRange(0, 999999.99)
    control.setDecimals(2)
    control.setSingleStep(.1)
    control.setValue(value)
    return control


class AttachmentEditor(QDialog):
    def __init__(self, window, item):
        super().__init__(window)
        self.window = window
        self.item = item
        self.setWindowTitle("已选附件")
        self.resize(720, 460)
        layout = QVBoxLayout(self)
        title = QLabel("已选附件")
        title.setObjectName("scheme2DialogTitle")
        layout.addWidget(title)
        note = QLabel("本报价内临时调整；数量和单价同时用于公式法与面价，不写入全局附件库。")
        note.setObjectName("scheme2Hint")
        layout.addWidget(note)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("名称", "规格", "数量", "单价"))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        add = QPushButton("＋ 临时附件")
        remove = QPushButton("删除所选")
        add.clicked.connect(self.add_row)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)
        for attachment in item.get("attachments", []):
            if isinstance(attachment, dict):
                self.add_row(attachment)

    def add_row(self, attachment=None):
        source = attachment if isinstance(attachment, dict) else {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = str(source.get("item_name") or source.get("name") or ("自定义附件" if not source else "附件"))
        spec = str(source.get("specification") or source.get("matched_specification") or "—")
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(spec))
        quantity = QSpinBox()
        quantity.setRange(1, 9999)
        quantity.setValue(max(1, int(_number(source.get("quantity", 1), 1))))
        price = _price_spin(abs(_number(source.get("unit_price_override", source.get("matched_price", 0)))))
        self.table.setCellWidget(row, 2, quantity)
        self.table.setCellWidget(row, 3, price)
        self.table.item(row, 0).setData(ROLE_ROW, dict(source))

    def accept(self):
        old_total = _number(_formula(self.item).get("attachment_fee"), _attachment_total(self.item))
        rows = []
        for row in range(self.table.rowCount()):
            data = self.table.item(row, 0).data(ROLE_ROW) or {}
            data = dict(data)
            data["item_name"] = self.table.item(row, 0).text().strip() or "自定义附件"
            data["specification"] = self.table.item(row, 1).text().strip()
            data["quantity"] = self.table.cellWidget(row, 2).value()
            data["unit_price_override"] = self.table.cellWidget(row, 3).value()
            data["matched_price"] = data["unit_price_override"]
            data["quick_amount_override"] = data["quantity"] * data["unit_price_override"]
            data.setdefault("selection_source", "QUOTE_LOCAL")
            rows.append(data)
        self.item["attachments"] = rows
        new_total = _attachment_total(self.item)
        for quote in (_formula(self.item), _quick(self.item)):
            previous = _number(quote.get("attachment_fee"), old_total)
            quote["attachment_fee"] = round(new_total, 2)
            quote["total_cost"] = round(_number(quote.get("total_cost")) - previous + new_total, 2)
        self.window.refresh_summary()
        super().accept()


class FaceDiscountEditor(QDialog):
    def __init__(self, window, item):
        super().__init__(window)
        self.window = window
        self.item = item
        self.setWindowTitle("面价折扣")
        self.setFixedWidth(330)
        layout = QVBoxLayout(self)
        title = QLabel("面价折扣")
        title.setObjectName("scheme2DialogTitle")
        layout.addWidget(title)
        base = _number(_quick(item).get("total_cost")) + _number(item.get("freight_fee", 0))
        layout.addWidget(QLabel(f"原面价    {_money(base)} 元"))
        self.discount = QDoubleSpinBox()
        self.discount.setRange(0.01, 10)
        self.discount.setDecimals(4)
        self.discount.setSingleStep(.01)
        self.discount.setValue(_number(item.get("quick_discount", 1), 1))
        layout.addWidget(_field("折扣（0.85 表示 85%）", self.discount))
        self.preview = QLabel()
        self.preview.setObjectName("scheme2DiscountPreview")
        layout.addWidget(self.preview)
        self.discount.valueChanged.connect(lambda value: self.preview.setText(f"折后面价    {_money(base * value)} 元"))
        self.discount.valueChanged.emit(self.discount.value())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        self.item["quick_discount"] = self.discount.value()
        self.window.refresh_summary()
        super().accept()


def _detail_rows(item):
    existing = item.get("cost_detail_rows")
    if isinstance(existing, list) and existing:
        return existing
    formula = _formula(item)
    rows = []
    for detail in formula.get("cabinet_material_part_details", []) or []:
        if not isinstance(detail, dict):
            continue
        rows.append({
            "category": "material_cost", "type": "材料成本", "name": detail.get("part_name", "材料"),
            "spec": f"{detail.get('material_code', '')} / {detail.get('sheet_thickness_mm', '')} mm",
            "formula": detail.get("area_formula", ""), "quantity": detail.get("billable_weight_kg", 0),
            "unit": "kg", "unit_price": detail.get("material_unit_price", 0),
            "base_amount": detail.get("material_cost", 0), "factor": 1.0,
        })
    for detail in formula.get("cabinet_spray_part_details", []) or []:
        if not isinstance(detail, dict):
            continue
        area = _number(detail.get("total_area_m2"))
        unit_price = _number(formula.get("spray_unit_price"))
        rows.append({
            "category": "spray_cost", "type": "喷涂费用", "name": detail.get("part_name", "喷涂"),
            "spec": str(formula.get("coating_type") or ""), "formula": detail.get("area_formula", ""),
            "quantity": area, "unit": "㎡", "unit_price": unit_price,
            "base_amount": area * unit_price, "factor": 1.0,
        })
    labels = {
        "material_cost": "材料成本", "auxiliary_cost": "辅材成本", "labor_cost": "人工成本",
        "attachment_fee": "附件成本", "spray_cost": "喷涂费用", "management_fee": "管理费用",
    }
    represented = {row.get("category") for row in rows}
    for key, label in labels.items():
        if key not in represented:
            amount = _number(formula.get(key))
            rows.append({"category": key, "type": label, "name": label, "spec": "报价快照汇总",
                         "formula": "现有报价结果", "quantity": 1, "unit": "项", "unit_price": amount,
                         "base_amount": amount, "factor": 1.0})
    item["cost_detail_rows"] = rows
    return rows


def _build_detail_page(window):
    page = QWidget()
    page.setObjectName("scheme2DetailPage")
    page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(18, 14, 18, 18)
    header = QHBoxLayout()
    back = QPushButton("‹ 返回成本计算")
    back.setObjectName("scheme2PrimaryGhost")
    title = QLabel("成本明细")
    title.setObjectName("scheme2PageTitle")
    header.addWidget(back)
    header.addWidget(title)
    header.addStretch(1)
    layout.addLayout(header)
    table = QTableWidget(0, 11)
    table.setObjectName("scheme2DetailTable")
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setHorizontalHeaderLabels((
        "成本类型", "明细项目", "规格/说明", "计算公式计算结果", "最终衡量", "单位",
        "单价（元）", "本项金额（元）", "系数", "行金额（元）", "备注",
    ))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    for column, width in enumerate((110, 160, 160, 270, 96, 66, 96, 112, 112, 112, 220)):
        table.setColumnWidth(column, width)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    layout.addWidget(table, 1)
    window.scheme2_detail_page = page
    window.scheme2_detail_table = table

    def close_detail():
        item = getattr(window, "_scheme2_detail_item", None)
        if isinstance(item, dict):
            totals = {}
            for row in item.get("cost_detail_rows", []):
                key = row.get("category")
                totals[key] = totals.get(key, 0.0) + _number(row.get("base_amount")) * _number(row.get("factor", 1), 1)
            for key, value in totals.items():
                _replace_component(item, key, value)
        window._scheme2_detail_item = None
        window.stack.setCurrentIndex(COST_ROUTE)
        window.refresh_summary()
        _apply_responsive(window)

    back.clicked.connect(close_detail)
    window.scheme2_close_detail = close_detail
    return page


def _show_detail(window, item):
    window._scheme2_detail_item = item
    table = window.scheme2_detail_table
    rows = _detail_rows(item)
    table.setRowCount(len(rows))
    for row_index, detail in enumerate(rows):
        amount = _number(detail.get("base_amount"))
        factor = _number(detail.get("factor", 1), 1)
        values = (
            detail.get("type", ""), detail.get("name", ""), detail.get("spec", ""), detail.get("formula", ""),
            f"{_number(detail.get('quantity')):,.4f}".rstrip("0").rstrip("."), detail.get("unit", ""),
            _money(detail.get("unit_price")), _money(amount), "", _money(amount * factor), detail.get("note", ""),
        )
        for column, value in enumerate(values):
            if column == 8:
                spin = QDoubleSpinBox()
                spin.setRange(.01, 10)
                spin.setDecimals(4)
                spin.setSingleStep(.01)
                spin.setValue(factor)
                spin.valueChanged.connect(lambda value, r=row_index, d=detail: (
                    d.__setitem__("factor", value),
                    table.item(r, 9).setText(_money(_number(d.get("base_amount")) * value)),
                ))
                table.setCellWidget(row_index, column, spin)
            else:
                table.setItem(row_index, column, QTableWidgetItem(str(value)))
    window.stack.setCurrentIndex(DETAIL_ROUTE)
    _apply_responsive(window)


def _cost_sidebar(window):
    bar = QFrame()
    bar.setObjectName("scheme2CostSidebar")
    bar.setFixedWidth(100)
    layout = QVBoxLayout(bar)
    layout.setContentsMargins(10, 12, 10, 12)
    layout.setSpacing(7)
    heading = QLabel("修改系数")
    heading.setObjectName("scheme2SidebarTitle")
    layout.addWidget(heading)
    company = getattr(window, "base_company_combo", None) or window.findChild(QComboBox, "baseCompanyCombo")
    if company is None:
        company = QComboBox()
    window.scheme2_company = company
    layout.addWidget(_field("下单公司", company))
    controls = {
        "galvanized_price": ("镀锌板价格", _price_spin(4.55)),
        "carbon_price": ("碳钢价格", _price_spin(4.20)),
        "waste_factor": ("废料系数", _price_spin(1.20)),
        "labor_discount": ("人工折扣", _price_spin(1.00)),
        "surface_price": ("表面处理价格", _price_spin(26.00)),
    }
    window.scheme2_cost_controls = {}
    for key, (label, control) in controls.items():
        if key in ("waste_factor", "labor_discount"):
            control.setRange(.01, 10)
            control.setDecimals(4)
        window.scheme2_cost_controls[key] = control
        layout.addWidget(_field(label, control))
        control.editingFinished.connect(lambda k=key, c=control: _apply_cost_control(window, k, c.value()))
    layout.addStretch(1)
    hint = QLabel("选中行时修改该行；未选中时作为下一项默认值")
    hint.setWordWrap(True)
    hint.setObjectName("scheme2SidebarHint")
    layout.addWidget(hint)
    return bar


def _apply_cost_control(window, key, value):
    item = _selected_item(window)
    if item is None:
        window.scheme2_defaults[key] = value
        hidden = {"waste_factor": "waste_factor_spin", "labor_discount": "labor_multiplier"}.get(key)
        control = getattr(window, hidden, None) if hidden else None
        if isinstance(control, QDoubleSpinBox):
            control.setValue(value)
        return
    state = item.setdefault("scheme2_cost_settings", {})
    old = _number(state.get(key), window.scheme2_defaults.get(key, value))
    state[key] = value
    formula = _formula(item)
    if key == "waste_factor":
        base = _number(item.setdefault("scheme2_cost_bases", {}).setdefault("material_cost", formula.get("material_cost")))
        original = _number(item.setdefault("scheme2_cost_bases", {}).setdefault("waste_factor", item.get("waste_factor", old)), 1.2)
        item["waste_factor"] = value
        _replace_component(item, "material_cost", base * value / max(original, .01))
    elif key == "labor_discount":
        base = _number(item.get("formula_base", formula).get("labor_cost", formula.get("labor_cost")))
        item["labor_multiplier"] = value
        _replace_component(item, "labor_cost", base * value)
        _replace_component(item, "management_fee", base * value * .13)
    elif key in ("carbon_price", "galvanized_price"):
        base_state = item.setdefault("scheme2_cost_bases", {})
        base = _number(base_state.setdefault("material_cost", formula.get("material_cost")))
        original_price = _number(base_state.setdefault(key, old), old)
        _replace_component(item, "material_cost", base * value / max(original_price, .01))
    elif key == "surface_price":
        base_state = item.setdefault("scheme2_cost_bases", {})
        base = _number(base_state.setdefault("spray_cost", formula.get("spray_cost")))
        original_price = _number(base_state.setdefault(key, old), old)
        _replace_component(item, "spray_cost", base * value / max(original_price, .01))
    window.refresh_summary()


def _build_cost_page(window):
    page = QWidget()
    page.setObjectName("scheme2CostPage")
    outer = QHBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addWidget(_cost_sidebar(window))
    body = QFrame()
    body.setObjectName("scheme2CostBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(14, 12, 14, 12)
    header = QHBoxLayout()
    title = QLabel("成本计算")
    title.setObjectName("scheme2PageTitle")
    hint = QLabel("运费、数量可直接编辑；点击面价设置折扣")
    hint.setObjectName("scheme2Hint")
    header.addWidget(title)
    header.addWidget(hint)
    header.addStretch(1)
    column_mode = QPushButton("完整 16 列")
    column_mode.setObjectName("scheme2PrimaryGhost")
    header.addWidget(column_mode)
    body_layout.addLayout(header)
    compact = QFrame()
    compact.setObjectName("scheme2CompactCoefficients")
    compact_row = QHBoxLayout(compact)
    compact_row.setContentsMargins(8, 5, 8, 5)
    compact_row.addWidget(QLabel("修改系数"))
    compact_key = QComboBox()
    compact_value = _price_spin(1.0)
    for key, label in (
        ("galvanized_price", "镀锌板价格"), ("carbon_price", "碳钢价格"),
        ("waste_factor", "废料系数"), ("labor_discount", "人工折扣"),
        ("surface_price", "表面处理价格"),
    ):
        compact_key.addItem(label, key)
    compact_row.addWidget(compact_key, 1)
    compact_row.addWidget(compact_value)
    compact.hide()
    body_layout.addWidget(compact)
    table = QTableWidget(0, len(HEADERS))
    table.setObjectName("summaryTable")
    table.setHorizontalHeaderLabels(HEADERS)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    table.verticalHeader().hide()
    table.horizontalHeader().setMinimumSectionSize(66)
    table.setColumnWidth(0, 52)
    table.setColumnWidth(1, 140)
    table.setColumnWidth(2, 90)
    table.setColumnWidth(3, 160)
    for column in range(4, 14):
        table.setColumnWidth(column, 92)
    table.setColumnWidth(14, 100)
    table.setColumnWidth(15, 88)
    window.summary_table = table
    body_layout.addWidget(table, 1)
    empty = QLabel("在选项配置页点击加入报价清单后，柜型会出现在这里", table.viewport())
    empty.setObjectName("scheme2EmptyState")
    empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty.hide()
    undo_bar = QFrame()
    undo_bar.setObjectName("scheme2UndoBar")
    undo_layout = QHBoxLayout(undo_bar)
    undo_layout.setContentsMargins(10, 4, 10, 4)
    undo_text = QLabel("已删除 1 行")
    undo = QPushButton("撤销")
    undo_layout.addWidget(undo_text)
    undo_layout.addStretch(1)
    undo_layout.addWidget(undo)
    undo_bar.hide()
    body_layout.addWidget(undo_bar)
    action_widget = QWidget()
    actions = QGridLayout(action_widget)
    actions.setContentsMargins(0, 0, 0, 0)
    delete = QPushButton("× 删除")
    up = QPushButton("↑ 上移")
    down = QPushButton("↓ 下移")
    edit = QPushButton("编辑选中项")
    back = QPushButton("返回选项配置")
    export = QPushButton("导出正式双报价单")
    export.setObjectName("scheme2PrimaryAction")
    action_buttons = (delete, up, down, edit, back, export)
    for column, button in enumerate(action_buttons):
        actions.addWidget(button, 0, column)
    actions.setColumnStretch(4, 1)
    body_layout.addWidget(action_widget)
    outer.addWidget(body, 1)
    delete.clicked.connect(lambda: _delete_selected(window))
    up.clicked.connect(lambda: window.move_selected_item(-1))
    down.clicked.connect(lambda: window.move_selected_item(1))
    edit.clicked.connect(lambda: _edit_selected(window))
    back.clicked.connect(lambda: window.show_section(OPTION_ROUTE))
    export.clicked.connect(lambda: window.confirm_and_export())
    undo.clicked.connect(lambda: _undo_delete(window))
    column_mode.clicked.connect(lambda: _set_cost_column_mode(window, not window._scheme2_full_columns))
    compact_key.currentIndexChanged.connect(lambda: _sync_compact_control(window))
    compact_value.editingFinished.connect(lambda: _apply_compact_control(window))
    table.cellChanged.connect(lambda row, column: _cost_cell_changed(window, row, column))
    table.cellClicked.connect(lambda row, column: _cost_cell_clicked(window, row, column))
    table.itemSelectionChanged.connect(lambda: _sync_sidebar(window))
    window.scheme2_cost_page = page
    window.scheme2_cost_sidebar = page.findChild(QFrame, "scheme2CostSidebar")
    window.scheme2_compact_coefficients = compact
    window.scheme2_compact_key = compact_key
    window.scheme2_compact_value = compact_value
    window.scheme2_cost_empty = empty
    window.scheme2_cost_export = export
    window.scheme2_cost_undo = undo_bar
    window.scheme2_undo_timer = QTimer(window)
    window.scheme2_undo_timer.setSingleShot(True)
    window.scheme2_undo_timer.timeout.connect(undo_bar.hide)
    window.scheme2_cost_action_grid = actions
    window.scheme2_cost_action_buttons = action_buttons
    window._scheme2_full_columns = False
    window._scheme2_deleted = None
    _set_cost_column_mode(window, False)
    return page


def _set_cost_column_mode(window, full):
    window._scheme2_full_columns = bool(full)
    core = {0, 1, 2, 3, 11, 12, 13, 15}
    for column in range(len(HEADERS)):
        window.summary_table.setColumnHidden(column, not full and column not in core)
    buttons = window.scheme2_cost_page.findChildren(QPushButton) if hasattr(window, "scheme2_cost_page") else []
    toggle = next((button for button in buttons if button.text() in ("完整 16 列", "核心 8 列")), None)
    if toggle is not None:
        toggle.setText("核心 8 列" if full else "完整 16 列")


def _sync_compact_control(window):
    key = window.scheme2_compact_key.currentData()
    source = window.scheme2_cost_controls.get(key)
    if source is None:
        return
    with QSignalBlocker(window.scheme2_compact_value):
        window.scheme2_compact_value.setDecimals(source.decimals())
        window.scheme2_compact_value.setRange(source.minimum(), source.maximum())
        window.scheme2_compact_value.setValue(source.value())


def _apply_compact_control(window):
    key = window.scheme2_compact_key.currentData()
    value = window.scheme2_compact_value.value()
    source = window.scheme2_cost_controls.get(key)
    if source is not None:
        source.setValue(value)
    _apply_cost_control(window, key, value)


def _delete_selected(window):
    row = _selected_row(window)
    items = getattr(window, "draft_items", [])
    if not 0 <= row < len(items):
        return
    window._scheme2_deleted = (row, items.pop(row))
    window.refresh_summary()
    window.scheme2_cost_undo.show()
    window.scheme2_undo_timer.start(5000)


def _undo_delete(window):
    deleted = getattr(window, "_scheme2_deleted", None)
    if deleted is None:
        return
    row, item = deleted
    window.draft_items.insert(min(row, len(window.draft_items)), item)
    window._scheme2_deleted = None
    window.scheme2_undo_timer.stop()
    window.scheme2_cost_undo.hide()
    window.refresh_summary()
    window.summary_table.selectRow(min(row, len(window.draft_items) - 1))


def _duplicate_selected(window):
    row = _selected_row(window)
    items = getattr(window, "draft_items", [])
    if not 0 <= row < len(items):
        return
    item = deepcopy(items[row])
    item["name"] = f"{item.get('name') or item.get('model_code') or '未命名'} - 副本"
    items.insert(row + 1, item)
    window.refresh_summary()
    window.summary_table.selectRow(row + 1)


def _layout_cost_actions(window, compact):
    grid = window.scheme2_cost_action_grid
    buttons = window.scheme2_cost_action_buttons
    while grid.count():
        grid.takeAt(0)
    if compact:
        for column, button in enumerate(buttons[:4]):
            grid.addWidget(button, 0, column)
        grid.addWidget(buttons[4], 1, 2)
        grid.addWidget(buttons[5], 1, 3)
        grid.setColumnStretch(1, 1)
    else:
        for column, button in enumerate(buttons):
            grid.addWidget(button, 0, column)
        grid.setColumnStretch(4, 1)


def _edit_selected(window):
    item = _selected_item(window)
    if item is None:
        return
    window._scheme2_edit_item = item
    window._scheme2_active_settings = dict(
        item.get("scheme2_cost_settings", window.scheme2_defaults)
    )
    window.load_draft_item(item)
    window.scheme2_name_edit.setText(str(item.get("name") or item.get("model_code") or ""))
    window.show_section(OPTION_ROUTE)


def _cost_cell_changed(window, row, column):
    if getattr(window, "_scheme2_refreshing", False) or column not in EDITABLE_COLUMNS:
        return
    items = getattr(window, "draft_items", [])
    if not 0 <= row < len(items):
        return
    cell = window.summary_table.item(row, column)
    if cell is None:
        return
    value = _number(cell.text(), -1)
    if value < 0:
        window.refresh_summary()
        return
    item = items[row]
    if column == 10:
        item["freight_fee"] = value
    else:
        item["quantity"] = max(1, int(value))
        drawing_ref = getattr(window, "_draft_drawing_refs", {}).get(id(item))
        if drawing_ref and drawing_ref[0] is not None:
            drawing_ref[0]["quantity"] = item["quantity"]
    window.refresh_summary()


def _cost_cell_clicked(window, row, column):
    items = getattr(window, "draft_items", [])
    if not 0 <= row < len(items):
        return
    item = items[row]
    if column == 13:
        FaceDiscountEditor(window, item).exec()
    elif column == 14:
        AttachmentEditor(window, item).exec()
    elif column == 15:
        _show_detail(window, item)


def _sync_sidebar(window):
    item = _selected_item(window)
    state = item.get("scheme2_cost_settings", {}) if isinstance(item, dict) else window.scheme2_defaults
    for key, control in window.scheme2_cost_controls.items():
        with QSignalBlocker(control):
            control.setValue(_number(state.get(key), window.scheme2_defaults[key]))
    if hasattr(window, "scheme2_compact_key"):
        _sync_compact_control(window)


def _refresh_cost_table(window):
    table = window.summary_table
    items = getattr(window, "draft_items", [])
    selected = _selected_row(window)
    window._scheme2_refreshing = True
    try:
        empty = getattr(window, "scheme2_cost_empty", None)
        export = getattr(window, "scheme2_cost_export", None)
        if empty is not None:
            empty.setGeometry(table.viewport().rect())
            empty.setVisible(not items)
            empty.raise_()
        if export is not None:
            export.setEnabled(bool(items))
        if not items:
            table.setRowCount(0)
            return
        table.setRowCount(len(items) + 1)
        for row, item in enumerate(items):
            values = list(_row_values(item))
            values[0] = row + 1
            for column, value in enumerate(values):
                text = _money(value) if column in MONEY_COLUMNS and column != 11 else str(value)
                cell = QTableWidgetItem(text)
                if column not in EDITABLE_COLUMNS:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column in (13, 14, 15):
                    cell.setForeground(QColor("#185FA5"))
                    font = cell.font()
                    font.setUnderline(True)
                    cell.setFont(font)
                if column in MONEY_COLUMNS:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, column, cell)
        total_row = len(items)
        quantity_total = sum(max(1, int(_number(item.get("quantity", 1), 1))) for item in items)
        cost_total = sum(_row_values(item)[12] * max(1, int(_number(item.get("quantity", 1), 1))) for item in items)
        face_total = sum(_row_values(item)[13] * max(1, int(_number(item.get("quantity", 1), 1))) for item in items)
        for column in range(len(HEADERS)):
            if column == 0:
                text = "汇总"
            elif column == 11:
                text = str(quantity_total)
            elif column == 12:
                text = _money(cost_total)
            elif column == 13:
                text = _money(face_total)
            else:
                text = "—"
            cell = QTableWidgetItem(text)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
            font = cell.font()
            font.setBold(True)
            cell.setFont(font)
            cell.setBackground(QColor("#F6F7F9"))
            table.setItem(total_row, column, cell)
        if 0 <= selected < len(items):
            table.selectRow(selected)
    finally:
        window._scheme2_refreshing = False


def _find_nav(window):
    buttons = [button for button in getattr(window, "nav_buttons", []) if isinstance(button, QPushButton)]
    return buttons[0].parentWidget() if buttons else None


def _configure_navigation(window):
    nav = _find_nav(window)
    window.scheme2_nav = nav
    wanted = {}
    for button in list(getattr(window, "nav_buttons", [])):
        text = button.text().replace("&", "").strip()
        if text == "报价计算":
            wanted[OPTION_ROUTE] = button
        elif text == "报价清单":
            wanted[COST_ROUTE] = button
        else:
            button.hide()
    if OPTION_ROUTE not in wanted or COST_ROUTE not in wanted:
        visible = [button for button in getattr(window, "nav_buttons", []) if isinstance(button, QPushButton)]
        wanted.setdefault(OPTION_ROUTE, visible[0])
        wanted.setdefault(COST_ROUTE, visible[-1])
    labels = {OPTION_ROUTE: "选项配置", COST_ROUTE: "成本计算"}
    for route, button in wanted.items():
        button.show()
        button.setText(labels[route])
        button.setIcon(button.icon().__class__())
        try:
            button.clicked.disconnect()
        except RuntimeError:
            pass
        button.clicked.connect(lambda _checked=False, value=route: window.show_section(value))
    window.nav_buttons = [wanted[OPTION_ROUTE], wanted[COST_ROUTE]]
    window.nav_routes = ((OPTION_ROUTE, "选项配置", "", None), (COST_ROUTE, "成本计算", "", None))
    if nav is not None:
        nav.setFixedWidth(88)
        if nav.layout() is not None:
            nav.layout().setContentsMargins(8, 10, 8, 10)
            nav.layout().setSpacing(8)
        for name in ("brandBlock", "navSectionLabel", "navFooter"):
            child = nav.findChild(QWidget, name)
            if child is not None:
                child.hide()
        nav_brand = QFrame()
        nav_brand.setObjectName("scheme2NavBrand")
        nav_brand_layout = QHBoxLayout(nav_brand)
        nav_brand_layout.setContentsMargins(0, 0, 0, 4)
        nav_brand_layout.setSpacing(5)
        nav_logo = QLabel("AI")
        nav_logo.setObjectName("scheme2NavLogo")
        nav_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_logo.setFixedSize(18, 18)
        nav_title = QLabel("智能报价")
        nav_title.setObjectName("scheme2NavTitle")
        nav_brand_layout.addWidget(nav_logo)
        nav_brand_layout.addWidget(nav_title)
        nav.layout().insertWidget(0, nav_brand)
        collapse = QPushButton("«")
        collapse.setObjectName("scheme2CollapseButton")
        collapse.clicked.connect(lambda: _set_nav_collapsed(window, True, manual=True))
        nav.layout().addStretch(1)
        nav.layout().addWidget(collapse)
    expand = QPushButton("»", window)
    expand.setObjectName("scheme2ExpandButton")
    expand.setFixedSize(22, 74)
    expand.clicked.connect(lambda: _set_nav_collapsed(window, False, manual=True))
    expand.hide()
    expand.raise_()
    window.scheme2_expand_button = expand
    window._scheme2_nav_manual = None


def _set_nav_collapsed(window, collapsed, manual=False):
    if manual:
        window._scheme2_nav_manual = collapsed
    nav = getattr(window, "scheme2_nav", None)
    if nav is not None:
        nav.setVisible(not collapsed)
    expand = getattr(window, "scheme2_expand_button", None)
    if expand is not None:
        expand.setVisible(collapsed and window.stack.currentIndex() != DETAIL_ROUTE)
        expand.raise_()


def _apply_navigation_state(window):
    route = window.stack.currentIndex()
    forced = route in (COST_ROUTE, DETAIL_ROUTE)
    responsive = window.width() < 1100
    manual = getattr(window, "_scheme2_nav_manual", None)
    collapsed = forced or (manual if manual is not None else responsive)
    _set_nav_collapsed(window, bool(collapsed))
    if route == DETAIL_ROUTE:
        window.scheme2_expand_button.hide()


def _detach(widget):
    if widget is None:
        return None
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.removeWidget(widget)
    return widget


def _option_field(window, title, control, provenance=None):
    block = QFrame()
    block.setObjectName("scheme2OptionField")
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    heading = QHBoxLayout()
    label = QLabel(title)
    label.setObjectName("scheme2OptionLabel")
    heading.addWidget(label)
    heading.addStretch(1)
    if provenance:
        badge = QLabel("待识别")
        badge.setObjectName("scheme2ProvenancePending")
        heading.addWidget(badge)
        window.scheme2_provenance_labels[provenance] = badge
    layout.addLayout(heading)
    layout.addWidget(control)
    return block


def _mark_manual(window, key):
    window.scheme2_manual_fields.add(key)
    badge = window.scheme2_provenance_labels.get(key)
    if badge is not None:
        badge.setText("已改 ✎")
        badge.setObjectName("scheme2ProvenanceManual")
        badge.style().unpolish(badge)
        badge.style().polish(badge)


def _mark_ai(window, key):
    if key in window.scheme2_manual_fields:
        return
    badge = window.scheme2_provenance_labels.get(key)
    if badge is not None:
        badge.setText("AI ✓")
        badge.setObjectName("scheme2ProvenanceAi")
        badge.style().unpolish(badge)
        badge.style().polish(badge)


def _open_attachment_overlay(window, dialog_class, anchor):
    current = getattr(window, "_scheme2_attachment_overlay", None)
    if current is not None:
        try:
            current.raise_()
            current.show()
            return
        except RuntimeError:
            window._scheme2_attachment_overlay = None
    dimensions = tuple(
        float(getattr(window, name).value())
        for name in ("width_spin", "height_spin", "depth_spin")
    )
    base_url = getattr(window, "base_url", lambda: "")()
    dialog = dialog_class(
        [dict(item) for item in getattr(window, "attachments", []) if isinstance(item, dict)],
        api_url=base_url,
        parent=window,
        target_dimensions=dimensions,
    )
    dialog.setWindowTitle("选择附件")
    for label in dialog.findChildren(QLabel):
        text = label.text().strip()
        if "附件价格清单" in text:
            label.setText("选择附件")
        elif "单价和数量" in text or "价格" in text and "已选择" in text:
            label.setText("已选择附件；单击附件行可选中，数量可双击修改。")
    for button in dialog.findChildren(QPushButton):
        text = button.text().strip()
        if "附件库" in text or "重新读取价格" in text:
            button.hide()
        elif text == "确认选择":
            button.setText("确定")
    table = getattr(dialog, "table", None)
    if isinstance(table, QTableWidget):
        for column in range(table.columnCount()):
            header = table.horizontalHeaderItem(column)
            text = header.text() if header is not None else ""
            if "价格" in text or "单价" in text or "金额" in text:
                table.setColumnHidden(column, True)
    custom_rows = []
    custom_frame = QFrame()
    custom_layout = QHBoxLayout(custom_frame)
    custom_layout.setContentsMargins(0, 3, 0, 3)
    custom_toggle = QPushButton("＋ 新增附件")
    custom_name = QLineEdit()
    custom_name.setPlaceholderText("请输入附件名称")
    custom_add = QPushButton("添加")
    custom_name.hide()
    custom_add.hide()
    custom_layout.addWidget(custom_toggle)
    custom_layout.addWidget(custom_name, 1)
    custom_layout.addWidget(custom_add)
    if dialog.layout() is not None:
        dialog.layout().insertWidget(max(0, dialog.layout().count() - 1), custom_frame)

    def show_custom_input():
        custom_toggle.hide()
        custom_name.show()
        custom_add.show()
        custom_name.setFocus()

    def add_custom():
        name = custom_name.text().strip()
        if not name:
            return
        custom_rows.append({"item_name": name, "name": name, "quantity": 1, "matched_price": 0, "custom": True})
        custom_toggle.setText(f"＋ 新增附件（已新增 {len(custom_rows)} 项）")
        custom_name.clear()
        custom_name.hide()
        custom_add.hide()
        custom_toggle.show()

    custom_toggle.clicked.connect(show_custom_input)
    custom_add.clicked.connect(add_custom)
    custom_name.returnPressed.connect(add_custom)
    dialog.setObjectName("scheme2AttachmentOverlay")
    dialog.setModal(False)
    dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    dialog.setMinimumSize(0, 0)
    top_left = anchor.mapTo(window, QPoint(0, 0))
    dialog.setGeometry(top_left.x(), top_left.y(), anchor.width(), anchor.height())

    def apply_selection():
        selected = dialog.collect_attachments()
        selected = list(selected or []) + custom_rows
        window.attachments = [dict(item) for item in selected if isinstance(item, dict)]
        window.attachment_default_opt_outs = set(getattr(dialog, "default_selection_opt_outs", set()))
        window.attachment_default_quantity_overrides = set(getattr(dialog, "default_quantity_manual_overrides", set()))
        refresh = getattr(window, "update_attachment_view", None)
        if callable(refresh):
            refresh()
        window._scheme2_attachment_overlay = None
        dialog.deleteLater()

    def close_overlay():
        window._scheme2_attachment_overlay = None
        dialog.deleteLater()

    dialog.accepted.connect(apply_selection)
    dialog.rejected.connect(close_overlay)
    window._scheme2_attachment_overlay = dialog
    dialog.show()
    dialog.setFixedSize(anchor.size())
    dialog.move(top_left)
    dialog.raise_()


def _configure_option_page(window, namespace):
    old_page = window.stack.widget(OPTION_ROUTE)
    page = QWidget()
    page.setObjectName("scheme2OptionPage")
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(0)
    header = QFrame()
    header.setObjectName("scheme2TopBar")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(14, 8, 14, 8)
    logo = QLabel("AI")
    logo.setObjectName("scheme2TopLogo")
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    logo.setFixedSize(20, 20)
    brand = QLabel("智能报价")
    brand.setObjectName("scheme2Brand")
    service = old_page.findChild(QLabel, "serviceStatusBadge")
    if service is None:
        service = QLabel("报价服务已连接")
    else:
        _detach(service)
    service.setObjectName("scheme2ServiceStatus")
    saved = QLabel("快照已保存")
    saved.setObjectName("scheme2SavedStatus")
    header_layout.addWidget(logo)
    header_layout.addWidget(brand)
    header_layout.addStretch(1)
    header_layout.addWidget(saved)
    header_layout.addWidget(service)
    page_layout.addWidget(header)

    workspace = QSplitter(Qt.Orientation.Horizontal)
    workspace.setObjectName("scheme2Workspace")
    workspace.setHandleWidth(1)
    workspace.setChildrenCollapsible(False)
    page_layout.addWidget(workspace, 1)

    left_scroll = QScrollArea()
    left_scroll.setObjectName("scheme2OptionScroll")
    left_scroll.setWidgetResizable(True)
    left_scroll.setFrameShape(QFrame.Shape.NoFrame)
    left = QWidget()
    left.setObjectName("scheme2OptionForm")
    form = QVBoxLayout(left)
    form.setContentsMargins(14, 12, 14, 14)
    form.setSpacing(9)
    form_title = QLabel("选项配置")
    form_title.setObjectName("scheme2SectionTitle")
    form.addWidget(form_title)
    window.scheme2_provenance_labels = {}
    window.scheme2_manual_fields = set()

    name_edit = QLineEdit()
    name_edit.setObjectName("scheme2NameInput")
    name_edit.setPlaceholderText("名称（默认取图纸文件名，可修改）")
    window.scheme2_name_edit = name_edit
    form.addWidget(_option_field(window, "名称", name_edit))
    product = _detach(getattr(window, "product_combo", None))
    if product is not None:
        form.addWidget(_option_field(window, "产品", product))
    specification = _detach(getattr(window, "quote_spec_edit", None))
    if specification is not None:
        form.addWidget(_option_field(window, "尺寸", specification, "dimensions"))
        specification.textEdited.connect(lambda *_: _mark_manual(window, "dimensions"))
    ganged = _detach(getattr(window, "ganged_cabinet_panel", None))
    if ganged is not None:
        form.addWidget(ganged)
    quantity = _detach(getattr(window, "quantity_spin", None))
    if quantity is not None:
        form.addWidget(_option_field(window, "数量", quantity))

    material_row = QGridLayout()
    material_row.setContentsMargins(0, 0, 0, 0)
    material_row.setHorizontalSpacing(8)
    material = _detach(getattr(window, "material_combo", None))
    coating = _detach(getattr(window, "coating_combo", None))
    if material is not None:
        material_row.addWidget(_option_field(window, "材质", material, "material"), 0, 0)
        material.activated.connect(lambda *_: _mark_manual(window, "material"))
    if coating is not None:
        material_row.addWidget(_option_field(window, "表面处理", coating, "coating"), 0, 1)
        coating.activated.connect(lambda *_: _mark_manual(window, "coating"))
    form.addLayout(material_row)
    color = QComboBox()
    color.setObjectName("scheme2ColorCombo")
    color.addItems(("RAL7035 浅灰", "RAL7032 灰", "RAL9005 黑", "RAL9016 白", "蓝色", "自定义"))
    color.activated.connect(lambda *_: _mark_manual(window, "color"))
    window.scheme2_color_combo = color
    form.addWidget(_option_field(window, "颜色", color, "color"))
    thickness = _detach(getattr(window, "cabinet_body_thickness_spin", None))
    if thickness is not None:
        form.addWidget(_option_field(window, "箱体料厚", thickness))

    doors = QGridLayout()
    doors.setContentsMargins(0, 0, 0, 0)
    doors.setHorizontalSpacing(8)
    single = _detach(getattr(window, "single_door_combo", None))
    double = _detach(getattr(window, "double_door_combo", None))
    if single is not None:
        doors.addWidget(_option_field(window, "单开门", single), 0, 0)
    if double is not None:
        doors.addWidget(_option_field(window, "双开门", double), 0, 1)
    form.addLayout(doors)

    attachment_card = QFrame()
    attachment_card.setObjectName("scheme2AttachmentCard")
    attachment_layout = QVBoxLayout(attachment_card)
    attachment_layout.setContentsMargins(10, 9, 10, 10)
    attachment_layout.setSpacing(6)
    attachment_header = QHBoxLayout()
    attachment_header.addWidget(QLabel("附件"))
    attachment_header.addStretch(1)
    attachment_button = old_page.findChild(QPushButton, "quietAction")
    if attachment_button is not None:
        _detach(attachment_button)
        attachment_button.setText("选择附件…")
        try:
            attachment_button.clicked.disconnect()
        except RuntimeError:
            pass
        attachment_button.clicked.connect(
            lambda _checked=False: _open_attachment_overlay(
                window, namespace["AttachmentDialog"], left_scroll
            )
        )
        attachment_header.addWidget(attachment_button)
    attachment_layout.addLayout(attachment_header)
    attachment_table = _detach(getattr(window, "attachment_summary_table", None))
    if isinstance(attachment_table, QTableWidget):
        for column in range(attachment_table.columnCount()):
            header_item = attachment_table.horizontalHeaderItem(column)
            text = header_item.text() if header_item is not None else ""
            attachment_table.setColumnHidden(column, text in {"图片", "一级分类"} or "金额" in text)
        attachment_table.setMinimumHeight(72)
        attachment_table.setMaximumHeight(180)
        attachment_layout.addWidget(attachment_table)
    form.addWidget(attachment_card)
    form.addStretch(1)
    left_scroll.setWidget(left)
    workspace.addWidget(left_scroll)

    quote_date = getattr(window, "quote_date", None)
    if quote_date is not None:
        quote_date.setDate(QDate.currentDate())
        quote_date.hide()
    for name in ("waste_factor_spin", "labor_multiplier", "freight_spin", "formula_discount"):
        control = getattr(window, name, None)
        if control is not None:
            if name == "formula_discount" and hasattr(control, "setValue"):
                control.setValue(1.0)
            control.hide()

    right = getattr(window, "quote_drawing_preview", None)
    right_shell = QFrame()
    right_shell.setObjectName("scheme2DrawingShell")
    right_layout = QVBoxLayout(right_shell)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(0)
    drawing_header = QFrame()
    drawing_header.setObjectName("scheme2DrawingHeader")
    drawing_header_layout = QHBoxLayout(drawing_header)
    drawing_header_layout.setContentsMargins(12, 8, 12, 8)
    drawing_header_layout.addWidget(QLabel("当前柜体图纸"))
    drawing_header_layout.addStretch(1)
    counter = QLabel("已完成 0 / 0")
    counter.setObjectName("scheme2CompletionPill")
    drawing_header_layout.addWidget(counter)
    right_layout.addWidget(drawing_header)
    if right is not None:
        _detach(right)
        for label in right.findChildren(QLabel):
            if label.objectName() in {"cardTitle", "cardSubtitle"}:
                label.hide()
        for tool in right.findChildren(QPushButton):
            if tool.text().strip() in {"返回图纸识别", "返回报价计算"}:
                tool.hide()
        canvas = getattr(right, "canvas", None)
        if canvas is not None:
            canvas.setObjectName("scheme2DrawingCanvas")
        right_layout.addWidget(right, 1)
        right.show()
        footer = QFrame()
        footer.setObjectName("scheme2RecognitionFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(10, 8, 10, 8)
        status = QLabel("等待图纸识别")
        status.setObjectName("scheme2RecognitionStatus")
        progress = QProgressBar()
        progress.setObjectName("scheme2AddProgress")
        progress.setRange(0, 5)
        progress.setTextVisible(True)
        progress.setFixedWidth(190)
        progress.hide()
        more = QToolButton()
        more.setText("更多")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        more.setMenu(menu)
        secondary = {"手写笔", "框选", "撤销", "删除选中", "清除"}
        for tool in right.findChildren(QPushButton):
            if tool.text().strip() in secondary:
                action = menu.addAction(tool.text().strip())
                action.triggered.connect(tool.click)
                tool.hide()
        for control_type in (QComboBox, QSpinBox):
            for control in right.findChildren(control_type):
                control.hide()
        manage = QPushButton("导入 / 管理图纸")
        manage.setObjectName("scheme2PrimaryGhost")
        add = QPushButton("加入报价清单")
        add.setObjectName("scheme2PrimaryAction")
        row.addWidget(status, 1)
        row.addWidget(progress)
        row.addWidget(more)
        row.addWidget(manage)
        row.addWidget(add)
        right.layout().addWidget(footer)
        manage.clicked.connect(lambda: window.show_section(0))
        add.clicked.connect(lambda: _calculate_and_add(window))
        window.scheme2_recognition_status = status
        window.scheme2_completion = counter
        window.scheme2_add_button = add
        window.scheme2_add_progress = progress
        window.scheme2_saved_status = saved
    workspace.addWidget(right_shell)
    workspace.setStretchFactor(0, 0)
    workspace.setStretchFactor(1, 1)
    window.scheme2_option_splitter = workspace
    window.scheme2_option_form_widget = left_scroll
    window.scheme2_drawing_widget = right_shell

    for control in (
        name_edit, window.quote_spec_edit, window.product_combo, window.quantity_spin,
        window.material_combo, window.coating_combo, color, thickness,
        window.single_door_combo, window.double_door_combo,
    ):
        if control is None:
            continue
        if isinstance(control, QLineEdit):
            control.textEdited.connect(lambda *_: _set_dirty(window, True))
        elif isinstance(control, QComboBox):
            control.activated.connect(lambda *_: _set_dirty(window, True))
        elif isinstance(control, QAbstractSpinBox):
            control.editingFinished.connect(lambda: _set_dirty(window, True))

    for name in ("primaryQuoteAction", "secondaryQuoteAction", "quietQuoteAction"):
        button = window.findChild(QPushButton, name)
        if button is not None and button is not attachment_button:
            button.hide()
    legacy_dock = window.findChild(QFrame, "quoteActionDock")
    if legacy_dock is not None:
        legacy_dock.hide()
        legacy_dock.setMaximumHeight(0)
    window.stack.removeWidget(old_page)
    old_page.setParent(window)
    old_page.hide()
    window.scheme2_legacy_quote_page = old_page
    window.stack.insertWidget(OPTION_ROUTE, page)
    if hasattr(window, "quote_right_stack"):
        window.quote_right_stack.setCurrentIndex(0)


def _calculate_and_add(window):
    if getattr(window, "quote_calculation_in_progress", False):
        return
    current = getattr(window, "current_result", None)
    valid = isinstance(current, dict) and current.get("input_signature") == window.quote_input_signature()
    if valid:
        _set_add_progress(window, 5, "保存快照并生成行")
        _finish_add(window)
        return
    window._scheme2_add_after_calculate = True
    window.scheme2_add_button.setEnabled(False)
    window.scheme2_add_button.setText("正在计算…")
    _set_add_progress(window, 1, "校验输入")
    QTimer.singleShot(80, lambda: _set_add_progress(window, 2, "附件匹配"))
    QTimer.singleShot(160, lambda: _set_add_progress(window, 3, "读取公式模板并计算"))
    window.calculate()


def _set_add_progress(window, step, label, failed=False):
    progress = getattr(window, "scheme2_add_progress", None)
    if progress is None:
        return
    progress.show()
    progress.setValue(step)
    progress.setFormat(f"{step}/5 {label}")
    progress.setProperty("failed", failed)
    progress.style().unpolish(progress)
    progress.style().polish(progress)


def _set_dirty(window, dirty=True):
    window._scheme2_dirty = bool(dirty)
    label = getattr(window, "scheme2_saved_status", None)
    if label is not None:
        label.setText("有未保存变更" if dirty else "快照已保存")
        label.setProperty("dirty", bool(dirty))
        label.style().unpolish(label)
        label.style().polish(label)


def _finish_add(window):
    before = len(getattr(window, "draft_items", []))
    editing = getattr(window, "_scheme2_edit_item", None)
    editing_index = window.draft_items.index(editing) if editing in window.draft_items else None
    window.add_current_to_summary()
    if len(getattr(window, "draft_items", [])) != before + 1:
        return
    item = window.draft_items[-1]
    if editing_index is not None:
        window.draft_items.pop()
        window.draft_items[editing_index] = item
    window._scheme2_edit_item = None
    item["name"] = window.scheme2_name_edit.text().strip() or item.get("model_code") or "未命名"
    item["display_color"] = window.scheme2_color_combo.currentText()
    item.setdefault("quick_discount", 1.0)
    item["scheme2_cost_settings"] = dict(
        getattr(window, "_scheme2_active_settings", None) or window.scheme2_defaults
    )
    window._scheme2_active_settings = None
    _set_add_progress(window, 5, "已完成")
    window.scheme2_add_button.setText("已加入")
    _set_dirty(window, False)
    window.refresh_summary()
    window.show_section(COST_ROUTE)
    target_row = editing_index if editing_index is not None else len(window.draft_items) - 1
    if target_row >= 0:
        window.summary_table.selectRow(target_row)
        for column in range(window.summary_table.columnCount()):
            cell = window.summary_table.item(target_row, column)
            if cell is not None:
                cell.setBackground(QColor("#EAF3DE"))
        QTimer.singleShot(1000, window.refresh_summary)


def _sync_completion(window):
    drawings = [row for row in getattr(window, "recognized_drawings", []) if isinstance(row, dict)]
    total = sum(1 for row in drawings if row.get("verified") or row.get("confirmed") or row.get("candidate_id"))
    completed_keys = {
        item.get("source_candidate_id") or item.get("model_code") or id(item)
        for item in getattr(window, "draft_items", []) if isinstance(item, dict)
    }
    completed = min(len(completed_keys), total) if total else len(getattr(window, "draft_items", []))
    if hasattr(window, "scheme2_completion"):
        window.scheme2_completion.setText(f"已完成 {completed} / {total}")
    drawing = getattr(window, "_quote_drawing", None)
    if hasattr(window, "scheme2_recognition_status"):
        window.scheme2_recognition_status.setText("已识别：尺寸 / 材质 / 表面处理 / 颜色" if drawing else "请导入并确认图纸")


def _advance_to_next_drawing(window):
    if getattr(window, "_scheme2_advancing", False):
        return
    completed = {
        item.get("source_candidate_id") for item in getattr(window, "draft_items", [])
        if isinstance(item, dict) and item.get("source_candidate_id")
    }
    ready = getattr(window, "_drawing_ready", lambda _item: True)
    next_drawing = next((
        drawing for drawing in getattr(window, "recognized_drawings", [])
        if isinstance(drawing, dict)
        and drawing.get("candidate_id") not in completed
        and ready(drawing)
    ), None)
    if next_drawing is None:
        return
    window._scheme2_advancing = True
    try:
        window.active_drawing = next_drawing
        window.use_selected_drawing()
    finally:
        window._scheme2_advancing = False


def _install_shortcuts(window):
    shortcuts = []

    def bind(sequence, callback):
        shortcut = QShortcut(QKeySequence(sequence), window)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(callback)
        shortcuts.append(shortcut)

    def submit():
        if window.stack.currentIndex() != OPTION_ROUTE:
            return
        focus = window.focusWidget()
        if isinstance(focus, (QComboBox, QAbstractSpinBox)) or isinstance(
                focus.parentWidget() if focus is not None else None, QComboBox):
            return
        _calculate_and_add(window)

    def escape():
        overlay = getattr(window, "_scheme2_attachment_overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.reject()
        elif window.stack.currentIndex() == DETAIL_ROUTE:
            window.scheme2_close_detail()

    def shift_move(delta):
        if window.stack.currentIndex() == COST_ROUTE:
            window.move_selected_item(delta)

    bind("Ctrl+1", lambda: window.show_section(OPTION_ROUTE))
    bind("Ctrl+2", lambda: window.show_section(COST_ROUTE))
    bind("Return", submit)
    bind("Enter", submit)
    bind("Escape", escape)
    bind("Shift+Up", lambda: shift_move(-1))
    bind("Shift+Down", lambda: shift_move(1))
    bind("Delete", lambda: _delete_selected(window) if window.stack.currentIndex() == COST_ROUTE else None)
    bind("Ctrl+D", lambda: _duplicate_selected(window) if window.stack.currentIndex() == COST_ROUTE else None)
    window.scheme2_shortcuts = shortcuts


def _apply_responsive(window):
    splitter = getattr(window, "scheme2_option_splitter", None)
    route = window.stack.currentIndex()
    width = window.width()
    option_page = window.stack.widget(OPTION_ROUTE)
    main_scroll = window.findChild(QScrollArea, "mainScroll")
    if splitter is not None:
        if route != OPTION_ROUTE:
            option_page.setMinimumHeight(0)
            splitter.setMinimumHeight(0)
            for index in range(splitter.count()):
                splitter.widget(index).setMinimumHeight(0)
            window.stack.setMinimumHeight(0)
            if main_scroll is not None and main_scroll.widget() is not None:
                main_scroll.widget().setMinimumHeight(0)
        elif width < 900:
            drawing = getattr(window, "scheme2_drawing_widget", None)
            form_widget = getattr(window, "scheme2_option_form_widget", None)
            if drawing is not None and form_widget is not None and splitter.widget(0) is not drawing:
                splitter.insertWidget(0, drawing)
                splitter.insertWidget(1, form_widget)
            splitter.setMaximumWidth(16777215)
            splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            if drawing is not None:
                drawing.setMinimumWidth(0)
                drawing.setMaximumWidth(16777215)
                drawing.setMaximumHeight(740)
            if form_widget is not None:
                form_widget.setMinimumWidth(0)
                form_widget.setMaximumWidth(16777215)
            splitter.setOrientation(Qt.Orientation.Vertical)
            option_page.setMinimumHeight(1320)
            splitter.setMinimumHeight(1220)
            window.stack.setMinimumHeight(1320)
            if main_scroll is not None and main_scroll.widget() is not None:
                main_scroll.widget().setMinimumHeight(1348)
            splitter.setSizes([700, 520])
        else:
            drawing = getattr(window, "scheme2_drawing_widget", None)
            form_widget = getattr(window, "scheme2_option_form_widget", None)
            if drawing is not None and form_widget is not None and splitter.widget(0) is not form_widget:
                splitter.insertWidget(0, form_widget)
                splitter.insertWidget(1, drawing)
            if drawing is not None:
                drawing.setMaximumHeight(16777215)
            splitter.setOrientation(Qt.Orientation.Horizontal)
            option_page.setMinimumHeight(0)
            splitter.setMinimumHeight(0)
            window.stack.setMinimumHeight(0)
            if main_scroll is not None and main_scroll.widget() is not None:
                main_scroll.widget().setMinimumHeight(0)
            form = 420 if width >= 1600 else (340 if width >= 1100 else 300)
            splitter.widget(0).setMinimumWidth(form)
            splitter.widget(0).setMaximumWidth(420 if width >= 1600 else (520 if width >= 1100 else 300))
            splitter.setSizes([form, max(500, width - form - 100)])
    sidebar = getattr(window, "scheme2_cost_sidebar", None)
    compact_coefficients = getattr(window, "scheme2_compact_coefficients", None)
    if sidebar is not None and compact_coefficients is not None:
        use_compact_coefficients = width < 1100
        sidebar.setVisible(not use_compact_coefficients)
        compact_coefficients.setVisible(use_compact_coefficients)
        if use_compact_coefficients:
            _sync_compact_control(window)
        _layout_cost_actions(window, width < 900)
    detail_table = getattr(window, "scheme2_detail_table", None)
    if detail_table is not None:
        card_columns = {0, 1, 7, 8, 9}
        for column in range(detail_table.columnCount()):
            detail_table.setColumnHidden(column, width < 900 and column not in card_columns)
    empty = getattr(window, "scheme2_cost_empty", None)
    if empty is not None:
        empty.setGeometry(window.summary_table.viewport().rect())
    legacy_dock = getattr(window, "quote_action_dock", None)
    if legacy_dock is not None:
        legacy_dock.hide()
        legacy_dock.setMaximumHeight(0)
    drawing = getattr(window, "scheme2_drawing_widget", None)
    preview = getattr(window, "quote_drawing_preview", None)
    canvas = getattr(preview, "canvas", None)
    if drawing is not None and canvas is not None and drawing.width() > 100:
        height_limit = max(300, window.height() - 250)
        a4_width = min(drawing.width() - 34, int(height_limit * (297 / 210)))
        a4_height = int(a4_width / (297 / 210))
        canvas.setFixedSize(a4_width, a4_height)
        if preview.layout() is not None:
            preview.layout().setAlignment(canvas, Qt.AlignmentFlag.AlignHCenter)
    expand = getattr(window, "scheme2_expand_button", None)
    if expand is not None:
        expand.move(0, max(90, (window.height() - expand.height()) // 2))
        expand.raise_()
    host = window.stack.parentWidget()
    host_layout = host.layout() if host is not None else None
    if host_layout is not None:
        # The stacked option page needs top pinning in its tall compact layout,
        # while cost/detail pages must consume the whole available work area.
        alignment = Qt.AlignmentFlag.AlignTop if route == OPTION_ROUTE else Qt.AlignmentFlag(0)
        host_layout.setAlignment(window.stack, alignment)
        if route != OPTION_ROUTE and main_scroll is not None and main_scroll.widget() is not None:
            main_scroll.widget().setMinimumHeight(main_scroll.viewport().height())
        host_layout.invalidate()
        host_layout.activate()
        margins = host_layout.contentsMargins()
        if route != OPTION_ROUTE:
            window.stack.setMinimumHeight(max(
                0, host.height() - margins.top() - margins.bottom()
            ))
        target_height = max(
            window.stack.minimumHeight(),
            host.height() - margins.top() - margins.bottom(),
        )
        window.stack.setGeometry(
            margins.left(), margins.top(),
            max(0, host.width() - margins.left() - margins.right()),
            target_height,
        )
    _apply_navigation_state(window)


def _apply_palette(window):
    window.setStyleSheet(window.styleSheet() + """
QMainWindow QWidget { font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI"; }
QMainWindow, QWidget#scheme2OptionPage, QWidget#scheme2CostPage, QWidget#scheme2DetailPage { background:#FFFFFF; color:#1C1C1E; }
QFrame#scheme2TopBar { background:#FFFFFF; border-bottom:1px solid rgba(0,0,0,.12); }
QLabel#scheme2TopLogo { background:#E6F1FB; color:#185FA5; border-radius:5px; font-size:10px; font-weight:600; }
QLabel#scheme2Brand { font-size:14px; font-weight:600; color:#1C1C1E; }
QLabel#scheme2ServiceStatus { color:#3B6D11; background:#EAF3DE; border-radius:10px; padding:3px 9px; font-size:11px; }
QLabel#scheme2SavedStatus { color:#3B6D11; font-size:11px; }
QLabel#scheme2SavedStatus[dirty="true"] { color:#854F0B; background:#FAEEDA; border-radius:9px; padding:2px 7px; }
QScrollArea#scheme2OptionScroll, QWidget#scheme2OptionForm { background:#FFFFFF; border:0; }
QFrame#scheme2DrawingShell { background:#EEF0F3; border-left:1px solid rgba(0,0,0,.12); }
QFrame#scheme2DrawingHeader { background:#FFFFFF; border-bottom:1px solid rgba(0,0,0,.12); }
QLabel#scheme2SectionTitle { font-size:14px; font-weight:600; color:#1C1C1E; }
QLabel#scheme2OptionLabel { font-size:11px; color:#5F5E5A; }
QLabel#scheme2ProvenancePending { font-size:10px; color:#8A8A86; }
QLabel#scheme2ProvenanceAi { font-size:10px; color:#3B6D11; background:#EAF3DE; border-radius:8px; padding:1px 6px; }
QLabel#scheme2ProvenanceManual { font-size:10px; color:#854F0B; background:#FAEEDA; border-radius:8px; padding:1px 6px; }
QFrame#scheme2AttachmentCard { background:#F6F7F9; border:1px solid rgba(0,0,0,.12); border-radius:8px; }
QWidget#scheme2DrawingCanvas { background:#FFFFFF; border:1px solid rgba(0,0,0,.24); }
QFrame#navPanel { background:#DCE8F7; border-right:1px solid #BBD0EA; }
QFrame#scheme2NavBrand { background:transparent; border:0; }
QLabel#scheme2NavLogo { background:#2563EB; color:#FFFFFF; border-radius:5px; font-size:9px; font-weight:600; }
QLabel#scheme2NavTitle { color:#1F3A6A; font-size:11px; font-weight:600; }
QFrame#navPanel QPushButton { color:#1F3A6A; border:0; border-radius:7px; padding:8px 7px; text-align:left; }
QFrame#navPanel QPushButton:checked { color:#FFFFFF; background:#2563EB; }
QFrame#scheme2CostSidebar { background:#DCE8F7; border-right:1px solid #BBD0EA; }
QFrame#scheme2CompactCoefficients { background:#DCE8F7; border:1px solid #BBD0EA; border-radius:7px; }
QFrame#scheme2CostBody { background:#FFFFFF; }
QFrame#scheme2UndoBar { background:#E6F1FB; border:1px solid #85B7EB; border-radius:7px; }
QLabel#scheme2EmptyState { color:#8A8A86; background:#FFFFFF; font-size:13px; }
QLabel#scheme2PageTitle { font-size:18px; font-weight:600; color:#1C1C1E; }
QLabel#scheme2DialogTitle { font-size:15px; font-weight:600; color:#1C1C1E; padding-bottom:4px; }
QLabel#scheme2SidebarTitle { font-size:14px; font-weight:600; color:#1F3A6A; }
QLabel#scheme2FieldLabel, QLabel#scheme2SidebarHint { font-size:10px; color:#5A7AAB; }
QLabel#scheme2Hint { color:#8A8A86; font-size:11px; }
QLabel#scheme2CompletionPill { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:12px; padding:4px 10px; }
QLabel#scheme2RecognitionStatus { color:#3B6D11; }
QLabel#scheme2DiscountPreview { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:8px; padding:9px; font-weight:600; }
QPushButton#scheme2PrimaryAction { color:#FFFFFF; background:#2563EB; border:1px solid #2563EB; border-radius:7px; padding:8px 16px; font-weight:600; }
QPushButton#scheme2PrimaryAction:hover { background:#1D4ED8; }
QPushButton#scheme2PrimaryAction:disabled { background:#AFC7E8; border-color:#AFC7E8; }
QPushButton#scheme2PrimaryGhost, QPushButton#scheme2CollapseButton, QPushButton#scheme2ExpandButton { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:6px; padding:6px 10px; }
QFrame#scheme2RecognitionFooter { background:#FFFFFF; border-top:1px solid rgba(0,0,0,.12); }
QTableWidget#summaryTable, QTableWidget#scheme2DetailTable { background:#FFFFFF; alternate-background-color:#F6F7F9; border:1px solid rgba(0,0,0,.12); border-radius:8px; gridline-color:rgba(0,0,0,.12); }
QTableWidget#summaryTable::item:selected, QTableWidget#scheme2DetailTable::item:selected { background:#E6F1FB; color:#1C1C1E; }
QTableWidget#summaryTable::item:hover { background:#F5F9FF; }
QHeaderView::section { background:#F6F7F9; color:#5F5E5A; border:0; border-bottom:1px solid rgba(0,0,0,.12); padding:7px 8px; font-weight:500; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#FFFFFF; border:1px solid rgba(0,0,0,.18); border-radius:7px; padding:5px 7px; min-height:22px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:#2563EB; }
QProgressBar#scheme2AddProgress { background:#EEF0F3; border:0; border-radius:5px; text-align:center; color:#1F3A6A; min-height:20px; }
QProgressBar#scheme2AddProgress::chunk { background:#97C459; border-radius:5px; }
QProgressBar#scheme2AddProgress[failed="true"]::chunk { background:#E24A4A; }
""")


def install_scheme2_ui(namespace):
    """Install the approved two-page UI after all legacy compatibility layers."""

    cls = namespace["MainWindow"]
    if getattr(cls, "_scheme2_ui_installed", False):
        return
    cls._scheme2_ui_installed = True
    remark_builder = namespace.get("build_standardized_quote_remark")
    if callable(remark_builder) and not getattr(remark_builder, "_scheme2_color_installed", False):
        def build_remark_with_color(item, raw_remark):
            remark = remark_builder(item, raw_remark)
            color = str(item.get("display_color") or "").strip() if isinstance(item, dict) else ""
            if color and color not in str(remark or ""):
                remark = f"{str(remark or '').rstrip('。；; ')}；颜色：{color}。"
            return remark

        build_remark_with_color._scheme2_color_installed = True
        namespace["build_standardized_quote_remark"] = build_remark_with_color
    api_worker = namespace.get("ApiWorker")
    if api_worker is not None and not getattr(api_worker, "_scheme2_fields_installed", False):
        original_worker_run = api_worker.run

        def worker_run(worker):
            payload = getattr(worker, "payload", None)
            owner = worker.parent()
            if isinstance(payload, dict) and owner is not None and hasattr(owner, "scheme2_defaults"):
                values = getattr(owner, "_scheme2_active_settings", None) or owner.scheme2_defaults
                payload.update({
                    "galvanized_sheet_unit_price_override": values["galvanized_price"],
                    "carbon_steel_unit_price_override": values["carbon_price"],
                    "surface_treatment_unit_price_override": values["surface_price"],
                })
            return original_worker_run(worker)

        api_worker.run = worker_run
        api_worker._scheme2_fields_installed = True

    original_init = cls.__init__
    original_resize = cls.resizeEvent
    original_close = cls.closeEvent
    original_section = cls.show_section
    original_show_result = cls.show_result
    original_show_error = cls.show_error
    original_refresh = cls.refresh_summary
    original_apply_drawing = cls._apply_confirmed_drawing_to_quote
    original_add = cls.add_current_to_summary

    def init(window, *args, **kwargs):
        window._scheme2_add_after_calculate = False
        window._scheme2_edit_item = None
        window._scheme2_detail_item = None
        window._scheme2_active_settings = None
        window.scheme2_defaults = {
            "galvanized_price": 4.55, "carbon_price": 4.20, "waste_factor": 1.20,
            "labor_discount": 1.0, "surface_price": 26.0,
        }
        original_init(window, *args, **kwargs)
        # The reference explicitly supports the <900 logical-pixel stacked
        # layout; the recovered client used a wider fixed minimum.
        window.setMinimumSize(1024, 700)
        window.statusBar().hide()
        old_cost_page = window.stack.widget(COST_ROUTE)
        window.stack.removeWidget(old_cost_page)
        old_cost_page.hide()
        window.stack.insertWidget(COST_ROUTE, _build_cost_page(window))
        detail = _build_detail_page(window)
        while window.stack.count() < DETAIL_ROUTE:
            window.stack.addWidget(QWidget())
        window.stack.insertWidget(DETAIL_ROUTE, detail)
        _configure_navigation(window)
        _configure_option_page(window, namespace)
        _install_shortcuts(window)
        _apply_palette(window)
        window.refresh_summary()
        window.show_section(OPTION_ROUTE)
        _set_dirty(window, False)
        _apply_responsive(window)

    def resize(window, event):
        original_resize(window, event)
        QTimer.singleShot(0, lambda: _apply_responsive(window))

    def close(window, event):
        if getattr(window, "_scheme2_dirty", False) and window.isVisible():
            answer = QMessageBox.question(
                window, "有未保存变更", "当前配置尚未加入报价清单，确定关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        original_close(window, event)

    def section(window, index):
        previous_index = window.stack.currentIndex()
        if index == COST_ROUTE:
            window.refresh_summary()
        result = original_section(window, index)
        if index == OPTION_ROUTE and hasattr(window, "quote_right_stack"):
            window.quote_right_stack.setCurrentIndex(0)
        _sync_completion(window)
        _apply_responsive(window)
        QTimer.singleShot(0, lambda: _apply_responsive(window))
        if index == OPTION_ROUTE and previous_index == COST_ROUTE:
            QTimer.singleShot(0, lambda: _advance_to_next_drawing(window))
        return result

    def show_result(window, payload, *args, **kwargs):
        result = original_show_result(window, payload, *args, **kwargs)
        if hasattr(window, "quote_right_stack"):
            window.quote_right_stack.setCurrentIndex(0)
        if window._scheme2_add_after_calculate and isinstance(getattr(window, "current_result", None), dict):
            _set_add_progress(window, 4, "双报价计算完成")
            window._scheme2_add_after_calculate = False
            window.scheme2_add_button.setEnabled(True)
            window.scheme2_add_button.setText("加入报价清单")
            QTimer.singleShot(0, lambda: _finish_add(window))
        return result

    def show_error(window, message):
        window._scheme2_add_after_calculate = False
        if hasattr(window, "scheme2_add_button"):
            window.scheme2_add_button.setEnabled(True)
            window.scheme2_add_button.setText("重试")
            _set_add_progress(window, 3, f"失败：{message}", failed=True)
        return original_show_error(window, message)

    def refresh(window):
        _refresh_cost_table(window)
        _sync_completion(window)

    def apply_drawing(window, item):
        controls = {
            "dimensions": getattr(window, "quote_spec_edit", None),
            "material": getattr(window, "material_combo", None),
            "coating": getattr(window, "coating_combo", None),
            "color": getattr(window, "scheme2_color_combo", None),
        }
        preserved = {}
        for key in getattr(window, "scheme2_manual_fields", set()):
            control = controls.get(key)
            if isinstance(control, QLineEdit):
                preserved[key] = control.text()
            elif isinstance(control, QComboBox):
                preserved[key] = control.currentIndex()
        overwrite = True
        if preserved and window.isVisible():
            answer = QMessageBox.question(
                window,
                "保留人工修改",
                "当前尺寸、材质、表面处理或颜色包含人工修改。\n是否使用新图纸的 AI 识别结果覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            overwrite = answer == QMessageBox.StandardButton.Yes
        result = original_apply_drawing(window, item)
        if not overwrite:
            for key, value in preserved.items():
                control = controls.get(key)
                if isinstance(control, QLineEdit):
                    control.setText(value)
                elif isinstance(control, QComboBox) and value >= 0:
                    control.setCurrentIndex(value)
        else:
            window.scheme2_manual_fields.clear()
            for key in ("dimensions", "material", "coating"):
                _mark_ai(window, key)
            recognized_color = str(item.get("color") or item.get("color_name") or item.get("ral_color") or "").strip()
            color = getattr(window, "scheme2_color_combo", None)
            if recognized_color and isinstance(color, QComboBox):
                matched = color.findText(recognized_color, Qt.MatchFlag.MatchContains)
                if matched >= 0:
                    color.setCurrentIndex(matched)
            _mark_ai(window, "color")
        model = getattr(window, "scheme2_name_edit", None)
        if isinstance(model, QLineEdit):
            source = str(item.get("source_path") or item.get("file_path") or item.get("filename") or "")
            stem = Path(source).stem if source else ""
            if stem:
                model.setText(stem)
        _sync_completion(window)
        return result

    def add(window, *args, **kwargs):
        result = original_add(window, *args, **kwargs)
        _sync_completion(window)
        return result

    cls.__init__ = init
    cls.resizeEvent = resize
    cls.closeEvent = close
    cls.show_section = section
    cls.show_result = show_result
    cls.show_error = show_error
    cls.refresh_summary = refresh
    cls._apply_confirmed_drawing_to_quote = apply_drawing
    cls.add_current_to_summary = add
