"""Install the approved ``界面方案2`` presentation over the recovered V3 core.

The overlay deliberately keeps the core quote, attachment, confirmation and
export objects alive.  It changes their presentation and stores new row-local
editing state inside the existing draft-item JSON snapshots.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import html
from pathlib import Path
import re
import tempfile
import time
from types import MethodType

from PySide6.QtCore import QDate, QEvent, QObject, QPoint, QRect, QSettings, QSignalBlocker, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QPolygon, QShortcut, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pypdf import PdfReader, PdfWriter


OPTION_ROUTE = 1
QUOTE_ROUTE = 2
COST_ROUTE = 3
DETAIL_ROUTE = 5
NAV_EXPANDED_WIDTH = 128
COST_SIDEBAR_WIDTH = 130
COMPANY_COMBO_HEIGHT = 56
QUOTE_COMPANY_FIELD_WIDTH = 420
DRAWING_FOOTER_HEIGHT = 46
DRAWING_VERTICAL_CHROME = 118
STAINLESS_DEFAULT_PRICES = {"SUS304": 16.0, "SUS316": 32.4}
SURFACE_DEFAULT_PRICES = {"橘纹": 26.0, "平光": 30.0, "无": 0.0}
WORKBENCH_WINDOW_TITLE = "AI 智能报价 · V0 交互工作台"
HEADERS = (
    "序号", "名称", "产品", "尺寸", "材料成本", "辅材成本", "人工成本",
    "附件成本", "喷涂费用", "管理费用", "运费", "数量", "已选附件",
    "面价", "折扣系数", "报价", "报价总价", "成本单价", "成本总价",
    "毛利率", "自制件重量", "成本明细",
)
MONEY_COLUMNS = frozenset((*range(4, 11), 13, 15, 16, 17, 18))
EDITABLE_COLUMNS = frozenset((10, 11, 14))
ROLE_ROW = int(Qt.ItemDataRole.UserRole)
ROLE_DERIVED_SPEC = ROLE_ROW + 1
_FONT_SIZE_RULE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)\s*(px|pt)", re.IGNORECASE)
_STYLE_LENGTH_RULE = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*(px|pt)", re.IGNORECASE)
GALVANIZED_MATERIAL_CODES = frozenset(("SGCC", "DX51D", "GI"))
THREE_ROW_BEAM_MODELS = ("JP760240", "JP760250", "JP760260", "JP760280", "JP760210")
LIGHT_SWITCH_MODELS = ("220V", "24V-0.28m", "24V-0.6m")


class _ClickableProgressBar(QProgressBar):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _ExportValidationWorker(QThread):
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, validation, parent=None):
        super().__init__(parent)
        self.validation = validation

    def run(self):
        try:
            self.validation()
            self.succeeded.emit()
        except Exception as error:
            self.failed.emit(str(error))


def _start_export_validation(window):
    worker = getattr(window, "_scheme2_export_validation_worker", None)
    if worker is not None and worker.isRunning():
        return
    window.set_export_busy(True, "正在检查云端导出服务…")
    worker = _ExportValidationWorker(window.validate_export_environment, window)
    window._scheme2_export_validation_worker = worker

    def proceed():
        window.set_export_busy(False, "")
        window._scheme2_export_validation_passed = True
        window.confirm_and_export()

    worker.succeeded.connect(proceed)
    worker.failed.connect(window.confirmation_failed)
    worker.finished.connect(lambda: setattr(window, "_scheme2_export_validation_worker", None))
    worker.finished.connect(worker.deleteLater)
    worker.start()


def _sync_export_company(window):
    """Copy the visible Scheme-2 company into the legacy export controller."""

    visible = getattr(window, "scheme2_company", None)
    export_combo = getattr(window, "company_combo", None)
    if not isinstance(visible, QComboBox) or not isinstance(export_combo, QComboBox):
        return
    text = visible.currentText().strip()
    data = visible.currentData()
    index = export_combo.findData(data) if data is not None else -1
    if index < 0 and text:
        index = export_combo.findText(text, Qt.MatchFlag.MatchFixedString)
    with QSignalBlocker(export_combo):
        if index >= 0:
            export_combo.setCurrentIndex(index)
        elif export_combo.isEditable():
            export_combo.setEditText(text)
        elif text:
            export_combo.addItem(text, data)
            export_combo.setCurrentIndex(export_combo.count() - 1)


class _Scheme2PageRecognitionWorker(QThread):
    succeeded = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, recognition_tools, page_entry, parent=None):
        super().__init__(parent)
        self.recognition_tools = recognition_tools
        self.page_entry = page_entry

    def run(self):
        entry = self.page_entry
        source = str(entry["source_path"])
        page_index = int(entry["page_index"])
        try:
            recognition_path = source
            with tempfile.TemporaryDirectory(prefix="scheme2-recognition-") as folder:
                if Path(source).suffix.lower() == ".pdf":
                    reader = PdfReader(source)
                    try:
                        if not 0 <= page_index < len(reader.pages):
                            raise ValueError("图纸页码无效")
                        writer = PdfWriter()
                        writer.add_page(reader.pages[page_index])
                        recognition_path = str(Path(folder) / f"page-{page_index + 1}.pdf")
                        with open(recognition_path, "wb") as stream:
                            writer.write(stream)
                        writer.close()
                    finally:
                        reader.close()
                item = self.recognition_tools.recognize_document(recognition_path)
            if not isinstance(item, dict):
                raise ValueError("图纸识别未返回有效结果")
            self._apply_source_context(item, entry)
            self.succeeded.emit(entry["key"], item)
        except Exception as error:
            self.failed.emit(entry["key"], str(error))

    @staticmethod
    def _apply_source_context(item, entry):
        source = str(entry["source_path"])
        page_index = int(entry["page_index"])
        page_count = int(entry["page_count"])
        for record in (item, *(item.get("cabinet_candidates") or [])):
            if not isinstance(record, dict):
                continue
            record["source_path"] = source
            record["path"] = source
            record["source_page_index"] = page_index
            record["source_page_number"] = page_index + 1
            record["source_page_count"] = page_count
            record.setdefault("candidate_id", entry["key"])


def _number(value, fallback=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result


def _money(value):
    return f"{_number(value):,.2f}"


def _surface_default_price(value):
    text = str(value or "").strip()
    for name, price in SURFACE_DEFAULT_PRICES.items():
        if text == name or name in text:
            return price
    return SURFACE_DEFAULT_PRICES["橘纹"]


def _formula(item):
    value = item.get("formula") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else {}


def _quick(item):
    value = item.get("quick") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else {}


def _attachment_amount(row):
    price = row.get("unit_price_override", row.get("matched_price", 0))
    sign = -1 if int(_number(row.get("attachment_price_sign", 1), 1)) == -1 else 1
    return int(_number(row.get("quantity", 1), 1)) * abs(_number(price)) * sign


def _attachment_total(item):
    return sum(_attachment_amount(row) for row in item.get("attachments", []) if isinstance(row, dict))


def _cost_product(item):
    return str(
        item.get("scheme2_selected_product_name")
        or item.get("scheme2_selected_product_code")
        or item.get("product_code")
        or "—"
    )


def _row_values(item):
    formula = _formula(item)
    quick = _quick(item)
    quantity = max(1, int(_number(item.get("quantity", 1), 1)))
    freight = max(0.0, _number(item.get("freight_fee", item.get("freight", 0))))
    formula_unit = _number(formula.get("total_cost")) + freight
    face_base = _number(quick.get("total_cost")) + freight
    discount = _number(item.get("quick_discount", 1), 1)
    quote = face_base * discount
    quote_total = quote * quantity
    cost_total = formula_unit * quantity
    gross_margin = (quote_total - cost_total) / quote_total if quote_total else 0.0
    billable_weight = _number(formula.get("corrected_material_weight_kg"))
    specification = str(item.get("specification") or item.get("model_code") or "—")
    name = str(item.get("name") or item.get("model_code") or "未命名")
    product = _cost_product(item)
    attachments = [row for row in item.get("attachments", []) if isinstance(row, dict)]
    return (
        "", name, product, specification,
        _number(formula.get("material_cost")),
        _number(formula.get("auxiliary_cost")),
        _number(formula.get("labor_cost")),
        _number(formula.get("attachment_fee"), _attachment_total(item)),
        _number(formula.get("spray_cost")),
        _number(formula.get("management_fee")),
        freight, quantity, f"{len(attachments)} 项 ›", face_base, discount,
        quote, quote_total, formula_unit, cost_total,
        f"{gross_margin:.2%}", billable_weight, "明细 ›",
    )


def _replace_component(item, key, value):
    formula = _formula(item)
    old = _number(formula.get(key))
    formula[key] = round(max(0.0, value), 2)
    formula["total_cost"] = round(max(0.0, _number(formula.get("total_cost")) - old + formula[key]), 2)


def _material_price_caption(material_code):
    code = str(material_code or "").strip().upper()
    return {
        "SUS304": "SUS304价格",
        "SUS316": "SUS316价格",
        "SECC": "碳钢价格",
    }.get(code, "碳钢价格")


def _reprice_material_details(item, state):
    formula = _formula(item)
    groups = formula.get("material_details")
    if not isinstance(groups, list) or not groups:
        return False
    selected_code = str(item.get("material_code") or "").strip().upper()
    current_price = _number(
        state.get("stainless_price") if selected_code in {"SUS304", "SUS316"}
        else state.get("carbon_price")
    )
    galvanized_price = _number(state.get("galvanized_price"))

    def price_for(code):
        normalized = str(code or "").strip().upper()
        if normalized in GALVANIZED_MATERIAL_CODES or (normalized == "SECC" and selected_code != "SECC"):
            return galvanized_price
        if normalized == selected_code:
            return current_price
        return None

    total = 0.0
    for group in groups:
        if not isinstance(group, dict):
            return False
        price = price_for(group.get("material_code"))
        if price is None:
            return False
        weight = _number(group.get("billable_weight_kg"))
        group["material_unit_price"] = price
        group["material_cost"] = round(weight * price, 2)
        total += weight * price
    for detail in formula.get("cabinet_material_part_details", []):
        if not isinstance(detail, dict):
            continue
        price = price_for(detail.get("material_code"))
        if price is None:
            continue
        detail["material_unit_price"] = price
        detail["material_cost"] = round(_number(detail.get("billable_weight_kg")) * price, 8)
    if len(groups) == 1:
        formula["material_unit_price"] = groups[0]["material_unit_price"]
    _replace_component(item, "material_cost", total)
    return True


def _current_material_unit_price(item):
    formula = _formula(item)
    selected_code = str(item.get("material_code") or "").strip().upper()
    for group in formula.get("material_details") or []:
        if str(group.get("material_code") or "").strip().upper() == selected_code:
            return _number(group.get("material_unit_price"))
    return _number(formula.get("material_unit_price"))


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


def _inline_field(label, control):
    box = QFrame()
    box.setObjectName("scheme2Field")
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    text = QLabel(label)
    text.setObjectName("scheme2FieldLabel")
    text.setBuddy(control)
    layout.addWidget(text)
    layout.addWidget(control, 1)
    return box


def _price_spin(value=0.0):
    control = QDoubleSpinBox()
    control.setRange(0, 999999.99)
    control.setDecimals(2)
    control.setSingleStep(.1)
    control.setValue(value)
    return control


def _sidebar_price_spin(value, display_decimals=2, decimals=2):
    control = _SchemePencilSpinBox(display_decimals)
    control.setRange(0, 999999.99)
    control.setDecimals(decimals)
    control.setSingleStep(.1)
    control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    control.setFixedHeight(36)
    control.setValue(value)
    return control


class _SchemeDimensionEditor(QDialog):
    def __init__(self, parent, title, dimensions, current_values):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("scheme2DimensionDialog")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if parent is not None:
            self.resize(parent.size())
            self.move(parent.mapToGlobal(QPoint(0, 0)))

        overlay = QVBoxLayout(self)
        overlay.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("scheme2DimensionShell")
        shell.setFixedWidth(362)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 14)
        shell_layout.setSpacing(0)

        title_bar = QFrame()
        title_bar.setObjectName("scheme2DimensionTitleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 0, 8, 0)
        title_label = QLabel(title)
        title_label.setObjectName("scheme2DimensionTitle")
        close_button = QToolButton()
        close_button.setObjectName("scheme2DimensionClose")
        close_button.setText("×")
        close_button.setFixedSize(28, 28)
        close_button.clicked.connect(self.reject)
        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        title_layout.addWidget(close_button)
        shell_layout.addWidget(title_bar)

        form = QFormLayout()
        form.setContentsMargins(16, 16, 16, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.fields = {}
        for name in dimensions:
            field = QLineEdit(str(current_values.get(name) or ""))
            field.setObjectName("scheme2DimensionInput")
            field.setPlaceholderText("请输入正数（mm）")
            validator = QDoubleValidator(0.0, 999999.0, 3, field)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            field.setValidator(validator)
            self.fields[name] = field
            form.addRow(str(name), field)
        shell_layout.addLayout(form)

        hint = QLabel("仅接受正数，单位固定 mm；非法输入时确定按钮置灰")
        hint.setObjectName("scheme2DimensionHint")
        shell_layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.setContentsMargins(16, 12, 16, 0)
        actions.setSpacing(10)
        actions.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("scheme2DimensionCancel")
        confirm = QPushButton("确定")
        confirm.setObjectName("scheme2DimensionConfirm")
        for button in (cancel, confirm):
            button.setMinimumSize(62, 34)
            button.setAutoDefault(False)
            button.setDefault(False)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        shell_layout.addLayout(actions)

        overlay.addStretch(1)
        overlay.addWidget(shell, 0, Qt.AlignmentFlag.AlignCenter)
        overlay.addStretch(1)
        self.confirm_button = confirm
        for field in self.fields.values():
            field.textChanged.connect(self._refresh_validity)
        self._refresh_validity()

    def _refresh_validity(self):
        try:
            valid = bool(self.fields) and all(float(field.text().strip()) > 0 for field in self.fields.values())
        except ValueError:
            valid = False
        self.confirm_button.setEnabled(valid)

    def values(self):
        return {name: float(field.text().strip()) for name, field in self.fields.items()}


def _attachment_dimension_or_model(source):
    """Show only attachment catalogue dimensions, never cabinet target size."""
    dimensions = []
    for axis, label in (("width", "宽"), ("depth", "深"), ("height", "高")):
        number = _number(source.get(f"{axis}_mm"))
        if number > 0:
            dimensions.append((axis, label, number))
    if len(dimensions) == 3:
        by_axis = {axis: value for axis, _label, value in dimensions}
        return f"{by_axis['width']:g}×{by_axis['depth']:g}×{by_axis['height']:g} mm"
    if dimensions:
        return " × ".join(f"{label} {value:g}" for _axis, label, value in dimensions) + " mm"

    return str(source.get("model_code") or "").strip()


class AttachmentEditor(QDialog):
    COL_NAME = 0
    COL_SPECIFICATION = 1
    COL_QUANTITY = 2
    COL_FORMULA_AMOUNT = 3
    COL_AMOUNT = 4

    def __init__(self, window, item):
        super().__init__(window)
        self.window = window
        self.item = item
        self.setWindowTitle("已选附件")
        self.setObjectName("scheme2AttachmentEditorDialog")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(650, 315)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        shell = QFrame()
        shell.setObjectName("scheme2AttachmentEditorShell")
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(0)
        outer.addWidget(shell)
        header = _SchemeAttachmentHeader(self)
        header.setObjectName("scheme2AttachmentEditorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(13, 0, 8, 0)
        title = QLabel("已选附件")
        title.setObjectName("scheme2AttachmentEditorTitle")
        close_button = QToolButton()
        close_button.setObjectName("scheme2AttachmentEditorClose")
        close_button.setText("×")
        close_button.setToolTip("保存并关闭")
        close_button.setFixedSize(28, 28)
        close_button.clicked.connect(self.accept)
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(close_button)
        layout.addWidget(header)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("scheme2AttachmentEditorTable")
        self.table.setHorizontalHeaderLabels(("名称", "尺寸 / 规格", "数量", "成本", "金额"))
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setToolTip("右键可添加或删除临时附件；按 Esc 取消修改")
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(self.COL_SPECIFICATION, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(self.COL_QUANTITY, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(self.COL_AMOUNT, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(self.COL_FORMULA_AMOUNT, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_QUANTITY, 62)
        self.table.setColumnWidth(self.COL_AMOUNT, 82)
        self.table.setColumnWidth(self.COL_FORMULA_AMOUNT, 88)
        self.table.cellClicked.connect(self.edit_missing_dimensions)
        layout.addWidget(self.table, 1)
        for attachment in item.get("attachments", []):
            if isinstance(attachment, dict):
                self.add_row(attachment)

    def _show_table_menu(self, position):
        menu = QMenu(self)
        add_action = menu.addAction("＋ 临时附件")
        remove_action = menu.addAction("删除所选")
        remove_action.setEnabled(self.table.currentRow() >= 0)
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is add_action:
            self.add_row()
        elif chosen is remove_action and self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def add_row(self, attachment=None):
        source = attachment if isinstance(attachment, dict) else {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 42)
        name = str(source.get("item_name") or source.get("name") or ("自定义附件" if not source else "附件"))
        spec = _attachment_dimension_or_model(source)
        self.table.setItem(row, self.COL_NAME, QTableWidgetItem(name))
        model_options = {
            "三排安装梁": THREE_ROW_BEAM_MODELS,
            "照明灯/行程开关": LIGHT_SWITCH_MODELS,
        }.get(name)
        if model_options:
            model = str(source.get("model_code") or source.get("specification") or "").strip().upper()
            selector = QComboBox()
            selector.setObjectName("scheme2AttachmentModelCombo")
            selector.view().setObjectName("scheme2AttachmentModelDropdown")
            selector.addItem("未选择", "")
            for option in model_options:
                selector.addItem(option, option)
            selector.setCurrentIndex(max(0, selector.findData(model)))
            self.table.setCellWidget(row, self.COL_SPECIFICATION, selector)
            selector.currentIndexChanged.connect(
                lambda _index, target_row=row, combo=selector: self._beam_model_changed(target_row, combo.currentData())
            )
        else:
            specification_item = QTableWidgetItem(spec)
            specification_item.setData(ROLE_DERIVED_SPEC, spec)
            self.table.setItem(row, self.COL_SPECIFICATION, specification_item)
        quantity = QSpinBox()
        quantity.setObjectName("scheme2AttachmentEditorQuantity")
        quantity.setRange(-9999, 9999)
        quantity.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        quantity.setAlignment(Qt.AlignmentFlag.AlignCenter)
        quantity.setValue(max(-9999, min(9999, int(_number(source.get("quantity", 1), 1)))))
        self.table.setCellWidget(row, self.COL_QUANTITY, quantity)
        self.table.item(row, self.COL_NAME).setData(ROLE_ROW, dict(source))
        self._render_amounts(row, source)
        quantity.valueChanged.connect(lambda value, target_row=row: self._quantity_changed(target_row, value))

    def _beam_model_changed(self, row, model):
        model = str(model or "").strip().upper()
        if not model:
            return
        source_item = self.table.item(row, self.COL_NAME)
        source = dict(source_item.data(ROLE_ROW) or {}) if source_item is not None else {}
        if str(source.get("model_code") or "").strip().upper() == model:
            return
        source.update({"model_code": model, "specification": model, "matched_specification": model})
        for key in ("attachment_price_id", "unit_price_override", "matched_price", "quick_amount", "formula_amount"):
            source.pop(key, None)
        source_item.setData(ROLE_ROW, source)
        self._reprice_row(row, source)

    @staticmethod
    def _pending_dimensions(source):
        return [str(name) for name in source.get("pending_manual_dimensions", []) if str(name).strip()]

    def _render_amounts(self, row, source):
        pending = bool(self._pending_dimensions(source))
        formula_amount = 0.0 if pending else _number(source.get("formula_amount"), 0)
        custom = bool(source.get("custom"))
        quick_fallback = formula_amount * 1.2 if custom else _attachment_amount(source)
        quick_amount = 0.0 if pending else _number(source.get("quick_amount"), quick_fallback)
        if custom:
            cost_editor = self.table.cellWidget(row, self.COL_FORMULA_AMOUNT)
            if not isinstance(cost_editor, QDoubleSpinBox):
                cost_editor = QDoubleSpinBox()
                cost_editor.setObjectName("scheme2AttachmentEditorCost")
                cost_editor.setRange(-999999.99, 999999.99)
                cost_editor.setDecimals(2)
                cost_editor.setSingleStep(1)
                cost_editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                cost_editor.setAlignment(Qt.AlignmentFlag.AlignRight)
                self.table.setCellWidget(row, self.COL_FORMULA_AMOUNT, cost_editor)
                cost_editor.valueChanged.connect(lambda value, target_row=row: self._custom_cost_changed(target_row, value))
            with QSignalBlocker(cost_editor):
                cost_editor.setValue(formula_amount)
            cost_editor.setProperty("schemeEdited", bool(source.get("custom_cost_edited")))
            cost_editor.setToolTip("人工填写成本；未手工改金额时，金额=成本×1.2")
        amount_editor = self.table.cellWidget(row, self.COL_AMOUNT)
        if not isinstance(amount_editor, QDoubleSpinBox):
            amount_editor = QDoubleSpinBox()
            amount_editor.setObjectName("scheme2AttachmentEditorAmount")
            amount_editor.setRange(-999999.99, 999999.99)
            amount_editor.setDecimals(2)
            amount_editor.setSingleStep(1)
            amount_editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            amount_editor.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.table.setCellWidget(row, self.COL_AMOUNT, amount_editor)
            amount_editor.valueChanged.connect(lambda value, target_row=row: self._amount_changed(target_row, value))
        with QSignalBlocker(amount_editor):
            amount_editor.setValue(quick_amount)
        amount_editor.setProperty("schemeEdited", False)
        amount_editor.setProperty("pending", pending)
        amount_editor.setToolTip("尺寸不完整，当前按 0 元计；点击“尺寸 / 规格”补充" if pending else "金额支持人工修改")
        amount_editor.style().unpolish(amount_editor)
        amount_editor.style().polish(amount_editor)

        if not custom:
            cell = QTableWidgetItem(_money(formula_amount))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            font = cell.font()
            font.setUnderline(True)
            cell.setFont(font)
            if pending:
                cell.setData(Qt.ItemDataRole.ForegroundRole, QColor("#C62828"))
                cell.setToolTip("尺寸不完整，当前按 0 元计；点击“尺寸 / 规格”补充")
                cell.setBackground(QColor("#FAEEDA"))
            self.table.setItem(row, self.COL_FORMULA_AMOUNT, cell)
        specification = self.table.item(row, self.COL_SPECIFICATION)
        if pending and specification is not None:
            specification.setText("点击补充：" + "、".join(self._pending_dimensions(source)))
            specification.setData(Qt.ItemDataRole.ForegroundRole, QColor("#C62828"))
            for column in (self.COL_NAME, self.COL_SPECIFICATION, self.COL_QUANTITY):
                cell = self.table.item(row, column)
                if cell is not None:
                    cell.setBackground(QColor("#FAEEDA"))

    def _amount_changed(self, row, value):
        editor = self.table.cellWidget(row, self.COL_AMOUNT)
        if editor is not None:
            editor.setProperty("schemeEdited", True)

    def _custom_cost_changed(self, row, value):
        cost_editor = self.table.cellWidget(row, self.COL_FORMULA_AMOUNT)
        if isinstance(cost_editor, QDoubleSpinBox):
            cost_editor.setProperty("schemeEdited", True)
        amount_editor = self.table.cellWidget(row, self.COL_AMOUNT)
        if isinstance(amount_editor, QDoubleSpinBox) and not amount_editor.property("schemeEdited"):
            with QSignalBlocker(amount_editor):
                amount_editor.setValue(value * 1.2)

    def _quantity_changed(self, row, value):
        amount_editor = self.table.cellWidget(row, self.COL_AMOUNT)
        source_item = self.table.item(row, self.COL_NAME)
        if not isinstance(amount_editor, QDoubleSpinBox) or amount_editor.property("schemeEdited"):
            return
        source = dict(source_item.data(ROLE_ROW) or {}) if source_item is not None else {}
        previous_quantity = int(_number(source.get("quantity", 1), 1))
        if source.get("custom"):
            cost_editor = self.table.cellWidget(row, self.COL_FORMULA_AMOUNT)
            if isinstance(cost_editor, QDoubleSpinBox):
                previous_cost = cost_editor.value()
                unit_cost = previous_cost / previous_quantity if previous_quantity else previous_cost
                with QSignalBlocker(cost_editor):
                    cost_editor.setValue(unit_cost * value)
                if not amount_editor.property("schemeEdited"):
                    with QSignalBlocker(amount_editor):
                        amount_editor.setValue(unit_cost * value * 1.2)
            return
        unit_amount = (
            _number(source.get("quick_amount"), _attachment_amount(source)) / previous_quantity
            if previous_quantity else 0
        )
        with QSignalBlocker(amount_editor):
            amount_editor.setValue(unit_amount * value)
        previous_formula = _number(source.get("formula_amount"), 0)
        formula = self.table.item(row, self.COL_FORMULA_AMOUNT)
        if formula is not None:
            formula.setText(_money((previous_formula / previous_quantity if previous_quantity else 0) * value))

    def edit_missing_dimensions(self, row, column):
        if column != self.COL_SPECIFICATION or not 0 <= row < self.table.rowCount():
            return
        source_item = self.table.item(row, self.COL_NAME)
        source = dict(source_item.data(ROLE_ROW) or {}) if source_item is not None else {}
        missing = self._pending_dimensions(source)
        if not missing:
            return
        manual = source.get("manual_inputs") if isinstance(source.get("manual_inputs"), dict) else {}
        editor = _SchemeDimensionEditor(
            self,
            f"{source.get('item_name', '附件')} · 补充尺寸",
            missing,
            manual,
        )
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        values = editor.values()
        source["manual_inputs"] = {**manual, **values}
        source_item.setData(ROLE_ROW, source)
        specification = self.table.item(row, self.COL_SPECIFICATION)
        if specification is not None:
            specification.setText("；".join(f"{name}={value:g} mm" for name, value in values.items()))
            specification.setData(Qt.ItemDataRole.ForegroundRole, QColor("#B45309"))
        self._reprice_row(row, source, specification)

    def _reprice_row(self, row, source, specification=None):
        source_item = self.table.item(row, self.COL_NAME)
        specification_editor = self.table.cellWidget(row, self.COL_SPECIFICATION)
        if isinstance(specification_editor, QComboBox):
            specification_editor.setEnabled(False)
        amount_editor = self.table.cellWidget(row, self.COL_AMOUNT)
        if isinstance(amount_editor, QDoubleSpinBox):
            amount_editor.setEnabled(False)
            amount_editor.setToolTip("计算中…")
        formula_item = self.table.item(row, self.COL_FORMULA_AMOUNT)
        if formula_item is not None:
            formula_item.setText("计算中…")
            formula_item.setData(Qt.ItemDataRole.ForegroundRole, QColor("#B45309"))
        reprice = getattr(self.window, "recalculate_draft_attachment", None)
        if not callable(reprice):
            QMessageBox.warning(self, "附件计算失败", "附件数据库计算功能不可用。")
            return

        def succeeded(calculated):
            source_item.setData(ROLE_ROW, dict(calculated))
            if isinstance(specification, QTableWidgetItem):
                specification.setData(Qt.ItemDataRole.ForegroundRole, QColor("#1C1C1E"))
            if isinstance(amount_editor, QDoubleSpinBox):
                amount_editor.setEnabled(True)
            if isinstance(specification_editor, QComboBox):
                specification_editor.setEnabled(True)
            self._render_amounts(row, calculated)

        def failed(message):
            if isinstance(amount_editor, QDoubleSpinBox):
                with QSignalBlocker(amount_editor):
                    amount_editor.setValue(0)
                amount_editor.setEnabled(True)
                amount_editor.setProperty("pending", True)
            if isinstance(specification_editor, QComboBox):
                specification_editor.setEnabled(True)
            formula_item = self.table.item(row, self.COL_FORMULA_AMOUNT)
            if formula_item is not None:
                formula_item.setText(_money(0))
                formula_item.setData(Qt.ItemDataRole.ForegroundRole, QColor("#C62828"))
            QMessageBox.warning(self, "附件计算失败", str(message))

        reprice(self.item, source, succeeded, failed)

    def accept(self):
        old_formula_total = _number(_formula(self.item).get("attachment_fee"), 0)
        old_quick_total = _number(_quick(self.item).get("attachment_fee"), _attachment_total(self.item))
        rows = []
        for row in range(self.table.rowCount()):
            data = self.table.item(row, self.COL_NAME).data(ROLE_ROW) or {}
            data = dict(data)
            previous_quantity = int(_number(data.get("quantity", 1), 1))
            previous_formula_amount = _number(data.get("formula_amount"), 0)
            data["item_name"] = self.table.item(row, self.COL_NAME).text().strip() or "自定义附件"
            specification_editor = self.table.cellWidget(row, self.COL_SPECIFICATION)
            specification_item = self.table.item(row, self.COL_SPECIFICATION)
            specification = (
                str(specification_editor.currentData() or specification_editor.currentText()).strip()
                if isinstance(specification_editor, QComboBox)
                else specification_item.text().strip()
            )
            if isinstance(specification_editor, QComboBox) or (
                specification_item.data(ROLE_DERIVED_SPEC) != specification
            ):
                data["specification"] = specification
            if data.get("item_name") in {"三排安装梁", "照明灯/行程开关"} and specification:
                data["model_code"] = specification
            data["quantity"] = self.table.cellWidget(row, self.COL_QUANTITY).value()
            amount_editor = self.table.cellWidget(row, self.COL_AMOUNT)
            amount = _number(amount_editor.value())
            custom = bool(data.get("custom"))
            cost_editor = self.table.cellWidget(row, self.COL_FORMULA_AMOUNT)
            if custom and isinstance(cost_editor, QDoubleSpinBox):
                data["formula_amount"] = round(cost_editor.value(), 2)
                data["custom_cost"] = round(cost_editor.value(), 2)
                data["custom_cost_edited"] = bool(cost_editor.property("schemeEdited"))
            data["quick_amount_override"] = round(amount, 2)
            data["quick_amount"] = round(amount, 2)
            if custom:
                unit_price = amount / data["quantity"] if data["quantity"] else amount
                data["unit_price_override"] = unit_price
                data["matched_price"] = unit_price
            else:
                formula_unit_amount = (
                    _number(data.get("formula_unit_cost"))
                    * (-1 if int(_number(data.get("attachment_price_sign", 1), 1)) == -1 else 1)
                    if data.get("formula_unit_cost") is not None
                    else previous_formula_amount / previous_quantity if previous_quantity else 0
                )
                data["formula_amount"] = round(formula_unit_amount * data["quantity"], 2)
            data.setdefault("selection_source", "QUOTE_LOCAL")
            rows.append(data)
        self.item["attachments"] = rows
        new_quick_total = sum(_number(row.get("quick_amount"), _attachment_amount(row)) for row in rows)
        new_formula_total = sum(_number(row.get("formula_amount"), 0) for row in rows)
        for quote, previous, current in (
            (_formula(self.item), old_formula_total, new_formula_total),
            (_quick(self.item), old_quick_total, new_quick_total),
        ):
            quote["attachment_fee"] = round(current, 2)
            quote["total_cost"] = round(_number(quote.get("total_cost")) - previous + current, 2)
        self.window.refresh_summary()
        super().accept()


class _SchemePencilSpinBox(QDoubleSpinBox):
    def __init__(self, display_decimals=2, parent=None):
        super().__init__(parent)
        self._display_decimals = display_decimals
        self.lineEdit().setTextMargins(0, 0, 18, 0)

    def textFromValue(self, value):
        return f"{value:.{self._display_decimals}f}"

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#5F5E5A"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x = self.width() - 15
        y = self.height() // 2
        painter.drawLine(QPoint(x - 4, y + 4), QPoint(x + 4, y - 4))
        painter.drawLine(QPoint(x - 2, y + 6), QPoint(x + 6, y - 2))
        painter.drawLine(QPoint(x - 4, y + 4), QPoint(x - 2, y + 6))


class FaceDiscountEditor(QDialog):
    def __init__(self, window, item, target_items=None):
        super().__init__(window)
        self.window = window
        self.item = item
        self.target_items = list(target_items or [item])
        self.setWindowTitle("面价折扣")
        self.setObjectName("scheme2DiscountDialog")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(348, 247)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("scheme2DiscountShell")
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(14, 0, 14, 12)
        layout.setSpacing(8)
        outer.addWidget(shell)
        header = QFrame()
        header.setObjectName("scheme2DiscountHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 8, 0, 8)
        product = _cost_product(item)
        title = QLabel(f"{product}统一面价折扣" if len(self.target_items) > 1 else "面价折扣")
        title.setObjectName("scheme2DialogTitle")
        close = QToolButton()
        close.setObjectName("scheme2DiscountClose")
        close.setText("×")
        close.setAccessibleName("关闭面价折扣")
        close.setFixedSize(26, 26)
        close.clicked.connect(self.reject)
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(close)
        layout.addWidget(header)
        base = _number(_quick(item).get("total_cost")) + _number(item.get("freight_fee", 0))
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("原面价"))
        base_row.addStretch(1)
        base_value = QLabel(f"{_money(base)} 元")
        base_value.setObjectName("scheme2DiscountBase")
        base_row.addWidget(base_value)
        layout.addLayout(base_row)
        discount_label = QLabel("折扣（如 0.85 / 85%）")
        discount_label.setObjectName("scheme2DiscountHint")
        layout.addWidget(discount_label)
        self.discount = _SchemePencilSpinBox(2)
        self.discount.setObjectName("scheme2DiscountInput")
        self.discount.setRange(0.01, 10)
        self.discount.setDecimals(4)
        self.discount.setSingleStep(.01)
        self.discount.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.discount.setValue(_number(item.get("quick_discount", 1), 1))
        layout.addWidget(self.discount)
        preview_frame = QFrame()
        preview_frame.setObjectName("scheme2DiscountPreview")
        preview_layout = QHBoxLayout(preview_frame)
        preview_layout.setContentsMargins(10, 0, 10, 0)
        preview_layout.addWidget(QLabel("折后面价"))
        preview_layout.addStretch(1)
        self.preview = QLabel()
        self.preview.setObjectName("scheme2DiscountPreviewValue")
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_frame)
        self.discount.valueChanged.connect(lambda value: self.preview.setText(f"{_money(base * value)} 元"))
        self.discount.valueChanged.emit(self.discount.value())
        actions = QHBoxLayout()
        confirm = QPushButton("确定")
        confirm.setObjectName("scheme2PrimaryAction")
        cancel = QPushButton("取消")
        cancel.setObjectName("scheme2DiscountCancel")
        confirm.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        actions.addWidget(confirm)
        actions.addWidget(cancel)
        actions.addStretch(1)
        layout.addLayout(actions)

    def accept(self):
        for item in self.target_items:
            item["quick_discount"] = self.discount.value()
        self.window.refresh_summary()
        super().accept()


def _printable_quote_html(window, font_step=0) -> str:
    company = html.escape(str(getattr(window, "scheme2_company", None).currentText() if getattr(window, "scheme2_company", None) is not None else ""))
    order_number = html.escape(str(getattr(window, "scheme2_order_number", None).text() if getattr(window, "scheme2_order_number", None) is not None else ""))
    quote_date = date.today().isoformat()
    rows = []
    total = 0.0
    for index, item in enumerate(getattr(window, "draft_items", []), 1):
        values = _row_values(item)
        amount = _number(values[16])
        total += amount
        remark = str(item.get("final_remark") or _scheme2_quote_remark(item))
        cells = (index, values[1], values[3], values[11], "台", f"{_number(values[15]):,.2f}", f"{amount:,.2f}", remark)
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in cells) + "</tr>")
    return f"""
    <html><head><style>
    body{{font-family:'Microsoft YaHei UI';font-size:{10 + font_step}pt;color:#202B38}}
    h1{{text-align:center;font-size:{18 + font_step}pt}} table{{width:100%;border-collapse:collapse}}
    th,td{{border:1px solid #64748B;padding:6px;text-align:center}} th{{background:#DCE8F7}}
    .meta td{{text-align:left}} .total{{font-weight:600}}
    </style></head><body><table class="meta">
    <tr><th>报价单</th><td>{order_number}</td><td colspan="6"></td></tr>
    <tr><th>日期</th><td>{quote_date}</td><td colspan="6"></td></tr><tr><td colspan="8">&nbsp;</td></tr>
    <tr><th>买方</th><td>{company}</td><th>卖方</th><td colspan="5">浙江京能电力设备有限公司</td></tr>
    <tr><th>地址</th><td></td><th>地址</th><td colspan="5">杭州临安横畈工业功能区桑园路18号</td></tr>
    <tr><th>电话</th><td></td><th>电话</th><td colspan="5">0571-88520091</td></tr>
    <tr><th>传真</th><td></td><th>传真</th><td colspan="5">0571-88520077</td></tr>
    <tr><th>邮箱</th><td></td><th>邮箱</th><td colspan="5"></td></tr><tr><td colspan="8">&nbsp;</td></tr>
    <tr><th>序号</th><th>名称</th><th>规格型号(W*D*H)</th><th>数量</th><th>单位</th><th>单价</th><th>总价</th><th>备注</th></tr>
    {''.join(rows)}<tr class="total"><td></td><td>合计</td><td colspan="4"></td><td>{total:,.2f}</td><td></td></tr></table></body></html>
    """


def _print_quote(window):
    if not getattr(window, "draft_items", []):
        QMessageBox.warning(window, "报价清单为空", "请先将至少一个柜型加入报价清单。")
        return
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer, window)
    dialog.setWindowTitle("打印报价单")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    document = QTextDocument(window)
    document.setHtml(_printable_quote_html(window))
    document.print_(printer)


def _quote_unit_price_changed(window, row, column):
    if getattr(window, "_scheme2_refreshing_quote", False) or column != 5 or row < 10:
        return
    items = getattr(window, "draft_items", [])
    index = row - 10
    if not 0 <= index < len(items):
        return
    cell = window.scheme2_quote_preview.item(row, column)
    unit_price = _number(cell.text().replace(",", ""), -1) if cell is not None else -1
    face_price = _number(_row_values(items[index])[13])
    if unit_price < 0 or face_price <= 0:
        _refresh_quote_page(window)
        return
    items[index]["quick_discount"] = unit_price / face_price
    window.refresh_summary()


def _refresh_quote_page(window):
    preview = getattr(window, "scheme2_quote_preview", None)
    if isinstance(preview, QTableWidget):
        items = getattr(window, "draft_items", [])
        company = window.scheme2_company.currentText() if hasattr(window, "scheme2_company") else ""
        order_number = window.scheme2_order_number.text() if hasattr(window, "scheme2_order_number") else ""
        window._scheme2_refreshing_quote = True
        try:
            preview.clearSpans()
            preview.setRowCount(11 + len(items))
            meta = (
                (0, "报价单", order_number, "", ""), (1, "日期", date.today().isoformat(), "", ""),
                (3, "买方", company, "卖方", "浙江京能电力设备有限公司"),
                (4, "地址", "", "地址", "杭州临安横畈工业功能区桑园路18号"),
                (5, "电话", "", "电话", "0571-88520091"),
                (6, "传真", "", "传真", "0571-88520077"), (7, "邮箱", "", "邮箱", ""),
            )
            for row in range(preview.rowCount()):
                for column in range(8):
                    cell = QTableWidgetItem("")
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    preview.setItem(row, column, cell)
            for row, left_label, left_value, right_label, right_value in meta:
                preview.item(row, 0).setText(left_label); preview.item(row, 1).setText(left_value)
                preview.item(row, 2).setText(right_label); preview.item(row, 3).setText(right_value)
                preview.setSpan(row, 3, 1, 5)
            headings = ("序号", "名称", "规格型号(W*D*H)", "数量", "单位", "单价", "总价", "备注")
            for column, heading in enumerate(headings):
                preview.item(9, column).setText(heading)
            total = 0.0
            for index, item in enumerate(items):
                row = 10 + index
                values = _row_values(item)
                amount = _number(values[16]); total += amount
                remark = str(item.get("final_remark") or _scheme2_quote_remark(item))
                data = (index + 1, values[1], values[3], values[11], "台", _money(values[15]), _money(amount), remark)
                for column, value in enumerate(data):
                    preview.item(row, column).setText(str(value))
                preview.item(row, 5).setFlags(preview.item(row, 5).flags() | Qt.ItemFlag.ItemIsEditable)
            total_row = 10 + len(items)
            preview.item(total_row, 1).setText("合计")
            preview.item(total_row, 6).setText(_money(total))
            preview.resizeRowsToContents()
            for row in range(10, 10 + len(items)):
                preview.setRowHeight(row, max(72, preview.rowHeight(row)))
        finally:
            window._scheme2_refreshing_quote = False
    enabled = bool(getattr(window, "draft_items", []))
    for button in (
        getattr(window, "scheme2_quote_print", None),
        getattr(window, "scheme2_quote_export", None),
    ):
        if isinstance(button, QPushButton):
            button.setEnabled(enabled)


def _build_quote_page(window):
    page = QWidget()
    page.setObjectName("scheme2QuotePage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(10)
    header = QHBoxLayout()
    title = QLabel("报价单")
    title.setObjectName("scheme2PageTitle")
    header.addWidget(title)
    header.addStretch(1)
    company_field = _inline_field("下单公司", window.scheme2_company)
    company_field.setObjectName("scheme2QuoteCompanyField")
    company_field.setFixedWidth(QUOTE_COMPANY_FIELD_WIDTH)
    print_button = QPushButton("打印")
    print_button.setObjectName("scheme2PrimaryGhost")
    export_button = QPushButton("导出报价单")
    export_button.setObjectName("scheme2PrimaryAction")
    header.addWidget(company_field)
    header.addWidget(print_button)
    header.addWidget(export_button)
    layout.addLayout(header)
    preview = QTableWidget(0, 8)
    preview.setObjectName("scheme2QuotePreview")
    preview.horizontalHeader().hide()
    preview.verticalHeader().hide()
    preview.setAlternatingRowColors(False)
    preview.setWordWrap(True)
    preview.setTextElideMode(Qt.TextElideMode.ElideNone)
    preview.setColumnWidth(0, 58); preview.setColumnWidth(1, 145); preview.setColumnWidth(2, 180)
    preview.setColumnWidth(3, 72); preview.setColumnWidth(4, 58); preview.setColumnWidth(5, 105)
    preview.setColumnWidth(6, 115); preview.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
    layout.addWidget(preview, 1)
    print_button.clicked.connect(lambda: _print_quote(window))
    export_button.clicked.connect(lambda: window.confirm_and_export())
    preview.cellChanged.connect(lambda row, column: _quote_unit_price_changed(window, row, column))
    window.scheme2_company.currentTextChanged.connect(lambda _text: _refresh_quote_page(window))
    window.scheme2_quote_page = page
    window.scheme2_quote_preview = preview
    window.scheme2_quote_company_field = company_field
    window.scheme2_quote_print = print_button
    window.scheme2_quote_export = export_button
    _install_export_busy_feedback(window, export_button)
    _refresh_quote_page(window)
    return page


def _detail_rows(item):
    existing = item.get("cost_detail_rows")
    if isinstance(existing, list) and existing and all(row.get("_scheme2_version") == 2 for row in existing if isinstance(row, dict)):
        return existing
    formula = _formula(item)
    rows = []

    def add_row(**values):
        values.setdefault("factor", 1.0)
        values["_scheme2_version"] = 2
        rows.append(values)

    for detail in formula.get("cabinet_material_part_details", []) or []:
        if not isinstance(detail, dict):
            continue
        area = _number(detail.get("area_m2"))
        waste = _number(detail.get("waste_factor"), 1)
        thickness = _number(detail.get("sheet_thickness_mm"))
        density = _number(detail.get("density_g_cm3"))
        add_row(
            category="material_cost", type="材料成本", name=detail.get("part_name", "材料"),
            spec=f"{detail.get('material_code', '')} / {detail.get('sheet_thickness_mm', '')} mm",
            formula=f"面积 {area:,.6f} m² × 系数 {waste:g} × 壁厚 {thickness:g} mm × 密度 {density:g}",
            quantity=detail.get("billable_weight_kg", 0),
            unit="kg", unit_price=detail.get("material_unit_price", 0),
            base_amount=detail.get("material_cost", 0),
            note="材料公式（面积×厚度×密度×废料系数）",
        )
    if not any(row.get("category") == "material_cost" for row in rows):
        amount = _number(formula.get("material_cost"))
        add_row(category="material_cost", type="材料成本", name="材料成本", spec="报价快照汇总",
                formula="现有报价结果", quantity=1, unit="项", unit_price=amount,
                base_amount=amount, note="")

    auxiliary_lines = [line for line in formula.get("cabinet_auxiliary_lines", []) or [] if isinstance(line, dict)]
    for line in auxiliary_lines:
        quantity = _number(line.get("internal_quantity"))
        unit = str(line.get("unit") or "件")
        unit_price = _number(line.get("unit_price"))
        amount = _number(line.get("line_total"), _number(line.get("base_cost")) + _number(line.get("spray_cost")))
        spec = " / ".join(filter(None, (
            str(line.get("spec_model") or "").strip(),
            str(line.get("material_name") or "").strip(),
        )))
        add_row(
            category="auxiliary_cost", type="辅材成本", name=line.get("item_name", "辅材"), spec=spec,
            formula=f"{quantity:g} {unit} × {unit_price:,.4f} 元/{unit} = {_money(amount)} 元",
            quantity=quantity, unit=unit, unit_price=unit_price, base_amount=amount,
            note=str(line.get("notes") or ""),
        )
    if not auxiliary_lines:
        amount = _number(formula.get("auxiliary_cost"))
        add_row(category="auxiliary_cost", type="辅材成本", name="辅材成本", spec="报价快照汇总",
                formula="现有报价结果", quantity=1, unit="项", unit_price=amount,
                base_amount=amount, note="")

    if _number(formula.get("labor_cost")) or formula.get("labor_source_formula"):
        labor = _number(formula.get("labor_cost"))
        add_row(
            category="labor_cost", type="人工成本", name="柜体人工成本",
            spec=str(formula.get("labor_method") or "人工成本"),
            formula=str(formula.get("labor_source_formula") or "人工成本计算结果"),
            quantity=1, unit="项", unit_price=labor, base_amount=labor,
            note="人工公式计算结果",
        )
    else:
        amount = _number(formula.get("labor_cost"))
        add_row(category="labor_cost", type="人工成本", name="人工成本", spec="报价快照汇总",
                formula="现有报价结果", quantity=1, unit="项", unit_price=amount,
                base_amount=amount, note="")

    attachment = _number(formula.get("attachment_fee"))
    add_row(category="attachment_fee", type="附件成本", name="附件成本", spec="报价快照汇总",
            formula="现有报价结果", quantity=1, unit="项", unit_price=attachment,
            base_amount=attachment, note="")

    for detail in formula.get("cabinet_spray_part_details", []) or []:
        if not isinstance(detail, dict):
            continue
        area = _number(detail.get("total_area_m2"))
        unit_price = _number(formula.get("spray_unit_price"))
        add_row(
            category="spray_cost", type="喷涂费用", name=detail.get("part_name", "喷涂"),
            spec=str(formula.get("coating_type") or ""),
            formula=f"面积 {area:,.6f} m² × {unit_price:,.4f} 元/m²",
            quantity=area, unit="㎡", unit_price=unit_price,
            base_amount=area * unit_price,
            note="喷塑公式（表面积×单价）",
        )
    if not any(row.get("category") == "spray_cost" for row in rows):
        amount = _number(formula.get("spray_cost"))
        add_row(category="spray_cost", type="喷涂费用", name="喷涂费用", spec="报价快照汇总",
                formula="现有报价结果", quantity=1, unit="项", unit_price=amount,
                base_amount=amount, note="")

    management = _number(formula.get("management_fee"))
    if management or formula.get("management_fee_rate") is not None:
        rate = _number(formula.get("management_fee_rate"), .13)
        labor = _number(formula.get("labor_cost"))
        add_row(
            category="management_fee", type="管理费用", name="管理费用",
            spec=f"人工成本的 {rate * 100:g}%",
            formula=f"{_money(labor)} × {rate:g} = {_money(management)} 元",
            quantity=1, unit="项", unit_price=management, base_amount=management,
            note="人工成本 × 管理费率",
        )
    else:
        add_row(category="management_fee", type="管理费用", name="管理费用", spec="报价快照汇总",
                formula="现有报价结果", quantity=1, unit="项", unit_price=management,
                base_amount=management, note="")
    item["cost_detail_rows"] = rows
    return rows


def _build_detail_page(window):
    page = QWidget()
    page.setObjectName("scheme2DetailPage")
    page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)
    header = QHBoxLayout()
    back = QPushButton("‹ 返回成本计算")
    back.setObjectName("scheme2PrimaryGhost")
    title = QLabel("成本明细")
    title.setObjectName("scheme2PageTitle")
    header.addWidget(back)
    header.addWidget(title)
    header.addStretch(1)
    meta = QLabel()
    meta.setObjectName("scheme2DetailMeta")
    header.addWidget(meta)
    layout.addLayout(header)
    table = QTableWidget(0, 11)
    table.setObjectName("scheme2DetailTable")
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setHorizontalHeaderLabels((
        "成本\n类型", "明细项目", "规格/说明", "计算公式\n计算结果", "最终衡\n量", "单\n位",
        "单价\n（元）", "本项金额\n（元）", "系数", "行金额\n（元）", "备注",
    ))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    table.horizontalHeader().setMinimumHeight(44)
    table.horizontalHeader().setStretchLastSection(True)
    for column, width in enumerate((72, 138, 125, 260, 78, 54, 80, 92, 70, 92, 150)):
        table.setColumnWidth(column, width)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(46)
    table.setAlternatingRowColors(True)
    table.setWordWrap(True)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    layout.addWidget(table, 1)
    window.scheme2_detail_page = page
    window.scheme2_detail_table = table
    window.scheme2_detail_meta = meta

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
    summary_index = len(rows)
    table.setRowCount(len(rows) + 1)
    meta = getattr(window, "scheme2_detail_meta", None)
    if isinstance(meta, QLabel):
        name = str(item.get("name") or item.get("model_code") or "未命名")
        product = _cost_product(item)
        specification = str(item.get("specification") or "—")
        meta.setText(f"名称 {name} · 产品 {product} · 规格 {specification}")

    def rendered_total():
        return sum(
            _number(detail.get("base_amount")) * _number(detail.get("factor", 1), 1)
            for detail in rows
        )

    def refresh_summary_total():
        total = rendered_total()
        for column in (6, 7, 9):
            cell = table.item(summary_index, column)
            if cell is not None:
                cell.setText(_money(total))

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
                spin = _SchemePencilSpinBox(2)
                spin.setObjectName("scheme2DetailFactor")
                spin.setRange(0, 10)
                spin.setDecimals(4)
                spin.setSingleStep(.01)
                spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
                spin.setValue(factor)

                def update_factor(value, r=row_index, d=detail):
                    d["factor"] = value
                    table.item(r, 9).setText(_money(_number(d.get("base_amount")) * value))
                    refresh_summary_total()

                spin.valueChanged.connect(update_factor)
                table.setCellWidget(row_index, column, spin)
            else:
                cell = QTableWidgetItem(str(value))
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cell.setToolTip(str(value))
                if column in (4, 6, 7, 9):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif column == 5:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_index, column, cell)
        table.setRowHeight(row_index, 46)

    total = rendered_total()
    summary_values = (
        "成型件成本", "合计成本", "折算 1.00 台", "材料+人工+喷塑等逐项汇总",
        "1.0000", "台", _money(total), _money(total), "1.0000", _money(total), "汇总行",
    )
    for column, value in enumerate(summary_values):
        cell = QTableWidgetItem(str(value))
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        font = cell.font()
        font.setBold(True)
        cell.setFont(font)
        if column in (4, 6, 7, 8, 9):
            cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif column == 5:
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(summary_index, column, cell)
    table.setRowHeight(summary_index, 46)
    window.stack.setCurrentIndex(DETAIL_ROUTE)
    _apply_responsive(window)
    _schedule_order_workspace_save(window)


class _MultilineComboPaintFilter(QObject):
    @staticmethod
    def _lines(text, metrics, width):
        lines = []
        current = ""
        for character in text:
            candidate = current + character
            if current and metrics.horizontalAdvance(candidate) > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current or not lines:
            lines.append(current)
        return lines

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Paint or not isinstance(watched, QComboBox):
            return super().eventFilter(watched, event)
        # Editable combo boxes already paint their line editor. Drawing the
        # combo text again after focus leaves produces two overlapping names.
        if watched.isEditable():
            return super().eventFilter(watched, event)
        option = QStyleOptionComboBox()
        watched.initStyleOption(option)
        option.currentText = ""
        painter = QPainter(watched)
        style = watched.style()
        style.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, watched)
        text_rect = style.subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            watched,
        ).adjusted(5, 4, -2, -4)
        painter.setPen(option.palette.text().color())
        font = watched.font()
        while True:
            metrics = QFontMetrics(font)
            lines = self._lines(watched.currentText(), metrics, text_rect.width())
            if len(lines) * metrics.lineSpacing() <= text_rect.height() or font.pointSizeF() <= 7:
                break
            font.setPointSizeF(font.pointSizeF() - .5)
        painter.setFont(font)
        line_height = metrics.lineSpacing()
        y = text_rect.top() + max(0, (text_rect.height() - len(lines) * line_height) // 2)
        for line in lines:
            painter.drawText(
                text_rect.left(), y, text_rect.width(), line_height,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )
            y += line_height
        return True


class _SchemeConfirmDialog(QDialog):
    def __init__(self, parent, title, message, accept_text, reject_text="继续编辑"):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("scheme2ConfirmDialog")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if parent is not None:
            self.resize(parent.size())
            self.move(parent.mapToGlobal(QPoint(0, 0)))

        overlay = QVBoxLayout(self)
        overlay.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("scheme2ConfirmShell")
        shell.setFixedWidth(386)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 14)
        shell_layout.setSpacing(0)

        title_bar = QFrame()
        title_bar.setObjectName("scheme2ConfirmTitleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 0, 8, 0)
        title_label = QLabel(title)
        title_label.setObjectName("scheme2ConfirmTitle")
        close_button = QToolButton()
        close_button.setObjectName("scheme2ConfirmClose")
        close_button.setText("×")
        close_button.setFixedSize(28, 28)
        close_button.clicked.connect(self.reject)
        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        title_layout.addWidget(close_button)
        shell_layout.addWidget(title_bar)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 12)
        content_layout.setSpacing(14)
        icon = QLabel("⚠")
        icon.setObjectName("scheme2ConfirmWarningIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(34, 34)
        message_label = QLabel(message)
        message_label.setObjectName("scheme2ConfirmMessage")
        message_label.setWordWrap(True)
        content_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        content_layout.addWidget(message_label, 1)
        shell_layout.addWidget(content)

        actions = QHBoxLayout()
        actions.setContentsMargins(16, 0, 16, 0)
        actions.setSpacing(10)
        actions.addStretch(1)
        reject_button = QPushButton(reject_text)
        reject_button.setObjectName("scheme2ConfirmReject")
        accept_button = QPushButton(accept_text)
        accept_button.setObjectName("scheme2ConfirmDanger")
        for button in (reject_button, accept_button):
            button.setMinimumHeight(30)
            button.setAutoDefault(False)
            button.setDefault(False)
        reject_button.clicked.connect(self.reject)
        accept_button.clicked.connect(self.accept)
        actions.addWidget(reject_button)
        actions.addWidget(accept_button)
        shell_layout.addLayout(actions)

        overlay.addStretch(1)
        overlay.addWidget(shell, 0, Qt.AlignmentFlag.AlignCenter)
        overlay.addStretch(1)
        self.shell = shell
        self.reject_button = reject_button
        self.accept_button = accept_button


def _confirm_discard_unsaved(parent):
    dialog = _SchemeConfirmDialog(
        parent,
        "有未保存变更",
        "当前配置尚未加入报价清单，关闭后将丢失本次填写的内容。",
        "放弃更改并关闭",
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


class _SchemeComboItemDelegate(QStyledItemDelegate):
    def __init__(self, combo, separator_index=-1):
        super().__init__(combo.view())
        self.combo = combo
        self.separator_index = separator_index
        self.setObjectName("scheme2DropdownItemDelegate")

    def sizeHint(self, option, index):
        return QSize(max(120, option.rect.width()), 40)

    @staticmethod
    def checkbox_rect(rect):
        return QRect(rect.left() + 14, rect.center().y() - 7, 15, 15)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        placeholder_value = self.combo.property("schemePlaceholderIndex")
        placeholder_index = int(placeholder_value) if placeholder_value is not None else -1
        if hasattr(self.combo, "is_row_selected"):
            chosen = self.combo.is_row_selected(index.row())
        else:
            chosen = (
                index.row() == self.combo.currentIndex()
                and self.combo.currentIndex() >= 0
                and index.row() != placeholder_index
            )
        hovered = bool(option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected))
        if chosen:
            painter.fillRect(rect, QColor("#E6F1FB"))
        elif hovered:
            painter.fillRect(rect, QColor("#F5F9FF"))
        else:
            painter.fillRect(rect, QColor("#FFFFFF"))
        if index.row() == self.separator_index:
            painter.setPen(QColor("#D7DCE3"))
            painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        custom = index.row() == self.separator_index
        shows_checkbox = hasattr(self.combo, "is_row_selected") and index.row() > 0
        if shows_checkbox:
            check_rect = self.checkbox_rect(rect)
            painter.setPen(QPen(QColor("#2563EB" if chosen else "#98A2B3"), 1))
            painter.setBrush(QColor("#2563EB") if chosen else QColor("#FFFFFF"))
            painter.drawRoundedRect(check_rect, 2, 2)
            if chosen:
                painter.setPen(QPen(QColor("#FFFFFF"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                center_y = check_rect.center().y()
                painter.drawLine(QPoint(check_rect.left() + 3, center_y), QPoint(check_rect.left() + 6, center_y + 3))
                painter.drawLine(QPoint(check_rect.left() + 6, center_y + 3), QPoint(check_rect.right() - 2, center_y - 4))
        painter.setPen(QColor("#185FA5" if chosen or custom else "#1C1C1E"))
        painter.drawText(
            rect.adjusted(40 if shows_checkbox else 14, 0, -14, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.restore()


class _DropdownPopupStateFilter(QObject):
    def __init__(self, combo, shell):
        super().__init__(combo)
        self.combo = combo
        self.shell = shell

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            opened = event.type() == QEvent.Type.Show
            placeholder_value = self.combo.property("schemePlaceholderIndex")
            placeholder_index = int(placeholder_value) if placeholder_value is not None else -1
            if opened and placeholder_index >= 0 and hasattr(self.combo.view(), "setRowHidden"):
                self.combo.view().setRowHidden(placeholder_index, True)
            self.combo.setProperty("popupOpen", opened)
            self.shell.setProperty("popupOpen", opened)
            for widget in (self.combo, self.shell):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
        return super().eventFilter(watched, event)


_CUSTOM_COMPANIES_KEY = "scheme2/custom_companies"


def _company_settings():
    return QSettings("AIQuoteDualSystem", "AIQuoteDualSystem")


def _saved_custom_companies():
    saved = _company_settings().value(_CUSTOM_COMPANIES_KEY, [])
    if isinstance(saved, str):
        saved = [saved]
    result = []
    for value in saved or []:
        name = str(value).strip()
        if name and name not in result:
            result.append(name)
    return result


def _restore_custom_companies(combo):
    if not isinstance(combo, QComboBox):
        return
    current = combo.currentText().strip()
    known = {combo.itemText(index).strip() for index in range(combo.count())}
    for name in _saved_custom_companies():
        if name not in known:
            combo.addItem(name, name)
            known.add(name)
    if current:
        combo.setEditText(current)


def _remember_custom_company(combo):
    name = combo.currentText().strip() if isinstance(combo, QComboBox) else ""
    if not name:
        return
    saved = _saved_custom_companies()
    if name not in saved:
        saved.append(name)
        settings = _company_settings()
        settings.setValue(_CUSTOM_COMPANIES_KEY, saved)
        settings.sync()
    if combo.findText(name, Qt.MatchFlag.MatchExactly) < 0:
        combo.addItem(name, name)
    combo.setEditText(name)


def _style_scheme_dropdown(combo, field, separator_index=-1):
    shell = field._scheme2_shell
    shell.setProperty("schemeDropdown", True)
    view = combo.view()
    view.setObjectName("scheme2OptionDropdown")
    view.setMouseTracking(True)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    combo.setMaxVisibleItems(max(1, combo.count()))
    combo._scheme2_item_delegate = _SchemeComboItemDelegate(combo, separator_index)
    view.setItemDelegate(combo._scheme2_item_delegate)
    combo._scheme2_popup_filter = _DropdownPopupStateFilter(combo, shell)
    view.installEventFilter(combo._scheme2_popup_filter)


def _refresh_product_placeholder(combo):
    placeholder_value = combo.property("schemePlaceholderIndex")
    placeholder_index = int(placeholder_value) if placeholder_value is not None else -1
    combo.setProperty("placeholderActive", combo.currentIndex() == placeholder_index)
    combo.style().unpolish(combo)
    combo.style().polish(combo)
    combo.update()


def _cost_sidebar(window):
    bar = QFrame()
    bar.setObjectName("scheme2CostSidebar")
    bar.setFixedWidth(COST_SIDEBAR_WIDTH)
    layout = QVBoxLayout(bar)
    layout.setContentsMargins(10, 12, 10, 12)
    layout.setSpacing(7)
    heading = QLabel("修改系数")
    heading.setObjectName("scheme2SidebarTitle")
    layout.addWidget(heading)
    company = getattr(window, "base_company_combo", None) or window.findChild(QComboBox, "baseCompanyCombo")
    if company is None:
        company = QComboBox()
    company.setEditable(True)
    company.setMinimumWidth(0)
    company.setMaximumWidth(16777215)
    company.setProperty("scheme2Multiline", True)
    company.setFixedHeight(COMPANY_COMBO_HEIGHT)
    company.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    company.view().setObjectName("scheme2CompanyDropdown")
    company.view().setMinimumWidth(320)
    company.view().setWordWrap(True)
    company.view().setTextElideMode(Qt.TextElideMode.ElideNone)
    company.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    company.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    company.setMaxVisibleItems(8)
    company._scheme2_company_delegate = _SchemeComboItemDelegate(company)
    company.view().setItemDelegate(company._scheme2_company_delegate)
    company._scheme2_multiline_filter = _MultilineComboPaintFilter(company)
    company.installEventFilter(company._scheme2_multiline_filter)
    if company.lineEdit() is not None:
        editor = company.lineEdit()
        editor.setReadOnly(False)
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        editor.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        editor.setStyleSheet(
            "QLineEdit{background:transparent;border:0;color:#1C1C1E;}"
            "QLineEdit:focus{color:#1C1C1E;selection-color:#FFFFFF;selection-background-color:#2563EB;}"
        )
        editor.editingFinished.connect(lambda combo=company: _remember_custom_company(combo))
    _restore_custom_companies(company)
    company.setToolTip(company.currentText())
    company.currentTextChanged.connect(company.setToolTip)
    window.scheme2_company = company
    controls = {
        "galvanized_price": ("镀锌板价格", _sidebar_price_spin(4.55, 2)),
        "carbon_price": ("碳钢价格", _sidebar_price_spin(4.20, 1)),
        "stainless_price": ("不锈钢价格", _sidebar_price_spin(STAINLESS_DEFAULT_PRICES["SUS304"], 2)),
        "waste_factor": ("废料系数", _sidebar_price_spin(1.20, 1, 4)),
        "labor_discount": ("人工折扣", _sidebar_price_spin(1.00, 2, 4)),
        "surface_price": ("表面处理价格", _sidebar_price_spin(26.00, 0)),
    }
    window.scheme2_cost_controls = {}
    for key, (label, control) in controls.items():
        if key in ("waste_factor", "labor_discount"):
            control.setRange(.01, 10)
            control.setDecimals(4)
        window.scheme2_cost_controls[key] = control
        field = _field(label, control)
        if key == "carbon_price":
            window.scheme2_material_price_label = field.findChild(QLabel, "scheme2FieldLabel")
        if key == "stainless_price":
            window.scheme2_stainless_price_field = field
            window.scheme2_stainless_price_label = field.findChild(QLabel, "scheme2FieldLabel")
            field.hide()
        layout.addWidget(field)
        control.editingFinished.connect(lambda k=key, c=control: _apply_cost_control(window, k, c.value()))
    layout.addStretch(1)
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
        ratio = value / max(original, .01)
        groups = formula.get("material_details") or []
        for group in groups:
            base_weight = _number(group.setdefault("_scheme2_base_billable_weight", group.get("billable_weight_kg")))
            group["billable_weight_kg"] = base_weight * ratio
        for detail in formula.get("cabinet_material_part_details") or []:
            base_weight = _number(detail.setdefault("_scheme2_base_billable_weight", detail.get("billable_weight_kg")))
            detail["billable_weight_kg"] = base_weight * ratio
        if not _reprice_material_details(item, state):
            _replace_component(item, "material_cost", base * ratio)
    elif key == "labor_discount":
        base = _number(item.get("formula_base", formula).get("labor_cost", formula.get("labor_cost")))
        item["labor_multiplier"] = value
        _replace_component(item, "labor_cost", base * value)
        management_rate = _number(formula.get("management_fee_rate"), .13)
        _replace_component(item, "management_fee", base * value * management_rate)
    elif key in ("carbon_price", "galvanized_price", "stainless_price"):
        if not _reprice_material_details(item, state):
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
    header.addWidget(title)
    header.addStretch(1)
    body_layout.addLayout(header)
    compact = QFrame()
    compact.setObjectName("scheme2CompactCoefficients")
    compact_row = QHBoxLayout(compact)
    compact_row.setContentsMargins(8, 5, 8, 5)
    compact_row.addWidget(QLabel("修改系数"))
    compact_key = QComboBox()
    compact_value = _price_spin(1.0)
    for key, label in (
        ("galvanized_price", "镀锌板价格"), ("carbon_price", "当前材质价格"),
        ("stainless_price", "不锈钢价格"),
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
    for column in range(4, len(HEADERS)):
        table.setColumnWidth(column, 92)
    table.setColumnWidth(12, 100)
    table.setColumnWidth(21, 88)
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
    edit = QPushButton("编辑")
    back = QPushButton("返回")
    generate = QPushButton("生成报价单")
    secondary_size = delete.sizeHint()
    for button in (delete, up, down, edit, back):
        # Reuse the option page's "导入图纸" visual role so every
        # interaction state continues to come from one shared QSS definition.
        button.setObjectName("scheme2PrimaryGhost")
        button.setFixedSize(secondary_size)
        button.setFixedHeight(28)
    generate.setObjectName("scheme2PrimaryAction")
    action_buttons = (delete, up, down, edit, back, generate)
    for column, button in enumerate(action_buttons[:4]):
        actions.addWidget(button, 0, column)
    actions.setColumnStretch(4, 1)
    actions.addWidget(back, 0, 5)
    actions.addWidget(generate, 0, 6)
    body_layout.addWidget(action_widget)
    outer.addWidget(body, 1)
    delete.clicked.connect(lambda: _delete_selected(window))
    up.clicked.connect(lambda: window.move_selected_item(-1))
    down.clicked.connect(lambda: window.move_selected_item(1))
    edit.clicked.connect(lambda: _edit_selected(window))
    back.clicked.connect(lambda: window.show_section(OPTION_ROUTE))
    generate.clicked.connect(lambda: window.show_section(QUOTE_ROUTE))
    undo.clicked.connect(lambda: _undo_delete(window))
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
    window.scheme2_cost_generate = generate
    window.scheme2_cost_return = back
    window.scheme2_cost_undo = undo_bar
    window.scheme2_undo_timer = QTimer(window)
    window.scheme2_undo_timer.setSingleShot(True)
    window.scheme2_undo_timer.timeout.connect(undo_bar.hide)
    window.scheme2_cost_action_grid = actions
    window.scheme2_cost_action_buttons = action_buttons
    window._scheme2_full_columns = True
    window._scheme2_deleted = None
    _set_cost_column_mode(window, True)
    return page


def _install_export_busy_feedback(window, export_button):
    """Mirror the legacy exporter state onto the visible scheme-2 action."""

    original = getattr(window, "set_export_busy", None)
    if not callable(original) or getattr(window, "_scheme2_export_busy_installed", False):
        return

    def set_export_busy_with_visible_feedback(self, busy, message=""):
        original(bool(busy), message)
        export_button.setText("正在导出…" if busy else "导出报价单")
        export_button.setEnabled(False if busy else bool(getattr(self, "draft_items", [])))
        export_button.setToolTip(message or "")

    window.set_export_busy = MethodType(set_export_busy_with_visible_feedback, window)
    window._scheme2_export_busy_installed = True


def _set_cost_column_mode(window, full):
    """Keep all cost columns visible; retained for compatibility with older callers."""
    window._scheme2_full_columns = True
    for column in range(len(HEADERS)):
        window.summary_table.setColumnHidden(column, False)


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
        grid.addWidget(buttons[4], 1, 0)
        grid.addWidget(buttons[5], 1, 1)
        grid.setColumnStretch(1, 1)
    else:
        for column, button in enumerate(buttons[:4]):
            grid.addWidget(button, 0, column)
        grid.setColumnStretch(4, 1)
        grid.addWidget(buttons[4], 0, 5)
        grid.addWidget(buttons[5], 0, 6)


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
    elif column == 11:
        item["quantity"] = max(1, int(value))
        drawing_ref = getattr(window, "_draft_drawing_refs", {}).get(id(item))
        if drawing_ref and drawing_ref[0] is not None:
            drawing_ref[0]["quantity"] = item["quantity"]
    else:
        item["quick_discount"] = value
    window.refresh_summary()


def _cost_cell_clicked(window, row, column):
    items = getattr(window, "draft_items", [])
    if not 0 <= row < len(items):
        return
    item = items[row]
    if column == 2:
        product = _cost_product(item)
        targets = [candidate for candidate in items if _cost_product(candidate) == product]
        FaceDiscountEditor(window, item, targets).exec()
    elif column == 12:
        AttachmentEditor(window, item).exec()
    elif column == 21:
        _show_detail(window, item)


def _sync_sidebar(window):
    item = _selected_item(window)
    state = item.get("scheme2_cost_settings", {}) if isinstance(item, dict) else window.scheme2_defaults
    material_code = str(item.get("material_code") or "").strip().upper() if isinstance(item, dict) else ""
    stainless = material_code in {"SUS304", "SUS316"}
    if stainless and "stainless_price" not in state:
        state["stainless_price"] = _current_material_unit_price(item) or window.scheme2_defaults["stainless_price"]
    for key, control in window.scheme2_cost_controls.items():
        with QSignalBlocker(control):
            control.setValue(_number(state.get(key), window.scheme2_defaults[key]))
    caption = "碳钢价格"
    if hasattr(window, "scheme2_material_price_label"):
        window.scheme2_material_price_label.setText(caption)
    stainless_field = getattr(window, "scheme2_stainless_price_field", None)
    if stainless_field is not None:
        stainless_field.setVisible(stainless)
    stainless_label = getattr(window, "scheme2_stainless_price_label", None)
    if isinstance(stainless_label, QLabel):
        stainless_label.setText(f"{material_code}价格" if stainless else "不锈钢价格")
    surface_control = getattr(window, "scheme2_cost_controls", {}).get("surface_price")
    if isinstance(surface_control, QDoubleSpinBox):
        surface_control.setPrefix("")
    if hasattr(window, "scheme2_compact_key"):
        material_index = window.scheme2_compact_key.findData("carbon_price")
        if material_index >= 0:
            window.scheme2_compact_key.setItemText(material_index, caption)
        stainless_index = window.scheme2_compact_key.findData("stainless_price")
        if stainless_index >= 0:
            window.scheme2_compact_key.setItemText(
                stainless_index, f"{material_code}价格" if stainless else "不锈钢价格"
            )
    if hasattr(window, "scheme2_compact_key"):
        _sync_compact_control(window)


def _refresh_cost_table(window):
    table = window.summary_table
    items = getattr(window, "draft_items", [])
    selected = _selected_row(window)
    window._scheme2_refreshing = True
    try:
        empty = getattr(window, "scheme2_cost_empty", None)
        generate = getattr(window, "scheme2_cost_generate", None)
        if empty is not None:
            empty.setGeometry(table.viewport().rect())
            empty.setVisible(not items)
            empty.raise_()
        if generate is not None:
            generate.setEnabled(bool(items))
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
                if column in (2, 12, 21):
                    cell.setForeground(QColor("#185FA5"))
                    font = cell.font()
                    font.setUnderline(True)
                    cell.setFont(font)
                if column in MONEY_COLUMNS:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, column, cell)
        total_row = len(items)
        quantity_total = sum(max(1, int(_number(item.get("quantity", 1), 1))) for item in items)
        quote_total = sum(_row_values(item)[16] for item in items)
        cost_total = sum(_row_values(item)[18] for item in items)
        weight_total = sum(
            _number(_row_values(item)[20]) * max(1, int(_number(item.get("quantity", 1), 1)))
            for item in items
        )
        gross_margin = (quote_total - cost_total) / quote_total if quote_total else 0.0
        for column in range(len(HEADERS)):
            if column == 0:
                text = "汇总"
            elif column == 11:
                text = str(quantity_total)
            elif column == 16:
                text = _money(quote_total)
            elif column == 18:
                text = _money(cost_total)
            elif column == 19:
                text = f"{gross_margin:.2%}"
            elif column == 20:
                text = _money(weight_total)
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
    spare = []
    for button in list(getattr(window, "nav_buttons", [])):
        text = button.text().replace("&", "").strip()
        if text == "报价计算":
            wanted[OPTION_ROUTE] = button
        elif text == "报价清单":
            wanted[COST_ROUTE] = button
        else:
            button.hide()
            spare.append(button)
    if OPTION_ROUTE not in wanted or COST_ROUTE not in wanted:
        visible = [button for button in getattr(window, "nav_buttons", []) if isinstance(button, QPushButton)]
        wanted.setdefault(OPTION_ROUTE, visible[0])
        wanted.setdefault(COST_ROUTE, visible[-1])
    wanted[QUOTE_ROUTE] = spare[0] if spare else QPushButton(nav)
    labels = {OPTION_ROUTE: "选项配置", COST_ROUTE: "成本计算", QUOTE_ROUTE: "报价单"}
    for route, button in wanted.items():
        button.show()
        button.setText(labels[route])
        button.setIcon(button.icon().__class__())
        button.setFixedHeight(28)
        try:
            button.clicked.disconnect()
        except RuntimeError:
            pass
        button.clicked.connect(lambda _checked=False, value=route: window.show_section(value))
    window.nav_buttons = [wanted[OPTION_ROUTE], wanted[COST_ROUTE], wanted[QUOTE_ROUTE]]
    window.nav_routes = (
        (OPTION_ROUTE, "选项配置", "", None),
        (COST_ROUTE, "成本计算", "", None),
        (QUOTE_ROUTE, "报价单", "", None),
    )
    if nav is not None:
        nav.setFixedWidth(NAV_EXPANDED_WIDTH)
        nav.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if nav.layout() is not None:
            nav.layout().setContentsMargins(12, 14, 12, 12)
            nav.layout().setSpacing(9)
        for name in ("brandBlock", "navSectionLabel", "navFooter"):
            child = nav.findChild(QWidget, name)
            if child is not None:
                child.hide()
        nav_brand = QFrame()
        nav_brand.setObjectName("scheme2NavBrand")
        nav_brand_layout = QHBoxLayout(nav_brand)
        nav_brand_layout.setContentsMargins(0, 0, 0, 6)
        nav_brand_layout.setSpacing(7)
        nav_logo = QLabel("AI")
        nav_logo.setObjectName("scheme2NavLogo")
        nav_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_logo.setFixedSize(26, 26)
        nav_title = QLabel("智能报价")
        nav_title.setObjectName("scheme2NavTitle")
        nav_brand_layout.addWidget(nav_logo)
        nav_brand_layout.addWidget(nav_title)
        nav.layout().insertWidget(0, nav_brand)
        collapse = QPushButton("«")
        collapse.setObjectName("scheme2CollapseButton")
        collapse.setFixedSize(28, 28)
        collapse.clicked.connect(lambda: _set_nav_collapsed(window, True, manual=True))
        nav_layout = nav.layout()
        while nav_layout.count():
            nav_layout.takeAt(0)
        nav_layout.addWidget(nav_brand)
        nav_layout.addWidget(wanted[OPTION_ROUTE])
        nav_layout.addWidget(wanted[COST_ROUTE])
        nav_layout.addWidget(wanted[QUOTE_ROUTE])
        nav_layout.addStretch(1)
        nav_layout.addWidget(collapse, 0, Qt.AlignmentFlag.AlignLeft)
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
    forced = route == DETAIL_ROUTE
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
    layout.setSpacing(6)
    label = None
    if title:
        label = QLabel(title)
        label.setObjectName("scheme2OptionLabel")
        layout.addWidget(label)
    shell = QFrame()
    shell.setObjectName("scheme2OptionControlShell")
    shell.setProperty("provenanceState", "pending" if provenance else "plain")
    shell_layout = QHBoxLayout(shell)
    shell_layout.setContentsMargins(0, 0, 7 if isinstance(control, QComboBox) else (8 if provenance else 0), 0)
    shell_layout.setSpacing(6)
    control.setMinimumWidth(0)
    control.setMaximumWidth(16777215)
    control.setMinimumHeight(50)
    control.setVisible(True)
    shell_layout.addWidget(control, 1)
    if provenance:
        badge = QLabel("待识别")
        badge.setObjectName("scheme2ProvenancePending")
        shell_layout.addWidget(badge)
        window.scheme2_provenance_labels[provenance] = badge
    if isinstance(control, QComboBox):
        control.view().setObjectName("scheme2OptionDropdown")
    layout.addWidget(shell)
    block._scheme2_label = label
    block._scheme2_shell = shell
    return block


def _promote_option_label(field):
    """Use the same typography as the 门型 section heading."""

    label = getattr(field, "_scheme2_label", None)
    if isinstance(label, QLabel):
        label.setObjectName("scheme2OptionGroupTitle")


def _json_order_value(value):
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {str(key): _json_order_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_order_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _order_workspace_payload(window):
    _save_current_scheme2_page(window)
    detail_item = getattr(window, "_scheme2_detail_item", None)
    detail_index = next((
        index for index, item in enumerate(getattr(window, "draft_items", []))
        if item is detail_item
    ), -1)
    pages = []
    for page in getattr(window, "_scheme2_drawing_pages", []):
        if isinstance(page, dict):
            pages.append({key: deepcopy(value) for key, value in page.items() if key not in {"item", "pixmap"}})
    return _json_order_value({
        "option_state": _capture_scheme2_page_state(window),
        "drawing_pages": pages,
        "drawing_page_index": int(getattr(window, "_scheme2_drawing_page_index", -1)),
        "draft_items": deepcopy(getattr(window, "draft_items", [])),
        "company": window.scheme2_company.currentText() if hasattr(window, "scheme2_company") else "",
        "active_route": int(window.stack.currentIndex()),
        "detail_item_index": detail_index,
    })


def _save_order_workspace(window, finished=None):
    order_number = window.scheme2_order_number.text().strip()
    if not order_number or getattr(window, "_scheme2_loading_order", False):
        if callable(finished):
            finished()
        return
    worker_class = getattr(window, "_scheme2_api_worker_class", None)
    if worker_class is None:
        if callable(finished):
            finished()
        return
    worker = worker_class(window.base_url() + "/api/orders/workspace/save", {
        "order_number": order_number, "payload": _order_workspace_payload(window),
    }, window)
    window._scheme2_order_save_worker = worker
    def completed(_value):
        window._scheme2_order_save_worker = None
        if callable(finished):
            finished()

    worker.succeeded.connect(completed)
    worker.failed.connect(completed)
    worker.start()


def _schedule_order_workspace_save(window):
    timer = getattr(window, "_scheme2_order_save_timer", None)
    if (isinstance(timer, QTimer) and window.scheme2_order_number.text().strip()
            and not getattr(window, "_scheme2_loading_order", False)):
        timer.start()


def _load_order_workspace(window):
    order_number = window.scheme2_order_number.text().strip()
    if not order_number:
        return
    worker_class = getattr(window, "_scheme2_api_worker_class", None)
    if worker_class is None:
        return
    worker = worker_class(window.base_url() + "/api/orders/workspace/load", {"order_number": order_number}, window)
    window._scheme2_order_load_worker = worker

    def loaded(result):
        window._scheme2_order_load_worker = None
        payload = result.get("payload") if isinstance(result, dict) else None
        if not isinstance(payload, dict):
            return
        window._scheme2_loading_order = True
        try:
            window.draft_items = deepcopy(payload.get("draft_items") or [])
            pages = deepcopy(payload.get("drawing_pages") or [])
            if pages:
                window._scheme2_drawing_pages = pages
                window._scheme2_drawing_page_index = int(payload.get("drawing_page_index", -1))
            _restore_scheme2_page_state(window, payload.get("option_state") or {})
            company = str(payload.get("company") or "").strip()
            if company:
                window.scheme2_company.setCurrentText(company)
            window.refresh_summary()
            _refresh_quote_page(window)
            route = int(payload.get("active_route", OPTION_ROUTE))
            detail_index = int(payload.get("detail_item_index", -1))
            if route == DETAIL_ROUTE and 0 <= detail_index < len(window.draft_items):
                _show_detail(window, window.draft_items[detail_index])
            else:
                window.show_section(route if route in (OPTION_ROUTE, COST_ROUTE, QUOTE_ROUTE) else OPTION_ROUTE)
            _set_dirty(window, False)
        finally:
            window._scheme2_loading_order = False

    worker.succeeded.connect(loaded)
    worker.failed.connect(lambda _message: setattr(window, "_scheme2_order_load_worker", None))
    worker.start()


def _scheme2_combo_state(combo):
    return {
        "index": combo.currentIndex(),
        "data": combo.currentData(),
        "text": combo.currentText(),
    }


def _restore_scheme2_combo(combo, state):
    if not isinstance(state, dict):
        return
    with QSignalBlocker(combo):
        data = state.get("data")
        index = combo.findData(data) if data is not None else -1
        if index < 0:
            index = combo.findText(str(state.get("text") or ""), Qt.MatchFlag.MatchExactly)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.isEditable():
            combo.setEditText(str(state.get("text") or ""))


def _capture_scheme2_page_state(window):
    combos = {}
    for name in (
        "product_combo", "material_combo", "coating_combo", "scheme2_color_combo",
        "single_door_combo", "double_door_combo",
    ):
        combo = getattr(window, name, None)
        if isinstance(combo, QComboBox):
            combos[name] = _scheme2_combo_state(combo)
    spins = {}
    for name in ("quantity_spin", "cabinet_body_thickness_spin"):
        spin = getattr(window, name, None)
        if isinstance(spin, QAbstractSpinBox) and hasattr(spin, "value"):
            spins[name] = spin.value()
    return {
        "name": window.scheme2_name_edit.text() if hasattr(window, "scheme2_name_edit") else "",
        "specification": window.quote_spec_edit.text() if hasattr(window, "quote_spec_edit") else "",
        "combos": combos,
        "spins": spins,
        "attachments": deepcopy(getattr(window, "attachments", [])),
        "attachments_manual": bool(getattr(window, "_scheme2_attachments_manual", False)),
        "manual_fields": set(getattr(window, "scheme2_manual_fields", set())),
        "dirty": bool(getattr(window, "_scheme2_dirty", False)),
    }


def _restore_scheme2_page_state(window, state):
    if not isinstance(state, dict):
        return
    with QSignalBlocker(window.scheme2_name_edit):
        window.scheme2_name_edit.setText(str(state.get("name") or ""))
    with QSignalBlocker(window.quote_spec_edit):
        window.quote_spec_edit.setText(str(state.get("specification") or ""))
    for name, value in (state.get("combos") or {}).items():
        combo = getattr(window, name, None)
        if isinstance(combo, QComboBox):
            _restore_scheme2_combo(combo, value)
    for name, value in (state.get("spins") or {}).items():
        spin = getattr(window, name, None)
        if isinstance(spin, QAbstractSpinBox) and hasattr(spin, "setValue"):
            with QSignalBlocker(spin):
                spin.setValue(value)
    window.attachments = deepcopy(state.get("attachments") or [])
    window._scheme2_attachments_manual = bool(state.get("attachments_manual", False))
    window.scheme2_manual_fields = set(state.get("manual_fields") or set())
    for key in ("dimensions", "material", "coating", "color"):
        if key in window.scheme2_manual_fields:
            _mark_manual(window, key)
        else:
            _mark_ai(window, key)
    refresh = getattr(window, "update_attachment_view", None)
    if callable(refresh):
        refresh()
    _refresh_scheme2_attachment_summary(window)
    _set_dirty(window, bool(state.get("dirty")))


def _scheme2_page_entry(window, key):
    return next((entry for entry in getattr(window, "_scheme2_drawing_pages", []) if entry["key"] == key), None)


def _save_current_scheme2_page(window):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if (
        0 <= index < len(pages)
        and pages[index].get("visited")
        and (pages[index].get("item") is not None or getattr(window, "_scheme2_dirty", False))
    ):
        pages[index]["state"] = _capture_scheme2_page_state(window)


def _sync_scheme2_add_action(window, quoted):
    add_button = getattr(window, "scheme2_add_button", None)
    if isinstance(add_button, QPushButton):
        add_button.setText("已加入" if quoted else "加入报价清单")
        add_button.setEnabled(True)


def _sync_scheme2_quoted_badge(window):
    badge = getattr(window, "scheme2_quoted_badge", None)
    if not isinstance(badge, QLabel):
        return
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    quoted = 0 <= index < len(pages) and bool(pages[index].get("quoted"))
    badge.setVisible(quoted)
    _sync_scheme2_add_action(window, quoted)


def _sync_scheme2_page_navigation(window):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    preview = getattr(window, "quote_drawing_preview", None)
    if preview is not None:
        preview.previous.setEnabled(index > 0)
        preview.next.setEnabled(0 <= index < len(pages) - 1)
        preview.counter.setText(f"{index + 1} / {len(pages)}" if 0 <= index < len(pages) else "0 / 0")
    selector = getattr(window, "scheme2_page_selector", None)
    if isinstance(selector, QSpinBox):
        with QSignalBlocker(selector):
            selector.setRange(1 if pages else 0, len(pages))
            selector.setValue(index + 1 if 0 <= index < len(pages) else 0)
        selector.setEnabled(bool(pages))
    button = getattr(window, "_scheme2_import_button", None)
    if isinstance(button, QPushButton):
        button.setEnabled(True)
    completion = getattr(window, "scheme2_completion", None)
    if isinstance(completion, QLabel) and pages:
        recognized = sum(1 for entry in pages if entry.get("item") is not None)
        completion.setText(f"已识别 {recognized} / {len(pages)}")
    status = getattr(window, "scheme2_recognition_status", None)
    if isinstance(status, QLabel) and pages:
        recognized = sum(1 for entry in pages if entry.get("item") is not None)
        failed = sum(1 for entry in pages if entry.get("error"))
        active_key = getattr(window, "_scheme2_recognition_key", None)
        active_index = next((i for i, entry in enumerate(pages) if entry["key"] == active_key), -1)
        if active_index >= 0:
            status.setText(f"图片识别进度：{recognized} / {len(pages)}，后台正在识别第 {active_index + 1} 页")
        elif recognized + failed >= len(pages):
            status.setText(f"图片识别完成：{recognized} / {len(pages)}")
        else:
            status.setText(f"图片识别进度：{recognized} / {len(pages)}")
    _sync_scheme2_quoted_badge(window)


def _show_scheme2_source_page(window, entry):
    preview = getattr(window, "quote_drawing_preview", None)
    if preview is None:
        return
    source = str(entry["source_path"])
    preview.set_document(entry["key"], source, source)
    page_index = int(entry["page_index"])
    if page_index:
        preview.page = page_index
        preview.pages[preview.document_key] = page_index
        preview.load_page()
    _sync_scheme2_page_navigation(window)


def _restore_scheme2_drawing_on_option_page(window):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if not (0 <= index < len(pages)):
        return
    _show_scheme2_source_page(window, pages[index])
    drawing = getattr(window, "scheme2_drawing_widget", None)
    preview = getattr(window, "quote_drawing_preview", None)
    if drawing is not None:
        drawing.show()
    if preview is not None:
        preview.show()


def _finish_scheme2_page_recognition(window, key, item):
    entry = _scheme2_page_entry(window, key)
    if entry is None:
        return
    builder = getattr(window, "_scheme2_candidate_builder", None)
    candidates = list(item.get("cabinet_candidates") or [])
    if not candidates and callable(builder):
        candidates = list(builder(item) or [])
    if not candidates:
        candidates = [item]
    _Scheme2PageRecognitionWorker._apply_source_context(item, entry)
    for candidate in candidates:
        _Scheme2PageRecognitionWorker._apply_source_context(candidate, entry)
        _confirm_scheme2_recognition(candidate)
    entry["document"] = item
    entry["item"] = candidates[0]
    window.recognized_documents = [
        row for row in getattr(window, "recognized_documents", [])
        if not (isinstance(row, dict) and row.get("scheme2_page_key") == key)
    ] + [item]
    item["scheme2_page_key"] = key
    retained = [
        row for row in getattr(window, "recognized_drawings", [])
        if not (isinstance(row, dict) and row.get("scheme2_page_key") == key)
    ]
    for candidate in candidates:
        candidate["scheme2_page_key"] = key
    window.recognized_drawings = retained + candidates
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if (
        0 <= index < len(pages)
        and pages[index]["key"] == key
        and entry.get("state") is None
        and not getattr(window, "_scheme2_dirty", False)
    ):
        window.active_drawing = entry["item"]
        window._quote_drawing = entry["item"]
        window.scheme2_manual_fields.clear()
        window._apply_confirmed_drawing_to_quote(entry["item"])
        entry["state"] = _capture_scheme2_page_state(window)
        _set_dirty(window, False)
    _sync_scheme2_page_navigation(window)


def _confirm_scheme2_recognition(item):
    """Make current-page recognition quote-ready without the retired review desk."""

    if not isinstance(item, dict):
        return item
    item["classification"] = "cabinet"
    item["review_status"] = "confirmed"
    item["confirmed"] = True
    item["verified"] = True
    item["manual_reviewed"] = True
    item["manual_confirmation_checked"] = True
    item["manual_reviewed_at"] = "scheme2-direct-recognition"
    item["remark_review_required"] = False
    if not str(item.get("specification") or "").strip():
        dimensions = list(item.get("dimensions") or [])
        if dimensions and len(dimensions[0]) >= 3:
            item["specification"] = "*".join(f"{_number(value):g}" for value in dimensions[0][:3])
    return item


def _apply_recognized_attachments(window, item):
    """Display OCR attachment matches; existing quote resolution supplies prices."""

    if getattr(window, "_scheme2_attachments_manual", False):
        return
    text = str(item.get("raw_text") or item.get("text") or "")
    recommend = getattr(window, "recommend_attachment_names", None)
    names = list(recommend(text) or []) if callable(recommend) else []
    if not names:
        return
    window.recommended_attachments = names
    window.attachments = [
        {"item_name": name, "name": name, "quantity": 1, "recognized": True}
        for name in names
    ]
    refresh = getattr(window, "update_attachment_view", None)
    if callable(refresh):
        refresh()
    _refresh_scheme2_attachment_summary(window)


def _synchronize_active_drawing_confirmation(window):
    """Confirm the current Scheme-2 fields without the retired review workbench."""

    item = getattr(window, "active_drawing", None)
    if not isinstance(item, dict):
        return
    width = _number(window.width_spin.value())
    height = _number(window.height_spin.value())
    depth = _number(window.depth_spin.value())
    specification = window.quote_spec_edit.text().strip()
    item["dimensions"] = [(width, height, depth)]
    item["specification"] = specification or f"{width:g}*{depth:g}*{height:g}"
    item["reviewed_remark"] = window.notes_text.toPlainText().strip()
    _confirm_scheme2_recognition(item)
    window._quote_drawing = item


def _fail_scheme2_page_recognition(window, key, message):
    entry = _scheme2_page_entry(window, key)
    if entry is not None:
        entry["error"] = str(message)
    _sync_scheme2_page_navigation(window)


def _recognize_scheme2_page(window, entry):
    if entry.get("item") is not None or getattr(window, "_scheme2_page_worker", None) is not None:
        return
    worker = _Scheme2PageRecognitionWorker(window._scheme2_recognition_tools, entry, window)
    window._scheme2_page_worker = worker
    window._scheme2_recognition_key = entry["key"]
    worker.succeeded.connect(lambda key, item: _finish_scheme2_page_recognition(window, key, item))
    worker.failed.connect(lambda key, message: _fail_scheme2_page_recognition(window, key, message))

    def finished():
        if getattr(window, "_scheme2_page_worker", None) is worker:
            window._scheme2_page_worker = None
            window._scheme2_recognition_key = None
        worker.deleteLater()
        _sync_scheme2_page_navigation(window)
        QTimer.singleShot(0, lambda: _start_next_scheme2_recognition(window))

    worker.finished.connect(finished)
    _sync_scheme2_page_navigation(window)
    worker.start()


def _start_next_scheme2_recognition(window):
    if getattr(window, "_scheme2_page_worker", None) is not None:
        return
    entry = next(
        (
            candidate for candidate in getattr(window, "_scheme2_drawing_pages", [])
            if candidate.get("item") is None and not candidate.get("error")
        ),
        None,
    )
    if entry is not None:
        _recognize_scheme2_page(window, entry)
    else:
        _sync_scheme2_page_navigation(window)


def _activate_scheme2_page(window, index):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    if not 0 <= index < len(pages):
        return
    _restore_add_action(window)
    _save_current_scheme2_page(window)
    window._scheme2_drawing_page_index = index
    entry = pages[index]
    entry["visited"] = True
    _show_scheme2_source_page(window, entry)
    if entry.get("state") is not None:
        window.active_drawing = entry.get("item")
        window._quote_drawing = entry.get("item")
        _restore_scheme2_page_state(window, entry["state"])
        window.scheme2_recognition_status.setText(
            f"已恢复第 {entry['page_index'] + 1} 页的选项配置"
        )
    elif entry.get("item") is not None:
        window.scheme2_manual_fields.clear()
        window.active_drawing = entry["item"]
        window._quote_drawing = entry["item"]
        window._apply_confirmed_drawing_to_quote(entry["item"])
        entry["state"] = _capture_scheme2_page_state(window)
        _set_dirty(window, False)
    _sync_scheme2_page_navigation(window)


def _change_scheme2_page(window, delta):
    _activate_scheme2_page(window, int(getattr(window, "_scheme2_drawing_page_index", -1)) + int(delta))


def _import_scheme2_drawings(window, paths=None):
    if paths is None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            window,
            "导入图纸",
            "",
            "图纸文件 (*.pdf *.dwg *.dxf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
    accepted = list(window._scheme2_accept_paths(list(paths or [])))
    if not accepted:
        return
    pages = getattr(window, "_scheme2_drawing_pages", [])
    had_pages = bool(pages)
    known = {entry["key"] for entry in pages}
    first_new = len(pages)
    for raw_path in accepted:
        source = str(Path(raw_path).resolve())
        try:
            if Path(source).suffix.lower() == ".pdf":
                reader = PdfReader(source)
                try:
                    page_count = len(reader.pages)
                finally:
                    reader.close()
            else:
                page_count = 1
        except Exception as error:
            QMessageBox.warning(window, "无法导入图纸", f"{Path(source).name}：{error}")
            continue
        for page_index in range(max(1, page_count)):
            key = f"{source.casefold()}#page={page_index + 1}"
            if key in known:
                continue
            pages.append({
                "key": key,
                "source_path": source,
                "page_index": page_index,
                "page_count": max(1, page_count),
                "item": None,
                "state": None,
            })
            known.add(key)
    window._scheme2_drawing_pages = pages
    if len(pages) > first_new and not had_pages:
        _activate_scheme2_page(window, first_new)
    else:
        _sync_scheme2_page_navigation(window)
    _start_next_scheme2_recognition(window)


def _scheme2_group_title(text):
    label = QLabel(text)
    label.setObjectName("scheme2OptionGroupTitle")
    return label


def _clear_widget_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if child is not None:
            _clear_widget_layout(child)
        if widget is not None:
            widget.deleteLater()


def _refresh_scheme2_ganged_ui(window):
    rows = [row for row in getattr(window, "ganged_cabinets", []) if isinstance(row, dict)]
    is_ganged = len(rows) > 1
    dimension_field = getattr(window, "scheme2_dimension_field", None)
    dimension_label = getattr(dimension_field, "_scheme2_label", None)
    if isinstance(dimension_label, QLabel):
        dimension_label.setVisible(is_ganged)
    dimensions_panel = getattr(window, "scheme2_ganged_dimensions", None)
    doors_panel = getattr(window, "scheme2_ganged_doors", None)
    regular_doors = getattr(window, "scheme2_regular_doors", None)
    if dimensions_panel is not None:
        dimensions_panel.setVisible(is_ganged)
    if doors_panel is not None:
        doors_panel.setVisible(is_ganged)
    if regular_doors is not None:
        regular_doors.setVisible(not is_ganged)
    if not is_ganged:
        return

    legacy_table = getattr(window, "ganged_cabinet_table", None)
    dimension_layout = dimensions_panel.layout()
    door_layout = doors_panel.layout()
    _clear_widget_layout(dimension_layout)
    _clear_widget_layout(door_layout)

    def copy_combo(source):
        combo = QComboBox()
        if isinstance(source, QComboBox):
            for index in range(source.count()):
                combo.addItem(source.itemText(index), source.itemData(index))
            combo.setCurrentIndex(combo.findData(source.currentData()))

            def sync_to_legacy(_index, target=source, editor=combo):
                target.setCurrentIndex(target.findData(editor.currentData()))
                QTimer.singleShot(0, lambda: _refresh_scheme2_ganged_ui(window))

            combo.currentIndexChanged.connect(sync_to_legacy)
        return combo

    for index, row in enumerate(rows):
        size_text = ""
        if isinstance(legacy_table, QTableWidget):
            cell = legacy_table.item(index, 1)
            size_text = cell.text() if cell is not None else ""
        if not size_text:
            values = (row.get("width_mm"), row.get("depth_mm"), row.get("height_mm"))
            size_text = "*".join(f"{float(value):g}" for value in values if value is not None)
        size_row = QFrame()
        size_row.setObjectName("scheme2GangedRow")
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(10)
        size_label = QLabel(f"柜体 {index + 1}")
        size_label.setObjectName("scheme2GangedLabel")
        size_label.setFixedWidth(60)
        size_box = QFrame()
        size_box.setObjectName("scheme2GangedValue")
        size_box_layout = QHBoxLayout(size_box)
        size_box_layout.setContentsMargins(12, 0, 10, 0)
        size_box_layout.addWidget(QLabel(size_text), 1)
        ai = QLabel("AI ✓")
        ai.setObjectName("scheme2GangedAi")
        size_box_layout.addWidget(ai)
        size_layout.addWidget(size_label)
        size_layout.addWidget(size_box, 1)
        dimension_layout.addWidget(size_row)

        door_row = QFrame()
        door_row.setObjectName("scheme2GangedRow")
        door_row_layout = QHBoxLayout(door_row)
        door_row_layout.setContentsMargins(0, 0, 0, 0)
        door_row_layout.setSpacing(10)
        door_label = QLabel(f"柜体 {index + 1}")
        door_label.setObjectName("scheme2GangedLabel")
        door_label.setFixedWidth(60)
        door_row_layout.addWidget(door_label)
        single_source = legacy_table.cellWidget(index, 2) if isinstance(legacy_table, QTableWidget) else None
        double_source = legacy_table.cellWidget(index, 3) if isinstance(legacy_table, QTableWidget) else None
        for caption, source in (("单门", single_source), ("双门", double_source)):
            host = QFrame()
            host.setObjectName("scheme2DoorValue")
            host_layout = QHBoxLayout(host)
            host_layout.setContentsMargins(10, 0, 4, 0)
            host_layout.setSpacing(5)
            host_layout.addWidget(QLabel(caption))
            editor = copy_combo(source)
            editor.view().setObjectName("scheme2OptionDropdown")
            host_layout.addWidget(editor, 1)
            door_row_layout.addWidget(host, 1)
        door_layout.addWidget(door_row)


def _mark_manual(window, key):
    window.scheme2_manual_fields.add(key)
    badge = window.scheme2_provenance_labels.get(key)
    if badge is not None:
        badge.setText("已改 ✎")
        badge.setObjectName("scheme2ProvenanceManual")
        shell = badge.parentWidget()
        if isinstance(shell, QFrame):
            shell.setProperty("provenanceState", "manual")
            shell.style().unpolish(shell)
            shell.style().polish(shell)
        badge.style().unpolish(badge)
        badge.style().polish(badge)


def _mark_ai(window, key):
    if key in window.scheme2_manual_fields:
        return
    badge = window.scheme2_provenance_labels.get(key)
    if badge is not None:
        badge.setText("AI ✓")
        badge.setObjectName("scheme2ProvenanceAi")
        shell = badge.parentWidget()
        if isinstance(shell, QFrame):
            shell.setProperty("provenanceState", "ai")
            shell.style().unpolish(shell)
            shell.style().polish(shell)
        badge.style().unpolish(badge)
        badge.style().polish(badge)


ATTACHMENT_CATEGORY_ORDER = (
    "侧板", "安装板", "安装附件", "底座", "照明灯/行程开关", "资料盒", "风机", "滤网",
    "门变形", "并柜件", "控制箱附件", "控制柜附件", "配置变形", "其他附件",
)
CONTROL_BOX_ATTACHMENT_PRODUCTS = frozenset(("JA", "JE", "JK", "JM"))
ATTACHMENT_OPTIONS = {
    "安装附件": ("固定立柱", "三排安装梁", "分段板", "绑线条"),
    "底座": ("固定底座", "活动底座"),
    "资料盒": ("A3资料盒", "A4资料盒"),
    "风机": (
        "KA1238HA2/B(卡固)", "KA1238DC/24V(卡固)", "KA1725HA2/B(卡固)",
        "KA1725DC/24V(卡固)", "KA2072HA2/B(卡固)", "KA1238HA2/B（国产）",
        "KA1725HA2/B（国产）", "KA1725DC/24V（国产）", "KA2072HA2/B（国产）",
    ),
    "滤网": (
        "过滤网FU-9803A(卡固)", "过滤网FU-9804A(卡固)", "过滤网FU-9805A(卡固)",
        "过滤网FU-9806A(卡固)", "过滤网FU-9803A（国产）", "过滤网FU-9804A（国产）",
        "过滤网FU-9805A（国产）", "过滤网FU-9806A（国产）",
    ),
    "门变形": (
        "JA、JE单开门改为双开门", "JS、JP单开门改为上下门", "JS、JP单开门改为双开门",
        "JS、JP后背板改为单开门", "JS、JP后背板改为双开门", "JA、JE箱小方锁改为搭扣锁（1把）",
        "JA、JE顶部加吊环（2个）", "平面锁改为MS830锁",
    ),
    "控制箱附件": ("内门", "JK安装板", "玻璃门", "壁挂件", "重型壁挂件", "防雨顶"),
    "控制柜附件": ("内门", "电脑托盘", "通风顶罩", "玻璃门", "门限位器", "防雨顶", "无孔承板", "有孔承板"),
    "配置变形": (
        "填充安装板", "接地线-黄绿线", "接地线-编织带", "福马轮", "丝印",
        "外部眉头（柜体顶板上方）", "网版", "进线胶圈（含安装）",
    ),
    "其他附件": ("侧门", "隔板", "铜排", "门加强筋"),
}


def _current_product_code(window):
    combo = getattr(window, "product_combo", None)
    if not isinstance(combo, QComboBox):
        return ""
    values = (combo.currentData(), combo.currentText())
    for value in values:
        if isinstance(value, dict):
            value = value.get("product_code") or value.get("code") or value.get("model_code") or ""
        text = str(value or "").strip().upper()
        for code in ("JP", "JS", "JK", "JA", "JE", "JM"):
            if text == code or text.startswith(code + " ") or text.startswith(code + "-"):
                return code
    return ""


def _stamp_selected_product(window, item):
    """Snapshot the option-page selection used by the cost table."""
    combo = getattr(window, "product_combo", None)
    if not isinstance(item, dict) or not isinstance(combo, QComboBox):
        return
    code = _current_product_code(window)
    name = combo.currentText().strip()
    if code:
        item["scheme2_selected_product_code"] = code
        item["scheme2_selected_product_name"] = name or code


class _SchemeAttachmentHeader(QFrame):
    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = dialog
        self._drag_offset = None
        self.setObjectName("scheme2AttachmentHeader")
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._dialog.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._dialog.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _SchemeAttachmentCombo(QComboBox):
    selectionChanged = Signal()

    _CHIP_HEIGHT = 24
    _CHIP_GAP = 5
    _CHIP_HORIZONTAL_PADDING = 9
    _CHIP_CLOSE_WIDTH = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_rows = set()
        self._keep_popup_open = False
        self._pressed_popup_row = -1
        self._chip_hit_rects = {}
        self.view().viewport().installEventFilter(self)

    def hidePopup(self):
        if self._keep_popup_open:
            return
        super().hidePopup()

    def is_row_selected(self, row):
        return row in self._selected_rows

    def selected_texts(self):
        return [self.itemText(row) for row in sorted(self._selected_rows)]

    def display_text(self):
        return "\n".join(self.selected_texts()) or self.itemText(0)

    def set_selected_texts(self, values):
        wanted = {str(value).strip() for value in values if str(value).strip()}
        self._selected_rows = {
            row for row in range(1, self.count()) if self.itemText(row) in wanted
        }
        self._sync_current_row()

    def clear_selection(self):
        if not self._selected_rows:
            self.setCurrentIndex(0)
            return
        self._selected_rows.clear()
        self._sync_current_row()
        self.selectionChanged.emit()

    def toggle_row(self, row):
        if row <= 0:
            self._selected_rows.clear()
        elif row in self._selected_rows:
            self._selected_rows.remove(row)
        else:
            self._selected_rows.add(row)
        self._sync_current_row(row)
        self.selectionChanged.emit()

    def _sync_current_row(self, preferred=None):
        if preferred in self._selected_rows:
            target = preferred
        elif self._selected_rows:
            target = min(self._selected_rows)
        else:
            target = 0
        blocker = QSignalBlocker(self)
        self.setCurrentIndex(target)
        del blocker
        self.setToolTip("、".join(self.selected_texts()))
        self.setAccessibleDescription(self.toolTip())
        self._update_display_height()
        self.updateGeometry()
        self.view().viewport().update()
        self.update()

    def eventFilter(self, watched, event):
        if watched is self.view().viewport():
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                index = self.view().indexAt(event.position().toPoint())
                self._pressed_popup_row = index.row() if index.isValid() else -1
                if index.isValid():
                    self._keep_popup_open = True
                    self.view().setCurrentIndex(index)
                    self.toggle_row(index.row())
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._pressed_popup_row = -1
                QTimer.singleShot(0, self._release_popup_guard)
                return True
            if event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
            ):
                index = self.view().currentIndex()
                if index.isValid():
                    self.toggle_row(index.row())
                return True
        return super().eventFilter(watched, event)

    def _release_popup_guard(self):
        self._keep_popup_open = False

    def _chip_layout(self, width=None):
        available_width = max(40, int(width if width is not None else self.width()) - 40)
        metrics = self.fontMetrics()
        x = 7
        y = 6
        right = 7 + available_width
        placements = []
        for row in sorted(self._selected_rows):
            chip_width = metrics.horizontalAdvance(self.itemText(row)) + (
                self._CHIP_HORIZONTAL_PADDING * 2 + self._CHIP_CLOSE_WIDTH
            )
            chip_width = min(chip_width, available_width)
            if placements and x + chip_width > right:
                x = 7
                y += self._CHIP_HEIGHT + self._CHIP_GAP
            rect = QRect(x, y, chip_width, self._CHIP_HEIGHT)
            placements.append((row, rect))
            x += chip_width + self._CHIP_GAP
        required_height = y + self._CHIP_HEIGHT + 6 if placements else 36
        return placements, max(36, required_height)

    def _update_display_height(self):
        _placements, height = self._chip_layout()
        self.setMinimumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display_height()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.view().isVisible():
                option = QStyleOptionComboBox()
                self.initStyleOption(option)
                arrow_rect = self.style().subControlRect(
                    QStyle.ComplexControl.CC_ComboBox,
                    option,
                    QStyle.SubControl.SC_ComboBoxArrow,
                    self,
                )
                if arrow_rect.contains(event.position().toPoint()):
                    self._keep_popup_open = False
                    super().hidePopup()
                    event.accept()
                    return
            for row, rect in self._chip_hit_rects.items():
                if rect.contains(event.position().toPoint()):
                    self.toggle_row(row)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, self)
        self.style().drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option, painter, self)
        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        ).adjusted(3, 3, -3, -3)
        self._chip_hit_rects = {}
        placements, _height = self._chip_layout()
        if placements:
            for row, chip_rect in placements:
                chip_rect = chip_rect.intersected(text_rect.adjusted(-3, -3, 3, 3))
                self._chip_hit_rects[row] = chip_rect
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#E6F1FB" if self.isEnabled() else "#EEF1F4"))
                painter.drawRoundedRect(chip_rect, 5, 5)
                painter.setPen(QColor("#2563EB" if self.isEnabled() else "#8A8A86"))
                painter.drawText(
                    chip_rect.adjusted(self._CHIP_HORIZONTAL_PADDING, 0, -self._CHIP_CLOSE_WIDTH, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    self.itemText(row),
                )
                painter.drawText(
                    chip_rect.adjusted(chip_rect.width() - self._CHIP_CLOSE_WIDTH - 4, 0, -4, 0),
                    Qt.AlignmentFlag.AlignCenter,
                    "×",
                )
        else:
            painter.setPen(QColor("#8A8A86"))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.itemText(0),
            )
        arrow_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        center = arrow_rect.center()
        opened = bool(self.property("popupOpen"))
        points = (
            (QPoint(center.x() - 5, center.y() + 3), QPoint(center.x() + 5, center.y() + 3), QPoint(center.x(), center.y() - 3))
            if opened else
            (QPoint(center.x() - 5, center.y() - 3), QPoint(center.x() + 5, center.y() - 3), QPoint(center.x(), center.y() + 3))
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1C1C1E" if self.isEnabled() else "#8A8A86"))
        painter.drawPolygon(QPolygon(points))


class _SchemeAttachmentDialog(QDialog):
    """Price-free attachment picker matching the approved scheme."""

    def __init__(self, selected, product_code, parent=None):
        super().__init__(parent)
        self.setObjectName("scheme2AttachmentOverlay")
        self.setWindowTitle("附件选择")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.category_names = []
        self.category_checks = {}
        self.category_combos = {}
        self.direct_checks = {}
        self.custom_rows = [dict(item) for item in selected if isinstance(item, dict) and item.get("custom")]
        selected_pairs = set()
        legacy_selected_names = set()
        for item in selected:
            if not isinstance(item, dict):
                continue
            name = str(item.get("item_name") or item.get("name") or "").strip()
            category = str(item.get("category_level1") or item.get("attachment_category") or "").strip()
            if category:
                selected_pairs.add((category, name))
            elif name:
                legacy_selected_names.add(name)

        def is_selected(category, name):
            return (category, name) in selected_pairs or name in legacy_selected_names

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = _SchemeAttachmentHeader(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 9, 8, 9)
        title = QLabel("选择附件")
        title.setObjectName("scheme2AttachmentTitle")
        close_button = QToolButton()
        close_button.setObjectName("scheme2AttachmentClose")
        close_button.setText("×")
        close_button.setAccessibleName("关闭附件选择")
        close_button.setFixedSize(28, 28)
        close_button.setCursor(Qt.CursorShape.ArrowCursor)
        close_button.clicked.connect(self.reject)
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(close_button)
        root.addWidget(header)

        hint = QLabel("勾选附件；带下拉标志的分类可展开选择具体附件")
        hint.setObjectName("scheme2AttachmentHint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        scroll = QScrollArea()
        scroll.setObjectName("scheme2AttachmentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("scheme2AttachmentContent")
        cards = QVBoxLayout(content)
        cards.setContentsMargins(10, 8, 10, 8)
        cards.setSpacing(6)

        for category in ATTACHMENT_CATEGORY_ORDER:
            if category == "侧板" and product_code != "JP":
                continue
            if category == "控制箱附件" and product_code not in CONTROL_BOX_ATTACHMENT_PRODUCTS:
                continue
            if category == "控制柜附件" and product_code not in {"JS", "JP"}:
                continue
            options = list(ATTACHMENT_OPTIONS.get(category, ()))
            if category == "控制箱附件" and product_code != "JK":
                options = [name for name in options if name != "JK安装板"]
            self.category_names.append(category)
            card = QFrame()
            card.setObjectName("scheme2AttachmentCategory")
            card.setProperty("categoryName", category)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 7, 10, 8)
            card_layout.setSpacing(6)
            if not options:
                check = QCheckBox(category)
                check.setObjectName("scheme2AttachmentDirect")
                check.setChecked(is_selected(category, category))
                self.direct_checks[category] = check
                card_layout.addWidget(check)
            else:
                category_check = QCheckBox(category)
                category_check.setObjectName("scheme2AttachmentCategoryCheck")
                combo = _SchemeAttachmentCombo()
                combo.setObjectName("scheme2AttachmentCombo")
                combo.addItem("未选择")
                combo.addItems(options)
                combo.setMaxVisibleItems(min(6, combo.count()))
                combo.view().setObjectName("scheme2AttachmentDropdown")
                combo.view().setMouseTracking(True)
                combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                combo.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                combo._scheme2_item_delegate = _SchemeComboItemDelegate(combo)
                combo.view().setItemDelegate(combo._scheme2_item_delegate)
                combo._scheme2_popup_filter = _DropdownPopupStateFilter(combo, card)
                combo.view().installEventFilter(combo._scheme2_popup_filter)
                selected_names = [name for name in options if is_selected(category, name)]
                combo.set_selected_texts(selected_names)
                category_check.setChecked(bool(selected_names))
                combo.setEnabled(True)

                def toggle_category(enabled, selector=combo):
                    if not enabled:
                        selector.clear_selection()

                def sync_category(category_toggle=category_check, selector=combo):
                    has_selection = bool(selector.selected_texts())
                    if category_toggle.isChecked() != has_selection:
                        category_toggle.setChecked(has_selection)

                category_check.toggled.connect(toggle_category)
                combo.selectionChanged.connect(sync_category)
                self.category_checks[category] = category_check
                self.category_combos[category] = combo
                card_layout.addWidget(category_check)
                card_layout.addWidget(combo)
            cards.addWidget(card)
        custom_card = QFrame()
        custom_card.setObjectName("scheme2CustomAttachmentCard")
        custom_layout = QHBoxLayout(custom_card)
        custom_layout.setContentsMargins(10, 7, 10, 7)
        custom_toggle = QPushButton("＋ 新增附件")
        custom_toggle.setObjectName("scheme2AddAttachment")
        custom_name = QLineEdit()
        custom_name.setObjectName("scheme2CustomAttachmentName")
        custom_name.setPlaceholderText("请输入附件名称")
        custom_add = QPushButton("添加")
        custom_add.setObjectName("scheme2CustomAttachmentConfirm")
        custom_cancel = QPushButton("取消")
        custom_cancel.setObjectName("scheme2CustomAttachmentCancel")
        for widget in (custom_name, custom_add, custom_cancel):
            widget.hide()
        custom_layout.addWidget(custom_toggle)
        custom_layout.addWidget(custom_name, 1)
        custom_layout.addWidget(custom_add)
        custom_layout.addWidget(custom_cancel)

        def show_custom_input():
            custom_toggle.hide()
            for widget in (custom_name, custom_add, custom_cancel):
                widget.show()
            custom_name.setFocus()

        def cancel_custom_input():
            custom_name.clear()
            for widget in (custom_name, custom_add, custom_cancel):
                widget.hide()
            custom_toggle.show()

        def add_custom():
            name = custom_name.text().strip()
            if not name:
                return
            self.custom_rows.append({
                "item_name": name, "name": name, "category_level1": "其他附件",
                "attachment_category": "其他附件", "quantity": 1,
                "matched_price": 0, "formula_amount": 0, "custom": True,
            })
            custom_toggle.setText(f"＋ 新增附件（已新增 {len(self.custom_rows)} 项）")
            cancel_custom_input()

        custom_toggle.clicked.connect(show_custom_input)
        custom_add.clicked.connect(add_custom)
        custom_cancel.clicked.connect(cancel_custom_input)
        custom_name.returnPressed.connect(add_custom)
        cards.addWidget(custom_card)
        cards.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.setObjectName("scheme2AttachmentActions")
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        confirm.setText("确认选择")
        confirm.setObjectName("scheme2PrimaryAction")
        cancel.setText("取消")
        cancel.setObjectName("scheme2AttachmentCancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def collect_attachments(self):
        selected = []
        for category, check in self.direct_checks.items():
            if check.isChecked():
                selected.append({
                    "item_name": category,
                    "name": category,
                    "category_level1": category,
                    "attachment_category": category,
                    "quantity": 1,
                })
        for category, combo in self.category_combos.items():
            check = self.category_checks[category]
            names = combo.selected_texts() if check.isChecked() else []
            for name in names:
                selected.append({
                    "item_name": name,
                    "name": name,
                    "category_level1": category,
                    "category_level2": name,
                    "attachment_category": category,
                    "quantity": 1,
                })
        selected.extend(dict(item) for item in self.custom_rows)
        return selected


def _open_legacy_attachment_overlay(window, dialog_class, anchor):
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
    dialog.setWindowTitle("附件选择")
    title_label = None
    for label in dialog.findChildren(QLabel):
        text = label.text().strip()
        if "附件价格清单" in text:
            label.setText("附件选择")
            title_label = label
        elif "单价和数量" in text or "价格" in text and "已选择" in text:
            label.setText("已选择附件；单击附件行可选中，数量可双击修改。")
    for button in dialog.findChildren(QPushButton):
        text = button.text().strip()
        if "附件库" in text or "重新读取价格" in text:
            button.hide()
        elif text == "确认选择":
            button.setText("确认选择")
    root_layout = dialog.layout()
    if title_label is not None and root_layout is not None:
        root_layout.removeWidget(title_label)
        title_label.setObjectName("scheme2AttachmentTitle")
        title_label.setStyleSheet("")
        title_bar = QFrame(dialog)
        title_bar.setObjectName("scheme2AttachmentHeader")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 8, 8, 8)
        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        close_button = QToolButton(title_bar)
        close_button.setObjectName("scheme2AttachmentClose")
        close_button.setText("×")
        close_button.setAccessibleName("关闭附件选择")
        close_button.setFixedSize(28, 28)
        close_button.clicked.connect(dialog.reject)
        title_layout.addWidget(close_button)
        root_layout.insertWidget(0, title_bar)
    button_box = dialog.findChild(QDialogButtonBox)
    if isinstance(button_box, QDialogButtonBox):
        confirm_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if confirm_button is not None:
            confirm_button.setObjectName("scheme2PrimaryAction")
        if cancel_button is not None:
            cancel_button.setObjectName("scheme2AttachmentCancel")
        try:
            button_box.accepted.disconnect()
        except RuntimeError:
            pass
        button_box.accepted.connect(dialog.accept)
    table = getattr(dialog, "table", None)
    if isinstance(table, QTableWidget):
        for column in range(table.columnCount()):
            header = table.horizontalHeaderItem(column)
            text = header.text() if header is not None else ""
            if "价格" in text or "单价" in text or "金额" in text:
                table.setColumnHidden(column, True)
    catalog_hint = getattr(dialog, "catalog_hint", None)
    if isinstance(catalog_hint, QLabel):
        catalog_hint.hide()
    selection_frame = getattr(dialog, "selection_status_frame", None)
    if isinstance(selection_frame, QFrame):
        selection_frame.hide()
    preview_timer = getattr(dialog, "_v2_timer", None)
    if isinstance(preview_timer, QTimer):
        preview_timer.stop()
        try:
            preview_timer.timeout.disconnect()
        except RuntimeError:
            pass

    panel = getattr(dialog, "category_panel", None)
    if isinstance(panel, QFrame):
        panel.setStyleSheet(
            "QFrame#attachmentCategoryBar{background:#fff;border:0;border-left:2px solid #85B7EB;}"
            "QLabel#attachmentCategoryTitle{color:#185FA5;font-weight:600;}"
            "QScrollArea#attachmentCategoryScroll{background:#fff;border:0;}"
            "QPushButton#attachmentCategoryBack{background:transparent;border:0;color:#185FA5;text-align:left;}"
            "QFrame#attachmentCategoryCardShell{background:#fff;border:1px solid rgba(0,0,0,.12);border-radius:7px;}"
            "QPushButton#attachmentCategoryCard{background:#fff;border:0;color:#1C1C1E;padding:7px 9px;text-align:left;}"
            "QPushButton#attachmentCategoryCard:hover{background:#E6F1FB;}"
            "QPushButton#attachmentQuickMatch,QPushButton#attachmentQuickMatchCancelled{background:#F6F7F9;color:#5F5E5A;border:0;padding:6px 8px;text-align:left;}"
            "QPushButton#attachmentQuickMatchSelected,QPushButton#attachmentQuickMatchManual,QPushButton#attachmentManualSelection{background:#EAF3DE;color:#3B6D11;border:0;padding:6px 8px;text-align:left;}"
        )
        hint = QLabel("勾选分类后选择附件；带 ▾ 的分类有可选项", panel)
        hint.setObjectName("scheme2AttachmentHint")
        hint.setWordWrap(True)
        panel.layout().insertWidget(1, hint)

    def restyle_categories():
        content = getattr(dialog, "category_scroll_content", None)
        if content is None:
            return
        search = getattr(dialog, "search_edit", None)
        if isinstance(search, QLineEdit):
            search.hide()
        breadcrumb = getattr(dialog, "category_breadcrumb", None)
        if isinstance(breadcrumb, QLabel):
            breadcrumb.setVisible(bool(getattr(dialog, "category_selection", [])))
        selected_categories = {
            str(item.get("category_level1") or item.get("attachment_category") or "").strip()
            for item in getattr(dialog, "attachments", []) if isinstance(item, dict)
        }
        for button in content.findChildren(QPushButton, "attachmentCategoryCard"):
            value = str(button.property("attachmentCategoryValue") or "").strip()
            if button.property("rootLevelCard"):
                lines = [part.strip() for part in button.text().splitlines() if part.strip()]
                count = next((part for part in reversed(lines) if "项" in part), "")
                mark = "☑" if value in selected_categories else "☐"
                button.setText(f"{mark} {value}\n▾ 选择具体附件" + (f"（{count}）" if count else ""))
                shell = button.parentWidget()
                layout = shell.layout() if shell is not None else None
                if isinstance(layout, QBoxLayout):
                    layout.setDirection(QBoxLayout.Direction.TopToBottom)
                button.setMinimumHeight(50)
            else:
                button.setMinimumHeight(42)
            if not button.property("scheme2RestyleConnected"):
                button.setProperty("scheme2RestyleConnected", True)
                button.clicked.connect(lambda: QTimer.singleShot(0, restyle_categories))
        back = getattr(dialog, "category_back_button", None)
        if isinstance(back, QPushButton) and not back.property("scheme2RestyleConnected"):
            back.setProperty("scheme2RestyleConnected", True)
            back.clicked.connect(lambda: QTimer.singleShot(0, restyle_categories))

    worker = getattr(dialog, "_v2_catalog_worker", None)
    if worker is not None and hasattr(worker, "succeeded"):
        worker.succeeded.connect(lambda *_: QTimer.singleShot(0, restyle_categories))
    QTimer.singleShot(0, restyle_categories)
    custom_rows = []
    custom_frame = QFrame()
    custom_layout = QHBoxLayout(custom_frame)
    custom_layout.setContentsMargins(0, 3, 0, 3)
    custom_toggle = QPushButton("＋ 新增附件")
    custom_toggle.setObjectName("scheme2AddAttachment")
    custom_name = QLineEdit()
    custom_name.setPlaceholderText("请输入附件名称")
    custom_add = QPushButton("添加")
    custom_cancel = QToolButton()
    custom_cancel.setText("取消")
    custom_cancel.setObjectName("scheme2AttachmentInlineCancel")
    custom_name.hide()
    custom_add.hide()
    custom_cancel.hide()
    custom_layout.addWidget(custom_toggle)
    custom_layout.addWidget(custom_name, 1)
    custom_layout.addWidget(custom_add)
    custom_layout.addWidget(custom_cancel)
    if dialog.layout() is not None:
        dialog.layout().insertWidget(max(0, dialog.layout().count() - 1), custom_frame)

    def show_custom_input():
        custom_toggle.hide()
        custom_name.show()
        custom_add.show()
        custom_cancel.show()
        custom_name.setFocus()

    def cancel_custom_input():
        custom_name.clear()
        custom_name.hide()
        custom_add.hide()
        custom_cancel.hide()
        custom_toggle.show()

    def add_custom():
        name = custom_name.text().strip()
        if not name:
            return
        custom_rows.append({"item_name": name, "name": name, "quantity": 1, "matched_price": 0, "custom": True})
        custom_toggle.setText(f"＋ 新增附件（已新增 {len(custom_rows)} 项）")
        custom_name.clear()
        custom_name.hide()
        custom_add.hide()
        custom_cancel.hide()
        custom_toggle.show()

    custom_toggle.clicked.connect(show_custom_input)
    custom_add.clicked.connect(add_custom)
    custom_cancel.clicked.connect(cancel_custom_input)
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
        window._scheme2_attachments_manual = True
        _set_dirty(window, True)
        _refresh_scheme2_attachment_summary(window)
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


def _open_attachment_overlay(window, _dialog_class, anchor):
    current = getattr(window, "_scheme2_attachment_overlay", None)
    if current is not None:
        try:
            current.raise_()
            current.show()
            return
        except RuntimeError:
            window._scheme2_attachment_overlay = None
    dialog = _SchemeAttachmentDialog(
        [dict(item) for item in getattr(window, "attachments", []) if isinstance(item, dict)],
        _current_product_code(window),
        window,
    )
    top_left = anchor.mapTo(window, QPoint(0, 0))
    dialog.setGeometry(top_left.x(), top_left.y(), anchor.width(), anchor.height())

    def apply_selection():
        window.attachments = dialog.collect_attachments()
        window.current_result = None
        window._attachment_v2_line_id = None
        window.attachment_default_opt_outs = set()
        window.attachment_default_quantity_overrides = set()
        refresh = getattr(window, "update_attachment_view", None)
        if callable(refresh):
            refresh()
        window._scheme2_attachments_manual = True
        _set_dirty(window, True)
        _refresh_scheme2_attachment_summary(window)
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


def _attachment_chip_text(item):
    name = str(item.get("item_name") or item.get("name") or "附件").strip()
    category = str(item.get("category_level1") or item.get("attachment_category") or "").strip()
    if item.get("custom"):
        quantity = max(1, int(_number(item.get("quantity"), 1)))
        return f"临时：{name} ×{quantity}"
    if category and name and name != category:
        return f"{category}：{name}"
    return f"{category or name} ✓"


def _remove_scheme2_attachment(window, index):
    attachments = getattr(window, "attachments", [])
    if not 0 <= index < len(attachments):
        return
    attachments.pop(index)
    window._scheme2_attachments_manual = True
    window.current_result = None
    refresh = getattr(window, "update_attachment_view", None)
    if callable(refresh):
        refresh()
    _refresh_scheme2_attachment_summary(window)
    _set_dirty(window, True)


def _refresh_scheme2_attachment_summary(window):
    summary = getattr(window, "scheme2_attachment_summary", None)
    if not isinstance(summary, QFrame) or summary.layout() is None:
        return
    layout = summary.layout()
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
    attachments = [item for item in getattr(window, "attachments", []) if isinstance(item, dict)]
    if not attachments:
        empty = QLabel("未选择附件")
        empty.setObjectName("scheme2AttachmentEmpty")
        layout.addWidget(empty)
    else:
        for index, attachment in enumerate(attachments):
            row = QFrame()
            row.setObjectName("scheme2AttachmentChipRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            chip = QLabel(_attachment_chip_text(attachment))
            chip.setObjectName("scheme2AttachmentChip")
            chip.setProperty("temporary", bool(attachment.get("custom")))
            chip.setWordWrap(True)
            chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            remove = QToolButton()
            remove.setObjectName("scheme2AttachmentRemove")
            remove.setText("×")
            remove.setToolTip("删除此附件")
            remove.setAccessibleName(f"删除附件：{_attachment_chip_text(attachment)}")
            remove.clicked.connect(lambda _checked=False, target=index: _remove_scheme2_attachment(window, target))
            row_layout.addWidget(chip)
            row_layout.addWidget(remove)
            layout.addWidget(row, 0, Qt.AlignmentFlag.AlignLeft)
    manual = bool(getattr(window, "_scheme2_attachments_manual", False))
    status = getattr(window, "scheme2_attachment_status", None)
    if isinstance(status, QLabel):
        status.setText("人工修改 ✎" if manual else "AI 已匹配 ✓")
        status.setProperty("manual", manual)
        status.style().unpolish(status)
        status.style().polish(status)
    card = getattr(window, "scheme2_attachment_card", None)
    if isinstance(card, QFrame):
        card.setProperty("provenanceState", "manual" if manual else "ai")
        card.style().unpolish(card)
        card.style().polish(card)
    button = getattr(window, "scheme2_attachment_button", None)
    if isinstance(button, QPushButton):
        button.setText("修改…" if attachments else "选择附件…")


def _clear_scheme2_attachments(window):
    """Clear the completed order's attachments from data, UI and page state."""

    window.attachments = []
    window._scheme2_attachments_manual = False
    refresh = getattr(window, "update_attachment_view", None)
    if callable(refresh):
        refresh()
    _refresh_scheme2_attachment_summary(window)
    pages = getattr(window, "_scheme2_drawing_pages", [])
    page_index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if 0 <= page_index < len(pages) and isinstance(pages[page_index].get("state"), dict):
        pages[page_index]["state"]["attachments"] = []
        pages[page_index]["state"]["attachments_manual"] = False


def _configure_option_page(window, namespace):
    old_page = window.stack.widget(OPTION_ROUTE)
    page = QWidget()
    page.setObjectName("scheme2OptionPage")
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(0)
    service = old_page.findChild(QLabel, "serviceStatusBadge")
    if service is None:
        service = QLabel("报价服务已连接")
    else:
        _detach(service)
    service.setObjectName("scheme2ServiceStatus")
    service.setWordWrap(True)
    service.setAlignment(Qt.AlignmentFlag.AlignCenter)
    nav_layout = window.scheme2_nav.layout()
    nav_layout.insertWidget(max(0, nav_layout.count() - 1), service)
    window.scheme2_service_status = service

    workspace = QSplitter(Qt.Orientation.Horizontal)
    workspace.setObjectName("scheme2Workspace")
    workspace.setHandleWidth(1)
    workspace.setChildrenCollapsible(False)
    page_layout.addWidget(workspace, 1)

    left_scroll = QScrollArea()
    left_scroll.setObjectName("scheme2OptionScroll")
    left_scroll.setWidgetResizable(True)
    left_scroll.setFrameShape(QFrame.Shape.NoFrame)
    left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    left = QWidget()
    left.setObjectName("scheme2OptionForm")
    form = QVBoxLayout(left)
    form.setContentsMargins(14, 4, 14, 16)
    form.setSpacing(11)
    form_title = QLabel("选项配置")
    form_title.setObjectName("scheme2SectionTitle")
    form.addWidget(form_title)
    window.scheme2_provenance_labels = {}
    window.scheme2_manual_fields = set()

    order_number = QLineEdit()
    order_number.setObjectName("scheme2OrderNumber")
    order_number.setPlaceholderText("请输入订单号")
    order_field = _option_field(window, "订单号", order_number)
    _promote_option_label(order_field)
    form.addWidget(order_field)
    window.scheme2_order_number = order_number
    order_number.editingFinished.connect(lambda: _load_order_workspace(window))

    name_edit = QLineEdit()
    name_edit.setObjectName("scheme2NameInput")
    name_edit.setPlaceholderText("名称（默认取图纸文件名，可修改）")
    name_edit.hide()
    window.scheme2_name_edit = name_edit
    product = _detach(getattr(window, "product_combo", None))
    if product is not None:
        product.setObjectName("scheme2ProductCombo")
        placeholder_index = next((
            index for index in range(product.count())
            if product.itemData(index) is None
            and (index == 0 or "产品型号" in product.itemText(index))
        ), -1)
        product.setProperty("schemePlaceholderIndex", placeholder_index)
        product_field = _option_field(window, "产品", product)
        _promote_option_label(product_field)
        _style_scheme_dropdown(product, product_field)
        _refresh_product_placeholder(product)
        product.currentIndexChanged.connect(lambda *_: _refresh_product_placeholder(product))
        form.addWidget(product_field)
    form.addWidget(_scheme2_group_title("尺寸（宽*深*高 mm）"))
    specification = _detach(getattr(window, "quote_spec_edit", None))
    if specification is not None:
        dimension_field = _option_field(window, "总尺寸", specification, "dimensions")
        form.addWidget(dimension_field)
        window.scheme2_dimension_field = dimension_field
        specification.textEdited.connect(lambda *_: _mark_manual(window, "dimensions"))
    ganged = _detach(getattr(window, "ganged_cabinet_panel", None))
    if ganged is not None:
        ganged.hide()
    ganged_dimensions = QFrame()
    ganged_dimensions.setObjectName("scheme2GangedDimensions")
    ganged_dimensions.setLayout(QVBoxLayout())
    ganged_dimensions.layout().setContentsMargins(0, 0, 0, 0)
    ganged_dimensions.layout().setSpacing(8)
    ganged_dimensions.hide()
    form.addWidget(ganged_dimensions)
    window.scheme2_ganged_dimensions = ganged_dimensions
    quantity = _detach(getattr(window, "quantity_spin", None))
    if quantity is not None:
        quantity_field = _option_field(window, "数量", quantity)
        _promote_option_label(quantity_field)
        form.addWidget(quantity_field)

    form.addWidget(_scheme2_group_title("材质 / 表面处理 / 颜色"))
    material = _detach(getattr(window, "material_combo", None))
    coating = _detach(getattr(window, "coating_combo", None))
    if material is not None:
        for index in range(material.count()):
            identity = f"{material.itemText(index)} {material.itemData(index) or ''}".upper()
            for code, label in (("SUS304", "不锈钢 SUS304"), ("SUS316", "不锈钢 SUS316"), ("SECC", "碳钢 SECC")):
                if code in identity:
                    material.setItemText(index, label)
                    break
        material_field = _option_field(window, "", material, "material")
        _style_scheme_dropdown(material, material_field)
        form.addWidget(material_field)
        material.activated.connect(lambda *_: _mark_manual(window, "material"))
    if coating is not None:
        current_coating = coating.currentData()
        coating_items = {
            coating.itemText(index).strip(): coating.itemData(index)
            for index in range(coating.count())
            if coating.itemText(index).strip() != "皱纹" and str(coating.itemData(index) or "").strip() != "皱纹"
        }
        with QSignalBlocker(coating):
            coating.clear()
            for text in ("无", "平光", "橘纹"):
                if text in coating_items:
                    coating.addItem(text, coating_items[text])
            for text, data in coating_items.items():
                if text not in {"无", "平光", "橘纹"}:
                    coating.addItem(text, data)
            restored = coating.findData(current_coating)
            coating.setCurrentIndex(restored if restored >= 0 else 0)
        coating_field = _option_field(window, "", coating, "coating")
        _style_scheme_dropdown(coating, coating_field)
        form.addWidget(coating_field)
        coating.activated.connect(lambda *_: _mark_manual(window, "coating"))
    color = QComboBox()
    color.setObjectName("scheme2ColorCombo")
    color.addItems(("RAL7035 浅灰", "RAL7032 灰", "RAL9005 黑", "RAL9016 白", "RAL5015 蓝", "自定义…"))
    color.setEditable(True)
    color.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    color.lineEdit().setPlaceholderText("输入颜色名称或色号…")
    color.lineEdit().setClearButtonEnabled(True)

    def color_selected(index):
        custom = index == color.findText("自定义…")
        editor = color.lineEdit()
        if custom:
            with QSignalBlocker(color):
                color.setEditText("")
            editor.setPlaceholderText("请输入自定义颜色")
            editor.setFocus()
        else:
            editor.setPlaceholderText("输入颜色名称或色号…")
        editor.setObjectName("scheme2ColorManualInput" if custom else "")
        editor.setAccessibleName("自定义颜色" if custom else "颜色")
        editor.setClearButtonEnabled(True)
        color.setProperty("manualEntry", custom)
        color.style().unpolish(color)
        color.style().polish(color)
        _mark_manual(window, "color")

    preset_colors = {color.itemText(index) for index in range(color.count() - 1)}

    def color_typed(text):
        manual = bool(text.strip()) and text not in preset_colors
        color.setProperty("manualEntry", manual)
        editor = color.lineEdit()
        editor.setObjectName("scheme2ColorManualInput" if manual else "")
        editor.setAccessibleName("自定义颜色" if manual else "颜色")
        if manual:
            _mark_manual(window, "color")
        color.style().unpolish(color)
        color.style().polish(color)
        _set_dirty(window, True)

    color.activated.connect(color_selected)
    color.editTextChanged.connect(color_typed)
    window.scheme2_color_combo = color
    color_field = _option_field(window, "", color, "color")
    _style_scheme_dropdown(color, color_field, color.count() - 1)
    form.addWidget(color_field)
    thickness = _detach(getattr(window, "cabinet_body_thickness_spin", None))
    if thickness is not None:
        thickness_field = _option_field(window, "箱体料厚", thickness)
        _promote_option_label(thickness_field)
        form.addWidget(thickness_field)

    form.addWidget(_scheme2_group_title("门型"))
    door_host = QFrame()
    door_host.setObjectName("scheme2RegularDoors")
    doors = QGridLayout()
    door_host.setLayout(doors)
    doors.setContentsMargins(0, 0, 0, 0)
    doors.setHorizontalSpacing(8)
    single = _detach(getattr(window, "single_door_combo", None))
    double = _detach(getattr(window, "double_door_combo", None))
    if single is not None:
        doors.addWidget(_option_field(window, "单开门", single), 0, 0)
    if double is not None:
        doors.addWidget(_option_field(window, "双开门", double), 0, 1)
    form.addWidget(door_host)
    window.scheme2_regular_doors = door_host
    ganged_doors = QFrame()
    ganged_doors.setObjectName("scheme2GangedDoors")
    ganged_doors.setLayout(QVBoxLayout())
    ganged_doors.layout().setContentsMargins(0, 0, 0, 0)
    ganged_doors.layout().setSpacing(8)
    ganged_doors.hide()
    form.addWidget(ganged_doors)
    window.scheme2_ganged_doors = ganged_doors

    attachment_card = QFrame()
    attachment_card.setObjectName("scheme2AttachmentCard")
    attachment_layout = QVBoxLayout(attachment_card)
    attachment_layout.setContentsMargins(10, 9, 10, 10)
    attachment_layout.setSpacing(6)
    attachment_header = QHBoxLayout()
    attachment_title = QLabel("附件")
    attachment_title.setObjectName("scheme2OptionGroupTitle")
    attachment_header.addWidget(attachment_title)
    attachment_header.addStretch(1)
    attachment_status = QLabel()
    attachment_status.setObjectName("scheme2AttachmentStatus")
    attachment_header.addWidget(attachment_status)
    attachment_button = old_page.findChild(QPushButton, "quietAction")
    if attachment_button is not None:
        _detach(attachment_button)
        attachment_button.setObjectName("scheme2AttachmentModify")
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
        attachment_table.hide()
    attachment_summary = QFrame()
    attachment_summary.setObjectName("scheme2AttachmentSummary")
    attachment_summary.setLayout(QVBoxLayout())
    attachment_summary.layout().setContentsMargins(0, 0, 0, 0)
    attachment_summary.layout().setSpacing(5)
    attachment_layout.addWidget(attachment_summary)
    window.scheme2_attachment_card = attachment_card
    window.scheme2_attachment_status = attachment_status
    window.scheme2_attachment_button = attachment_button
    window.scheme2_attachment_summary = attachment_summary
    _refresh_scheme2_attachment_summary(window)
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
    counter = QLabel("已识别 0 / 0")
    counter.setObjectName("scheme2CompletionPill")
    page_selector = QSpinBox()
    page_selector.setObjectName("scheme2PageSelector")
    page_selector.setPrefix("第 ")
    page_selector.setSuffix(" 页")
    page_selector.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
    page_selector.setFixedWidth(82)
    page_selector.setEnabled(False)
    quoted_badge = QLabel("已报价")
    quoted_badge.setObjectName("scheme2QuotedBadge")
    quoted_badge.hide()
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
        right.navigation_layout.insertWidget(3, counter)
        right.navigation_layout.insertWidget(4, page_selector)
        right.navigation_layout.addWidget(quoted_badge)
        right.message.hide()
        right_layout.addWidget(right, 1)
        right.show()
        footer = QFrame()
        footer.setObjectName("scheme2RecognitionFooter")
        footer.setFixedHeight(DRAWING_FOOTER_HEIGHT)
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(footer)
        row.setContentsMargins(10, 8, 10, 8)
        status = QLabel("等待图纸识别")
        status.setObjectName("scheme2RecognitionStatus")
        progress = _ClickableProgressBar()
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
        manage = QPushButton("导入图纸")
        manage.setObjectName("scheme2PrimaryGhost")
        add = QPushButton("加入报价清单")
        add.setObjectName("scheme2PrimaryAction")
        row.addWidget(status, 1)
        row.addWidget(progress)
        row.addWidget(more)
        row.addWidget(manage)
        row.addWidget(add)
        right.layout().addWidget(footer)
        manage.clicked.connect(lambda: _import_scheme2_drawings(window))
        add.clicked.connect(lambda: _calculate_and_add(window))
        progress.clicked.connect(lambda: _show_add_failure_reason(window))
        try:
            right.previous.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            right.next.clicked.disconnect()
        except RuntimeError:
            pass
        right.previous.clicked.connect(lambda: _change_scheme2_page(window, -1))
        right.next.clicked.connect(lambda: _change_scheme2_page(window, 1))
        page_selector.valueChanged.connect(
            lambda value: _activate_scheme2_page(window, value - 1)
            if value > 0 and value - 1 != getattr(window, "_scheme2_drawing_page_index", -1)
            else None
        )
        original_update_tools = right.update_tools

        def update_page_tools(preview):
            original_update_tools()
            _sync_scheme2_page_navigation(window)

        right.update_tools = MethodType(update_page_tools, right)
        window._scheme2_import_button = manage
        window.scheme2_recognition_status = status
        window.scheme2_completion = counter
        window.scheme2_page_selector = page_selector
        window.scheme2_quoted_badge = quoted_badge
        window.scheme2_add_button = add
        window.scheme2_add_progress = progress
        _sync_scheme2_page_navigation(window)
    workspace.addWidget(right_shell)
    workspace.setStretchFactor(0, 0)
    workspace.setStretchFactor(1, 1)
    window.scheme2_option_splitter = workspace
    window.scheme2_option_form_widget = left_scroll
    window.scheme2_drawing_widget = right_shell

    if specification is not None:
        specification.textChanged.connect(
            lambda *_: QTimer.singleShot(0, lambda: _refresh_scheme2_ganged_ui(window))
        )
    if product is not None:
        product.activated.connect(
            lambda *_: QTimer.singleShot(0, lambda: _refresh_scheme2_ganged_ui(window))
        )
    QTimer.singleShot(0, lambda: _refresh_scheme2_ganged_ui(window))

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


def _monitor_formula_calculation(window):
    """Restore the scheme action when formula preparation ends without a quote."""

    previous = getattr(window, "_scheme2_formula_monitor", None)
    if isinstance(previous, QTimer):
        previous.stop()
        previous.deleteLater()
    timer = QTimer(window)
    timer.setInterval(200)
    window._scheme2_formula_monitor = timer

    def running(worker):
        try:
            return worker is not None and worker.isRunning()
        except RuntimeError:
            return False

    def check():
        if not getattr(window, "_scheme2_add_after_calculate", False):
            timer.stop()
            return
        if getattr(window, "quote_calculation_in_progress", False) or running(getattr(window, "worker", None)):
            timer.stop()
            return
        debounce = getattr(window, "_formula_template_debounce_timer", None)
        if (
            getattr(window, "_pending_formula_calculation", False)
            or running(getattr(window, "template_worker", None))
            or (isinstance(debounce, QTimer) and debounce.isActive())
        ):
            return
        if isinstance(getattr(window, "current_result", None), dict):
            timer.stop()
            return
        timer.stop()
        risk = getattr(window, "risk_label", None)
        detail = risk.text().strip() if isinstance(risk, QLabel) else ""
        window.show_error(detail or "公式模板未能完成计算，请重试。")

    timer.timeout.connect(check)
    timer.start()


def _calculate_and_add(window):
    if getattr(window, "quote_calculation_in_progress", False):
        return
    window._scheme2_add_started_at = time.monotonic()
    elapsed_timer = getattr(window, "_scheme2_add_elapsed_timer", None)
    if isinstance(elapsed_timer, QTimer):
        elapsed_timer.start()
    pending_attachments = [
        item for item in getattr(window, "attachments", [])
        if isinstance(item, dict) and not item.get("custom") and item.get("attachment_price_id") is None
    ]
    current = getattr(window, "current_result", None)
    valid = not pending_attachments and isinstance(current, dict) and current.get("input_signature") == window.quote_input_signature()
    if valid:
        _set_add_progress(window, 5, "保存快照并生成行")
        _finish_add(window)
        return
    window._scheme2_add_after_calculate = True
    window.scheme2_add_button.setEnabled(False)
    window.scheme2_add_button.setText("正在计算…")
    _set_add_progress(window, 1, "校验输入")

    def calculate_quote():
        _set_add_progress(window, 3, "读取公式模板并计算")
        window.calculate()
        _monitor_formula_calculation(window)

    if pending_attachments:
        resolver = getattr(window, "resolve_attachments_for_quote", None)
        if not callable(resolver):
            window.show_error("附件价格库解析功能不可用")
            return
        _set_add_progress(window, 2, "读取附件价格库并匹配")
        resolver(calculate_quote, window.show_error)
        return
    _set_add_progress(window, 2, "附件价格已就绪")
    calculate_quote()


def _refresh_add_progress_display(window):
    progress = getattr(window, "scheme2_add_progress", None)
    if progress is None:
        return
    step = int(progress.property("step") or 0)
    label = str(progress.property("stepLabel") or "")
    started = getattr(window, "_scheme2_add_started_at", None)
    elapsed = max(0.0, time.monotonic() - started) if started is not None else 0.0
    progress.setFormat(f"{step}/5 {label} · {elapsed:.1f}秒")


def _set_add_progress(window, step, label, failed=False):
    progress = getattr(window, "scheme2_add_progress", None)
    if progress is None:
        return
    progress.show()
    progress.setValue(step)
    progress.setProperty("step", int(step))
    progress.setProperty("stepLabel", str(label))
    _refresh_add_progress_display(window)
    progress.setProperty("failed", failed)
    progress.setProperty("failureReason", str(label).removeprefix("失败：").strip() if failed else "")
    progress.setToolTip("点击查看完整失败原因" if failed else "")
    progress.setCursor(Qt.CursorShape.PointingHandCursor if failed else Qt.CursorShape.ArrowCursor)
    progress.setFocusPolicy(Qt.FocusPolicy.StrongFocus if failed else Qt.FocusPolicy.NoFocus)
    progress.style().unpolish(progress)
    progress.style().polish(progress)
    if failed:
        timer = getattr(window, "_scheme2_add_elapsed_timer", None)
        if isinstance(timer, QTimer):
            timer.stop()


def _show_add_failure_reason(window):
    progress = getattr(window, "scheme2_add_progress", None)
    reason = str(progress.property("failureReason") or "").strip() if progress is not None else ""
    if reason:
        QMessageBox.warning(window, "失败原因", reason)


def _set_dirty(window, dirty=True):
    window._scheme2_dirty = bool(dirty)
    if dirty:
        _restore_add_action(window)
    label = getattr(window, "scheme2_saved_status", None)
    if label is not None:
        label.setText("有未保存变更" if dirty else "快照已保存")
        label.setProperty("dirty", bool(dirty))
        label.style().unpolish(label)
        label.style().polish(label)


def _restore_add_action(window):
    add_button = getattr(window, "scheme2_add_button", None)
    if isinstance(add_button, QPushButton) and add_button.text() == "已加入":
        add_button.setText("加入报价清单")
        add_button.setEnabled(True)


def _scheme2_quote_remark(item):
    """Build the formal quote remark only from confirmed program fields."""

    product = str(
        item.get("scheme2_selected_product_name")
        or item.get("scheme2_selected_product_code")
        or item.get("product_family")
        or item.get("product_code")
        or ""
    ).strip()
    product = re.sub(r"_(?:SINGLE|DOUBLE|DEFAULT)$", "", product, flags=re.IGNORECASE)
    material = str(item.get("scheme2_selected_material") or item.get("material_code") or "").strip()
    surface = str(item.get("scheme2_selected_surface") or item.get("coating_type") or "").strip()
    color = str(item.get("display_color") or "").strip()
    attachment_names = []
    for attachment in item.get("attachments") or []:
        name = str(attachment.get("item_name") or attachment.get("name") or attachment.get("model_code") or "").strip()
        if name and name not in attachment_names:
            attachment_names.append(name)
    attachments = "、".join(attachment_names) or "无附件"
    parts = [f"仿威图{product}柜", material, surface, color, attachments]
    return "，".join(part for part in parts if part) + "。"


def _synchronize_export_remark(item, remark):
    """Keep the confirmed/exported remark fields on one authoritative value."""

    value = str(remark or "").strip()
    item["final_remark"] = value
    item["notes"] = value
    item["source_ocr_remark"] = value
    item["source_reviewed_remark"] = value


def _finish_add(window):
    before = len(getattr(window, "draft_items", []))
    editing = getattr(window, "_scheme2_edit_item", None)
    editing_index = window.draft_items.index(editing) if editing in window.draft_items else None
    window.add_current_to_summary()
    if len(getattr(window, "draft_items", [])) != before + 1:
        return
    item = window.draft_items[-1]
    _stamp_selected_product(window, item)
    if editing_index is not None:
        window.draft_items.pop()
        window.draft_items[editing_index] = item
    window._scheme2_edit_item = None
    item["name"] = window.scheme2_name_edit.text().strip() or item.get("model_code") or "未命名"
    item["scheme2_selected_material"] = window.material_combo.currentText().strip()
    item["scheme2_selected_surface"] = window.coating_combo.currentText().strip()
    item["display_color"] = window.scheme2_color_combo.currentText()
    _synchronize_export_remark(item, _scheme2_quote_remark(item))
    pages = getattr(window, "_scheme2_drawing_pages", [])
    page_index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if 0 <= page_index < len(pages):
        page = pages[page_index]
        page["quoted"] = True
        item["source_path"] = page["source_path"]
        item["source_page_index"] = int(page["page_index"])
        item["source_page_number"] = int(page["page_index"]) + 1
        item["source_page_count"] = int(page["page_count"])
    item.setdefault("quick_discount", 1.0)
    active_settings = getattr(window, "_scheme2_active_settings", None)
    item["scheme2_cost_settings"] = dict(active_settings or window.scheme2_defaults)
    material_code = str(item.get("material_code") or "").strip().upper()
    if active_settings is None and material_code in STAINLESS_DEFAULT_PRICES:
        item["scheme2_cost_settings"]["stainless_price"] = STAINLESS_DEFAULT_PRICES[material_code]
    if active_settings is None:
        item["scheme2_cost_settings"]["surface_price"] = _surface_default_price(
            item["scheme2_selected_surface"]
        )
    window._scheme2_active_settings = None
    window._scheme2_clear_attachments_on_return = True
    _clear_scheme2_attachments(window)
    _set_add_progress(window, 5, "已完成")
    timer = getattr(window, "_scheme2_add_elapsed_timer", None)
    if isinstance(timer, QTimer):
        timer.stop()
    window.scheme2_add_button.setText("已加入")
    _set_dirty(window, False)
    window.refresh_summary()
    _sync_scheme2_quoted_badge(window)
    _refresh_quote_page(window)
    target_row = editing_index if editing_index is not None else len(window.draft_items) - 1
    if target_row >= 0:
        window.summary_table.selectRow(target_row)
        for column in range(window.summary_table.columnCount()):
            cell = window.summary_table.item(target_row, column)
            if cell is not None:
                cell.setBackground(QColor("#EAF3DE"))
        QTimer.singleShot(1000, window.refresh_summary)


def _sync_completion(window):
    if getattr(window, "_scheme2_drawing_pages", None):
        _sync_scheme2_page_navigation(window)
        return
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
    bind("Ctrl+3", lambda: window.show_section(QUOTE_ROUTE))
    bind("Return", submit)
    bind("Enter", submit)
    bind("Escape", escape)
    bind("Shift+Up", lambda: shift_move(-1))
    bind("Shift+Down", lambda: shift_move(1))
    bind("Delete", lambda: _delete_selected(window) if window.stack.currentIndex() == COST_ROUTE else None)
    bind("Ctrl+D", lambda: _duplicate_selected(window) if window.stack.currentIndex() == COST_ROUTE else None)
    window.scheme2_shortcuts = shortcuts


def _scaled_style_metrics(style_sheet, scale):
    def replace(match):
        value = max(1.0, float(match.group(1)) * scale)
        formatted = str(int(round(value))) if value >= 2 else f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{formatted}{match.group(2)}"

    return _STYLE_LENGTH_RULE.sub(replace, style_sheet)


def _apply_proportional_scale(window):
    reference = getattr(window, "_scheme2_scale_reference", None)
    styles = getattr(window, "_scheme2_scale_styles", None)
    if reference is None or not styles:
        return 1.0
    scale = min(window.width() / max(1, reference.width()), window.height() / max(1, reference.height()))
    if abs(scale - float(getattr(window, "_scheme2_scale", 0.0))) < 0.01:
        return scale
    window._scheme2_scale = scale
    for widget, base_style in styles:
        widget.setStyleSheet(_scaled_style_metrics(base_style, scale))
    nav = getattr(window, "scheme2_nav", None)
    if nav is not None:
        nav.setFixedWidth(max(1, round(NAV_EXPANDED_WIDTH * scale)))
    sidebar = getattr(window, "scheme2_cost_sidebar", None)
    if sidebar is not None:
        sidebar.setFixedWidth(max(1, round(COST_SIDEBAR_WIDTH * scale)))
    company = getattr(window, "scheme2_company", None)
    if company is not None:
        company.setFixedHeight(max(1, round(COMPANY_COMBO_HEIGHT * scale)))
    quote_company_field = getattr(window, "scheme2_quote_company_field", None)
    if quote_company_field is not None:
        quote_company_field.setFixedWidth(max(1, round(QUOTE_COMPANY_FIELD_WIDTH * scale)))
    return scale


def _apply_responsive(window):
    scale = _apply_proportional_scale(window)
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
            form_min = max(1, round(340 * scale))
            form_max = max(form_min, round(420 * scale))
            form = min(form_max, max(form_min, (width - round(NAV_EXPANDED_WIDTH * scale)) // 3))
            splitter.widget(0).setMinimumWidth(form)
            splitter.widget(0).setMaximumWidth(form_max)
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
        canvas_width = max(300, drawing.width() - 34)
        canvas_height = max(300, drawing.height() - DRAWING_VERTICAL_CHROME)
        canvas.setFixedSize(canvas_width, canvas_height)
        if preview.layout() is not None:
            preview.layout().setAlignment(canvas, Qt.AlignmentFlag.AlignHCenter)
    expand = getattr(window, "scheme2_expand_button", None)
    if expand is not None:
        expand.move(0, max(90, (window.height() - expand.height()) // 2))
        expand.raise_()
    host = window.stack.parentWidget()
    host_layout = host.layout() if host is not None else None
    if host_layout is not None:
        # Every route must consume the available height.  Pinning the option
        # page to the top leaves a grey strip when the window grows vertically.
        host_layout.setAlignment(window.stack, Qt.AlignmentFlag(0))
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


def _increase_font_sizes(style_sheet, step=1.0):
    """Raise every existing explicit UI font by one shared type-scale step."""

    def replace(match):
        size = float(match.group(1)) + step
        formatted = str(int(size)) if size.is_integer() else str(size).rstrip("0").rstrip(".")
        return f"font-size:{formatted}{match.group(2)}"

    return _FONT_SIZE_RULE.sub(replace, style_sheet)


def _increase_region_font_sizes(root, step=2):
    """Apply a one-time pixel-size increase to one complete UI region."""

    if root is None or root.property("scheme2FontIncrease"):
        return
    widgets = [root, *root.findChildren(QWidget)]
    sizes = []
    for widget in widgets:
        widget.ensurePolished()
        size = widget.font().pixelSize()
        if size > 0:
            sizes.append((widget, size + step))
    for widget, size in sizes:
        existing = widget.styleSheet().rstrip().rstrip(";")
        widget.setStyleSheet(f"{existing};font-size:{size}px;" if existing else f"font-size:{size}px;")
    root.setProperty("scheme2FontIncrease", True)


def _apply_palette(window):
    base_font = window.font()
    base_font.setFeature(QFont.Tag.fromString("tnum"), 1)
    window.setFont(base_font)
    scheme_style = """
QMainWindow QWidget { font-family:"Microsoft YaHei UI","Segoe UI"; font-size:13px; font-weight:400; color:#2A3541; }
QMainWindow, QWidget#scheme2OptionPage, QWidget#scheme2CostPage, QWidget#scheme2DetailPage { background:#FFFFFF; color:#2A3541; }
QMainWindow QPushButton { font-size:12px; font-weight:500; min-height:26px; max-height:26px; padding-top:0; padding-bottom:0; }
QLabel#scheme2ServiceStatus { color:#3B6D11; background:#EAF3DE; border-radius:7px; padding:5px 6px; font-size:11px; }
QDialog#scheme2ConfirmDialog { background:rgba(22,28,36,0.45); }
QDialog#scheme2DimensionDialog { background:rgba(22,28,36,0.45); }
QFrame#scheme2DimensionShell { background:#FFFFFF; border:0; border-radius:9px; }
QFrame#scheme2DimensionTitleBar { background:#FFFFFF; border:0; border-bottom:1px solid #E2E5E9; border-top-left-radius:9px; border-top-right-radius:9px; min-height:40px; }
QLabel#scheme2DimensionTitle { color:#1F3A6A; font-size:13px; font-weight:600; border:0; }
QToolButton#scheme2DimensionClose { color:#8A8A86; background:transparent; border:0; font-size:16px; }
QToolButton#scheme2DimensionClose:hover { color:#1C1C1E; }
QLineEdit#scheme2DimensionInput { background:#FFFFFF; border:1px solid #2563EB; border-radius:7px; padding:6px 10px; min-height:24px; }
QLabel#scheme2DimensionHint { color:#2A3541; font-size:13px; margin-left:16px; margin-right:16px; }
QPushButton#scheme2DimensionCancel { color:#1C1C1E; background:#FFFFFF; border:1px solid #C8CDD4; border-radius:7px; }
QPushButton#scheme2DimensionConfirm { color:#FFFFFF; background:#2563EB; border:1px solid #2563EB; border-radius:7px; font-weight:600; }
QPushButton#scheme2DimensionConfirm:disabled { background:#AFC7E8; border-color:#AFC7E8; }
QFrame#scheme2ConfirmShell { background:#FFFFFF; border:1px solid #D7DCE3; border-radius:8px; }
QFrame#scheme2ConfirmTitleBar { background:#FFFFFF; border:0; border-bottom:1px solid #E2E5E9; border-top-left-radius:8px; border-top-right-radius:8px; min-height:40px; }
QLabel#scheme2ConfirmTitle { color:#1F3A6A; font-size:13px; font-weight:600; border:0; }
QToolButton#scheme2ConfirmClose { color:#8A8A86; background:transparent; border:0; font-size:16px; }
QToolButton#scheme2ConfirmClose:hover { color:#1C1C1E; }
QLabel#scheme2ConfirmWarningIcon { color:#B55D08; background:#FFF4E5; border:1px solid #F2A33A; border-radius:17px; font-size:16px; }
QLabel#scheme2ConfirmMessage { color:#2A3541; background:transparent; border:0; font-size:13px; }
QPushButton#scheme2ConfirmReject { color:#1C1C1E; background:#FFFFFF; border:1px solid #C8CDD4; border-radius:6px; padding:0 14px; }
QPushButton#scheme2ConfirmDanger { color:#FFFFFF; background:#C9362B; border:1px solid #C9362B; border-radius:6px; padding:0 14px; font-weight:600; }
QPushButton#scheme2ConfirmDanger:hover { background:#B52E25; border-color:#B52E25; }
QScrollArea#scheme2OptionScroll, QWidget#scheme2OptionForm { background:#FFFFFF; border:0; }
QScrollArea#scheme2OptionScroll QScrollBar:vertical { background:#EEF0F3; width:10px; margin:0; }
QScrollArea#scheme2OptionScroll QScrollBar::handle:vertical { background:#C3CBD6; border-radius:5px; min-height:36px; }
QScrollArea#scheme2OptionScroll QScrollBar::add-line:vertical, QScrollArea#scheme2OptionScroll QScrollBar::sub-line:vertical { height:0; }
QFrame#scheme2DrawingShell { background:#EEF0F3; border-left:1px solid rgba(0,0,0,.12); }
QFrame#scheme2DrawingHeader { background:#FFFFFF; border-bottom:1px solid rgba(0,0,0,.12); }
QLabel#scheme2SectionTitle { font-size:16px; font-weight:600; color:#1F3A6A; }
QLabel#scheme2OptionGroupTitle { font-size:13px; font-weight:600; color:#1F3A6A; margin-top:3px; }
QLabel#scheme2OptionLabel { font-size:12px; font-weight:400; color:#3F5A82; }
QFrame#scheme2OptionControlShell { min-height:52px; background:#FFFFFF; border:1px solid rgba(0,0,0,.16); border-radius:11px; }
QFrame#scheme2OptionControlShell[schemeDropdown="true"] { border-color:#B8BEC7; border-radius:6px; }
QFrame#scheme2OptionControlShell[schemeDropdown="true"][popupOpen="true"] { border-color:#2563EB; }
QFrame#scheme2OptionControlShell[provenanceState="ai"] { background:#F6F7F9; }
QFrame#scheme2OptionControlShell[provenanceState="manual"] { background:#FAEEDA; border-color:#EF9F27; }
QFrame#scheme2OptionControlShell QLineEdit, QFrame#scheme2OptionControlShell QComboBox, QFrame#scheme2OptionControlShell QSpinBox, QFrame#scheme2OptionControlShell QDoubleSpinBox { background:transparent; border:0; border-radius:0; padding:8px 14px; min-height:34px; font-size:13px; font-weight:400; color:#2A3541; }
QFrame#scheme2OptionControlShell QComboBox::drop-down, QFrame#scheme2DoorValue QComboBox::drop-down { border:0; width:28px; }
QFrame#scheme2OptionControlShell QComboBox::down-arrow, QFrame#scheme2DoorValue QComboBox::down-arrow { width:8px; height:6px; }
QComboBox#scheme2ProductCombo[placeholderActive="true"] { color:#8A8A86; }
QAbstractItemView#scheme2OptionDropdown { background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; border-radius:6px; outline:0; padding:0; selection-background-color:#F5F9FF; selection-color:#1C1C1E; }
QAbstractItemView#scheme2OptionDropdown::item { min-height:40px; padding:0; border:0; }
QComboBox#scheme2ColorCombo[manualEntry="true"] QLineEdit#scheme2ColorManualInput { background:transparent; border:0; padding:8px 14px; }
QLabel#scheme2ProvenancePending { font-size:10px; color:#8A8A86; }
QLabel#scheme2ProvenanceAi { font-size:10px; color:#3B6D11; background:transparent; padding:1px 5px; }
QLabel#scheme2ProvenanceManual { font-family:"Segoe UI Symbol","Microsoft YaHei UI"; font-size:10px; color:#854F0B; background:#FFFFFF; border-radius:12px; padding:4px 10px; }
QFrame#scheme2GangedRow { background:transparent; border:0; }
QLabel#scheme2GangedLabel { color:#3F5A82; font-size:12px; }
QFrame#scheme2GangedValue, QFrame#scheme2DoorValue { min-height:42px; background:#F6F7F9; border:1px solid rgba(0,0,0,.14); border-radius:10px; }
QFrame#scheme2GangedValue QLabel { font-size:13px; color:#2A3541; }
QLabel#scheme2GangedAi { color:#3B6D11; font-size:10px; }
QFrame#scheme2DoorValue QLabel { color:#5F5E5A; font-size:13px; }
QFrame#scheme2DoorValue QComboBox { background:transparent; border:0; min-height:30px; }
QFrame#scheme2AttachmentCard { background:#FFFFFF; border:1px solid #85B7EB; border-radius:8px; }
QFrame#scheme2AttachmentCard[provenanceState="manual"] { border-color:#F2A33A; }
QFrame#scheme2AttachmentSummary { background:transparent; border:0; }
QLabel#scheme2AttachmentEmpty { color:#8A8A86; background:transparent; border:0; font-size:13px; }
QLabel#scheme2AttachmentChip { color:#185FA5; background:#E6F1FB; border:0; border-radius:6px; padding:3px 8px; font-size:13px; }
QLabel#scheme2AttachmentChip[temporary="true"] { color:#854F0B; background:#FAEEDA; }
QFrame#scheme2AttachmentChipRow { background:transparent; border:0; }
QToolButton#scheme2AttachmentRemove { color:#B42318; background:transparent; border:0; padding:0; min-width:22px; min-height:22px; font-size:16px; }
QToolButton#scheme2AttachmentRemove:hover { background:#FEE4E2; border-radius:6px; }
QLabel#scheme2AttachmentStatus { color:#3B6D11; background:#EAF3DE; border:0; border-radius:9px; padding:2px 7px; font-size:10px; }
QLabel#scheme2AttachmentStatus[manual="true"] { color:#854F0B; background:#FAEEDA; }
QPushButton#scheme2AttachmentModify { color:#185FA5; background:transparent; border:0; padding:2px 0; min-height:22px; }
QPushButton#scheme2AttachmentModify:hover { color:#0B326B; text-decoration:underline; }
QFrame#scheme2AttachmentHeader { background:#E6F1FB; border:0; border-bottom:1px solid #85B7EB; }
QLabel#scheme2AttachmentTitle { color:#1F3A6A; font-size:13px; font-weight:600; }
QToolButton#scheme2AttachmentClose { color:#5F5E5A; background:transparent; border:0; border-radius:5px; font-size:18px; }
QToolButton#scheme2AttachmentClose:hover { color:#1C1C1E; background:#FFFFFF; }
QDialog#scheme2AttachmentOverlay { background:#FFFFFF; border:1px solid #85B7EB; }
QLabel#scheme2AttachmentHint { color:#5F5E5A; background:#F6F7F9; padding:8px 12px; border-bottom:1px solid rgba(0,0,0,.10); }
QScrollArea#scheme2AttachmentScroll, QWidget#scheme2AttachmentContent { background:#FFFFFF; border:0; }
QFrame#scheme2AttachmentCategory { background:#FFFFFF; border:1px solid rgba(0,0,0,.14); border-radius:7px; }
QFrame#scheme2AttachmentCategory[popupOpen="true"] { background:#F5F9FF; border-color:#85B7EB; }
QCheckBox#scheme2AttachmentDirect, QCheckBox#scheme2AttachmentCategoryCheck { color:#1C1C1E; min-height:28px; spacing:8px; }
QComboBox#scheme2AttachmentCombo { background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; border-radius:6px; padding:6px 30px 6px 10px; min-height:32px; }
QComboBox#scheme2AttachmentCombo:focus, QComboBox#scheme2AttachmentCombo[popupOpen="true"] { border-color:#2563EB; }
QComboBox#scheme2AttachmentCombo:disabled { background:#F6F7F9; color:#8A8A86; border-color:#D7DCE3; }
QComboBox#scheme2AttachmentCombo::drop-down { border:0; width:28px; }
QComboBox#scheme2AttachmentCombo::down-arrow { width:8px; height:6px; }
QAbstractItemView#scheme2AttachmentDropdown { background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; border-radius:6px; outline:0; padding:0; selection-background-color:#F5F9FF; selection-color:#1C1C1E; }
QAbstractItemView#scheme2AttachmentDropdown::item { min-height:40px; padding:0; border:0; }
QDialogButtonBox#scheme2AttachmentActions { background:#FFFFFF; border-top:1px solid rgba(0,0,0,.12); padding:9px 10px; }
QPushButton#scheme2AttachmentCancel { color:#185FA5; background:#FFFFFF; border:1px solid #85B7EB; border-radius:7px; padding:0 16px; }
QWidget#scheme2DrawingCanvas { background:#FFFFFF; border:1px solid rgba(0,0,0,.24); }
QFrame#navPanel { background:#DCE8F7; border:1px solid #BBD0EA; border-top-left-radius:13px; border-bottom-left-radius:13px; border-top-right-radius:0; border-bottom-right-radius:0; }
QFrame#scheme2NavBrand { background:transparent; border:0; }
QLabel#scheme2NavLogo { background:#2563EB; color:#FFFFFF; border-radius:6px; font-size:11px; font-weight:600; }
QLabel#scheme2NavTitle { color:#1F3A6A; font-size:13px; font-weight:600; }
QFrame#navPanel QPushButton { color:#0B326B; border:0; border-radius:8px; padding:0 10px; min-height:28px; max-height:28px; text-align:left; font-size:15px; font-weight:500; }
QFrame#navPanel QPushButton:checked { color:#FFFFFF; background:#2563EB; }
QPushButton#scheme2CollapseButton { color:#5A7AAB; background:transparent; border:0; padding:0; text-align:center; font-size:13px; }
QPushButton#scheme2CollapseButton:hover { background:#E6F1FB; }
QFrame#scheme2CostSidebar { background:#DCE8F7; border-right:1px solid #BBD0EA; }
QFrame#scheme2CostSidebar QDoubleSpinBox { background:#FFFFFF; color:#2A3541; border:1px solid #BBD0EA; border-radius:7px; padding:1px 22px 1px 7px; min-height:28px; font-size:13px; font-weight:400; }
QFrame#scheme2CostSidebar QDoubleSpinBox:focus { border-color:#2563EB; }
QFrame#scheme2CompactCoefficients { background:#DCE8F7; border:1px solid #BBD0EA; border-radius:7px; }
QFrame#scheme2CostBody { background:#FFFFFF; }
QFrame#scheme2QuoteCompanyField { background:transparent; border:0; }
QFrame#scheme2UndoBar { background:#E6F1FB; border:1px solid #85B7EB; border-radius:7px; }
QLabel#scheme2EmptyState { color:#8A8A86; background:#FFFFFF; font-size:13px; }
QLabel#scheme2PageTitle { font-size:16px; font-weight:600; color:#1F3A6A; }
QLabel#scheme2DialogTitle { font-size:13px; font-weight:600; color:#1F3A6A; padding-bottom:4px; }
QDialog#scheme2AttachmentEditorDialog { background:transparent; }
QFrame#scheme2AttachmentEditorShell { background:#FFFFFF; border:1px solid #B8BEC7; border-radius:14px; }
QFrame#scheme2AttachmentEditorHeader { background:#F6F7F9; border:0; border-bottom:1px solid #D7DCE3; min-height:40px; }
QLabel#scheme2AttachmentEditorTitle { color:#1F3A6A; font-size:13px; font-weight:600; border:0; }
QToolButton#scheme2AttachmentEditorClose { color:#8A8A86; background:transparent; border:0; font-size:18px; }
QToolButton#scheme2AttachmentEditorClose:hover { color:#1C1C1E; }
QTableWidget#scheme2AttachmentEditorTable { background:#FFFFFF; alternate-background-color:#FFFFFF; border:0; gridline-color:transparent; outline:0; }
QTableWidget#scheme2AttachmentEditorTable::item { padding:6px 8px; border:0; border-bottom:1px solid #D7DCE3; }
QTableWidget#scheme2AttachmentEditorTable::item:selected { color:#1C1C1E; background:#E6F1FB; }
QTableWidget#scheme2AttachmentEditorTable { font-size:12px; color:#2A3541; }
QTableWidget#scheme2AttachmentEditorTable QHeaderView::section { background:#2563EB; color:#FFFFFF; border:0; border-bottom:1px solid #D7DCE3; padding:7px 8px; font-size:12px; font-weight:600; }
QSpinBox#scheme2AttachmentEditorQuantity { background:transparent; border:0; border-bottom:1px solid #5F5E5A; border-radius:0; padding:2px; min-height:24px; }
QDoubleSpinBox#scheme2AttachmentEditorAmount { color:#1C1C1E; background:transparent; border:0; border-bottom:1px solid #5F5E5A; border-radius:0; padding:2px 15px 2px 2px; min-height:24px; }
QDoubleSpinBox#scheme2AttachmentEditorAmount:focus { border-bottom:2px solid #2563EB; }
QDoubleSpinBox#scheme2AttachmentEditorAmount[pending="true"] { color:#C62828; background:#FAEEDA; }
QComboBox#scheme2AttachmentModelCombo { background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; border-radius:6px; padding:4px 24px 4px 8px; min-height:24px; }
QComboBox#scheme2AttachmentModelCombo:focus, QComboBox#scheme2AttachmentModelCombo:on { border-color:#2563EB; }
QComboBox#scheme2AttachmentModelCombo::drop-down { border:0; width:24px; }
QAbstractItemView#scheme2AttachmentModelDropdown { background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; outline:0; selection-background-color:#F5F9FF; selection-color:#1C1C1E; }
QAbstractItemView#scheme2AttachmentModelDropdown::item { min-height:34px; padding:0 8px; }
QDialog#scheme2DiscountDialog { background:transparent; }
QFrame#scheme2DiscountShell { background:#FFFFFF; border:1px solid #B8BEC7; border-radius:14px; }
QFrame#scheme2DiscountHeader { background:#F6F7F9; border:0; border-bottom:1px solid #D7DCE3; }
QToolButton#scheme2DiscountClose { background:transparent; color:#8A8A86; border:0; font-size:18px; }
QToolButton#scheme2DiscountClose:hover { color:#1C1C1E; }
QLabel#scheme2DiscountBase, QLabel#scheme2DiscountPreviewValue { font-weight:600; }
QLabel#scheme2DiscountHint { color:#2A3541; font-size:13px; }
QDoubleSpinBox#scheme2DiscountInput { min-height:30px; border:1px solid #D7DCE3; border-radius:9px; padding:5px 10px; }
QDoubleSpinBox#scheme2DiscountInput:focus { border:1px solid #2563EB; }
QFrame#scheme2DiscountPreview { min-height:36px; color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:8px; }
QFrame#scheme2DiscountPreview QLabel { color:#185FA5; }
QPushButton#scheme2DiscountCancel { color:#5F5E5A; background:#FFFFFF; border:1px solid #D7DCE3; border-radius:7px; padding:0 16px; }
QLabel#scheme2SidebarTitle { font-size:13px; font-weight:600; color:#1F3A6A; background:transparent; border:0; padding:0; }
QLabel#scheme2FieldLabel, QLabel#scheme2SidebarHint { font-size:12px; font-weight:400; color:#3F5A82; }
QLabel#scheme2Hint { color:#2A3541; font-size:13px; }
QLabel#scheme2CompletionPill { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:12px; padding:4px 10px; font-size:10px; }
QLabel#scheme2QuotedBadge { color:#B42318; background:#FEE4E2; border:1px solid #FDA29B; border-radius:10px; padding:3px 9px; font-weight:600; }
QLabel#scheme2RecognitionStatus { color:#3B6D11; }
QPushButton#scheme2PrimaryAction { color:#FFFFFF; background:#2563EB; border:1px solid #2563EB; border-radius:7px; padding:0 16px; font-weight:500; }
QPushButton#scheme2PrimaryAction:hover { background:#1D4ED8; }
QPushButton#scheme2PrimaryAction:disabled { background:#AFC7E8; border-color:#AFC7E8; }
QPushButton#scheme2PrimaryGhost, QPushButton#scheme2CollapseButton, QPushButton#scheme2ExpandButton { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:6px; padding:0 10px; }
QFrame#scheme2RecognitionFooter { background:#FFFFFF; border-top:1px solid rgba(0,0,0,.12); }
QTableWidget#summaryTable, QTableWidget#scheme2DetailTable { background:#FFFFFF; color:#2A3541; alternate-background-color:#F6F7F9; border:1px solid rgba(0,0,0,.12); border-radius:8px; gridline-color:rgba(0,0,0,.12); font-size:12px; font-weight:400; }
QTableWidget#summaryTable::item:selected, QTableWidget#scheme2DetailTable::item:selected { background:#E6F1FB; color:#1C1C1E; }
QTableWidget#summaryTable::item:hover { background:#F5F9FF; }
QTableWidget#scheme2DetailTable { alternate-background-color:#F6F7F9; }
QTableWidget#scheme2DetailTable::item { padding:5px 7px; }
QLabel#scheme2DetailMeta { color:#8A8A86; font-size:12px; }
QDoubleSpinBox#scheme2DetailFactor { background:transparent; border:0; border-bottom:1px solid #185FA5; border-radius:0; padding:2px 1px; min-height:24px; }
QDoubleSpinBox#scheme2DetailFactor:focus { border-bottom:2px solid #2563EB; }
QHeaderView::section { background:#2563EB; color:#FFFFFF; border:0; border-bottom:1px solid rgba(0,0,0,.12); padding:7px 8px; font-size:12px; font-weight:600; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#FFFFFF; color:#2A3541; border:1px solid rgba(0,0,0,.18); border-radius:7px; padding:5px 7px; min-height:22px; font-size:13px; font-weight:400; }
QComboBox[scheme2Multiline="true"] { padding:4px 5px; }
QAbstractItemView#scheme2CompanyDropdown { min-width:320px; background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; outline:0; padding:0; }
QAbstractItemView#scheme2CompanyDropdown::item { min-height:40px; padding:0; border:0; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:#2563EB; }
QProgressBar#scheme2AddProgress { background:#EEF0F3; border:0; border-radius:5px; text-align:center; color:#1F3A6A; min-height:20px; }
QProgressBar#scheme2AddProgress::chunk { background:#97C459; border-radius:5px; }
QProgressBar#scheme2AddProgress[failed="true"]::chunk { background:#E24A4A; }
"""
    window.setStyleSheet(_increase_font_sizes(window.styleSheet() + scheme_style))
    tabular_tag = QFont.Tag.fromString("tnum")
    for control_type in (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget):
        for control in window.findChildren(control_type):
            control_font = control.font()
            control_font.setFeature(tabular_tag, 1)
            control.setFont(control_font)


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
                material_code = str(payload.get("material_code") or "").strip().upper()
                coating = (
                    owner.coating_combo.currentText().strip()
                    if isinstance(getattr(owner, "coating_combo", None), QComboBox)
                    else str(payload.get("coating_type") or "").strip()
                )
                updates = {
                    "galvanized_sheet_unit_price_override": values["galvanized_price"],
                    "carbon_steel_unit_price_override": values["carbon_price"],
                    "surface_treatment_unit_price_override": (
                        values["surface_price"]
                        if getattr(owner, "_scheme2_active_settings", None) is not None
                        else _surface_default_price(coating)
                    ),
                }
                if material_code in STAINLESS_DEFAULT_PRICES:
                    active = getattr(owner, "_scheme2_active_settings", None)
                    updates["material_unit_price_override"] = (
                        values["stainless_price"] if active is not None
                        else STAINLESS_DEFAULT_PRICES[material_code]
                    )
                else:
                    updates["material_unit_price_override"] = values["carbon_price"]
                pages = getattr(owner, "_scheme2_drawing_pages", [])
                page_index = int(getattr(owner, "_scheme2_drawing_page_index", -1))
                if 0 <= page_index < len(pages):
                    page = pages[page_index]
                    updates["drawing_context"] = {
                        "source_name": Path(page["source_path"]).name,
                        "page_number": int(page["page_index"]) + 1,
                        "page_count": int(page["page_count"]),
                    }
                payload.update(updates)
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
    original_confirm_and_export = cls.confirm_and_export
    original_company_catalog_loaded = getattr(cls, "company_catalog_loaded", None)

    def init(window, *args, **kwargs):
        window._scheme2_add_after_calculate = False
        window._scheme2_edit_item = None
        window._scheme2_detail_item = None
        window._scheme2_active_settings = None
        window._scheme2_attachments_manual = False
        window._scheme2_drawing_pages = []
        window._scheme2_drawing_page_index = -1
        window._scheme2_page_worker = None
        window._scheme2_recognition_key = None
        window._scheme2_recognition_tools = namespace["DrawingRecognitionTools"]
        window._scheme2_candidate_builder = namespace.get("build_review_candidates")
        window._scheme2_api_worker_class = namespace.get("ApiWorker")
        window._scheme2_accept_paths = namespace["ImportDropZone"].accepted_paths
        window.scheme2_defaults = {
            "galvanized_price": 4.55, "carbon_price": 4.20, "waste_factor": 1.20,
            "stainless_price": STAINLESS_DEFAULT_PRICES["SUS304"],
            "labor_discount": 1.0, "surface_price": 26.0,
        }
        original_init(window, *args, **kwargs)
        window.setWindowTitle(WORKBENCH_WINDOW_TITLE)
        window._scheme2_add_started_at = None
        window._scheme2_add_elapsed_timer = QTimer(window)
        window._scheme2_add_elapsed_timer.setInterval(100)
        window._scheme2_add_elapsed_timer.timeout.connect(lambda: _refresh_add_progress_display(window))
        # The reference explicitly supports the <900 logical-pixel stacked
        # layout; the recovered client used a wider fixed minimum.
        window.setMinimumSize(1024, 700)
        window.statusBar().hide()
        old_cost_page = window.stack.widget(COST_ROUTE)
        window.stack.removeWidget(old_cost_page)
        old_cost_page.setParent(window)
        old_cost_page.hide()
        window._scheme2_retired_pages = [old_cost_page]
        window.stack.insertWidget(COST_ROUTE, _build_cost_page(window))
        old_quote_page = window.stack.widget(QUOTE_ROUTE)
        window.stack.removeWidget(old_quote_page)
        old_quote_page.setParent(window)
        old_quote_page.hide()
        window._scheme2_retired_pages.append(old_quote_page)
        window.stack.insertWidget(QUOTE_ROUTE, _build_quote_page(window))
        detail = _build_detail_page(window)
        while window.stack.count() < DETAIL_ROUTE:
            window.stack.addWidget(QWidget())
        window.stack.insertWidget(DETAIL_ROUTE, detail)
        _configure_navigation(window)
        _configure_option_page(window, namespace)
        window._scheme2_loading_order = False
        window._scheme2_order_save_worker = None
        window._scheme2_order_load_worker = None
        window._scheme2_order_save_timer = QTimer(window)
        window._scheme2_order_save_timer.setSingleShot(True)
        window._scheme2_order_save_timer.setInterval(600)
        window._scheme2_order_save_timer.timeout.connect(lambda: _save_order_workspace(window))
        for control in (
            window.scheme2_name_edit, window.quote_spec_edit, window.product_combo,
            window.quantity_spin, window.cabinet_body_thickness_spin, window.material_combo,
            window.coating_combo, window.scheme2_color_combo, window.single_door_combo,
            window.double_door_combo, window.scheme2_company,
        ):
            signal = (getattr(control, "textChanged", None)
                      or getattr(control, "currentTextChanged", None)
                      or getattr(control, "valueChanged", None))
            if signal is not None:
                signal.connect(lambda *_: _schedule_order_workspace_save(window))
        # Preserve route indices while removing the retired recognition and
        # cabinet-review pages from the live interface.  Their nonvisual
        # controller widgets are still used by quote/history payload builders,
        # so keep the page objects alive instead of deleting their children.
        for route in (0, 4):
            retired = window.stack.widget(route)
            placeholder = QWidget()
            window.stack.removeWidget(retired)
            retired.setParent(window)
            retired.hide()
            window._scheme2_retired_pages.append(retired)
            window.stack.insertWidget(route, placeholder)
        preview = getattr(window, "quote_drawing_preview", None)
        if preview is not None:
            try:
                preview.return_to_recognition.disconnect()
            except RuntimeError:
                pass
            preview.return_to_recognition.connect(lambda: window.show_section(OPTION_ROUTE))
        _install_shortcuts(window)
        _apply_palette(window)
        for region in (
            getattr(window, "scheme2_drawing_widget", None),
            getattr(window, "scheme2_cost_page", None),
            getattr(window, "scheme2_quote_page", None),
        ):
            _increase_region_font_sizes(region, 2)
        window.scheme2_company.setFixedHeight(COMPANY_COMBO_HEIGHT)
        window._scheme2_scale_reference = QSize(window.width(), window.height())
        window._scheme2_scale_styles = [
            (widget, widget.styleSheet())
            for widget in (window, *window.findChildren(QWidget))
            if widget.styleSheet()
        ]
        window._scheme2_scale = 0.0
        window.refresh_summary()
        window.show_section(OPTION_ROUTE)
        _set_dirty(window, False)
        _apply_responsive(window)

    def resize(window, event):
        original_resize(window, event)
        QTimer.singleShot(0, lambda: _apply_responsive(window))

    def confirm_and_export(window):
        _sync_export_company(window)
        if not getattr(window, "_scheme2_export_validation_passed", False):
            _start_export_validation(window)
            return
        window._scheme2_export_validation_passed = False
        had_override = "validate_export_environment" in window.__dict__
        previous = window.__dict__.get("validate_export_environment")
        window.validate_export_environment = MethodType(lambda _self: None, window)
        try:
            return original_confirm_and_export(window)
        finally:
            if had_override:
                window.validate_export_environment = previous
            else:
                del window.validate_export_environment

    def close(window, event):
        worker = getattr(window, "_scheme2_page_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            event.ignore()
            return
        if (window.scheme2_order_number.text().strip()
                and not getattr(window, "_scheme2_close_after_workspace_save", False)):
            timer = getattr(window, "_scheme2_order_save_timer", None)
            if isinstance(timer, QTimer):
                timer.stop()
            window._scheme2_close_after_workspace_save = True
            event.ignore()
            _save_order_workspace(window, lambda: window.close())
            return
        if getattr(window, "_scheme2_dirty", False) and window.isVisible():
            if not _confirm_discard_unsaved(window):
                window._scheme2_close_after_workspace_save = False
                event.ignore()
                return
        original_close(window, event)

    def section(window, index):
        if index == 0:
            index = OPTION_ROUTE
        previous_index = window.stack.currentIndex()
        if index == COST_ROUTE:
            window.refresh_summary()
        elif index == QUOTE_ROUTE:
            _refresh_quote_page(window)
        result = original_section(window, index)
        if index == OPTION_ROUTE and hasattr(window, "quote_right_stack"):
            window.quote_right_stack.setCurrentIndex(0)
        if index == OPTION_ROUTE:
            QTimer.singleShot(0, lambda: _restore_scheme2_drawing_on_option_page(window))
        _sync_completion(window)
        _apply_responsive(window)
        QTimer.singleShot(0, lambda: _apply_responsive(window))
        if index == OPTION_ROUTE and previous_index == COST_ROUTE:
            if getattr(window, "_scheme2_clear_attachments_on_return", False):
                window._scheme2_clear_attachments_on_return = False
                QTimer.singleShot(0, lambda: _clear_scheme2_attachments(window))
        _schedule_order_workspace_save(window)
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
        _refresh_quote_page(window)
        _sync_completion(window)
        _schedule_order_workspace_save(window)

    def apply_drawing(window, item):
        _confirm_scheme2_recognition(item)
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
        _apply_recognized_attachments(window, item)
        _sync_completion(window)
        return result

    def add(window, *args, **kwargs):
        _synchronize_active_drawing_confirmation(window)
        result = original_add(window, *args, **kwargs)
        _sync_completion(window)
        return result

    def company_catalog_loaded(window, *args, **kwargs):
        result = original_company_catalog_loaded(window, *args, **kwargs)
        _restore_custom_companies(getattr(window, "scheme2_company", None))
        return result

    cls.__init__ = init
    cls.resizeEvent = resize
    cls.confirm_and_export = confirm_and_export
    cls.closeEvent = close
    cls.show_section = section
    cls.show_result = show_result
    cls.show_error = show_error
    cls.refresh_summary = refresh
    cls._apply_confirmed_drawing_to_quote = apply_drawing
    cls.add_current_to_summary = add
    if callable(original_company_catalog_loaded):
        cls.company_catalog_loaded = company_catalog_loaded
