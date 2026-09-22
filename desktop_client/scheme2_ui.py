"""Install the approved ``界面方案2`` presentation over the recovered V3 core.

The overlay deliberately keeps the core quote, attachment, confirmation and
export objects alive.  It changes their presentation and stores new row-local
editing state inside the existing draft-item JSON snapshots.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
from types import MethodType

from PySide6.QtCore import QDate, QEvent, QObject, QPoint, QSettings, QSignalBlocker, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeySequence, QPainter, QPen, QPolygon, QShortcut
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pypdf import PdfReader, PdfWriter


OPTION_ROUTE = 1
COST_ROUTE = 3
DETAIL_ROUTE = 5
NAV_EXPANDED_WIDTH = 128
COST_SIDEBAR_WIDTH = 100
COMPANY_COMBO_HEIGHT = 96
HEADERS = (
    "序号", "名称", "产品", "尺寸", "材料成本", "辅材成本", "人工成本",
    "附件成本", "喷涂费用", "管理费用", "运费", "数量", "成本单价",
    "面价", "已选附件", "成本明细",
)
MONEY_COLUMNS = frozenset(range(4, 14))
EDITABLE_COLUMNS = frozenset((10, 11))
ROLE_ROW = int(Qt.ItemDataRole.UserRole)
GALVANIZED_MATERIAL_CODES = frozenset(("SGCC", "DX51D", "GI"))


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
                    if not 0 <= page_index < len(reader.pages):
                        raise ValueError("图纸页码无效")
                    writer = PdfWriter()
                    writer.add_page(reader.pages[page_index])
                    recognition_path = str(Path(folder) / f"page-{page_index + 1}.pdf")
                    with open(recognition_path, "wb") as stream:
                        writer.write(stream)
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


def _material_price_caption(material_code):
    code = str(material_code or "").strip().upper()
    return {
        "SUS304": "SUS304价格",
        "SUS316": "SUS316价格",
        "SECC": "碳钢价格",
    }.get(code, "当前材质价格")


def _reprice_material_details(item, state):
    formula = _formula(item)
    groups = formula.get("material_details")
    if not isinstance(groups, list) or not groups:
        return False
    selected_code = str(item.get("material_code") or "").strip().upper()
    current_price = _number(state.get("carbon_price"))
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
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("名称", "尺寸 / 规格", "数量", "单价", "快速金额", "附件成本"))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self.edit_missing_dimensions)
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
        self._render_amounts(row, source)

    @staticmethod
    def _pending_dimensions(source):
        return [str(name) for name in source.get("pending_manual_dimensions", []) if str(name).strip()]

    def _render_amounts(self, row, source):
        pending = bool(self._pending_dimensions(source))
        quick_amount = 0.0 if pending else _number(source.get("quick_amount"), _attachment_amount(source))
        formula_amount = 0.0 if pending else _number(source.get("formula_amount"), 0)
        for column, amount in ((4, quick_amount), (5, formula_amount)):
            cell = QTableWidgetItem(_money(amount))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if pending:
                cell.setData(Qt.ItemDataRole.ForegroundRole, QColor("#C62828"))
                cell.setToolTip("尺寸不完整，当前按 0 元计；点击“尺寸 / 规格”补充")
            self.table.setItem(row, column, cell)
        specification = self.table.item(row, 1)
        if pending and specification is not None:
            specification.setText("点击补充：" + "、".join(self._pending_dimensions(source)))
            specification.setData(Qt.ItemDataRole.ForegroundRole, QColor("#C62828"))

    def edit_missing_dimensions(self, row, column):
        if column != 1 or not 0 <= row < self.table.rowCount():
            return
        source_item = self.table.item(row, 0)
        source = dict(source_item.data(ROLE_ROW) or {}) if source_item is not None else {}
        missing = self._pending_dimensions(source)
        if not missing:
            return
        editor = QDialog(self)
        editor.setWindowTitle(f"{source.get('item_name', '附件')} · 补充尺寸")
        layout = QVBoxLayout(editor)
        form = QFormLayout()
        fields = {}
        manual = source.get("manual_inputs") if isinstance(source.get("manual_inputs"), dict) else {}
        for name in missing:
            field = QLineEdit(str(manual.get(name) or ""))
            field.setPlaceholderText("请输入正数（mm）")
            fields[name] = field
            form.addRow(name, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(editor.accept)
        buttons.rejected.connect(editor.reject)
        layout.addWidget(buttons)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        values = {}
        try:
            for name, field in fields.items():
                value = float(field.text().strip())
                if value <= 0:
                    raise ValueError
                values[name] = value
        except ValueError:
            QMessageBox.warning(self, "尺寸无效", "缺失尺寸必须填写大于 0 的数字。")
            return
        source["manual_inputs"] = {**manual, **values}
        source_item.setData(ROLE_ROW, source)
        specification = self.table.item(row, 1)
        if specification is not None:
            specification.setText("；".join(f"{name}={value:g} mm" for name, value in values.items()))
            specification.setData(Qt.ItemDataRole.ForegroundRole, QColor("#B45309"))
        for column_index in (4, 5):
            self.table.item(row, column_index).setText("计算中…")
            self.table.item(row, column_index).setData(Qt.ItemDataRole.ForegroundRole, QColor("#B45309"))
        reprice = getattr(self.window, "recalculate_draft_attachment", None)
        if not callable(reprice):
            QMessageBox.warning(self, "附件计算失败", "附件数据库计算功能不可用。")
            return

        def succeeded(calculated):
            source_item.setData(ROLE_ROW, dict(calculated))
            if specification is not None:
                specification.setData(Qt.ItemDataRole.ForegroundRole, QColor("#1C1C1E"))
            self._render_amounts(row, calculated)

        def failed(message):
            for column_index in (4, 5):
                self.table.item(row, column_index).setText(_money(0))
                self.table.item(row, column_index).setData(Qt.ItemDataRole.ForegroundRole, QColor("#C62828"))
            QMessageBox.warning(self, "附件计算失败", str(message))

        reprice(self.item, source, succeeded, failed)

    def accept(self):
        old_formula_total = _number(_formula(self.item).get("attachment_fee"), 0)
        old_quick_total = _number(_quick(self.item).get("attachment_fee"), _attachment_total(self.item))
        rows = []
        for row in range(self.table.rowCount()):
            data = self.table.item(row, 0).data(ROLE_ROW) or {}
            data = dict(data)
            data["item_name"] = self.table.item(row, 0).text().strip() or "自定义附件"
            specification_editor = self.table.cellWidget(row, 1)
            specification = (
                specification_editor.currentText().strip()
                if isinstance(specification_editor, QComboBox)
                else self.table.item(row, 1).text().strip()
            )
            data["specification"] = specification
            data["quantity"] = self.table.cellWidget(row, 2).value()
            data["unit_price_override"] = self.table.cellWidget(row, 3).value()
            data["matched_price"] = data["unit_price_override"]
            data["quick_amount_override"] = data["quantity"] * data["unit_price_override"]
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
    def __init__(self, window, item):
        super().__init__(window)
        self.window = window
        self.item = item
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
        title = QLabel("面价折扣")
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
        self.item["quick_discount"] = self.discount.value()
        self.window.refresh_summary()
        super().accept()


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
        product = str(item.get("product_code") or item.get("product_name") or "—")
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
                spin.setRange(.01, 10)
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
        if watched.isEditable() and watched.lineEdit() is not None and watched.lineEdit().hasFocus():
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


class _SchemeComboItemDelegate(QStyledItemDelegate):
    def __init__(self, combo, separator_index=-1):
        super().__init__(combo.view())
        self.combo = combo
        self.separator_index = separator_index
        self.setObjectName("scheme2DropdownItemDelegate")

    def sizeHint(self, option, index):
        return QSize(max(120, option.rect.width()), 40)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        chosen = index.row() == self.combo.currentIndex() and self.combo.currentIndex() >= 0
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
        painter.setPen(QColor("#185FA5" if chosen or custom else "#1C1C1E"))
        painter.drawText(
            rect.adjusted(14, 0, -36, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        if chosen:
            center_y = rect.center().y()
            right = rect.right() - 14
            painter.setPen(QPen(QColor("#2563EB"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(QPoint(right - 8, center_y), QPoint(right - 5, center_y + 4))
            painter.drawLine(QPoint(right - 5, center_y + 4), QPoint(right + 1, center_y - 5))
        painter.restore()


class _DropdownPopupStateFilter(QObject):
    def __init__(self, combo, shell):
        super().__init__(combo)
        self.combo = combo
        self.shell = shell

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            opened = event.type() == QEvent.Type.Show
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
    company.view().setWordWrap(True)
    company.view().setTextElideMode(Qt.TextElideMode.ElideNone)
    company._scheme2_multiline_filter = _MultilineComboPaintFilter(company)
    company.installEventFilter(company._scheme2_multiline_filter)
    if company.lineEdit() is not None:
        editor = company.lineEdit()
        editor.setReadOnly(False)
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        editor.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        editor.setStyleSheet(
            "QLineEdit{background:transparent;border:0;color:transparent;"
            "selection-color:transparent;selection-background-color:transparent;}"
            "QLineEdit:focus{color:#1C1C1E;selection-color:#FFFFFF;selection-background-color:#2563EB;}"
        )
        editor.editingFinished.connect(lambda combo=company: _remember_custom_company(combo))
    _restore_custom_companies(company)
    company.setToolTip(company.currentText())
    company.currentTextChanged.connect(company.setToolTip)
    window.scheme2_company = company
    layout.addWidget(_field("下单公司", company))
    controls = {
        "galvanized_price": ("镀锌板价格", _price_spin(4.55)),
        "carbon_price": ("当前材质价格", _price_spin(4.20)),
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
        field = _field(label, control)
        if key == "carbon_price":
            window.scheme2_material_price_label = field.findChild(QLabel, "scheme2FieldLabel")
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
        _replace_component(item, "material_cost", base * value / max(original, .01))
    elif key == "labor_discount":
        base = _number(item.get("formula_base", formula).get("labor_cost", formula.get("labor_cost")))
        item["labor_multiplier"] = value
        _replace_component(item, "labor_cost", base * value)
        _replace_component(item, "management_fee", base * value * .13)
    elif key in ("carbon_price", "galvanized_price"):
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
        ("galvanized_price", "镀锌板价格"), ("carbon_price", "当前材质价格"),
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
    back = QPushButton("返回")
    back.setObjectName("scheme2CostReturn")
    secondary_size = delete.sizeHint()
    for button in (delete, up, down, back):
        button.setFixedSize(secondary_size)
    export = QPushButton("导出报价单")
    export.setObjectName("scheme2PrimaryAction")
    action_buttons = (delete, up, down, back, export)
    for column, button in enumerate(action_buttons[:3]):
        actions.addWidget(button, 0, column)
    actions.setColumnStretch(3, 1)
    actions.addWidget(back, 0, 4)
    actions.addWidget(export, 0, 5)
    body_layout.addWidget(action_widget)
    outer.addWidget(body, 1)
    delete.clicked.connect(lambda: _delete_selected(window))
    up.clicked.connect(lambda: window.move_selected_item(-1))
    down.clicked.connect(lambda: window.move_selected_item(1))
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
    window.scheme2_cost_return = back
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
        for column, button in enumerate(buttons[:3]):
            grid.addWidget(button, 0, column)
        grid.addWidget(buttons[3], 1, 1)
        grid.addWidget(buttons[4], 1, 2)
        grid.setColumnStretch(1, 1)
    else:
        for column, button in enumerate(buttons[:3]):
            grid.addWidget(button, 0, column)
        grid.setColumnStretch(3, 1)
        grid.addWidget(buttons[3], 0, 4)
        grid.addWidget(buttons[4], 0, 5)


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
    caption = _material_price_caption(item.get("material_code") if isinstance(item, dict) else None)
    if hasattr(window, "scheme2_material_price_label"):
        window.scheme2_material_price_label.setText(caption)
    if hasattr(window, "scheme2_compact_key"):
        material_index = window.scheme2_compact_key.findData("carbon_price")
        if material_index >= 0:
            window.scheme2_compact_key.setItemText(material_index, caption)
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
        button.setFixedHeight(36)
        try:
            button.clicked.disconnect()
        except RuntimeError:
            pass
        button.clicked.connect(lambda _checked=False, value=route: window.show_section(value))
    window.nav_buttons = [wanted[OPTION_ROUTE], wanted[COST_ROUTE]]
    window.nav_routes = ((OPTION_ROUTE, "选项配置", "", None), (COST_ROUTE, "成本计算", "", None))
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
    window.scheme2_manual_fields = set(state.get("manual_fields") or set())
    for key in ("dimensions", "material", "coating", "color"):
        if key in window.scheme2_manual_fields:
            _mark_manual(window, key)
        else:
            _mark_ai(window, key)
    refresh = getattr(window, "update_attachment_view", None)
    if callable(refresh):
        refresh()
    summary = getattr(window, "scheme2_attachment_summary", None)
    if isinstance(summary, QLabel):
        names = [str(item.get("item_name") or item.get("name") or "附件") for item in window.attachments]
        summary.setText("未选择附件" if not names else f"已选择 {len(names)} 项：" + "、".join(names[:3]))
    _set_dirty(window, bool(state.get("dirty")))


def _scheme2_page_entry(window, key):
    return next((entry for entry in getattr(window, "_scheme2_drawing_pages", []) if entry["key"] == key), None)


def _save_current_scheme2_page(window):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if 0 <= index < len(pages) and pages[index].get("item") is not None:
        pages[index]["state"] = _capture_scheme2_page_state(window)


def _sync_scheme2_page_navigation(window):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    busy = bool(getattr(window, "_scheme2_page_worker", None))
    preview = getattr(window, "quote_drawing_preview", None)
    if preview is not None:
        preview.previous.setEnabled(not busy and index > 0)
        preview.next.setEnabled(not busy and 0 <= index < len(pages) - 1)
        preview.counter.setText(f"{index + 1} / {len(pages)}" if 0 <= index < len(pages) else "0 / 0")
    button = getattr(window, "_scheme2_import_button", None)
    if isinstance(button, QPushButton):
        button.setEnabled(not busy)
    completion = getattr(window, "scheme2_completion", None)
    if isinstance(completion, QLabel) and pages:
        recognized = sum(1 for entry in pages if entry.get("item") is not None)
        completion.setText(f"已识别 {recognized} / {len(pages)}")


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
    if 0 <= index < len(pages) and pages[index]["key"] == key:
        window.active_drawing = entry["item"]
        window._quote_drawing = entry["item"]
        window.scheme2_manual_fields.clear()
        window._apply_confirmed_drawing_to_quote(entry["item"])
        entry["state"] = _capture_scheme2_page_state(window)
        _set_dirty(window, False)
        window.scheme2_recognition_status.setText(
            f"已识别第 {entry['page_index'] + 1} 页：尺寸 / 材质 / 表面处理 / 颜色"
        )
    _sync_scheme2_page_navigation(window)


def _fail_scheme2_page_recognition(window, key, message):
    entry = _scheme2_page_entry(window, key)
    if entry is not None:
        entry["error"] = str(message)
    status = getattr(window, "scheme2_recognition_status", None)
    if isinstance(status, QLabel):
        status.setText(f"当前页识别失败：{message}")
    _sync_scheme2_page_navigation(window)


def _recognize_scheme2_page(window, entry):
    if entry.get("item") is not None or getattr(window, "_scheme2_page_worker", None) is not None:
        return
    status = getattr(window, "scheme2_recognition_status", None)
    if isinstance(status, QLabel):
        status.setText(f"正在识别第 {entry['page_index'] + 1} / {entry['page_count']} 页…")
    worker = _Scheme2PageRecognitionWorker(window._scheme2_recognition_tools, entry, window)
    window._scheme2_page_worker = worker
    worker.succeeded.connect(lambda key, item: _finish_scheme2_page_recognition(window, key, item))
    worker.failed.connect(lambda key, message: _fail_scheme2_page_recognition(window, key, message))

    def finished():
        if getattr(window, "_scheme2_page_worker", None) is worker:
            window._scheme2_page_worker = None
        worker.deleteLater()
        _sync_scheme2_page_navigation(window)

    worker.finished.connect(finished)
    _sync_scheme2_page_navigation(window)
    worker.start()


def _activate_scheme2_page(window, index):
    pages = getattr(window, "_scheme2_drawing_pages", [])
    if getattr(window, "_scheme2_page_worker", None) is not None or not 0 <= index < len(pages):
        return
    _save_current_scheme2_page(window)
    window._scheme2_drawing_page_index = index
    entry = pages[index]
    _show_scheme2_source_page(window, entry)
    if entry.get("state") is not None:
        window.active_drawing = entry.get("item")
        window._quote_drawing = entry.get("item")
        _restore_scheme2_page_state(window, entry["state"])
        window.scheme2_recognition_status.setText(
            f"已恢复第 {entry['page_index'] + 1} 页的选项配置"
        )
    else:
        window.scheme2_manual_fields.clear()
        _set_dirty(window, False)
        _recognize_scheme2_page(window, entry)
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
    known = {entry["key"] for entry in pages}
    first_new = len(pages)
    for raw_path in accepted:
        source = str(Path(raw_path).resolve())
        try:
            page_count = len(PdfReader(source).pages) if Path(source).suffix.lower() == ".pdf" else 1
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
    if len(pages) > first_new:
        _activate_scheme2_page(window, first_new)
    else:
        _sync_scheme2_page_navigation(window)


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
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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
                selected_index = next((combo.findText(name) for name in options if is_selected(category, name)), 0)
                category_check.setChecked(selected_index > 0)
                combo.setCurrentIndex(max(0, selected_index))
                combo.setEnabled(category_check.isChecked())

                def toggle_category(enabled, selector=combo):
                    selector.setEnabled(enabled)
                    if not enabled:
                        selector.setCurrentIndex(0)

                def select_option(index, category_toggle=category_check):
                    if index <= 0:
                        category_toggle.setChecked(False)
                    elif not category_toggle.isChecked():
                        category_toggle.setChecked(True)

                category_check.toggled.connect(toggle_category)
                combo.activated.connect(select_option)
                self.category_checks[category] = category_check
                self.category_combos[category] = combo
                card_layout.addWidget(category_check)
                card_layout.addWidget(combo)
            cards.addWidget(card)
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
            name = combo.currentText().strip()
            if check.isChecked() and combo.currentIndex() > 0 and name:
                selected.append({
                    "item_name": name,
                    "name": name,
                    "category_level1": category,
                    "category_level2": name,
                    "attachment_category": category,
                    "quantity": 1,
                })
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
        summary = getattr(window, "scheme2_attachment_summary", None)
        if isinstance(summary, QLabel):
            names = [str(item.get("item_name") or item.get("name") or "附件") for item in window.attachments]
            summary.setText("未选择附件" if not names else f"已选择 {len(names)} 项：" + "、".join(names[:3]))
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
        summary = getattr(window, "scheme2_attachment_summary", None)
        if isinstance(summary, QLabel):
            names = [item["item_name"] for item in window.attachments]
            summary.setText("未选择附件" if not names else f"已选择 {len(names)} 项：" + "、".join(names[:3]))
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

    name_edit = QLineEdit()
    name_edit.setObjectName("scheme2NameInput")
    name_edit.setPlaceholderText("名称（默认取图纸文件名，可修改）")
    name_edit.hide()
    window.scheme2_name_edit = name_edit
    product = _detach(getattr(window, "product_combo", None))
    if product is not None:
        form.addWidget(_option_field(window, "产品", product))
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
        form.addWidget(_option_field(window, "数量", quantity))

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
        form.addWidget(_option_field(window, "箱体料厚", thickness))

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
        attachment_table.hide()
    selected_names = [
        str(item.get("item_name") or item.get("name") or "附件")
        for item in getattr(window, "attachments", []) if isinstance(item, dict)
    ]
    attachment_summary = QLabel(
        "未选择附件" if not selected_names
        else f"已选择 {len(selected_names)} 项：" + "、".join(selected_names[:3])
    )
    attachment_summary.setObjectName("scheme2AttachmentSummary")
    attachment_summary.setWordWrap(True)
    attachment_layout.addWidget(attachment_summary)
    window.scheme2_attachment_summary = attachment_summary
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
        original_update_tools = right.update_tools

        def update_page_tools(preview):
            original_update_tools()
            _sync_scheme2_page_navigation(window)

        right.update_tools = MethodType(update_page_tools, right)
        window._scheme2_import_button = manage
        window.scheme2_recognition_status = status
        window.scheme2_completion = counter
        window.scheme2_add_button = add
        window.scheme2_add_progress = progress
        window.scheme2_saved_status = saved
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


def _calculate_and_add(window):
    if getattr(window, "quote_calculation_in_progress", False):
        return
    pending_attachments = [
        item for item in getattr(window, "attachments", [])
        if isinstance(item, dict) and item.get("attachment_price_id") is None
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


def _set_add_progress(window, step, label, failed=False):
    progress = getattr(window, "scheme2_add_progress", None)
    if progress is None:
        return
    progress.show()
    progress.setValue(step)
    progress.setFormat(f"{step}/5 {label}")
    progress.setProperty("failed", failed)
    progress.setProperty("failureReason", str(label).removeprefix("失败：").strip() if failed else "")
    progress.setToolTip("点击查看完整失败原因" if failed else "")
    progress.setCursor(Qt.CursorShape.PointingHandCursor if failed else Qt.CursorShape.ArrowCursor)
    progress.setFocusPolicy(Qt.FocusPolicy.StrongFocus if failed else Qt.FocusPolicy.NoFocus)
    progress.style().unpolish(progress)
    progress.style().polish(progress)


def _show_add_failure_reason(window):
    progress = getattr(window, "scheme2_add_progress", None)
    reason = str(progress.property("failureReason") or "").strip() if progress is not None else ""
    if reason:
        QMessageBox.warning(window, "失败原因", reason)


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
    pages = getattr(window, "_scheme2_drawing_pages", [])
    page_index = int(getattr(window, "_scheme2_drawing_page_index", -1))
    if 0 <= page_index < len(pages):
        page = pages[page_index]
        item["source_path"] = page["source_path"]
        item["source_page_index"] = int(page["page_index"])
        item["source_page_number"] = int(page["page_index"]) + 1
        item["source_page_count"] = int(page["page_count"])
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
            form = min(420, max(340, (width - NAV_EXPANDED_WIDTH) // 3))
            splitter.widget(0).setMinimumWidth(form)
            splitter.widget(0).setMaximumWidth(420)
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
QScrollArea#scheme2OptionScroll QScrollBar:vertical { background:#EEF0F3; width:10px; margin:0; }
QScrollArea#scheme2OptionScroll QScrollBar::handle:vertical { background:#C3CBD6; border-radius:5px; min-height:36px; }
QScrollArea#scheme2OptionScroll QScrollBar::add-line:vertical, QScrollArea#scheme2OptionScroll QScrollBar::sub-line:vertical { height:0; }
QFrame#scheme2DrawingShell { background:#EEF0F3; border-left:1px solid rgba(0,0,0,.12); }
QFrame#scheme2DrawingHeader { background:#FFFFFF; border-bottom:1px solid rgba(0,0,0,.12); }
QLabel#scheme2SectionTitle { font-size:17px; font-weight:500; color:#1C1C1E; }
QLabel#scheme2OptionGroupTitle { font-size:17px; font-weight:400; color:#5F5E5A; margin-top:3px; }
QLabel#scheme2OptionLabel { font-size:15px; color:#777672; }
QFrame#scheme2OptionControlShell { min-height:52px; background:#FFFFFF; border:1px solid rgba(0,0,0,.16); border-radius:11px; }
QFrame#scheme2OptionControlShell[schemeDropdown="true"] { border-color:#B8BEC7; border-radius:6px; }
QFrame#scheme2OptionControlShell[schemeDropdown="true"][popupOpen="true"] { border-color:#2563EB; }
QFrame#scheme2OptionControlShell[provenanceState="ai"] { background:#F6F7F9; }
QFrame#scheme2OptionControlShell[provenanceState="manual"] { background:#FAEEDA; border-color:#EF9F27; }
QFrame#scheme2OptionControlShell QLineEdit, QFrame#scheme2OptionControlShell QComboBox, QFrame#scheme2OptionControlShell QSpinBox, QFrame#scheme2OptionControlShell QDoubleSpinBox { background:transparent; border:0; border-radius:0; padding:8px 14px; min-height:34px; font-size:15px; color:#1C1C1E; }
QFrame#scheme2OptionControlShell QComboBox::drop-down, QFrame#scheme2DoorValue QComboBox::drop-down { border:0; width:28px; }
QFrame#scheme2OptionControlShell QComboBox::down-arrow, QFrame#scheme2DoorValue QComboBox::down-arrow { width:8px; height:6px; }
QAbstractItemView#scheme2OptionDropdown { background:#FFFFFF; color:#1C1C1E; border:1px solid #B8BEC7; border-radius:6px; outline:0; padding:0; selection-background-color:#F5F9FF; selection-color:#1C1C1E; }
QAbstractItemView#scheme2OptionDropdown::item { min-height:40px; padding:0; border:0; }
QComboBox#scheme2ColorCombo[manualEntry="true"] QLineEdit#scheme2ColorManualInput { background:transparent; border:0; padding:8px 14px; }
QLabel#scheme2ProvenancePending { font-size:10px; color:#8A8A86; }
QLabel#scheme2ProvenanceAi { font-size:13px; color:#3B6D11; background:transparent; padding:1px 5px; }
QLabel#scheme2ProvenanceManual { font-family:"Segoe UI Symbol","Microsoft YaHei UI"; font-size:13px; color:#854F0B; background:#FFFFFF; border-radius:12px; padding:4px 10px; }
QFrame#scheme2GangedRow { background:transparent; border:0; }
QLabel#scheme2GangedLabel { color:#777672; font-size:15px; }
QFrame#scheme2GangedValue, QFrame#scheme2DoorValue { min-height:42px; background:#F6F7F9; border:1px solid rgba(0,0,0,.14); border-radius:10px; }
QFrame#scheme2GangedValue QLabel { font-size:15px; color:#1C1C1E; }
QLabel#scheme2GangedAi { color:#3B6D11; font-size:13px; }
QFrame#scheme2DoorValue QLabel { color:#5F5E5A; font-size:13px; }
QFrame#scheme2DoorValue QComboBox { background:transparent; border:0; min-height:30px; }
QFrame#scheme2AttachmentCard { background:#F6F7F9; border:1px solid rgba(0,0,0,.12); border-radius:11px; }
QLabel#scheme2AttachmentSummary { min-height:28px; background:#FFFFFF; color:#8A8A86; border:1px solid rgba(0,0,0,.12); border-radius:7px; padding:8px 11px; font-size:14px; }
QFrame#scheme2AttachmentHeader { background:#E6F1FB; border:0; border-bottom:1px solid #85B7EB; }
QLabel#scheme2AttachmentTitle { color:#185FA5; font-size:14px; font-weight:600; }
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
QPushButton#scheme2AttachmentCancel { color:#185FA5; background:#FFFFFF; border:1px solid #85B7EB; border-radius:7px; padding:8px 16px; }
QWidget#scheme2DrawingCanvas { background:#FFFFFF; border:1px solid rgba(0,0,0,.24); }
QFrame#navPanel { background:#DCE8F7; border:1px solid #BBD0EA; border-top-left-radius:13px; border-bottom-left-radius:13px; border-top-right-radius:0; border-bottom-right-radius:0; }
QFrame#scheme2NavBrand { background:transparent; border:0; }
QLabel#scheme2NavLogo { background:#2563EB; color:#FFFFFF; border-radius:6px; font-size:11px; font-weight:600; }
QLabel#scheme2NavTitle { color:#0B326B; font-size:16px; font-weight:600; }
QFrame#navPanel QPushButton { color:#0B326B; border:0; border-radius:8px; padding:7px 10px; text-align:left; font-size:14px; }
QFrame#navPanel QPushButton:checked { color:#FFFFFF; background:#2563EB; }
QPushButton#scheme2CollapseButton { color:#5A7AAB; background:transparent; border:0; padding:0; text-align:center; font-size:13px; }
QPushButton#scheme2CollapseButton:hover { background:#E6F1FB; }
QFrame#scheme2CostSidebar { background:#DCE8F7; border-right:1px solid #BBD0EA; }
QFrame#scheme2CompactCoefficients { background:#DCE8F7; border:1px solid #BBD0EA; border-radius:7px; }
QFrame#scheme2CostBody { background:#FFFFFF; }
QFrame#scheme2UndoBar { background:#E6F1FB; border:1px solid #85B7EB; border-radius:7px; }
QLabel#scheme2EmptyState { color:#8A8A86; background:#FFFFFF; font-size:13px; }
QLabel#scheme2PageTitle { font-size:18px; font-weight:600; color:#1C1C1E; }
QLabel#scheme2DialogTitle { font-size:15px; font-weight:600; color:#1C1C1E; padding-bottom:4px; }
QDialog#scheme2DiscountDialog { background:transparent; }
QFrame#scheme2DiscountShell { background:#FFFFFF; border:1px solid #B8BEC7; border-radius:14px; }
QFrame#scheme2DiscountHeader { background:#F6F7F9; border:0; border-bottom:1px solid #D7DCE3; }
QToolButton#scheme2DiscountClose { background:transparent; color:#8A8A86; border:0; font-size:18px; }
QToolButton#scheme2DiscountClose:hover { color:#1C1C1E; }
QLabel#scheme2DiscountBase, QLabel#scheme2DiscountPreviewValue { font-weight:600; }
QLabel#scheme2DiscountHint { color:#8A8A86; font-size:11px; }
QDoubleSpinBox#scheme2DiscountInput { min-height:30px; border:1px solid #D7DCE3; border-radius:9px; padding:5px 10px; }
QDoubleSpinBox#scheme2DiscountInput:focus { border:1px solid #2563EB; }
QFrame#scheme2DiscountPreview { min-height:36px; color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:8px; }
QFrame#scheme2DiscountPreview QLabel { color:#185FA5; }
QPushButton#scheme2DiscountCancel { color:#5F5E5A; background:#FFFFFF; border:1px solid #D7DCE3; border-radius:7px; padding:8px 16px; }
QLabel#scheme2SidebarTitle { font-size:14px; font-weight:600; color:#1F3A6A; }
QLabel#scheme2FieldLabel, QLabel#scheme2SidebarHint { font-size:10px; color:#5A7AAB; }
QLabel#scheme2Hint { color:#8A8A86; font-size:11px; }
QLabel#scheme2CompletionPill { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:12px; padding:4px 10px; }
QLabel#scheme2RecognitionStatus { color:#3B6D11; }
QPushButton#scheme2PrimaryAction { color:#FFFFFF; background:#2563EB; border:1px solid #2563EB; border-radius:7px; padding:8px 16px; font-weight:600; }
QPushButton#scheme2PrimaryAction:hover { background:#1D4ED8; }
QPushButton#scheme2PrimaryAction:disabled { background:#AFC7E8; border-color:#AFC7E8; }
QPushButton#scheme2PrimaryGhost, QPushButton#scheme2CollapseButton, QPushButton#scheme2ExpandButton { color:#185FA5; background:#E6F1FB; border:1px solid #85B7EB; border-radius:6px; padding:6px 10px; }
QFrame#scheme2RecognitionFooter { background:#FFFFFF; border-top:1px solid rgba(0,0,0,.12); }
QTableWidget#summaryTable, QTableWidget#scheme2DetailTable { background:#FFFFFF; alternate-background-color:#F6F7F9; border:1px solid rgba(0,0,0,.12); border-radius:8px; gridline-color:rgba(0,0,0,.12); }
QTableWidget#summaryTable::item:selected, QTableWidget#scheme2DetailTable::item:selected { background:#E6F1FB; color:#1C1C1E; }
QTableWidget#summaryTable::item:hover { background:#F5F9FF; }
QTableWidget#scheme2DetailTable { font-size:12px; alternate-background-color:#F6F7F9; }
QTableWidget#scheme2DetailTable::item { padding:5px 7px; }
QLabel#scheme2DetailMeta { color:#8A8A86; font-size:12px; }
QDoubleSpinBox#scheme2DetailFactor { background:transparent; border:0; border-bottom:1px solid #185FA5; border-radius:0; padding:2px 1px; min-height:24px; }
QDoubleSpinBox#scheme2DetailFactor:focus { border-bottom:2px solid #2563EB; }
QHeaderView::section { background:#F6F7F9; color:#5F5E5A; border:0; border-bottom:1px solid rgba(0,0,0,.12); padding:7px 8px; font-weight:500; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#FFFFFF; border:1px solid rgba(0,0,0,.18); border-radius:7px; padding:5px 7px; min-height:22px; }
QComboBox[scheme2Multiline="true"] { padding:4px 5px; }
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
                updates = {
                    "galvanized_sheet_unit_price_override": values["galvanized_price"],
                    "material_unit_price_override": values["carbon_price"],
                    "carbon_steel_unit_price_override": values["carbon_price"],
                    "surface_treatment_unit_price_override": values["surface_price"],
                }
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
    original_company_catalog_loaded = getattr(cls, "company_catalog_loaded", None)

    def init(window, *args, **kwargs):
        window._scheme2_add_after_calculate = False
        window._scheme2_edit_item = None
        window._scheme2_detail_item = None
        window._scheme2_active_settings = None
        window._scheme2_drawing_pages = []
        window._scheme2_drawing_page_index = -1
        window._scheme2_page_worker = None
        window._scheme2_recognition_tools = namespace["DrawingRecognitionTools"]
        window._scheme2_candidate_builder = namespace.get("build_review_candidates")
        window._scheme2_accept_paths = namespace["ImportDropZone"].accepted_paths
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
        window.scheme2_company.setFixedHeight(COMPANY_COMBO_HEIGHT)
        window.refresh_summary()
        window.show_section(OPTION_ROUTE)
        _set_dirty(window, False)
        _apply_responsive(window)

    def resize(window, event):
        original_resize(window, event)
        QTimer.singleShot(0, lambda: _apply_responsive(window))

    def close(window, event):
        worker = getattr(window, "_scheme2_page_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            event.ignore()
            return
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
        if index == 0:
            index = OPTION_ROUTE
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
            QTimer.singleShot(0, lambda: _change_scheme2_page(window, 1))
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

    def company_catalog_loaded(window, *args, **kwargs):
        result = original_company_catalog_loaded(window, *args, **kwargs)
        _restore_custom_companies(getattr(window, "scheme2_company", None))
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
    if callable(original_company_catalog_loaded):
        cls.company_catalog_loaded = company_catalog_loaded
