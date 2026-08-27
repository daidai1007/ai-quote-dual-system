"""Presentation and approved interaction refinements for the V3 workbench.

The recovered V3 core continues to own recognition, formula evaluation, BOM
data and workbook export. This overlay adds the source-controlled UI state,
database catalogue presentation and API interactions approved for V3.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from quote_defaults import (
    DEFAULT_COATING_TYPE,
    DEFAULT_MATERIAL_CODE,
    restore_combo_selection,
)
from quote_remark_rules import replace_door_configuration_phrase
from quick_discount_rules import (
    effective_attachment_line_amount,
    quick_attachment_line_amount,
    quick_discount_breakdown,
    quick_order_line_breakdown,
)
from attachment_category_browser import (
    DOOR_TRANSFORMATION_RULE_PREFIX,
    DEFAULT_A4_FOLDER,
    DEFAULT_DOOR_REINFORCEMENT,
    DEFAULT_DOOR_LIMITER,
    DEFAULT_COPPER_BUSBAR,
    DEFAULT_FIXED_BASE,
    DEFAULT_GROUND_WIRE,
    DEFAULT_JP_SIDE_PANEL,
    DEFAULT_LIGHT_SWITCH,
    GANGED_FIXED_BASE_INDEX_KEY,
    GANGED_FIXED_BASE_MATCH_KEY,
    category_options,
    category_path as attachment_category_path,
    category_value as attachment_category_value,
    default_rule_for_item,
    door_limiter_default_quantity,
    door_reinforcement_default_quantity,
    door_transformation_default_names,
    final_attachment_quantity,
    is_base_selection,
    is_jp_product,
    match_attachment_size,
    match_default_a4_folder,
    match_default_door_reinforcement,
    match_default_door_limiter,
    match_default_copper_busbar,
    match_default_ground_wire,
    match_default_light_switch,
    match_door_transformation_defaults,
    match_fixed_base,
    match_jp_side_panel,
    parse_base_specification,
    SIZE_MATCH_METADATA_KEYS,
    size_match_group_key,
    valid_selection_prefix,
)
from ganged_cabinet_rules import (
    cascade_door_counts,
    ganged_split_count,
    parse_ganged_specification,
    subcabinet_specification,
)


WIDGET_MAX = 16_777_215
# 管理费固定为人工成本的 13%（见运行规则：管理费 = 人工成本 × 0.13）。
MANAGEMENT_FEE_RATE = 0.13
VALID_DOOR_COMBINATIONS = {(1, 0), (0, 1), (0, 2), (2, 0), (1, 1)}
FORMULA_MULTI_DOOR_FAMILIES = {"JS", "JP", "JA", "JE"}
QUOTE_WIDE_BREAKPOINT = 1280
QUOTE_STACK_BREAKPOINT = 1050
QUOTE_ACTION_DOCK_HEIGHT = 62


class _GangedQuoteWorker(QThread):
    """Call the existing single-cabinet endpoint once per split cabinet."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        url: str,
        payloads: list[dict],
        attachment_total: float,
        headers_factory,
        weight_total: float | None,
        area_total: float | None,
        parent=None,
    ):
        super().__init__(parent)
        self.url = url
        self.payloads = payloads
        self.attachment_total = float(attachment_total)
        self.headers_factory = headers_factory
        self.weight_total = weight_total
        self.area_total = area_total

    @staticmethod
    def _sum(results: list[dict], section: str, key: str) -> float | None:
        values = []
        for result in results:
            value = (result.get(section) or {}).get(key)
            if value is None:
                return None
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                return None
        return sum(values)

    def run(self) -> None:
        try:
            results = []
            for payload in self.payloads:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers = (
                    self.headers_factory(True)
                    if callable(self.headers_factory)
                    else {"Content-Type": "application/json; charset=utf-8"}
                )
                request = urllib.request.Request(
                    self.url,
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    results.append(json.loads(response.read().decode("utf-8")))

            formula_keys = (
                "material_cost", "auxiliary_cost", "labor_cost", "spray_cost",
                "management_fee",
            )
            formula = {
                key: self._sum(results, "formula_cost", key) for key in formula_keys
            }
            formula_base_total = self._sum(results, "formula_cost", "total_cost")
            formula_existing_attachment = self._sum(
                results, "formula_cost", "attachment_fee"
            ) or 0.0
            if formula_base_total is not None:
                formula_base_total -= formula_existing_attachment
            formula["attachment_fee"] = self.attachment_total
            formula["product_area_m2"] = (
                self.area_total
                if self.area_total is not None
                else self._sum(results, "formula_cost", "product_area_m2")
            )
            formula["total_cost"] = (
                formula_base_total + self.attachment_total
                if formula_base_total is not None else None
            )

            quick_base = self._sum(results, "quick_quote", "base_price")
            quick = {
                "base_price": quick_base,
                "attachment_fee": self.attachment_total,
                "total_cost": (
                    quick_base + self.attachment_total
                    if quick_base is not None else None
                ),
                "match_method": "ganged_cabinet_sum",
                "dimension_distance": sum(
                    float((result.get("quick_quote") or {}).get("dimension_distance") or 0)
                    for result in results
                ),
                "matched_experience": {
                    "ganged_cabinet_count": len(results),
                    "items": [
                        (result.get("quick_quote") or {}).get("matched_experience")
                        for result in results
                    ],
                },
            }
            risks = []
            for result in results:
                risks.extend(result.get("risk_flags") or [])
            self.succeeded.emit({
                "quote_id": self.payloads[0].get("quote_id", "") if self.payloads else "",
                "formula_cost": formula,
                "quick_quote": quick,
                "risk_flags": risks,
                "ganged_cabinet_results": results,
                "ganged_weight_kg": self.weight_total,
                "ganged_area_m2": formula.get("product_area_m2"),
            })
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            self.failed.emit(detail or f"HTTP {exc.code}")
        except Exception as exc:
            self.failed.emit(str(exc))


class _QuotedTextSafeCellPattern:
    """Proxy a compiled cell regex while preserving quoted Excel strings."""

    def __init__(self, pattern):
        self.pattern = pattern

    def sub(self, replacement, expression: str, count: int = 0) -> str:
        segments = re.split(r'("(?:[^"]|"")*")', expression)
        remaining = int(count or 0)
        output = []
        for index, segment in enumerate(segments):
            if index % 2:
                output.append(segment)
                continue
            limit = remaining if count else 0
            replaced, matches = self.pattern.subn(replacement, segment, count=limit)
            output.append(replaced)
            if count:
                remaining -= matches
                if remaining <= 0:
                    output.extend(segments[index + 1:])
                    break
        return "".join(output)


def _install_formula_cell_reference_guard(namespace: dict) -> None:
    calculator = namespace.get("FormulaDatabaseCalculator")
    pattern = getattr(calculator, "_CELL_RE", None) if calculator is not None else None
    if pattern is None or isinstance(pattern, _QuotedTextSafeCellPattern):
        return
    calculator._CELL_RE = _QuotedTextSafeCellPattern(pattern)
    calculator.DETAIL_ROWS.update({
        "JS_SINGLE": (5, 25, 28, 28, 1),
        "JS_DOUBLE": (5, 25, 28, 28, 1),
        "JP_SINGLE": (5, 26, 29, 29, 1),
        "JP_DOUBLE": (5, 26, 29, 29, 1),
        "JA_SINGLE": (5, 25, 28, 28, 2),
        "JE_SINGLE": (5, 25, 28, 28, 2),
        "JE_DOUBLE": (5, 25, 28, 28, 2),
    })
    calculator.DOOR_CONTROL_CELLS.update({
        "JS_SINGLE": ("B17", "B11"),
        "JS_DOUBLE": ("B17", "B11"),
        "JP_SINGLE": ("B24", "B11"),
        "JP_DOUBLE": ("B24", "B11"),
        "JA_SINGLE": ("B16", "B17"),
        "JE_SINGLE": ("B16", "B17"),
        "JE_DOUBLE": ("B16", "B17"),
    })
    if not getattr(calculator, "_unified_formula_hydration_installed", False):
        original_load_template = calculator.load_template

        def load_template_with_dynamic_totals(self, payload):
            result = original_load_template(self, payload)
            template = payload.get("template", payload) if isinstance(payload, dict) else {}
            code = str(template.get("template_code") or "").strip()
            sheet = self.sheets.get(code) if code else None
            formulas = sheet.get("formulas") if isinstance(sheet, dict) else None
            if not isinstance(formulas, dict):
                return result
            # Excel evaluates ``1000>=B8>=350`` as
            # ``1000>=(B8>=350)``. Python treats it as a mathematical range
            # comparison, which changes the JS side-panel branch for deep
            # cabinets. Parenthesize the Excel right-hand comparison before
            # the recovered V3 evaluator sees it.
            chained_comparison = re.compile(
                r"(?P<left>\d+(?:\.\d+)?)\s*(?P<left_op>>=|<=|>|<)\s*"
                r"(?P<middle>\$?[A-Z]{1,3}\$?\d+)\s*"
                r"(?P<right_op>>=|<=|>|<)\s*(?P<right>\d+(?:\.\d+)?)"
            )
            for ref, formula in list(formulas.items()):
                formulas[ref] = chained_comparison.sub(
                    r"\g<left>\g<left_op>(\g<middle>\g<right_op>\g<right>)",
                    str(formula),
                )
            for rule in template.get("rules") or []:
                raw = rule.get("raw_rule") or {}
                row = int(rule.get("source_row_no") or raw.get("source_row_no") or 0)
                if row <= 0:
                    continue
                if rule.get("include_material_cost") and f"M{row}" not in formulas:
                    formulas[f"M{row}"] = (
                        f"L{row}*J{row}*I{row}*H{row}*G{row}*F{row}*1.2"
                    )
                if f"K{row}" in formulas and f"L{row}" not in formulas:
                    formulas[f"L{row}"] = f"K{row}*B$9"
                if rule.get("include_spray_area") and f"Y{row}" not in formulas:
                    formulas[f"Y{row}"] = (
                        f'IF(OR(N{row}="镀锌板",N{row}="蓝白锌",'
                        f'N{row}="镀彩锌",N{row}="镀白锌",N{row}="镀锡",'
                        f'N{row}="镀铜",N{row}="外协",N{row}="外购"),0,'
                        f'(F{row}/1000)*(G{row}/1000)*2*L{row})'
                    )
            return result

        calculator.load_template = load_template_with_dynamic_totals
        calculator._unified_formula_hydration_installed = True

    if not getattr(calculator, "_workbook_weight_total_guard_installed", False):
        original_evaluate_sheet = calculator._evaluate_sheet

        def evaluate_sheet_with_workbook_weight_total(
            self,
            product_code,
            width,
            height,
            depth,
            single_door_count=1,
            double_door_count=0,
        ):
            result = original_evaluate_sheet(
                self,
                product_code,
                width,
                height,
                depth,
                single_door_count,
                double_door_count,
            )
            if not result:
                return result
            detail_values = getattr(self, "last_detail_values", None)
            if not isinstance(detail_values, dict):
                return result

            weight = 0.0
            is_jp = str(product_code).startswith("JP_")
            for item_name, thickness, row_weight, treatment, _row_area in detail_values.values():
                item_name = "" if item_name in (None, 0.0) else str(item_name)
                treatment = "" if treatment in (None, 0.0) else str(treatment)
                try:
                    thickness_value = float(thickness or 0)
                    row_weight_value = float(row_weight or 0)
                except (TypeError, ValueError):
                    continue
                is_lock = "锁杆" in item_name
                is_frame = "框架" in item_name
                if treatment == "镀锌板":
                    galvanized = (2.5,) if is_jp else (2, 2.5, 3)
                    if any(abs(thickness_value - value) < 1e-6 for value in galvanized):
                        weight += row_weight_value
                elif is_lock:
                    weight += row_weight_value
                elif is_jp:
                    if any(
                        abs(thickness_value - value) < 1e-6
                        for value in (1, 1.5, 2, 2.5, 3)
                    ):
                        weight += row_weight_value
                elif (
                    (abs(thickness_value - 1.5) < 1e-6 and not is_frame)
                    or any(
                        abs(thickness_value - value) < 1e-6
                        for value in (2, 2.5, 3)
                    )
                ):
                    weight += row_weight_value
            if product_code == "JM":
                weight *= 1.1
            return max(weight, 0.0), result[1]

        calculator._evaluate_sheet = evaluate_sheet_with_workbook_weight_total
        calculator._workbook_weight_total_guard_installed = True

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


def _install_door_remark_sync(namespace: dict) -> None:
    """Make current door counts authoritative for the door wording only."""

    original_builder = namespace.get("build_standardized_quote_remark")
    if not callable(original_builder) or getattr(original_builder, "_door_remark_sync_installed", False):
        return

    def build_remark_with_current_door_counts(item, raw_remark):
        remark = original_builder(item, raw_remark)
        return replace_door_configuration_phrase(remark, item)

    build_remark_with_current_door_counts._door_remark_sync_installed = True
    namespace["build_standardized_quote_remark"] = build_remark_with_current_door_counts


def _find(root: QWidget, widget_type, object_name: str):
    return root.findChild(widget_type, object_name)


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _formula_workbook_value(value) -> str:
    """Use the one-decimal precision displayed by the material workbook."""

    return f"{float(value):.1f}"


def _round_formula_workbook_fields(window) -> None:
    for name in ("weight_edit", "area_edit"):
        field = getattr(window, name, None)
        if not isinstance(field, QLineEdit):
            continue
        value = _safe_float(field.text())
        if value is not None:
            field.setText(_formula_workbook_value(value))


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


def _parse_specification_dimensions(text: str, parser=None) -> tuple[float, float, float] | None:
    """Return width, height and depth from an operator-entered W*D*H spec."""

    value = str(text or "").strip()
    if not value:
        return None
    base_specification = parse_base_specification(value)
    if base_specification is not None:
        width, height, depth, _base_height = base_specification
        return width, height, depth
    if callable(parser):
        try:
            parsed = parser(value)
            dimensions = parsed.get("dimensions") if isinstance(parsed, dict) else None
            if isinstance(dimensions, (list, tuple)) and len(dimensions) >= 3:
                width, height, depth = map(float, dimensions[:3])
                if min(width, height, depth) > 0:
                    return width, height, depth
        except Exception:
            pass

    # The visible specification convention is width * depth * height.  Keep
    # the accepted separators intentionally small and predictable.
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*[xX×＊*]\s*"
        r"(\d+(?:\.\d+)?)\s*[xX×＊*]\s*(\d+(?:\.\d+)?)\s*",
        value,
    )
    if not match:
        return None
    width, depth, height = (float(part) for part in match.groups())
    if min(width, height, depth) <= 0:
        return None
    return width, height, depth


def _ganged_rows(window) -> list[dict]:
    rows = getattr(window, "ganged_cabinets", [])
    return [dict(row) for row in rows if isinstance(row, dict)]


def _ganged_count(window) -> int:
    rows = _ganged_rows(window)
    return len(rows) if len(rows) > 1 else 1


def _product_code_for_door_counts(window, single: int, double: int) -> tuple[str | None, str | None]:
    entry = getattr(window, "product_catalog", {}).get(
        getattr(getattr(window, "product_combo", None), "currentData", lambda: None)() or "",
        {},
    )
    codes = entry.get("codes") or {}
    wanted = "SINGLE" if int(single) > 0 else "DOUBLE"
    for variant in (wanted, "DEFAULT", "SINGLE", "DOUBLE"):
        code = codes.get(variant)
        if code:
            return str(code), variant
    return None, None


def _normalize_door_pair(single: int, double: int, source: str) -> tuple[int, int]:
    single, double = int(single), int(double)
    if (single, double) in VALID_DOOR_COMBINATIONS:
        return single, double
    if source == "single":
        if single == 0:
            double = double if double in (1, 2) else 1
        elif single == 1:
            double = double if double in (0, 1) else 0
        else:
            double = 0
    else:
        if double == 0:
            single = single if single in (1, 2) else 1
        elif double == 1:
            single = single if single in (0, 1) else 0
        else:
            single = 0
    return (single, double) if (single, double) in VALID_DOOR_COMBINATIONS else (1, 0)


def _door_transform_matches_for_window(window, catalog: list[dict]) -> dict[str, dict]:
    product_code = (_door_transform_context(window) or ("", ()))[0]
    rows = _ganged_rows(window)
    if len(rows) <= 1:
        counts = _current_door_counts(window)
        return (
            match_door_transformation_defaults(catalog, product_code, *counts)
            if counts is not None else {}
        )
    matches: dict[str, dict] = {}
    for row in rows:
        counts = (
            int(row.get("single_door_count", 1)),
            int(row.get("double_door_count", 0)),
        )
        for rule, candidate in match_door_transformation_defaults(
            catalog, product_code, *counts
        ).items():
            matches.setdefault(rule, candidate)
    return matches


def _sync_manual_specification_to_dimensions(window, text: str, parser=None) -> bool:
    """Populate dimension fields from a manual specification without recursion."""

    if getattr(window, "active_drawing", None):
        return False
    dimensions = _parse_specification_dimensions(text, parser)
    if dimensions is None:
        return False

    width, height, depth = dimensions
    fields = (
        (getattr(window, "width_spin", None), width),
        (getattr(window, "height_spin", None), height),
        (getattr(window, "depth_spin", None), depth),
    )
    if not all(isinstance(field, QDoubleSpinBox) for field, _ in fields):
        return False
    for field, number in fields:
        previous = field.blockSignals(True)
        try:
            field.setValue(number)
        finally:
            field.blockSignals(previous)

    source = getattr(window, "quote_parameter_source", None)
    if isinstance(source, QLabel):
        source.setText("来源：人工输入规格")
        source.setToolTip("已从规格型号按宽×深×高自动填充")

    for method_name in (
        "clear_quote_result",
        "refresh_formula_inputs",
        "request_history_match",
        "update_quote_readiness",
    ):
        method = getattr(window, method_name, None)
        if callable(method):
            try:
                method()
            except TypeError:
                pass
    return True


def _sync_quote_specification(window, text: str, parser=None) -> bool:
    """Apply one specification edit to dimensions and horizontal-ganging state."""

    _sync_manual_specification_to_dimensions(window, text, parser)
    return _sync_ganged_specification(window, text)


def _allowed_door_combinations(window) -> set[tuple[int, int]]:
    product_combo = getattr(window, "product_combo", None)
    if not isinstance(product_combo, QComboBox):
        return set(VALID_DOOR_COMBINATIONS)
    family = str(product_combo.currentData() or "").strip().upper()
    if family in FORMULA_MULTI_DOOR_FAMILIES:
        return set(VALID_DOOR_COMBINATIONS)
    entry = getattr(window, "product_catalog", {}).get(product_combo.currentData() or "", {})
    codes = entry.get("codes") or {}
    allowed = set()
    if "SINGLE" in codes:
        allowed.add((1, 0))
    if "DOUBLE" in codes:
        allowed.add((0, 1))
    return allowed


def _current_door_counts(window) -> tuple[int, int] | None:
    getter = getattr(window, "door_counts", None)
    if not callable(getter):
        return None
    try:
        single, double = getter()
        return int(single), int(double)
    except (TypeError, ValueError):
        return None


def _sync_door_count_default_quantities(
    window,
    previous_counts: tuple[int, int] | None = None,
) -> bool:
    """Update system-managed limiter/reinforcement after real count changes."""

    current_counts = _current_door_counts(window)
    if current_counts is None:
        return False
    if previous_counts is None:
        previous_counts = getattr(window, "_attachment_default_door_counts", None)
    window._attachment_default_door_counts = current_counts
    if previous_counts is None or tuple(previous_counts) == current_counts:
        return False

    opt_outs = set(getattr(window, "attachment_default_opt_outs", set()))
    quantity_overrides = set(
        getattr(window, "attachment_default_quantity_overrides", set())
    )
    attachments = getattr(window, "attachments", None)
    if not isinstance(attachments, list):
        return False
    changed = False
    for rule, quantity in (
        (DEFAULT_DOOR_LIMITER, door_limiter_default_quantity(*current_counts)),
        (DEFAULT_DOOR_REINFORCEMENT, door_reinforcement_default_quantity(*current_counts)),
    ):
        if quantity is None or rule in opt_outs or rule in quantity_overrides:
            continue
        for item in attachments:
            if not isinstance(item, dict) or default_rule_for_item(item) != rule:
                continue
            try:
                old_quantity = int(item.get("quantity", 1))
            except (TypeError, ValueError):
                old_quantity = None
            if old_quantity != quantity:
                item["quantity"] = quantity
                changed = True
    if changed:
        refresh = getattr(window, "update_attachment_view", None)
        if callable(refresh):
            refresh()
    return changed


def _sync_door_limiter_default_quantity(
    window,
    previous_counts: tuple[int, int] | None = None,
) -> bool:
    """Backward-compatible wrapper for the expanded door-count defaults."""

    return _sync_door_count_default_quantities(window, previous_counts)


def _formula_order_line_breakdown(item: dict) -> dict[str, float]:
    """Return a formula-quote line total with attachment quantity exceptions."""

    quote = item.get("formula") or {}
    attachments = [row for row in item.get("attachments", []) if isinstance(row, dict)]
    cabinets = _safe_float(item.get("quantity")) or 1.0
    split_count = float(ganged_split_count(item))
    discount = _safe_float(item.get("formula_discount")) or 1.0
    listed = sum(quick_attachment_line_amount(row) for row in attachments)
    attachment_fee = _safe_float(quote.get("attachment_fee"))
    if attachment_fee is None:
        attachment_fee = listed
    base = (_safe_float(quote.get("total_cost")) or 0.0) - attachment_fee
    effective = sum(
        effective_attachment_line_amount(row, cabinets, split_count)
        for row in attachments
    )
    effective += (attachment_fee - listed) * cabinets * split_count
    line_total = (base * cabinets + effective) * discount
    return {
        "cabinet_quantity": cabinets,
        "ganged_cabinet_count": split_count,
        "attachment_total": effective,
        "line_total": line_total,
        "equivalent_unit_total": line_total / cabinets if cabinets else line_total,
    }


def _door_transform_context(window) -> tuple[str, tuple] | None:
    counts = _current_door_counts(window)
    if counts is None:
        return None
    getter = getattr(window, "selected_product_code", None)
    product_code = getter() if callable(getter) else _current_product_selection(window)
    rows = _ganged_rows(window)
    if len(rows) > 1:
        door_rows = tuple(
            (
                int(row.get("single_door_count", 1)),
                int(row.get("double_door_count", 0)),
            )
            for row in rows
        )
        return str(product_code or "").strip().upper(), door_rows
    return str(product_code or "").strip().upper(), counts


def _sync_door_transform_defaults(window) -> bool:
    """Reapply door transformations only after a real family/count change."""

    current = _door_transform_context(window)
    previous = getattr(window, "attachment_door_transform_context", None)
    if current is None or previous is None or tuple(previous) == current:
        return False
    window.attachment_door_transform_context = current
    opt_outs = {
        rule for rule in set(getattr(window, "attachment_default_opt_outs", set()))
        if not str(rule).startswith(DOOR_TRANSFORMATION_RULE_PREFIX)
    }
    window.attachment_default_opt_outs = opt_outs
    attachments = [
        item for item in getattr(window, "attachments", [])
        if not (
            isinstance(item, dict)
            and (
                attachment_category_value(item, 0) == "门变形"
                or str(default_rule_for_item(item) or "").startswith(
                    DOOR_TRANSFORMATION_RULE_PREFIX
                )
            )
        )
    ]
    catalog = [
        item for item in getattr(window, "attachment_door_transform_catalog", [])
        if isinstance(item, dict)
    ]
    matches = _door_transform_matches_for_window(window, catalog)
    for candidate in matches.values():
        selected = dict(candidate)
        selected["quantity"] = 1
        attachments.append(selected)
    changed = attachments != getattr(window, "attachments", [])
    window.attachments = attachments
    if changed:
        refresh = getattr(window, "update_attachment_view", None)
        if callable(refresh):
            refresh()
    return changed


def _set_default_door_combination(window) -> None:
    single = getattr(window, "single_door_combo", None)
    double = getattr(window, "double_door_combo", None)
    if not isinstance(single, QComboBox) or not isinstance(double, QComboBox):
        return
    if not single.isEnabled() and not double.isEnabled():
        setter = getattr(window, "set_door_counts", None)
        if callable(setter):
            setter(1, 0)
        return
    counts = (single.currentData(), double.currentData())
    try:
        counts = tuple(int(value) for value in counts)
    except (TypeError, ValueError):
        counts = (-1, -1)
    allowed = _allowed_door_combinations(window)
    if counts in allowed:
        return
    target = (1, 0) if (1, 0) in allowed else ((0, 1) if (0, 1) in allowed else None)
    if target is None:
        return
    setter = getattr(window, "set_door_counts", None)
    if callable(setter):
        setter(*target)
        return
    for combo, wanted in ((single, target[0]), (double, target[1])):
        index = combo.findData(wanted)
        if index >= 0:
            combo.setCurrentIndex(index)


def _restore_quote_selections_after_product_change(
    window,
    material_selected,
    coating_selected,
) -> None:
    """Keep manual quote selections, falling back only when they are blank."""

    for name, selected, default in (
        ("material_combo", material_selected, DEFAULT_MATERIAL_CODE),
        ("coating_combo", coating_selected, DEFAULT_COATING_TYPE),
    ):
        combo = getattr(window, name, None)
        if not isinstance(combo, QComboBox):
            continue
        signals_were_blocked = combo.blockSignals(True)
        try:
            restore_combo_selection(combo, selected, default)
        finally:
            combo.blockSignals(signals_were_blocked)


def _current_product_selection(window):
    combo = getattr(window, "product_combo", None)
    if not isinstance(combo, QComboBox) or combo.currentIndex() < 0:
        return None
    return combo.currentData() or combo.currentText().strip() or None


def _restore_product_selection(window, selection) -> bool:
    """Restore a retained product without inventing a catalogue option."""

    if selection in (None, ""):
        return False
    combo = getattr(window, "product_combo", None)
    if not isinstance(combo, QComboBox):
        return False
    index = combo.findData(selection)
    if index < 0:
        index = combo.findText(str(selection))
    if index < 0:
        return False
    if combo.currentIndex() != index:
        combo.setCurrentIndex(index)
    return True


def _enforce_product_door_combination(window, source: str) -> bool:
    count_getter = getattr(window, "door_counts", None)
    setter = getattr(window, "set_door_counts", None)
    if not callable(count_getter) or not callable(setter):
        return False
    counts = tuple(count_getter())
    allowed = _allowed_door_combinations(window)
    if not allowed or counts in allowed:
        return False
    if source == "double" and (0, 1) in allowed and counts[1] > 0:
        target = (0, 1)
    elif source == "single" and (1, 0) in allowed and counts[0] > 0:
        target = (1, 0)
    else:
        target = (1, 0) if (1, 0) in allowed else (0, 1)
    setter(*target)
    for method_name in ("refresh_formula_inputs", "request_history_match"):
        method = getattr(window, method_name, None)
        if callable(method):
            method()
    return True


def _ensure_ganged_cabinet_panel(window) -> None:
    if getattr(window, "ganged_cabinet_panel", None) is not None:
        return
    specification = getattr(window, "quote_spec_edit", None)
    model_edit = getattr(window, "model_edit", None)
    anchor = specification if isinstance(specification, QLineEdit) else model_edit
    if not isinstance(anchor, QLineEdit):
        return
    anchor_parent = anchor.parentWidget()
    form = anchor_parent.layout() if anchor_parent is not None else None
    placement = "grid"
    input_box = anchor_parent
    anchor_block = None
    if not isinstance(form, QGridLayout):
        anchor_block = anchor_parent
        input_box = anchor_parent.parentWidget() if anchor_parent is not None else None
        form = input_box.layout() if input_box is not None else None
        placement = "vertical"
    if not isinstance(form, (QGridLayout, QVBoxLayout)):
        return

    label = QLabel("并柜拆分", input_box)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    panel = QFrame(input_box)
    panel.setObjectName("gangedCabinetPanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    hint = QLabel(panel)
    hint.setObjectName("gangedCabinetHint")
    hint.setWordWrap(True)
    table = QTableWidget(0, 4, panel)
    table.setObjectName("gangedCabinetTable")
    table.setHorizontalHeaderLabels(["序号", "拆分尺寸（宽×深×高）", "单门", "双门"])
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    layout.addWidget(hint)
    layout.addWidget(table)
    if placement == "grid":
        form.addWidget(label, 11, 0)
        form.addWidget(panel, 11, 1, 1, 3)
    else:
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        insert_at = form.indexOf(anchor_block) + 1
        form.insertWidget(insert_at, label)
        form.insertWidget(insert_at + 1, panel)
    window.ganged_cabinet_label = label
    window.ganged_cabinet_panel = panel
    window.ganged_cabinet_hint = hint
    window.ganged_cabinet_table = table
    label.hide()
    panel.hide()


def _render_ganged_cabinet_table(window) -> None:
    table = getattr(window, "ganged_cabinet_table", None)
    if not isinstance(table, QTableWidget):
        return
    rows = _ganged_rows(window)
    table.blockSignals(True)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        index_item = QTableWidgetItem(str(row_index + 1))
        index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        size_item = QTableWidgetItem(subcabinet_specification(row))
        size_item.setToolTip("并柜仅拆分宽度；深度、柜高和底座高度在各子柜间共用")
        table.setItem(row_index, 0, index_item)
        table.setItem(row_index, 1, size_item)
        for column, key, source in (
            (2, "single_door_count", "single"),
            (3, "double_door_count", "double"),
        ):
            combo = QComboBox(table)
            for count in (0, 1, 2):
                combo.addItem(str(count), count)
            wanted = int(row.get(key, 1 if source == "single" else 0))
            combo.setCurrentIndex(combo.findData(wanted))
            combo.currentIndexChanged.connect(
                lambda _index, r=row_index, s=source: _ganged_door_changed(window, r, s)
            )
            table.setCellWidget(row_index, column, combo)
    table.blockSignals(False)
    table.setFixedHeight(min(42 + 34 * len(rows), 246))
    hint = getattr(window, "ganged_cabinet_hint", None)
    if isinstance(hint, QLabel):
        hint.setText(
            f"已拆分为 {len(rows)} 个子柜；报价按子柜分别计算后合并，"
            "下方柜型数量表示整套并柜的台数。"
        )


def _set_ganged_controls_enabled(window, ganged: bool) -> None:
    for name in ("width_spin", "height_spin", "depth_spin"):
        field = getattr(window, name, None)
        if isinstance(field, QDoubleSpinBox):
            field.setEnabled(not ganged)
    single = getattr(window, "single_door_combo", None)
    double = getattr(window, "double_door_combo", None)
    if ganged:
        if isinstance(single, QComboBox):
            single.setEnabled(False)
        if isinstance(double, QComboBox):
            double.setEnabled(False)
        return
    entry = getattr(window, "product_catalog", {}).get(
        getattr(getattr(window, "product_combo", None), "currentData", lambda: None)() or "",
        {},
    )
    enabled = bool(set((entry.get("codes") or {}).keys()) & {"SINGLE", "DOUBLE"})
    if isinstance(single, QComboBox):
        single.setEnabled(enabled)
    if isinstance(double, QComboBox):
        double.setEnabled(enabled)


def _sync_ganged_specification(window, text: str) -> bool:
    parsed = parse_ganged_specification(text)
    panel = getattr(window, "ganged_cabinet_panel", None)
    label = getattr(window, "ganged_cabinet_label", None)
    previous = _ganged_rows(window)
    if parsed is None:
        was_ganged = len(previous) > 1
        window.ganged_cabinets = []
        window.ganged_cabinet_count = 1
        window.ganged_cabinet_specification = ""
        _render_ganged_cabinet_table(window)
        if panel is not None:
            panel.hide()
        if label is not None:
            label.hide()
        _set_ganged_controls_enabled(window, False)
        if was_ganged:
            refresh = getattr(window, "update_attachment_view", None)
            if callable(refresh):
                refresh()
        return False

    default_counts = _current_door_counts(window) or (1, 0)
    rows = []
    for index, dimensions in enumerate(parsed["rows"]):
        old = previous[index] if index < len(previous) else {}
        row = dict(dimensions)
        row["single_door_count"] = int(old.get("single_door_count", default_counts[0]))
        row["double_door_count"] = int(old.get("double_door_count", default_counts[1]))
        rows.append(row)
    window.ganged_cabinets = rows
    window.ganged_cabinet_count = len(rows)
    window.ganged_cabinet_specification = parsed["specification"]
    first = rows[0]
    for name, value in (
        ("width_spin", first["width_mm"]),
        ("height_spin", first["height_mm"]),
        ("depth_spin", first["depth_mm"]),
    ):
        field = getattr(window, name, None)
        if isinstance(field, QDoubleSpinBox):
            blocked = field.blockSignals(True)
            field.setValue(float(value))
            field.blockSignals(blocked)
    setter = getattr(window, "set_door_counts", None)
    if callable(setter):
        setter(first["single_door_count"], first["double_door_count"])
    _set_ganged_controls_enabled(window, True)
    if panel is not None:
        panel.show()
    if label is not None:
        label.show()
    _render_ganged_cabinet_table(window)
    _sync_door_transform_defaults(window)
    refresh = getattr(window, "update_attachment_view", None)
    if callable(refresh):
        refresh()
    return True


def _ganged_door_changed(window, row_index: int, source: str) -> None:
    table = getattr(window, "ganged_cabinet_table", None)
    rows = _ganged_rows(window)
    if not isinstance(table, QTableWidget) or not (0 <= row_index < len(rows)):
        return
    single_combo = table.cellWidget(row_index, 2)
    double_combo = table.cellWidget(row_index, 3)
    if not isinstance(single_combo, QComboBox) or not isinstance(double_combo, QComboBox):
        return
    single, double = _normalize_door_pair(
        int(single_combo.currentData() or 0),
        int(double_combo.currentData() or 0),
        source,
    )
    window.ganged_cabinets = cascade_door_counts(rows, row_index, single, double)
    if row_index == 0:
        setter = getattr(window, "set_door_counts", None)
        if callable(setter):
            setter(single, double)
    _render_ganged_cabinet_table(window)
    _sync_door_transform_defaults(window)
    for method_name in ("clear_quote_result", "refresh_formula_inputs", "request_history_match"):
        method = getattr(window, method_name, None)
        if callable(method):
            try:
                method()
            except TypeError:
                pass


def _build_ganged_quote_payloads(window) -> tuple[list[dict], float | None, float | None]:
    rows = _ganged_rows(window)
    if len(rows) <= 1:
        return [], None, None
    material_combo = getattr(window, "material_combo", None)
    coating_combo = getattr(window, "coating_combo", None)
    quote_date = getattr(window, "quote_date", None)
    calculator = getattr(window, "formula_calculator", None)
    weights: list[float] = []
    areas: list[float] = []
    local_complete = True
    payloads = []
    quote_prefix = "TMP" + datetime.now().strftime("%Y%m%d%H%M%S%f")[-12:]
    for index, row in enumerate(rows):
        single = int(row.get("single_door_count", 1))
        double = int(row.get("double_door_count", 0))
        code, variant = _product_code_for_door_counts(window, single, double)
        if not code:
            raise ValueError(f"第 {index + 1} 个子柜没有可用的产品变体")
        local = None
        if calculator is not None:
            local = calculator.calculate(
                code,
                float(row["width_mm"]),
                float(row["height_mm"]),
                float(row["depth_mm"]),
                single,
                double,
            )
        if local:
            # Formula quotes use the one-decimal values displayed by the
            # authoritative workbook.  Keep child-cabinet API inputs on the
            # same precision as ordinary (non-ganged) quotes so identical
            # cabinets cannot produce different costs solely because they
            # travelled through the ganged path.
            local = (
                float(_formula_workbook_value(local[0])),
                float(_formula_workbook_value(local[1])),
            )
            weights.append(local[0])
            areas.append(local[1])
        else:
            local_complete = False
        payloads.append({
            "quote_id": f"{quote_prefix}-{index + 1}",
            "product_code": code,
            # Each existing API call must match the child cabinet rather than
            # the combined customer-facing specification.  The original
            # combined text is restored on the saved/exported quote item.
            "model_code": subcabinet_specification(row),
            "material_code": material_combo.currentData() if material_combo is not None else None,
            "width_mm": float(row["width_mm"]),
            "height_mm": float(row["height_mm"]),
            "depth_mm": float(row["depth_mm"]),
            "base_material_weight_kg": local[0] if local else None,
            "product_area_m2": local[1] if local else None,
            "coating_type": coating_combo.currentData() if coating_combo is not None else None,
            "variant_code": variant,
            "single_door_count": single,
            "double_door_count": double,
            "quote_date": quote_date.date().toString("yyyy-MM-dd") if quote_date is not None else None,
            # Attachments are priced once in the aggregate result.  Sending
            # them in every child request would duplicate the three manual
            # quantity exceptions.
            "attachments": [],
        })
    return (
        payloads,
        sum(weights) if local_complete else None,
        sum(areas) if local_complete else None,
    )


def _start_ganged_calculation(window, headers_factory) -> bool:
    if _ganged_count(window) <= 1:
        return False
    try:
        payloads, weight_total, area_total = _build_ganged_quote_payloads(window)
    except Exception as exc:
        QMessageBox.warning(window, "并柜规格无法计算", str(exc))
        return True
    if not payloads:
        return False
    attachment_total = sum(
        quick_attachment_line_amount(item)
        for item in getattr(window, "attachments", [])
        if isinstance(item, dict)
    )
    api_url = str(getattr(window, "api_url", None).text() or "").strip()
    worker = _GangedQuoteWorker(
        api_url,
        payloads,
        attachment_total,
        headers_factory,
        weight_total,
        area_total,
        window,
    )
    window.calculate_button.setEnabled(False)
    window.worker = worker

    def show_ganged_result(result):
        if weight_total is None:
            window.weight_edit.clear()
        else:
            window.weight_edit.setText(_formula_workbook_value(weight_total))
        result_area = result.get("ganged_area_m2")
        if result_area is None:
            window.area_edit.clear()
        else:
            window.area_edit.setText(_formula_workbook_value(result_area))
        window.show_result(result)

    worker.succeeded.connect(show_ganged_result)
    worker.failed.connect(window.show_error)
    worker.finished.connect(lambda: window.calculate_button.setEnabled(True))
    worker.start()
    return True


def _configure_quote_rule_interactions(window, parser=None) -> None:
    _ensure_ganged_cabinet_panel(window)
    for name, label in (
        ("width_spin", "宽度（mm）"),
        ("depth_spin", "深度（mm）"),
        ("height_spin", "高度（mm）"),
    ):
        field = getattr(window, name, None)
        if isinstance(field, QDoubleSpinBox):
            field.setSpecialValueText("")
            field.lineEdit().setPlaceholderText("")
            field.setAccessibleName(label)
            field.setToolTip("可直接输入；在规格型号输入宽×深×高也会自动填充")

    single = getattr(window, "single_door_combo", None)
    double = getattr(window, "double_door_combo", None)
    if isinstance(single, QComboBox):
        single.setAccessibleName("单门数量")
        single.setToolTip("单门数量；JS/JP/JA/JE 支持五种组合，其他产品按数据库单/双门记录选择")
    if isinstance(double, QComboBox):
        double.setAccessibleName("双门数量")
        double.setToolTip("双门数量；JS/JP/JA/JE 的五种组合在快速报价中均读取 SINGLE 记录")
    _set_default_door_combination(window)

    model_edit = getattr(window, "model_edit", None)
    if isinstance(model_edit, QLineEdit):
        model_edit.setPlaceholderText(
            "规格型号；并柜示例：（200+200）×600×（600+200）"
        )
        if not getattr(model_edit, "_ganged_specification_connected", False):
            def sync_model_specification(value):
                _sync_manual_specification_to_dimensions(window, value, parser)
                _sync_ganged_specification(window, value)

            model_edit.textEdited.connect(sync_model_specification)
            model_edit._ganged_specification_connected = True

    specification = getattr(window, "quote_spec_edit", None)
    if isinstance(specification, QLineEdit):
        specification.setPlaceholderText("例如 760*500*(960+100)；无底座则不写括号和 +100")
        specification.setToolTip(
            "输入宽×深×高；需要底座时写成宽×深×(柜高+底座高)，例如 760×500×(960+100)"
        )
        if not getattr(specification, "_manual_dimension_sync_connected", False):
            specification.textEdited.connect(
                lambda value: _sync_quote_specification(window, value, parser)
            )
            specification._manual_dimension_sync_connected = True


def _refresh_model_suggestions(window) -> None:
    model_edit = getattr(window, "model_edit", None)
    product_combo = getattr(window, "product_combo", None)
    if not isinstance(model_edit, QLineEdit) or not isinstance(product_combo, QComboBox):
        return
    entry = getattr(window, "product_catalog", {}).get(product_combo.currentData() or "", {})
    models = entry.get("models") or []
    values = sorted({
        str(item.get("model_code") or "").strip()
        for item in models if isinstance(item, dict) and item.get("model_code")
    })
    completer = QCompleter(values, model_edit)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    model_edit.setCompleter(completer)
    model_edit._database_completer = completer
    model_edit.setToolTip(
        "输入型号；下拉建议来自当前产品的数据库记录"
        if values else "当前产品暂无数据库型号建议，可输入非标规格"
    )


def _apply_database_catalog_options(window, result: dict) -> None:
    if not isinstance(result, dict):
        return
    records = result.get("items") or []
    family_for_code = getattr(window, "family_for_code", None)
    catalog = getattr(window, "product_catalog", {})
    if callable(family_for_code) and isinstance(catalog, dict):
        for row in records:
            if not isinstance(row, dict):
                continue
            family = family_for_code(row.get("product_code"))
            if family in catalog:
                catalog[family].setdefault("models", []).extend(row.get("models") or [])
                defaults = (
                    row.get("default_width_mm"),
                    row.get("default_height_mm"),
                    row.get("default_depth_mm"),
                )
                if all(value is not None for value in defaults):
                    code = str(row.get("product_code") or "")
                    variant = "SINGLE" if code.endswith("_SINGLE") else "DOUBLE" if code.endswith("_DOUBLE") else "DEFAULT"
                    catalog[family].setdefault("defaults_by_variant", {})[variant] = defaults

    material_combo = getattr(window, "material_combo", None)
    materials = result.get("materials") or []
    if isinstance(material_combo, QComboBox) and materials:
        selected = material_combo.currentData()
        material_combo.blockSignals(True)
        material_combo.clear()
        for item in materials:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            code = str(item["code"])
            name = str(item.get("name") or code)
            material_combo.addItem(f"{name} ({code})" if name != code else code, code)
        restore_combo_selection(material_combo, selected, DEFAULT_MATERIAL_CODE)
        material_combo.blockSignals(False)
        material_combo.setToolTip("可选材质由数据库材料表提供")

    coating_combo = getattr(window, "coating_combo", None)
    coatings = [str(value).strip() for value in (result.get("coatings") or []) if str(value).strip()]
    if isinstance(coating_combo, QComboBox) and coatings:
        selected = coating_combo.currentData()
        coating_combo.blockSignals(True)
        coating_combo.clear()
        for coating in coatings:
            coating_combo.addItem(coating, coating)
        restore_combo_selection(coating_combo, selected, DEFAULT_COATING_TYPE)
        coating_combo.blockSignals(False)
        coating_combo.setToolTip("可选喷塑方式由数据库喷塑价格表提供")
    _refresh_model_suggestions(window)


def _apply_nonstandard_formula_ratio(window) -> bool:
    """Scale DB standard weight/area by nearest-standard perimeter ratio."""

    product_combo = getattr(window, "product_combo", None)
    if not isinstance(product_combo, QComboBox):
        return False
    entry = getattr(window, "product_catalog", {}).get(product_combo.currentData() or "", {})
    if entry.get("method") != "formula":
        return False
    variant_getter = getattr(window, "selected_variant_code", None)
    variant = variant_getter() if callable(variant_getter) else "DEFAULT"
    defaults = (entry.get("defaults_by_variant") or {}).get(variant) or entry.get("defaults")
    if not defaults or len(defaults) < 3:
        return False
    default_width, default_height, default_depth = map(float, defaults[:3])
    input_width = float(window.width_spin.value())
    input_height = float(window.height_spin.value())
    input_depth = float(window.depth_spin.value())
    if all(abs(current - standard) < 0.0001 for current, standard in (
        (input_width, default_width),
        (input_height, default_height),
        (input_depth, default_depth),
    )):
        return False
    denominator = default_width + default_height + default_depth
    if denominator <= 0:
        return False
    code_getter = getattr(window, "selected_product_code", None)
    count_getter = getattr(window, "door_counts", None)
    code = code_getter() if callable(code_getter) else None
    counts = count_getter() if callable(count_getter) else (0, 0)
    values = window.formula_calculator.calculate(
        code, default_width, default_height, default_depth, counts[0], counts[1]
    )
    if not values:
        return False
    ratio = (input_width + input_height + input_depth) / denominator
    window.weight_edit.setText(_formula_workbook_value(float(values[0]) * ratio))
    window.area_edit.setText(_formula_workbook_value(float(values[1]) * ratio))
    source = getattr(window, "quote_parameter_source", None)
    if isinstance(source, QLabel):
        source.setText("来源：数据库标准尺寸·周长比例")
        source.setToolTip(
            f"非标尺寸按输入周长÷匹配周长换算，当前比例 {ratio:.6f}"
        )
    window._nonstandard_perimeter_ratio = ratio
    return True


def _history_price_match_payload(window) -> dict | None:
    """Return the three visible values used by the exact historical lookup."""

    company = getattr(window, "company_combo", None)
    specification = getattr(window, "quote_spec_edit", None)
    product = getattr(window, "product_combo", None)
    if not all(isinstance(widget, (QComboBox, QLineEdit)) for widget in (
        company,
        specification,
        product,
    )):
        return None
    company_name = company.currentText().strip()
    specification_text = specification.text().strip()
    cabinet_type = product.currentText().strip()
    if not company_name or not specification_text or not cabinet_type or product.currentData() is None:
        return None
    return {
        "company_name": company_name,
        "specification": specification_text,
        "cabinet_type": cabinet_type,
    }


def _set_history_price_state(window, text: str, tone: str = "muted", tooltip: str = "") -> None:
    state = getattr(window, "history_price_state", None)
    if not isinstance(state, QLabel):
        return
    state.setText(text)
    state.setProperty("tone", tone)
    state.setToolTip(tooltip)
    state.style().unpolish(state)
    state.style().polish(state)


def _render_history_price_matches(window, result: dict) -> None:
    table = getattr(window, "history_price_table", None)
    if not isinstance(table, QTableWidget):
        return
    items = result.get("items") if isinstance(result, dict) else []
    items = [item for item in (items or []) if isinstance(item, dict)]
    table.setRowCount(len(items))
    for row, item in enumerate(items):
        contract = QTableWidgetItem(str(item.get("dingtalk_contract_no") or "—"))
        try:
            price_text = f"{float(item.get('tax_included_unit_price')):,.2f} 元"
        except (TypeError, ValueError):
            price_text = "—"
        price = QTableWidgetItem(price_text)
        price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, 0, contract)
        table.setItem(row, 1, price)
        table.setRowHeight(row, 30)

    if items:
        source_rows = int(result.get("source_row_count") or len(items))
        unique_results = int(result.get("unique_result_count") or len(items))
        suffix = "" if source_rows == unique_results else f"（源表 {source_rows} 行）"
        _set_history_price_state(
            window,
            f"完全匹配 {unique_results} 条{suffix}",
            "matched",
            "公司名称、规格型号和产品选型均与历史价格库完全一致。",
        )
    else:
        _set_history_price_state(
            window,
            "未找到完全匹配记录",
            "empty",
            "需要公司名称、规格型号和产品选型三项完全一致。",
        )


def _history_price_match_failed(window, message: str, serial: int) -> None:
    if serial != getattr(window, "_history_price_request_serial", 0):
        return
    table = getattr(window, "history_price_table", None)
    if isinstance(table, QTableWidget):
        table.setRowCount(0)
    _set_history_price_state(window, "历史价格读取失败", "error", str(message or ""))


def _request_history_price_match(window) -> None:
    window._history_price_request_serial = getattr(window, "_history_price_request_serial", 0) + 1
    serial = window._history_price_request_serial
    table = getattr(window, "history_price_table", None)
    payload = _history_price_match_payload(window)
    if payload is None:
        if isinstance(table, QTableWidget):
            table.setRowCount(0)
        _set_history_price_state(window, "等待完整输入", "muted", "请先选择公司和产品，并填写规格型号。")
        return

    worker_class = getattr(window, "_history_price_api_worker_class", None)
    base_url = getattr(window, "base_url", None)
    if not callable(worker_class) or not callable(base_url):
        _set_history_price_state(window, "历史价格接口不可用", "error")
        return

    _set_history_price_state(window, "正在精确匹配…", "loading")
    worker = worker_class(base_url() + "/api/history-prices/match", payload, window)
    workers = getattr(window, "_history_price_workers", None)
    if not isinstance(workers, dict):
        workers = {}
        window._history_price_workers = workers
    workers[serial] = worker

    def loaded(result, request_serial=serial):
        if request_serial != getattr(window, "_history_price_request_serial", 0):
            return
        _render_history_price_matches(window, result if isinstance(result, dict) else {})

    worker.succeeded.connect(loaded)
    worker.failed.connect(lambda message, request_serial=serial: _history_price_match_failed(
        window,
        message,
        request_serial,
    ))
    if hasattr(worker, "finished"):
        worker.finished.connect(lambda request_serial=serial: workers.pop(request_serial, None))
    worker.start()


def _ensure_history_price_panel(window, worker_class=None) -> None:
    if worker_class is not None:
        window._history_price_api_worker_class = worker_class
    if getattr(window, "history_price_table", None) is not None:
        return
    stack = getattr(window, "stack", None)
    if stack is None or stack.count() <= 1:
        return
    page = stack.widget(1)
    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is None or workspace.count() < 2:
        return
    result_panel = workspace.widget(1)
    result_layout = result_panel.layout()
    if result_layout is None:
        return

    card = QFrame(result_panel)
    card.setObjectName("historyPriceCard")
    card.setMinimumHeight(150)
    card.setMaximumHeight(210)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(7)

    header = QHBoxLayout()
    title = QLabel("历史价格", card)
    title.setObjectName("historyPriceTitle")
    state = QLabel("等待完整输入", card)
    state.setObjectName("historyPriceState")
    state.setProperty("tone", "muted")
    state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    header.addWidget(title)
    header.addStretch(1)
    header.addWidget(state)
    layout.addLayout(header)

    table = QTableWidget(0, 2, card)
    table.setObjectName("historyPriceTable")
    table.setHorizontalHeaderLabels(("钉钉合同号", "价格"))
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setAlternatingRowColors(True)
    table.setMinimumHeight(92)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    layout.addWidget(table)

    anchor = getattr(window, "risk_label", None)
    direct_child = anchor if isinstance(anchor, QWidget) else None
    while direct_child is not None and direct_child.parentWidget() is not result_panel:
        direct_child = direct_child.parentWidget()
    anchor_index = result_layout.indexOf(direct_child) if direct_child is not None else -1
    insert_at = anchor_index + 1 if anchor_index >= 0 else max(0, result_layout.count() - 2)
    result_layout.insertWidget(insert_at, card)

    window.history_price_card = card
    window.history_price_title = title
    window.history_price_state = state
    window.history_price_table = table
    window._history_price_request_serial = 0
    window._history_price_workers = {}

    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.setInterval(280)
    timer.timeout.connect(lambda: _request_history_price_match(window))
    window._history_price_timer = timer
    for widget, signal_name in (
        (getattr(window, "company_combo", None), "currentTextChanged"),
        (getattr(window, "product_combo", None), "currentTextChanged"),
        (getattr(window, "quote_spec_edit", None), "textChanged"),
    ):
        signal = getattr(widget, signal_name, None)
        if signal is not None:
            signal.connect(lambda *_args, match_timer=timer: match_timer.start())
    QTimer.singleShot(0, lambda: _request_history_price_match(window))


def _quote_layout_mode(window, workspace: QSplitter) -> str:
    page = window.stack.widget(1)
    available_width = max(0, workspace.width())
    if not window.isVisible() or not page.isVisible():
        available_width = max(0, window.width() - 204)
    if available_width >= QUOTE_WIDE_BREAKPOINT:
        return "wide"
    if available_width >= QUOTE_STACK_BREAKPOINT:
        return "medium"
    return "stacked"


def _configure_quote_header(window, mode: str) -> None:
    page = window.stack.widget(1)
    company = _find(page, QComboBox, "baseCompanyCombo")
    if company is not None:
        company.setMinimumWidth({"wide": 220, "medium": 180, "stacked": 140}[mode])
        company.setMaximumWidth(260 if mode == "wide" else 220)

    status = _find(page, QLabel, "serviceStatusBadge")
    if status is not None:
        status.setMinimumWidth(112)
        status.setMaximumWidth(140)


def _position_quote_action_dock(window) -> None:
    dock = getattr(window, "quote_action_dock", None)
    main_scroll = _find(window, QScrollArea, "mainScroll")
    stack = getattr(window, "stack", None)
    if dock is None or main_scroll is None or stack is None:
        return

    visible = stack.currentIndex() == 1 and main_scroll.viewport().isVisible()
    main_scroll.setViewportMargins(
        0,
        0,
        0,
        QUOTE_ACTION_DOCK_HEIGHT + 8 if visible else 0,
    )
    dock.setVisible(visible)
    if not visible:
        return

    page = stack.widget(1)
    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is None or workspace.count() < 2:
        dock.hide()
        return

    viewport = main_scroll.viewport()
    target = workspace
    origin = target.mapTo(main_scroll, QPoint(0, 0))
    left = max(8, origin.x())
    right_padding = 8
    width = min(target.width(), main_scroll.width() - left - right_padding)
    if width < 360:
        left = 8
        width = max(360, main_scroll.width() - 16)
    top = max(8, main_scroll.height() - QUOTE_ACTION_DOCK_HEIGHT - 4)
    dock.setGeometry(left, top, width, QUOTE_ACTION_DOCK_HEIGHT)
    dock.raise_()


def _ensure_quote_action_dock(window) -> None:
    if getattr(window, "quote_action_dock", None) is not None:
        _position_quote_action_dock(window)
        return

    main_scroll = _find(window, QScrollArea, "mainScroll")
    if main_scroll is None:
        return

    page = window.stack.widget(1)
    buttons = [
        _find(window, QPushButton, "primaryQuoteAction"),
        _find(window, QPushButton, "secondaryQuoteAction"),
        _find(window, QPushButton, "quietQuoteAction"),
    ]
    if any(button is None for button in buttons):
        return

    dock = QFrame(main_scroll)
    dock.setObjectName("quoteActionDock")
    dock.setFixedHeight(QUOTE_ACTION_DOCK_HEIGHT)
    layout = QHBoxLayout(dock)
    layout.setContentsMargins(10, 9, 10, 9)
    layout.setSpacing(8)

    label = QLabel("当前柜型操作", dock)
    label.setObjectName("quoteActionDockLabel")
    layout.addWidget(label)
    layout.addStretch(1)

    for button, minimum, maximum in zip(
        buttons,
        (200, 160, 110),
        (260, 210, 130),
    ):
        parent = button.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(button)
        button.setParent(dock)
        button.setMinimumHeight(40)
        button.setMaximumHeight(40)
        button.setMinimumWidth(minimum)
        button.setMaximumWidth(maximum)
        layout.addWidget(button)

    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is not None and workspace.count() >= 2:
        result_layout = workspace.widget(1).layout()
        if result_layout is not None:
            spacer = QWidget(workspace.widget(1))
            spacer.setObjectName("quoteActionDockSpacer")
            spacer.setFixedHeight(QUOTE_ACTION_DOCK_HEIGHT)
            result_layout.addWidget(spacer)
            window.quote_action_dock_spacer = spacer

    window.quote_action_dock = dock
    window.quote_action_dock_label = label
    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is not None:
        workspace.splitterMoved.connect(lambda *_args: _position_quote_action_dock(window))
    main_scroll.verticalScrollBar().valueChanged.connect(
        lambda *_args: _position_quote_action_dock(window)
    )
    main_scroll.horizontalScrollBar().valueChanged.connect(
        lambda *_args: _position_quote_action_dock(window)
    )
    window.stack.currentChanged.connect(
        lambda *_args: QTimer.singleShot(
            0,
            lambda: (
                _apply_quote_responsive_layout(window),
                _position_quote_action_dock(window),
            ),
        )
    )
    _position_quote_action_dock(window)


def _apply_quote_responsive_layout(window, *, force: bool = False) -> None:
    page = window.stack.widget(1)
    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is None or workspace.count() < 2:
        return

    mode = _quote_layout_mode(window, workspace)
    previous_mode = workspace.property("responsiveMode")
    input_panel, result_panel = workspace.widget(0), workspace.widget(1)

    workspace.setChildrenCollapsible(False)
    workspace.setHandleWidth(8)
    input_panel.setMaximumWidth(WIDGET_MAX)
    result_panel.setMaximumWidth(WIDGET_MAX)
    input_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    result_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    if mode == "wide":
        page.setMinimumHeight(0)
        workspace.setOrientation(Qt.Orientation.Horizontal)
        workspace.setMinimumHeight(0)
        input_panel.setMinimumWidth(620)
        result_panel.setMinimumWidth(560)
        input_panel.setMinimumHeight(0)
        result_panel.setMinimumHeight(0)
        workspace.setStretchFactor(0, 11)
        workspace.setStretchFactor(1, 9)
        target_sizes = [704, 576]
    elif mode == "medium":
        page.setMinimumHeight(0)
        workspace.setOrientation(Qt.Orientation.Horizontal)
        workspace.setMinimumHeight(0)
        input_panel.setMinimumWidth(520)
        result_panel.setMinimumWidth(500)
        input_panel.setMinimumHeight(0)
        result_panel.setMinimumHeight(0)
        workspace.setStretchFactor(0, 13)
        workspace.setStretchFactor(1, 12)
        target_sizes = [546, 504]
    else:
        page.setMinimumHeight(1220)
        workspace.setOrientation(Qt.Orientation.Vertical)
        workspace.setMinimumHeight(1118)
        input_panel.setMinimumWidth(0)
        result_panel.setMinimumWidth(0)
        input_panel.setMinimumHeight(590)
        result_panel.setMinimumHeight(520)
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 1)
        target_sizes = [590, 520]

    if force or previous_mode != mode:
        workspace.setSizes(target_sizes)
    workspace.setProperty("responsiveMode", mode)
    _configure_quote_header(window, mode)

    main_scroll = _find(window, QScrollArea, "mainScroll")
    if main_scroll is not None and main_scroll.widget() is not None:
        quote_is_current = window.stack.currentIndex() == 1
        window.stack.setMinimumHeight(
            1220 if mode == "stacked" and quote_is_current else 0
        )
        main_scroll.widget().setMinimumHeight(
            1250 if mode == "stacked" and quote_is_current else 0
        )
    QTimer.singleShot(0, lambda: _position_quote_action_dock(window))


def _refresh_quote_page(window) -> None:
    page = window.stack.widget(1)
    workspace = _find(page, QSplitter, "quoteWorkspace")
    if workspace is None or workspace.count() < 2:
        return

    for card_name in ("formulaCard", "quickCard"):
        card = _find(page, QFrame, card_name)
        if card is not None:
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            for spin in card.findChildren(QDoubleSpinBox):
                spin.setMinimumWidth(116)

    attachment_list = getattr(window, "attachment_list", None)
    if attachment_list is not None:
        attachment_list.setMaximumHeight(84)

    _ensure_quote_action_dock(window)
    _apply_quote_responsive_layout(window, force=True)


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
    multiplier.setFixedWidth(116)
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
QFrame#historyPriceCard {{
    background: {PAPER}; border: 1px solid {STEEL_LINE};
    border-left: 4px solid {BLUEPRINT}; border-radius: 7px;
}}
QLabel#historyPriceTitle {{ color: {GRAPHITE}; font-weight: 700; font-size: 11pt; }}
QLabel#historyPriceState {{ color: {MUTED_INK}; font-size: 9pt; }}
QLabel#historyPriceState[tone="matched"] {{ color: #246B49; font-weight: 600; }}
QLabel#historyPriceState[tone="loading"] {{ color: #24577B; }}
QLabel#historyPriceState[tone="error"] {{ color: #A33D32; }}
QTableWidget#historyPriceTable {{
    background: #FBFCFD; border: 1px solid #DDE3E8; border-radius: 4px;
    gridline-color: #E2E6EA; alternate-background-color: #F5F8FA;
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
QPushButton#addAttachmentCatalogButton {{
    background: {PAPER}; color: #145681; border: 1px solid #9CC7E2;
    border-radius: 6px; font-weight: 700; padding: 7px 12px;
}}
QPushButton#addAttachmentCatalogButton:hover {{ background: {BLUEPRINT_PALE}; }}
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
QSplitter#quoteWorkspace::handle:vertical {{
    background: {STEEL_LINE}; margin: 1px 8px; border-radius: 2px;
}}
QFrame#quoteActionDock {{
    background: {PAPER}; border: 1px solid #B8C7D3; border-radius: 8px;
}}
QLabel#quoteActionDockLabel {{ color: {MUTED_INK}; font-weight: 700; padding-left: 4px; }}
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

    window.setMinimumSize(980, 700)
    stack_host = window.stack.parentWidget()
    if stack_host is not None and stack_host.layout() is not None:
        stack_host.layout().setAlignment(window.stack, Qt.AlignmentFlag.AlignTop)
    nav = _find(window, QFrame, "navPanel")
    if nav is not None:
        nav.setFixedWidth(168)
        nav_hint = _find(nav, QLabel, "navHint")
        if nav_hint is not None:
            nav_hint.setText("QUOTE DESK")

    main_scroll = _find(window, QScrollArea, "mainScroll")
    if main_scroll is not None:
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = main_scroll.widget()
        if canvas is not None:
            canvas.setMinimumWidth(0)
            policy = canvas.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            canvas.setSizePolicy(policy)
            shell_layout = canvas.layout()
            if shell_layout is not None:
                shell_layout.setAlignment(window.stack, Qt.AlignmentFlag.AlignTop)

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


def _refresh_quick_discount_total(window, money) -> None:
    current = getattr(window, "current_result", {}) or {}
    quick = current.get("quick")
    labels = getattr(window, "quick_labels", {})
    discount_widget = getattr(window, "quick_discount", None)
    if not isinstance(quick, dict) or not isinstance(labels, dict) or "total" not in labels:
        return
    discount = _safe_float(getattr(discount_widget, "value", lambda: 1.0)())
    amount = quick_order_line_breakdown(
        quick,
        getattr(window, "attachments", []),
        1.0 if discount is None else discount,
        1,
        _ganged_count(window),
    )["line_total"]
    labels["total"].setText(money(amount))
    if "attachment" in labels:
        attachment_total = sum(
            effective_attachment_line_amount(item, 1, _ganged_count(window))
            for item in getattr(window, "attachments", []) if isinstance(item, dict)
        )
        labels["attachment"].setText(money(attachment_total))


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
            retained_product = getattr(
                self,
                "_persistent_product_selection",
                None,
            ) or _current_product_selection(self)
            result = original_reset(self, *args, **kwargs)
            _restore_product_selection(self, retained_product)
            self._formula_base_result = None
            self.attachment_default_opt_outs = set()
            self.attachment_default_quantity_overrides = set()
            self.attachment_door_transform_context = None
            self._attachment_default_door_counts = _current_door_counts(self)
            self.ganged_cabinets = []
            self.ganged_cabinet_count = 1
            self.ganged_cabinet_specification = ""
            panel = getattr(self, "ganged_cabinet_panel", None)
            label = getattr(self, "ganged_cabinet_label", None)
            if panel is not None:
                panel.hide()
            if label is not None:
                label.hide()
            _set_ganged_controls_enabled(self, False)
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
            _refresh_quick_discount_total(self, money)
            return

        labor = base_labor * multiplier
        management = labor * MANAGEMENT_FEE_RATE
        rendered = dict(base)
        rendered["labor_cost"] = labor
        rendered["management_fee"] = management
        rendered["total_cost"] = base_total - base_labor - base_management + labor + management

        self.current_result["formula"] = rendered
        original_refresh(self)
        area_value = _safe_float(rendered.get("product_area_m2"))
        if area_value is not None and "area" in labels:
            labels["area"].setText(f"{area_value:,.1f} m²")
        if _ganged_count(self) > 1:
            discount_widget = getattr(self, "formula_discount", None)
            formula_discount = discount_widget.value() if discount_widget is not None else 1.0
            formula_line = _formula_order_line_breakdown({
                "formula": rendered,
                "attachments": getattr(self, "attachments", []),
                "quantity": 1,
                "formula_discount": formula_discount,
                "ganged_cabinet_count": _ganged_count(self),
            })
            if "total" in labels:
                labels["total"].setText(money(formula_line["line_total"]))
            if "attachment" in labels:
                labels["attachment"].setText(money(formula_line["attachment_total"]))
        _refresh_quick_discount_total(self, money)

    main_window.refresh_discounted_totals = refresh_discounted_totals_with_labor

    original_add = getattr(main_window, "add_current_to_summary", None)
    if callable(original_add):
        def add_current_to_summary_with_labor_state(self):
            self.refresh_discounted_totals()
            base = getattr(self, "_formula_base_result", None)
            ganged_rows = _ganged_rows(self)
            ganged_specification = str(
                getattr(self, "ganged_cabinet_specification", "") or ""
            ).strip()
            default_opt_outs = set(getattr(self, "attachment_default_opt_outs", set()))
            quantity_overrides = set(
                getattr(self, "attachment_default_quantity_overrides", set())
            )
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
                item["attachment_default_opt_outs"] = sorted(default_opt_outs)
                item["attachment_default_quantity_overrides"] = sorted(
                    quantity_overrides
                )
                item["attachment_door_transform_context"] = getattr(
                    self, "attachment_door_transform_context", None
                )
                if len(ganged_rows) > 1:
                    item["specification"] = str(
                        ganged_specification
                        or item.get("model_code") or ""
                    ).strip()
                    item["ganged_cabinet_count"] = len(ganged_rows)
                    item["ganged_cabinets"] = ganged_rows
                self.refresh_summary()
            return result
        main_window.add_current_to_summary = add_current_to_summary_with_labor_state

    original_load = getattr(main_window, "load_draft_item", None)
    if callable(original_load):
        def load_draft_item_with_labor_state(self, item):
            restored_ganged_rows = [
                dict(row) for row in item.get("ganged_cabinets", [])
                if isinstance(row, dict)
            ] if isinstance(item, dict) else []
            base = item.get("formula_base") if isinstance(item, dict) else None
            if not isinstance(base, dict) and isinstance(item, dict):
                base = item.get("formula")
            self._formula_base_result = dict(base) if isinstance(base, dict) else None
            multiplier_widget = getattr(self, "labor_multiplier", None)
            if isinstance(multiplier_widget, QDoubleSpinBox):
                multiplier_widget.setValue(float(item.get("labor_multiplier", 1.0)))
            opt_outs = set(item.get("attachment_default_opt_outs", [])) if isinstance(item, dict) else set()
            quantity_overrides = (
                set(item.get("attachment_default_quantity_overrides", []))
                if isinstance(item, dict)
                else set()
            )
            self.attachment_default_opt_outs = opt_outs
            self.attachment_default_quantity_overrides = quantity_overrides
            self.attachment_door_transform_context = item.get(
                "attachment_door_transform_context"
            ) if isinstance(item, dict) else None
            result = original_load(self, item)
            if len(restored_ganged_rows) > 1:
                self.ganged_cabinets = restored_ganged_rows
                self.ganged_cabinet_count = len(restored_ganged_rows)
                self.ganged_cabinet_specification = str(
                    item.get("specification") or item.get("model_code") or ""
                ).strip()
                _set_ganged_controls_enabled(self, True)
                panel = getattr(self, "ganged_cabinet_panel", None)
                label = getattr(self, "ganged_cabinet_label", None)
                if panel is not None:
                    panel.show()
                if label is not None:
                    label.show()
                _render_ganged_cabinet_table(self)
            self._formula_base_result = dict(base) if isinstance(base, dict) else None
            self.attachment_default_opt_outs = opt_outs
            self.attachment_default_quantity_overrides = quantity_overrides
            self.attachment_door_transform_context = item.get(
                "attachment_door_transform_context"
            ) if isinstance(item, dict) else None
            self._attachment_default_door_counts = _current_door_counts(self)
            self.refresh_discounted_totals()
            return result
        main_window.load_draft_item = load_draft_item_with_labor_state

    main_window._layout_refresh_discount_patched = True


def _attachment_api_url(dialog) -> str:
    base = str(getattr(dialog, "api_url", "") or "").rstrip("/")
    marker = base.find("/api/")
    if marker >= 0:
        base = base[:marker]
    return f"{base}/api/attachments/catalog"


def _new_optional_dimension(parent) -> QDoubleSpinBox:
    field = QDoubleSpinBox(parent)
    field.setRange(0, 1_000_000)
    field.setDecimals(2)
    field.setSpecialValueText("")
    field.setSuffix(" mm")
    return field


def _show_add_attachment_dialog(owner, namespace: dict) -> None:
    editor = QDialog(owner)
    editor.setWindowTitle("新增附件到附件库")
    editor.setMinimumWidth(460)
    root = QVBoxLayout(editor)
    root.setContentsMargins(18, 16, 18, 16)
    root.setSpacing(12)
    explanation = QLabel("保存后会立即加入附件库，下次打开也可继续使用。", editor)
    explanation.setWordWrap(True)
    root.addWidget(explanation)

    form = QFormLayout()
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    name = QLineEdit(editor)
    name.setPlaceholderText("必填")
    model = QLineEdit(editor)
    variant = QLineEdit(editor)
    width = _new_optional_dimension(editor)
    depth = _new_optional_dimension(editor)
    height = _new_optional_dimension(editor)
    price = QDoubleSpinBox(editor)
    price.setRange(0, 100_000_000)
    price.setDecimals(2)
    price.setPrefix("¥ ")
    unit = QLineEdit("元", editor)
    source = QLineEdit("人工新增", editor)
    notes = QLineEdit(editor)
    for caption, field in (
        ("附件名称 *", name),
        ("型号（可选）", model),
        ("变体（可选）", variant),
        ("宽度（可选）", width),
        ("深度（可选）", depth),
        ("高度（可选）", height),
        ("价格 *", price),
        ("单位", unit),
        ("来源", source),
        ("备注", notes),
    ):
        form.addRow(caption, field)
    root.addLayout(form)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
        parent=editor,
    )
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    save.setText("保存到附件库")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    root.addWidget(buttons)

    def submit():
        item_name = name.text().strip()
        if not item_name:
            name.setFocus()
            QMessageBox.warning(editor, "信息不完整", "请输入附件名称。")
            return
        payload = {
            "item_name": item_name,
            "model_code": model.text().strip() or None,
            "variant": variant.text().strip() or None,
            "width_mm": width.value() or None,
            "depth_mm": depth.value() or None,
            "height_mm": height.value() or None,
            "price": price.value(),
            "unit": unit.text().strip() or "元",
            "price_source": source.text().strip() or "人工新增",
            "notes": notes.text().strip() or None,
        }
        save.setEnabled(False)
        save.setText("正在保存…")
        try:
            header_builder = namespace.get("api_headers")
            headers = header_builder(True) if callable(header_builder) else {"Content-Type": "application/json"}
            request = urllib.request.Request(
                _attachment_api_url(owner),
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
            reload_catalog = getattr(owner, "reload_catalog", None)
            if callable(reload_catalog):
                reload_catalog()
            search = getattr(owner, "search_edit", None)
            if isinstance(search, QLineEdit):
                search.setText(item_name)
            editor.accept()
            created = bool(result.get("created")) if isinstance(result, dict) else True
            message = "已新增并保存到附件库。" if created else "附件库中已存在相同记录，已为你定位。"
            QMessageBox.information(owner, "附件库已更新", message)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            QMessageBox.critical(editor, "保存失败", f"附件服务返回错误：{detail}")
        except Exception as error:
            QMessageBox.critical(editor, "保存失败", f"无法保存附件：{error}")
        finally:
            save.setEnabled(True)
            save.setText("保存到附件库")

    save.clicked.connect(submit)
    buttons.rejected.connect(editor.reject)
    editor.exec()


def _install_attachment_catalog_addition(namespace: dict) -> None:
    dialog_class = namespace.get("AttachmentDialog")
    if dialog_class is None or getattr(dialog_class, "_catalog_addition_installed", False):
        return
    original_init = dialog_class.__init__

    def init_with_catalog_addition(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        button = QPushButton("新增附件到附件库", self)
        button.setObjectName("addAttachmentCatalogButton")
        button.setAccessibleName("新增附件到附件库")
        button.setToolTip("当当前附件库缺少所需附件时，永久新增一条记录")
        button.clicked.connect(lambda: _show_add_attachment_dialog(self, namespace))
        layout = self.layout()
        if layout is not None and hasattr(layout, "insertWidget"):
            layout.insertWidget(1, button, 0, Qt.AlignmentFlag.AlignRight)
        elif layout is not None:
            layout.addWidget(button)
        self.add_attachment_catalog_button = button

    dialog_class.__init__ = init_with_catalog_addition
    dialog_class._catalog_addition_installed = True


def _install_attachment_default_selection_filters(namespace: dict) -> None:
    """Add category drilling plus visible, reversible default selections."""

    dialog_class = namespace.get("AttachmentDialog")
    if dialog_class is None or getattr(dialog_class, "_default_selection_filters_installed", False):
        return

    original_init = dialog_class.__init__
    original_apply_filter = dialog_class.apply_filter
    original_rebuild_table = dialog_class.rebuild_table
    original_table_item_changed = dialog_class.table_item_changed
    original_accept_selection = dialog_class.accept_selection
    original_collect_attachments = dialog_class.collect_attachments

    category_rules = {
        "底座": DEFAULT_FIXED_BASE,
        "侧板": DEFAULT_JP_SIDE_PANEL,
        "灯开关": DEFAULT_LIGHT_SWITCH,
        "文件夹": DEFAULT_A4_FOLDER,
        "门限位器": DEFAULT_DOOR_LIMITER,
        "门加强筋": DEFAULT_DOOR_REINFORCEMENT,
        "接地线": DEFAULT_GROUND_WIRE,
        "铜排": DEFAULT_COPPER_BUSBAR,
    }

    def specification_text(self) -> str:
        parent = self.parentWidget()
        for name in ("quote_spec_edit", "model_edit"):
            field = getattr(parent, name, None) if parent is not None else None
            if isinstance(field, QLineEdit) and field.text().strip():
                return field.text().strip()
        return str(getattr(self, "default_match_specification", "") or "").strip()

    def selected_product_code(self) -> str:
        parent = self.parentWidget()
        getter = getattr(parent, "selected_product_code", None) if parent is not None else None
        if callable(getter):
            try:
                value = getter()
                if value:
                    return str(value)
            except (AttributeError, TypeError, ValueError):
                pass
        combo = getattr(parent, "product_combo", None) if parent is not None else None
        if isinstance(combo, QComboBox):
            return str(combo.currentData() or combo.currentText() or "")
        return str(getattr(parent, "product_code", "") or "") if parent is not None else ""

    def selected_door_counts(self) -> tuple[int, int]:
        parent = self.parentWidget()
        counts = _current_door_counts(parent) if parent is not None else None
        # Compatibility for isolated dialogs without a quote window: the
        # historical default was the ordinary 1/0 single-door case.
        return counts if counts is not None else (1, 0)

    def default_door_quantity(self, rule: str) -> int | None:
        if rule == DEFAULT_DOOR_REINFORCEMENT:
            return door_reinforcement_default_quantity(*selected_door_counts(self))
        return door_limiter_default_quantity(*selected_door_counts(self))

    def same_choice(self, left: dict, right: dict) -> bool:
        matcher = getattr(self, "_same_catalog_choice", None)
        if callable(matcher):
            return bool(matcher(left, right))
        left_id = left.get("attachment_price_id")
        right_id = right.get("attachment_price_id")
        if left_id is not None and right_id is not None:
            return str(left_id) == str(right_id)
        return (
            str(left.get("item_name") or "").strip() == str(right.get("item_name") or "").strip()
            and str(left.get("model_code") or "").strip() == str(right.get("model_code") or "").strip()
            and str(left.get("variant") or "").strip() == str(right.get("variant") or "").strip()
        )

    def target_dimensions(self) -> tuple[float, float, float] | None:
        value = getattr(self, "target_dimensions", None)
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return float(value[0]), float(value[1]), float(value[2])
            except (TypeError, ValueError):
                pass
        parsed = parse_base_specification(specification_text(self))
        if parsed is not None:
            return parsed[0], parsed[1], parsed[2]
        return None

    def size_target_for_source(self, source: dict) -> tuple[float, float, float] | None:
        if bool(source.get(GANGED_FIXED_BASE_MATCH_KEY)):
            parent = self.parentWidget()
            rows = _ganged_rows(parent) if parent is not None else []
            try:
                index = int(source.get(GANGED_FIXED_BASE_INDEX_KEY))
                row = rows[index]
                base_height = float(row["base_height_mm"])
                return float(row["width_mm"]), base_height, float(row["depth_mm"])
            except (IndexError, KeyError, TypeError, ValueError):
                return None
        dimensions = target_dimensions(self)
        if dimensions is None:
            return None
        if default_rule_for_item(source) == DEFAULT_FIXED_BASE:
            parsed = parse_base_specification(specification_text(self))
            if parsed is not None:
                return parsed[0], parsed[3], parsed[2]
        return dimensions

    def quick_match_source(self, source: dict) -> dict | None:
        target = size_target_for_source(self, source)
        return match_attachment_size(getattr(self, "catalog", []), source, target)

    def build_default_matches(self) -> dict[str, dict | None]:
        catalog = [item for item in getattr(self, "catalog", []) if isinstance(item, dict)]
        parsed = parse_base_specification(specification_text(self))
        dimensions = target_dimensions(self)
        parent = self.parentWidget()
        ganged_rows = _ganged_rows(parent) if parent is not None else []
        ganged_base_matches: list[dict | None] = []
        base = None
        if len(ganged_rows) > 1 and all(row.get("base_height_mm") not in (None, "") for row in ganged_rows):
            base_source = next(
                (item for item in catalog if default_rule_for_item(item) == DEFAULT_FIXED_BASE),
                None,
            )
            for index, row in enumerate(ganged_rows):
                target = (
                    float(row["width_mm"]),
                    float(row["base_height_mm"]),
                    float(row["depth_mm"]),
                )
                exact = match_fixed_base(catalog, target[0], target[2], target[1])
                source = exact or base_source
                matched = (
                    match_attachment_size(catalog, source, target)
                    if source is not None else None
                )
                if matched is not None:
                    matched[GANGED_FIXED_BASE_MATCH_KEY] = True
                    matched[GANGED_FIXED_BASE_INDEX_KEY] = index
                    matched["ganged_fixed_base_split_count"] = len(ganged_rows)
                    matched["ganged_fixed_base_specification"] = subcabinet_specification(row)
                    matched["quantity"] = 1
                ganged_base_matches.append(matched)
            base = next((item for item in ganged_base_matches if item is not None), None)
        elif parsed is not None:
            width, _height, depth = dimensions or parsed[:3]
            exact_base = match_fixed_base(catalog, width, depth, parsed[3])
            base = (
                match_attachment_size(catalog, exact_base, (width, parsed[3], depth))
                if exact_base is not None
                else None
            )
            if base is None:
                base_source = next(
                    (item for item in catalog if default_rule_for_item(item) == DEFAULT_FIXED_BASE),
                    None,
                )
                if base_source is not None:
                    base = match_attachment_size(catalog, base_source, (width, parsed[3], depth))
        side = None
        product_code = selected_product_code(self)
        if is_jp_product(product_code) and dimensions is not None:
            exact_side = match_jp_side_panel(catalog, dimensions[1], dimensions[2])
            side_source = exact_side or next(
                (item for item in catalog if default_rule_for_item(item) == DEFAULT_JP_SIDE_PANEL),
                None,
            )
            if side_source is not None:
                side = match_attachment_size(catalog, side_source, dimensions)
        matches = {
            DEFAULT_FIXED_BASE: base,
            DEFAULT_LIGHT_SWITCH: match_default_light_switch(catalog),
            DEFAULT_A4_FOLDER: match_default_a4_folder(catalog),
            DEFAULT_DOOR_LIMITER: match_default_door_limiter(catalog),
            DEFAULT_DOOR_REINFORCEMENT: match_default_door_reinforcement(catalog),
            DEFAULT_GROUND_WIRE: match_default_ground_wire(catalog),
            DEFAULT_COPPER_BUSBAR: match_default_copper_busbar(catalog),
            DEFAULT_JP_SIDE_PANEL: side,
        }
        door_counts = selected_door_counts(self)
        self.default_ganged_fixed_base_matches = tuple(ganged_base_matches)
        if len(ganged_rows) > 1:
            transform_names = []
            transform_matches = {}
            door_context = []
            for row in ganged_rows:
                counts = (
                    int(row.get("single_door_count", 1)),
                    int(row.get("double_door_count", 0)),
                )
                door_context.append(counts)
                for name in door_transformation_default_names(product_code, *counts):
                    if name not in transform_names:
                        transform_names.append(name)
                for rule, candidate in match_door_transformation_defaults(
                    catalog, product_code, *counts
                ).items():
                    transform_matches.setdefault(rule, candidate)
            self.default_door_transformation_names = tuple(transform_names)
            matches.update(transform_matches)
            self.default_match_door_counts = tuple(door_context)
        else:
            self.default_door_transformation_names = door_transformation_default_names(
                product_code, *door_counts
            )
            matches.update(match_door_transformation_defaults(
                catalog, product_code, *door_counts
            ))
            self.default_match_door_counts = door_counts
        self.default_match_spec = parsed
        self.default_match_dimensions = dimensions
        self.default_match_product_code = product_code
        self.default_door_limiter_quantity = default_door_quantity(self, DEFAULT_DOOR_LIMITER)
        self.default_door_reinforcement_quantity = default_door_quantity(
            self, DEFAULT_DOOR_REINFORCEMENT
        )
        self.default_matches = matches
        return matches

    def prepare_default_selections(self) -> int:
        matches = build_default_matches(self)
        opt_outs = getattr(self, "default_selection_opt_outs", set())
        selected_items = [item for item in getattr(self, "attachments", []) if isinstance(item, dict)]
        added = 0
        ganged_base_matches = [
            candidate for candidate in getattr(self, "default_ganged_fixed_base_matches", ())
            if isinstance(candidate, dict)
        ]
        if ganged_base_matches:
            manual_bases = [
                item for item in selected_items
                if default_rule_for_item(item) == DEFAULT_FIXED_BASE
                and not bool(item.get(GANGED_FIXED_BASE_MATCH_KEY))
            ]
            existing_by_index = {
                int(item.get(GANGED_FIXED_BASE_INDEX_KEY)): item
                for item in selected_items
                if default_rule_for_item(item) == DEFAULT_FIXED_BASE
                and bool(item.get(GANGED_FIXED_BASE_MATCH_KEY))
                and str(item.get(GANGED_FIXED_BASE_INDEX_KEY, "")).isdigit()
            }
            retained = [
                item for item in selected_items
                if not (
                    default_rule_for_item(item) == DEFAULT_FIXED_BASE
                    and bool(item.get(GANGED_FIXED_BASE_MATCH_KEY))
                )
            ]
            if DEFAULT_FIXED_BASE not in opt_outs and not manual_bases:
                for candidate in ganged_base_matches:
                    index = int(candidate[GANGED_FIXED_BASE_INDEX_KEY])
                    existing = existing_by_index.get(index)
                    expected_target = tuple(
                        candidate.get(key) for key in (
                            "size_match_target_width_mm",
                            "size_match_target_height_mm",
                            "size_match_target_depth_mm",
                        )
                    )
                    existing_target = tuple(
                        (existing or {}).get(key) for key in (
                            "size_match_target_width_mm",
                            "size_match_target_height_mm",
                            "size_match_target_depth_mm",
                        )
                    )
                    chosen = existing if existing is not None and existing_target == expected_target else dict(candidate)
                    retained.append(chosen)
                    if existing is None:
                        added += 1
            self.attachments = retained
            selected_items = retained
        else:
            stale_ids = {
                id(item) for item in selected_items
                if bool(item.get(GANGED_FIXED_BASE_MATCH_KEY))
            }
            if stale_ids:
                self.attachments = [item for item in selected_items if id(item) not in stale_ids]
                selected_items = list(self.attachments)
        for rule, candidate in matches.items():
            if rule == DEFAULT_FIXED_BASE and ganged_base_matches:
                continue
            if candidate is None or rule in opt_outs:
                continue
            if any(default_rule_for_item(item) == rule for item in selected_items):
                continue
            selected = dict(candidate)
            if rule in (DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT):
                quantity = default_door_quantity(self, rule)
                if quantity is None:
                    continue
                selected["quantity"] = quantity
            else:
                selected["quantity"] = 1
            self.attachments.append(selected)
            selected_items.append(selected)
            added += 1
        return added

    def rematch_selected_for_dimensions(self) -> int:
        """Re-match selected sized items only when the true W/H/D target changed."""

        changed = 0
        rematched = []
        for selected in getattr(self, "attachments", []):
            if not isinstance(selected, dict) or size_match_group_key(selected) is None:
                rematched.append(selected)
                continue
            target = size_target_for_source(self, selected)
            if target is None:
                rematched.append(selected)
                continue
            stored_target = tuple(
                selected.get(key)
                for key in (
                    "size_match_target_width_mm",
                    "size_match_target_height_mm",
                    "size_match_target_depth_mm",
                )
            )
            try:
                target_unchanged = all(
                    value is not None and abs(float(value) - target[index]) <= 0.0001
                    for index, value in enumerate(stored_target)
                )
            except (TypeError, ValueError):
                target_unchanged = False
            if target_unchanged:
                rematched.append(selected)
                continue
            matched = match_attachment_size(getattr(self, "catalog", []), selected, target)
            if matched is None:
                rematched.append(selected)
                continue
            matched["quantity"] = selected.get("quantity", 1)
            for key in (
                GANGED_FIXED_BASE_MATCH_KEY,
                GANGED_FIXED_BASE_INDEX_KEY,
                "ganged_fixed_base_split_count",
                "ganged_fixed_base_specification",
            ):
                if selected.get(key) is not None:
                    matched[key] = selected[key]
            rematched.append(matched)
            changed += 1
        if changed:
            self.attachments = rematched
        return changed

    def checked_sources(self, rule: str) -> list[dict]:
        table = getattr(self, "table", None)
        if not isinstance(table, QTableWidget):
            return [
                item for item in getattr(self, "attachments", [])
                if isinstance(item, dict) and default_rule_for_item(item) == rule
            ]
        result = []
        for row in range(table.rowCount()):
            check_item = table.item(row, self.COL_CHECK)
            if check_item is None or check_item.checkState() != Qt.CheckState.Checked:
                continue
            source = check_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(source, dict) and default_rule_for_item(source) == rule:
                result.append(source)
        return result

    def is_installation_board(source: dict | None) -> bool:
        item = source or {}
        combined = " ".join(
            str(item.get(key) or "")
            for key in (
                "category_level1", "category_level2", "category_level3",
                "item_name", "model_code",
            )
        )
        return "安装板" in combined and "安装板单发" not in combined

    def checked_sources_for_category(self, category: str) -> list[dict]:
        table = getattr(self, "table", None)
        if not isinstance(table, QTableWidget):
            return [
                item for item in getattr(self, "attachments", [])
                if isinstance(item, dict) and attachment_category_value(item, 0) == category
            ]
        result = []
        for row in range(table.rowCount()):
            check_item = table.item(row, self.COL_CHECK)
            if check_item is None or check_item.checkState() != Qt.CheckState.Checked:
                continue
            source = check_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(source, dict) and attachment_category_value(source, 0) == category:
                result.append(source)
        return result

    def selected_summary(items: list[dict]) -> str:
        names = []
        for item in items:
            name = str(item.get("item_name") or item.get("model_code") or "未命名附件").strip()
            if name and name not in names:
                names.append(name)
        if not names:
            return ""
        return names[0] if len(names) == 1 else f"{names[0]}等 {len(names)} 项"

    def installation_board_price_sign(self) -> int:
        try:
            return -1 if int(getattr(self, "installation_board_sign", 1)) == -1 else 1
        except (TypeError, ValueError):
            return 1

    def stored_attachment_price_sign(item: dict | None) -> int:
        try:
            return -1 if int((item or {}).get("attachment_price_sign", 1)) == -1 else 1
        except (TypeError, ValueError):
            return 1

    def apply_installation_board_sign(self, source: dict, price_cell=None) -> dict:
        signed = dict(source)
        sign = installation_board_price_sign(self)
        signed["attachment_price_sign"] = sign
        if price_cell is not None:
            try:
                price = abs(float(price_cell.text().strip()))
                price_cell.setText(f"{price * sign:g}")
            except (AttributeError, TypeError, ValueError):
                pass
        return signed

    def toggle_installation_board_sign(self) -> None:
        self.installation_board_sign = -installation_board_price_sign(self)
        table = getattr(self, "table", None)
        if isinstance(table, QTableWidget):
            self._default_selection_guard = True
            table.blockSignals(True)
            try:
                for row in range(table.rowCount()):
                    check_item = table.item(row, self.COL_CHECK)
                    source = check_item.data(Qt.ItemDataRole.UserRole) if check_item else None
                    if (
                        check_item is None
                        or check_item.checkState() != Qt.CheckState.Checked
                        or not isinstance(source, dict)
                        or not is_installation_board(source)
                    ):
                        continue
                    price_cell = table.item(row, self.COL_PRICE)
                    check_item.setData(
                        Qt.ItemDataRole.UserRole,
                        apply_installation_board_sign(self, source, price_cell),
                    )
            finally:
                table.blockSignals(False)
                self._default_selection_guard = False
        sync_attachments_from_table(self)
        refresh_category_browser(self)

    def default_card_state(self, option: dict) -> tuple[str, str, str, str | None, bool]:
        if getattr(self, "category_selection", []):
            return "快速匹配\n待配置", "attachmentQuickMatch", "该分类尚未配置快速匹配规则", None, False
        category_name = str(option.get("value") or "")
        if category_name == "门变形":
            selected = checked_sources_for_category(self, category_name)
            wanted = tuple(getattr(self, "default_door_transformation_names", ()))
            if selected:
                summary = selected_summary(selected)
                return (
                    f"快速匹配已选择\n{summary}",
                    "attachmentQuickMatchSelected",
                    "按当前产品家族和门数组合选择；进入分类可人工修改",
                    None,
                    True,
                )
            if not wanted:
                return (
                    "快速匹配\n无需门变形",
                    "attachmentQuickMatch",
                    "当前产品家族和门数组合不需要门变形附件",
                    None,
                    False,
                )
            return (
                "默认选择未匹配\n" + "、".join(wanted),
                "attachmentQuickMatchMissing",
                "附件库中没有匹配当前门数组合的门变形附件，或已被人工取消",
                None,
                False,
            )
        rule = category_rules.get(category_name)
        if rule is None:
            selected = checked_sources_for_category(self, str(option.get("value") or ""))
            if selected:
                summary = selected_summary(selected)
                return (
                    f"人工已选择\n{summary}",
                    "attachmentQuickMatchManual",
                    "当前附件由人工选择；返回分类可继续修改",
                    None,
                    True,
                )
            return "快速匹配\n待配置", "attachmentQuickMatch", "该分类尚未配置快速匹配规则", None, False

        parsed = getattr(self, "default_match_spec", None)
        dimensions = getattr(self, "default_match_dimensions", None)
        product_code = getattr(self, "default_match_product_code", "")
        candidate = getattr(self, "default_matches", {}).get(rule)
        detail = ""
        missing_tip = "附件库中没有唯一匹配项"
        if rule == DEFAULT_FIXED_BASE:
            if parsed is None:
                return "快速匹配\n无需底座", "attachmentQuickMatch", "规格高度没有括号和 +，不自动选择底座", rule, False
            ganged_candidates = [
                item for item in getattr(self, "default_ganged_fixed_base_matches", ())
                if isinstance(item, dict)
            ]
            ganged_rows = _ganged_rows(self.parentWidget())
            if len(ganged_rows) > 1:
                detail = f"固定 · {len(ganged_candidates)}/{len(ganged_rows)} 个子柜分别匹配"
                missing_tip = "部分子柜在附件库中没有可安全匹配的固定底座"
            else:
                detail = f"固定 · 高 {parsed[3]:g} mm"
                missing_tip = "附件库中没有与当前宽度、深度和底座高度完全一致的固定底座"
        elif rule == DEFAULT_LIGHT_SWITCH:
            detail = "灯开关"
        elif rule == DEFAULT_A4_FOLDER:
            detail = "A4资料盒"
        elif rule == DEFAULT_DOOR_LIMITER:
            quantity = getattr(self, "default_door_limiter_quantity", None)
            if quantity is None:
                return (
                    "默认选择未配置\n门限位器",
                    "attachmentQuickMatchMissing",
                    "当前门型组合没有门限位器默认数量规则",
                    rule,
                    False,
                )
            detail = f"门限位器 · 数量：{quantity} 个"
        elif rule == DEFAULT_DOOR_REINFORCEMENT:
            quantity = getattr(self, "default_door_reinforcement_quantity", None)
            if quantity is None:
                return (
                    "默认选择未配置\n门加强筋",
                    "attachmentQuickMatchMissing",
                    "当前门型组合没有门加强筋默认数量规则",
                    rule,
                    False,
                )
            detail = f"门加强筋 · 数量：{quantity} 个"
        elif rule == DEFAULT_GROUND_WIRE:
            detail = "红绿线"
        elif rule == DEFAULT_COPPER_BUSBAR:
            detail = "铜排 · 默认数量：1 件"
        elif rule == DEFAULT_JP_SIDE_PANEL:
            if not is_jp_product(product_code):
                return "快速匹配\n仅 JP 默认匹配", "attachmentQuickMatch", "当前产品不是 JP，不自动选择侧板", rule, False
            if dimensions is not None:
                detail = f"JP侧板 · {dimensions[1]:g}×{dimensions[2]:g} mm"
            else:
                detail = "JP侧板 · 尺寸无效"
            missing_tip = "附件库中没有与当前柜体高度、深度完全一致的唯一侧板"

        if rule == DEFAULT_FIXED_BASE and len(_ganged_rows(self.parentWidget())) > 1:
            expected = [
                item for item in getattr(self, "default_ganged_fixed_base_matches", ())
                if isinstance(item, dict)
            ]
            selected = checked_sources(self, rule)
            selected_by_index = {
                int(item.get(GANGED_FIXED_BASE_INDEX_KEY)): item
                for item in selected
                if bool(item.get(GANGED_FIXED_BASE_MATCH_KEY))
                and str(item.get(GANGED_FIXED_BASE_INDEX_KEY, "")).isdigit()
            }
            all_selected = bool(expected) and all(
                int(item[GANGED_FIXED_BASE_INDEX_KEY]) in selected_by_index
                and same_choice(
                    self,
                    selected_by_index[int(item[GANGED_FIXED_BASE_INDEX_KEY])],
                    item,
                )
                for item in expected
            )
            if all_selected and len(expected) == len(_ganged_rows(self.parentWidget())):
                return f"默认已选择\n{detail}", "attachmentQuickMatchSelected", "每个子柜分别匹配一只底座；最终数量只乘整套柜体数量", rule, True
            if selected:
                return "人工已选择\n底座", "attachmentQuickMatchManual", "当前底座由人工选择；单击恢复各子柜快速匹配", rule, True
            if expected:
                return f"默认选择已取消\n{detail}", "attachmentQuickMatchCancelled", "已取消各子柜底座；单击可恢复", rule, True
            return f"默认选择未匹配\n{detail}", "attachmentQuickMatchMissing", missing_tip, rule, False
        if candidate is None:
            return f"默认选择未匹配\n{detail}", "attachmentQuickMatchMissing", missing_tip, rule, False
        selected = checked_sources(self, rule)
        if any(same_choice(self, item, candidate) for item in selected):
            if rule == DEFAULT_COPPER_BUSBAR:
                selected_attachment = next(
                    (
                        item for item in getattr(self, "attachments", [])
                        if isinstance(item, dict) and default_rule_for_item(item) == rule
                    ),
                    {},
                )
                quantity = selected_attachment.get("quantity", 1)
                if str(quantity) not in {"1", "1.0"}:
                    return (
                        f"人工数量\n铜排 · 数量：{quantity} 件",
                        "attachmentQuickMatchManual",
                        "当前数量由人工修改；进入分类可继续修改或取消",
                        rule,
                        True,
                    )
            if rule in getattr(self, "default_quantity_manual_overrides", set()):
                selected_attachment = next(
                    (
                        item for item in getattr(self, "attachments", [])
                        if isinstance(item, dict) and default_rule_for_item(item) == rule
                    ),
                    {},
                )
                quantity = selected_attachment.get("quantity", 1)
                label = "门加强筋" if rule == DEFAULT_DOOR_REINFORCEMENT else "门限位器"
                return (
                    f"人工数量\n{label} · 数量：{quantity} 个",
                    "attachmentQuickMatchManual",
                    "当前数量由人工修改；单击恢复系统默认",
                    rule,
                    True,
                )
            return f"默认已选择\n{detail}", "attachmentQuickMatchSelected", "已默认选择；单击可取消", rule, True
        if selected:
            item_name = str(selected[0].get("item_name") or "人工选择")
            return f"人工已选择\n{item_name}", "attachmentQuickMatchManual", "当前使用人工选择；单击恢复系统默认", rule, True
        return f"默认选择已取消\n{detail}", "attachmentQuickMatchCancelled", "已取消默认选择；单击可恢复", rule, True

    def set_checked_for_rule(self, rule: str, candidate: dict | None) -> None:
        table = getattr(self, "table", None)
        if not isinstance(table, QTableWidget):
            return
        self._default_selection_guard = True
        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                check_item = table.item(row, self.COL_CHECK)
                source = check_item.data(Qt.ItemDataRole.UserRole) if check_item else None
                if not isinstance(source, dict) or default_rule_for_item(source) != rule:
                    continue
                should_check = candidate is not None and same_choice(self, source, candidate)
                if should_check:
                    check_item.setData(Qt.ItemDataRole.UserRole, dict(candidate))
                check_item.setCheckState(Qt.CheckState.Checked if should_check else Qt.CheckState.Unchecked)
        finally:
            table.blockSignals(False)
            self._default_selection_guard = False
        self.update_selection_hint()

    def set_default_quantity_for_rule(self, rule: str) -> None:
        if rule not in (DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT):
            return
        quantity = default_door_quantity(self, rule)
        candidate = getattr(self, "default_matches", {}).get(rule)
        table = getattr(self, "table", None)
        if quantity is None or candidate is None or not isinstance(table, QTableWidget):
            return
        self._default_selection_guard = True
        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                check_item = table.item(row, self.COL_CHECK)
                source = check_item.data(Qt.ItemDataRole.UserRole) if check_item else None
                if (
                    check_item is not None
                    and check_item.checkState() == Qt.CheckState.Checked
                    and isinstance(source, dict)
                    and same_choice(self, source, candidate)
                ):
                    quantity_item = table.item(row, self.COL_QUANTITY)
                    if quantity_item is not None:
                        quantity_item.setText(str(quantity))
        finally:
            table.blockSignals(False)
            self._default_selection_guard = False

    def sync_attachments_from_table(self) -> None:
        collector = getattr(self, "collect_attachments", None)
        if not callable(collector):
            return
        current = collector(show_errors=False)
        if current is not None:
            self.attachments = current

    def toggle_default_selection(self, rule: str) -> None:
        if rule == DEFAULT_FIXED_BASE:
            ganged_candidates = [
                dict(item) for item in getattr(self, "default_ganged_fixed_base_matches", ())
                if isinstance(item, dict)
            ]
            if ganged_candidates:
                selected = checked_sources(self, rule)
                if selected:
                    self.attachments = [
                        item for item in getattr(self, "attachments", [])
                        if not (isinstance(item, dict) and default_rule_for_item(item) == rule)
                    ]
                    self.default_selection_opt_outs.add(rule)
                else:
                    self.attachments = [
                        item for item in getattr(self, "attachments", [])
                        if not (isinstance(item, dict) and default_rule_for_item(item) == rule)
                    ] + ganged_candidates
                    self.default_selection_opt_outs.discard(rule)
                self.default_quantity_manual_overrides.discard(rule)
                self.rebuild_table()
                return
        candidate = getattr(self, "default_matches", {}).get(rule)
        if candidate is None:
            return
        selected = checked_sources(self, rule)
        default_is_selected = any(same_choice(self, item, candidate) for item in selected)
        if (
            default_is_selected
            and rule in getattr(self, "default_quantity_manual_overrides", set())
        ):
            self.default_selection_opt_outs.discard(rule)
            self.default_quantity_manual_overrides.discard(rule)
            set_default_quantity_for_rule(self, rule)
        elif default_is_selected:
            set_checked_for_rule(self, rule, None)
            self.default_selection_opt_outs.add(rule)
            self.default_quantity_manual_overrides.discard(rule)
        else:
            set_checked_for_rule(self, rule, candidate)
            self.default_selection_opt_outs.discard(rule)
            self.default_quantity_manual_overrides.discard(rule)
            set_default_quantity_for_rule(self, rule)
        sync_attachments_from_table(self)
        refresh_category_browser(self)

    def apply_classification_filter(self, text: str):
        if not hasattr(self, "category_selection"):
            return original_apply_filter(self, text)
        needle = str(text or "").strip().casefold()
        selected = tuple(self.category_selection)
        table = getattr(self, "table", None)
        if not isinstance(table, QTableWidget):
            return original_apply_filter(self, text)
        for row in range(table.rowCount()):
            check_item = table.item(row, self.COL_CHECK)
            source = check_item.data(Qt.ItemDataRole.UserRole) if check_item else {}
            source = source if isinstance(source, dict) else {}
            path = attachment_category_path(source)
            category_matches = path[:len(selected)] == selected
            table_text = [
                table.item(row, column).text()
                for column in (self.COL_NAME, self.COL_SPEC, self.COL_SCHEME, self.COL_PRICE)
                if table.item(row, column) is not None
            ]
            haystack = " ".join([
                *path,
                str(source.get("item_name") or ""),
                str(source.get("model_code") or ""),
                str(source.get("variant") or ""),
                *table_text,
            ]).casefold()
            table.setRowHidden(row, not category_matches or bool(needle and needle not in haystack))
        options = category_options(getattr(self, "catalog", []), selected)
        show_table = bool(needle) or not bool(options)
        scroll = getattr(self, "category_scroll", None)
        if isinstance(scroll, QScrollArea):
            scroll.setVisible(not show_table)
        table.setVisible(show_table)

    def clear_category_cards(self):
        grid = getattr(self, "category_grid", None)
        if not isinstance(grid, QGridLayout):
            return
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def refresh_category_browser(self):
        catalog = [item for item in getattr(self, "catalog", []) if isinstance(item, dict)]
        for item in catalog:
            for level, key in enumerate(("category_level1", "category_level2", "category_level3")):
                item[key] = attachment_category_value(item, level)
        self.category_selection = valid_selection_prefix(catalog, getattr(self, "category_selection", []))
        clear_category_cards(self)
        options = category_options(catalog, self.category_selection)
        labels = [value or "本级附件" for value in self.category_selection]
        breadcrumb = "附件库"
        if labels:
            breadcrumb += "  ›  " + "  ›  ".join(labels)
        level_label = ('一', '二', '三')[len(self.category_selection)] if len(self.category_selection) < 3 else '三'
        breadcrumb += f"  /  选择{level_label}级分类" if options else "  /  选择具体附件"
        self.category_breadcrumb.setText(breadcrumb)
        self.category_back_button.setVisible(bool(self.category_selection))
        self.category_back_button.setEnabled(bool(self.category_selection))

        for index, option in enumerate(options):
            card = QFrame(self.category_scroll_content)
            card.setObjectName("attachmentCategoryCardShell")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)
            button = QPushButton(f"{option['label']}\n{option['count']} 项", card)
            button.setObjectName("attachmentCategoryCard")
            button.setAccessibleName(f"{option['label']}，{option['count']}项")
            button.setToolTip(f"进入“{option['label']}”")
            button.setMinimumHeight(64)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=option["value"]: open_attachment_category(self, value))

            text, object_name, tooltip, rule, enabled = default_card_state(self, option)
            quick_button = QPushButton(text, card)
            quick_button.setObjectName(object_name)
            quick_button.setAccessibleName(f"{option['label']}，{text.replace(chr(10), '，')}")
            quick_button.setToolTip(tooltip)
            quick_button.setEnabled(enabled)
            quick_button.setMinimumHeight(54 if text.count("\n") == 1 else 70)
            quick_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if rule is not None and enabled:
                quick_button.clicked.connect(lambda _checked=False, value=rule: toggle_default_selection(self, value))
            card_layout.addWidget(button)
            if str(option.get("value") or "") == "安装板":
                quick_row = QHBoxLayout()
                quick_row.setContentsMargins(0, 0, 8, 0)
                quick_row.setSpacing(6)
                quick_row.addWidget(quick_button, 1)
                sign = installation_board_price_sign(self)
                sign_button = QPushButton("−" if sign < 0 else "+", card)
                sign_button.setObjectName(
                    "attachmentPriceSignNegative" if sign < 0 else "attachmentPriceSignPositive"
                )
                sign_button.setAccessibleName("安装板价格减项" if sign < 0 else "安装板价格加项")
                sign_button.setToolTip(
                    "当前安装板按负值计价；单击恢复加项"
                    if sign < 0 else "当前安装板按正值计价；单击切换为减项"
                )
                sign_button.setFixedSize(34, 34)
                sign_button.clicked.connect(lambda: toggle_installation_board_sign(self))
                quick_row.addWidget(sign_button, 0, Qt.AlignmentFlag.AlignVCenter)
                card_layout.addLayout(quick_row)
            else:
                card_layout.addWidget(quick_button)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.category_grid.addWidget(card, index // 4, index % 4)

        needle = self.search_edit.text().strip()
        at_category_level = bool(options)
        show_table = bool(needle) or not at_category_level
        self.category_scroll.setVisible(not show_table)
        self.search_edit.setVisible(True)
        self.table.setVisible(show_table)
        if show_table:
            apply_classification_filter(self, needle)
        hint = getattr(self, "catalog_hint", None)
        if catalog and isinstance(hint, QLabel):
            level1_count = len({attachment_category_value(item, 0) for item in catalog})
            hint.setText(
                f"已读取 {len(catalog)} 条附件价格，覆盖 {level1_count} 个一级分类。"
                "绿色默认项已自动勾选；单击默认项可取消，进入分类可人工改选。"
            )

    def open_attachment_category(self, value: str):
        self.category_selection.append(str(value))
        self.search_edit.clear()
        refresh_category_browser(self)

    def back_attachment_category(self):
        if self.category_selection:
            self.category_selection.pop()
        self.search_edit.clear()
        refresh_category_browser(self)

    def restore_ganged_fixed_base_rows(self) -> None:
        """Restore per-child metadata after the legacy table rebuild.

        The recovered table identifies checked rows by catalogue identity and
        may replace the selection snapshot with the raw catalogue record.
        Ganged bases need their child index and target dimensions to survive
        collection, costing and export, including when two children resolve to
        the same catalogue row.
        """

        selections = [
            item for item in getattr(self, "attachments", [])
            if isinstance(item, dict) and bool(item.get(GANGED_FIXED_BASE_MATCH_KEY))
        ]
        table = getattr(self, "table", None)
        if not selections or not isinstance(table, QTableWidget):
            return
        used_rows: set[int] = set()
        self._default_selection_guard = True
        table.blockSignals(True)
        try:
            for selected in selections:
                target_row = next(
                    (
                        row for row in range(table.rowCount())
                        if row not in used_rows
                        and isinstance(
                            table.item(row, self.COL_CHECK).data(Qt.ItemDataRole.UserRole)
                            if table.item(row, self.COL_CHECK) is not None else None,
                            dict,
                        )
                        and same_choice(
                            self,
                            selected,
                            table.item(row, self.COL_CHECK).data(Qt.ItemDataRole.UserRole),
                        )
                    ),
                    None,
                )
                if target_row is None:
                    append_row = getattr(self, "_append_row", None)
                    if callable(append_row):
                        append_row(selected, selected, historical=True)
                        target_row = table.rowCount() - 1
                if target_row is None:
                    continue
                used_rows.add(target_row)
                check_item = table.item(target_row, self.COL_CHECK)
                check_item.setData(Qt.ItemDataRole.UserRole, dict(selected))
                check_item.setCheckState(Qt.CheckState.Checked)
                quantity_item = table.item(target_row, self.COL_QUANTITY)
                if quantity_item is not None:
                    quantity_item.setText(str(selected.get("quantity", 1)))
                price_item = table.item(target_row, self.COL_PRICE)
                price = selected.get(
                    "unit_price_override",
                    selected.get("matched_price", selected.get("price")),
                )
                if price_item is not None and price is not None:
                    price_item.setText(f"{float(price):g}")
        finally:
            table.blockSignals(False)
            self._default_selection_guard = False
        self.update_selection_hint()

    def rebuild_table_with_defaults(self):
        if hasattr(self, "category_selection"):
            rematch_selected_for_dimensions(self)
            prepare_default_selections(self)
        result = original_rebuild_table(self)
        if hasattr(self, "category_selection"):
            restore_ganged_fixed_base_rows(self)
            refresh_category_browser(self)
        return result

    def table_item_changed_with_defaults(self, item):
        if getattr(self, "_default_selection_guard", False):
            return original_table_item_changed(self, item)
        quick_match_notice = ""
        if item.column() == self.COL_CHECK:
            source = item.data(Qt.ItemDataRole.UserRole)
            if (
                item.checkState() == Qt.CheckState.Checked
                and isinstance(source, dict)
                and size_match_group_key(source) is not None
            ):
                matched = quick_match_source(self, source)
                if matched is not None:
                    target_item = item
                    matched_id = matched.get("attachment_price_id")
                    self._default_selection_guard = True
                    self.table.blockSignals(True)
                    try:
                        for row in range(self.table.rowCount()):
                            candidate_item = self.table.item(row, self.COL_CHECK)
                            candidate_source = (
                                candidate_item.data(Qt.ItemDataRole.UserRole)
                                if candidate_item is not None else None
                            )
                            if not isinstance(candidate_source, dict):
                                continue
                            same_group = size_match_group_key(candidate_source) == size_match_group_key(source)
                            same_record = (
                                matched_id is not None
                                and str(candidate_source.get("attachment_price_id")) == str(matched_id)
                            ) or same_choice(self, matched, candidate_source)
                            if same_record:
                                target_item = candidate_item
                            elif same_group:
                                candidate_item.setCheckState(Qt.CheckState.Unchecked)
                        target_item.setData(Qt.ItemDataRole.UserRole, dict(matched))
                        target_item.setCheckState(Qt.CheckState.Checked)
                        price_cell = self.table.item(target_item.row(), self.COL_PRICE)
                        price = matched.get(
                            "unit_price_override",
                            matched.get("matched_price", matched.get("price")),
                        )
                        if price_cell is not None:
                            if price is not None:
                                price_cell.setText(f"{float(price):g}")
                            else:
                                price_cell.setText(str(matched.get("price_text") or matched.get("price") or ""))
                            warning = str(matched.get("size_match_warning") or "")
                            price_cell.setToolTip(warning)
                        warning = str(matched.get("size_match_warning") or "")
                        if warning:
                            quick_match_notice = f"尺寸已匹配；{warning}。请人工填写安全的单一数值价格。"
                        elif matched.get("size_match_exact"):
                            quick_match_notice = "已精确匹配附件尺寸，保留数据库原价。"
                        else:
                            quick_match_notice = (
                                "已按 W+H+D 最近周长快速匹配并比例折价："
                                f"比例 {float(matched.get('size_match_ratio', 1)):g}。"
                            )
                        item = target_item
                        source = matched
                    finally:
                        self.table.blockSignals(False)
                        self._default_selection_guard = False
            if (
                item.checkState() == Qt.CheckState.Checked
                and isinstance(source, dict)
                and is_installation_board(source)
            ):
                self._default_selection_guard = True
                self.table.blockSignals(True)
                try:
                    price_cell = self.table.item(item.row(), self.COL_PRICE)
                    source = apply_installation_board_sign(self, source, price_cell)
                    item.setData(Qt.ItemDataRole.UserRole, source)
                finally:
                    self.table.blockSignals(False)
                    self._default_selection_guard = False
            rule = default_rule_for_item(source) if isinstance(source, dict) else None
            if rule is not None:
                if item.checkState() == Qt.CheckState.Checked:
                    self._default_selection_guard = True
                    self.table.blockSignals(True)
                    try:
                        for row in range(self.table.rowCount()):
                            other = self.table.item(row, self.COL_CHECK)
                            other_source = other.data(Qt.ItemDataRole.UserRole) if other else None
                            if other is item or not isinstance(other_source, dict):
                                continue
                            if default_rule_for_item(other_source) == rule:
                                other.setCheckState(Qt.CheckState.Unchecked)
                    finally:
                        self.table.blockSignals(False)
                        self._default_selection_guard = False
                candidate = getattr(self, "default_matches", {}).get(rule)
                now_selected = checked_sources(self, rule)
                if candidate is not None and any(same_choice(self, value, candidate) for value in now_selected):
                    self.default_selection_opt_outs.discard(rule)
                    self.default_quantity_manual_overrides.discard(rule)
                    set_default_quantity_for_rule(self, rule)
                else:
                    self.default_selection_opt_outs.add(rule)
                    self.default_quantity_manual_overrides.discard(rule)
                sync_attachments_from_table(self)
            elif isinstance(source, dict):
                sync_attachments_from_table(self)
        elif item.column() == self.COL_QUANTITY:
            check_item = self.table.item(item.row(), self.COL_CHECK)
            source = check_item.data(Qt.ItemDataRole.UserRole) if check_item else None
            rule = default_rule_for_item(source) if isinstance(source, dict) else None
            if check_item is not None and check_item.checkState() == Qt.CheckState.Checked:
                # Persist every valid manual quantity before category/search/
                # dimension refreshes rebuild the table. Door-derived defaults
                # additionally track whether the operator overrode the matrix.
                sync_attachments_from_table(self)
            if (
                rule in (DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT)
                and check_item is not None
                and check_item.checkState() == Qt.CheckState.Checked
            ):
                candidate = getattr(self, "default_matches", {}).get(rule)
                expected = default_door_quantity(self, rule)
                try:
                    actual = float(item.text().strip())
                except (TypeError, ValueError):
                    actual = None
                if (
                    candidate is not None
                    and same_choice(self, source, candidate)
                    and expected is not None
                    and actual == float(expected)
                ):
                    self.default_quantity_manual_overrides.discard(rule)
                else:
                    self.default_quantity_manual_overrides.add(rule)
                sync_attachments_from_table(self)
                refresh_category_browser(self)
        result = original_table_item_changed(self, item)
        if quick_match_notice:
            hint = getattr(self, "catalog_hint", None)
            if isinstance(hint, QLabel):
                hint.setText(quick_match_notice)
        return result

    def collect_attachments_with_metadata(self, show_errors: bool = True):
        # The recovered V3 collector predates signed attachment rows and
        # validates every displayed price as non-negative.  Feed it the
        # positive source snapshot, then restore the visible minus sign and
        # attach ``attachment_price_sign`` separately.
        signed_price_cells = []
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                check_item = self.table.item(row, self.COL_CHECK)
                source = check_item.data(Qt.ItemDataRole.UserRole) if check_item else None
                price_cell = self.table.item(row, self.COL_PRICE)
                if (
                    check_item is not None
                    and check_item.checkState() == Qt.CheckState.Checked
                    and isinstance(source, dict)
                    and is_installation_board(source)
                    and price_cell is not None
                ):
                    try:
                        current = price_cell.text()
                        price_cell.setText(f"{abs(float(current)):g}")
                        signed_price_cells.append((price_cell, current))
                    except (TypeError, ValueError):
                        pass
            selected = original_collect_attachments(self, show_errors=show_errors)
        finally:
            for price_cell, text in signed_price_cells:
                price_cell.setText(text)
            self.table.blockSignals(False)
        if selected is None:
            return None
        sources = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, self.COL_CHECK)
            if check_item is None or check_item.checkState() != Qt.CheckState.Checked:
                continue
            source = check_item.data(Qt.ItemDataRole.UserRole)
            sources.append(source if isinstance(source, dict) else {})
        for output, source in zip(selected, sources):
            for key in (
                "attachment_price_id",
                "category_level1", "category_level2", "category_level3",
                "attachment_price_sign",
                GANGED_FIXED_BASE_MATCH_KEY,
                GANGED_FIXED_BASE_INDEX_KEY,
                "ganged_fixed_base_split_count",
                "ganged_fixed_base_specification",
                *SIZE_MATCH_METADATA_KEYS,
            ):
                if source.get(key) is not None:
                    output[key] = source[key]
            if source.get("matched_price") is not None:
                output["matched_price"] = source["matched_price"]
            if source.get("unit_price_override") is not None:
                output["unit_price_override"] = source["unit_price_override"]
            if is_installation_board(source) or is_installation_board(output):
                output["attachment_price_sign"] = installation_board_price_sign(self)
                for price_key in ("matched_price", "unit_price_override"):
                    if output.get(price_key) is not None:
                        try:
                            output[price_key] = abs(float(output[price_key]))
                        except (TypeError, ValueError):
                            pass
        for output in selected:
            if is_installation_board(output):
                output["attachment_price_sign"] = installation_board_price_sign(self)
                for price_key in ("matched_price", "unit_price_override"):
                    if output.get(price_key) is not None:
                        try:
                            output[price_key] = abs(float(output[price_key]))
                        except (TypeError, ValueError):
                            pass
        return selected

    def accept_selection_with_defaults(self):
        original_accept_selection(self)
        if self.result() == QDialog.DialogCode.Accepted:
            for rule in (DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT):
                candidate = getattr(self, "default_matches", {}).get(rule)
                expected = default_door_quantity(self, rule)
                selected = next(
                    (
                        item for item in getattr(self, "attachments", [])
                        if isinstance(item, dict) and default_rule_for_item(item) == rule
                    ),
                    None,
                )
                if rule in self.default_selection_opt_outs or selected is None:
                    self.default_quantity_manual_overrides.discard(rule)
                elif candidate is not None and same_choice(self, selected, candidate) and expected is not None:
                    try:
                        selected_quantity = int(selected.get("quantity", 1))
                    except (TypeError, ValueError):
                        selected_quantity = None
                    if selected_quantity == expected:
                        self.default_quantity_manual_overrides.discard(rule)
                    else:
                        self.default_quantity_manual_overrides.add(rule)
            parent = self.parentWidget()
            if parent is not None:
                parent.attachment_default_opt_outs = set(self.default_selection_opt_outs)
                parent.attachment_default_quantity_overrides = set(
                    self.default_quantity_manual_overrides
                )
                parent.attachment_door_transform_context = (
                    str(getattr(self, "default_match_product_code", "") or "").strip().upper(),
                    tuple(getattr(self, "default_match_door_counts", (1, 0))),
                )
                parent.attachment_door_transform_catalog = [
                    dict(item) for item in getattr(self, "catalog", [])
                    if isinstance(item, dict)
                    and attachment_category_value(item, 0) == "门变形"
                ]

    def init_with_default_filters(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.resize(900, 680)
        self.category_selection = []
        parent = self.parentWidget()
        self.default_selection_opt_outs = set(getattr(parent, "attachment_default_opt_outs", set()))
        self.default_quantity_manual_overrides = set(
            getattr(parent, "attachment_default_quantity_overrides", set())
        )
        self._default_selection_guard = False
        parent_rows = _ganged_rows(parent) if parent is not None else []
        current_transform_context = (
            selected_product_code(self).strip().upper(),
            tuple(
                (
                    int(row.get("single_door_count", 1)),
                    int(row.get("double_door_count", 0)),
                )
                for row in parent_rows
            ) if len(parent_rows) > 1 else tuple(selected_door_counts(self)),
        )
        previous_transform_context = (
            getattr(parent, "attachment_door_transform_context", None)
            if parent is not None else None
        )
        if previous_transform_context is not None and tuple(previous_transform_context) != current_transform_context:
            self.attachments = [
                item for item in getattr(self, "attachments", [])
                if not (
                    isinstance(item, dict)
                    and str(
                        item.get("category_level1")
                        or item.get("attachment_category")
                        or ""
                    ).strip() == "门变形"
                )
            ]
            self.default_selection_opt_outs = {
                rule for rule in self.default_selection_opt_outs
                if not str(rule).startswith(DOOR_TRANSFORMATION_RULE_PREFIX)
            }
        self.installation_board_sign = -1 if any(
            isinstance(item, dict)
            and is_installation_board(item)
            and stored_attachment_price_sign(item) == -1
            for item in getattr(self, "attachments", [])
        ) else 1
        panel = QFrame(self)
        panel.setObjectName("attachmentCategoryBar")
        panel.setStyleSheet(
            "QFrame#attachmentCategoryBar {background:#eef5fb;border:1px solid #c8d9e8;border-left:4px solid #2c78c4;border-radius:8px;}"
            "QLabel#attachmentCategoryTitle {color:#174a73;font-weight:700;}"
            "QScrollArea#attachmentCategoryScroll {background:transparent;border:0;}"
            "QPushButton#attachmentCategoryBack {background:transparent;border:0;color:#2c6fa8;padding:4px 8px;font-weight:600;}"
            "QFrame#attachmentCategoryCardShell {background:#fbfdff;border:1px solid #a9c5d9;border-left:5px solid #2c78c4;border-radius:7px;}"
            "QPushButton#attachmentCategoryCard {background:transparent;border:0;border-bottom:1px solid #d8e5ef;border-radius:0;color:#173f67;font-weight:700;padding:10px 14px;text-align:left;}"
            "QPushButton#attachmentCategoryCard:hover {background:#e4f1fb;border-bottom-color:#6da4cc;}"
            "QPushButton#attachmentCategoryCard:pressed {background:#d5e8f6;}"
            "QPushButton#attachmentQuickMatch,QPushButton#attachmentQuickMatchCancelled {background:#f1f4f6;color:#66727e;padding:7px 12px;border:0;text-align:left;}"
            "QPushButton#attachmentQuickMatchSelected {background:#e3f3e9;color:#1f6841;font-weight:700;padding:7px 12px;border:0;text-align:left;}"
            "QPushButton#attachmentQuickMatchSelected:hover {background:#d4eadc;}"
            "QPushButton#attachmentQuickMatchManual {background:#e7f1fb;color:#245f91;font-weight:700;padding:7px 12px;border:0;text-align:left;}"
            "QPushButton#attachmentQuickMatchManual:hover {background:#d8e9f7;}"
            "QPushButton#attachmentQuickMatchCancelled:hover {background:#e4e9ed;color:#44515d;}"
            "QPushButton#attachmentQuickMatchMissing {background:#fff5df;color:#9a620e;font-weight:700;padding:7px 12px;border:0;text-align:left;}"
            "QPushButton#attachmentPriceSignPositive,QPushButton#attachmentPriceSignNegative {border-radius:17px;font-size:20px;font-weight:800;padding:0;}"
            "QPushButton#attachmentPriceSignPositive {background:#e7f1fb;color:#245f91;border:1px solid #7eafd3;}"
            "QPushButton#attachmentPriceSignPositive:hover {background:#d8e9f7;}"
            "QPushButton#attachmentPriceSignNegative {background:#fff0f0;color:#b42318;border:1px solid #e59a94;}"
            "QPushButton#attachmentPriceSignNegative:hover {background:#ffe0e0;}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 10, 14, 12)
        panel_layout.setSpacing(9)
        header = QHBoxLayout()
        self.category_back_button = QPushButton("← 返回上一级", panel)
        self.category_back_button.setObjectName("attachmentCategoryBack")
        self.category_back_button.clicked.connect(lambda: back_attachment_category(self))
        self.category_breadcrumb = QLabel("附件库 / 一级分类", panel)
        self.category_breadcrumb.setObjectName("attachmentCategoryTitle")
        self.category_breadcrumb.setWordWrap(True)
        header.addWidget(self.category_back_button)
        header.addWidget(self.category_breadcrumb, 1)
        panel_layout.addLayout(header)
        self.category_scroll = QScrollArea(panel)
        self.category_scroll.setObjectName("attachmentCategoryScroll")
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.category_scroll.setMinimumHeight(360)
        self.category_scroll_content = QWidget(self.category_scroll)
        self.category_grid = QGridLayout(self.category_scroll_content)
        self.category_grid.setContentsMargins(0, 0, 0, 0)
        self.category_grid.setHorizontalSpacing(10)
        self.category_grid.setVerticalSpacing(10)
        self.category_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        for column in range(4):
            self.category_grid.setColumnStretch(column, 1)
        self.category_scroll.setWidget(self.category_scroll_content)
        panel_layout.addWidget(self.category_scroll)
        layout = self.layout()
        search = getattr(self, "search_edit", None)
        if layout is not None and hasattr(layout, "insertWidget"):
            index = layout.indexOf(search) if search is not None else -1
            if isinstance(search, QLineEdit):
                layout.removeWidget(search)
                panel_layout.insertWidget(0, search)
            layout.insertWidget(index if index >= 0 else 1, panel)
        elif layout is not None:
            layout.addWidget(panel)
        self.attachment_category_panel = panel
        if isinstance(search, QLineEdit):
            search.setPlaceholderText("搜索附件名称、型号、规格、尺寸或价格方案")
        self.default_match_specification = specification_text(self)
        prepare_default_selections(self)
        original_rebuild_table(self)
        refresh_category_browser(self)

    dialog_class.__init__ = init_with_default_filters
    dialog_class.rebuild_table = rebuild_table_with_defaults
    dialog_class.apply_filter = apply_classification_filter
    dialog_class.collect_attachments = collect_attachments_with_metadata
    dialog_class.table_item_changed = table_item_changed_with_defaults
    dialog_class.accept_selection = accept_selection_with_defaults
    dialog_class.refresh_category_browser = refresh_category_browser
    dialog_class.open_attachment_category = open_attachment_category
    dialog_class.back_attachment_category = back_attachment_category
    dialog_class.prepare_default_selections = prepare_default_selections
    dialog_class.rematch_selected_for_dimensions = rematch_selected_for_dimensions
    dialog_class.build_default_matches = build_default_matches
    dialog_class.toggle_default_selection = toggle_default_selection
    dialog_class.default_card_state = default_card_state
    dialog_class._default_selection_filters_installed = True


def install_layout_refresh(namespace: dict) -> None:
    """Install the layout pass on an extracted or packaged V3 namespace."""

    _install_formula_cell_reference_guard(namespace)
    _install_door_remark_sync(namespace)
    main_window = namespace["MainWindow"]
    if getattr(main_window, "_layout_refresh_installed", False):
        return

    _install_stable_preview(namespace)
    _install_attachment_catalog_addition(namespace)
    _install_attachment_default_selection_filters(namespace)
    _patch_family_for_code(main_window)
    _patch_discounted_totals(namespace, main_window)

    original_build_ui = main_window.build_ui
    original_resize_event = main_window.resizeEvent
    original_refresh_document_list = main_window._refresh_document_list
    original_import_drawing_paths = main_window.import_drawing_paths
    original_recognition_progress = main_window.pdf_recognition_progress
    original_recognition_finished = main_window.pdf_recognition_finished
    original_refresh_summary = main_window.refresh_summary
    original_update_attachment_view = getattr(main_window, "update_attachment_view", None)
    original_calculate = getattr(main_window, "calculate", None)
    original_product_changed = getattr(main_window, "product_changed", None)
    original_door_counts_changed = getattr(main_window, "door_counts_changed", None)
    original_product_catalog_loaded = getattr(main_window, "product_catalog_loaded", None)
    original_formula_template_loaded = getattr(main_window, "formula_template_loaded", None)

    def build_ui_with_refresh(self):
        original_build_ui(self)
        apply_layout_refresh(self)
        _ensure_history_price_panel(self, namespace.get("ApiWorker"))
        _configure_quote_rule_interactions(self, namespace.get("parse_review_specification"))
        self.attachment_default_opt_outs = set(
            getattr(self, "attachment_default_opt_outs", set())
        )
        self.attachment_default_quantity_overrides = set(
            getattr(self, "attachment_default_quantity_overrides", set())
        )
        self._attachment_default_door_counts = _current_door_counts(self)
        self.attachment_door_transform_context = getattr(
            self, "attachment_door_transform_context", None
        )
        self.ganged_cabinets = list(getattr(self, "ganged_cabinets", []))
        self.ganged_cabinet_count = ganged_split_count(
            getattr(self, "ganged_cabinet_count", 1)
        )
        self.ganged_cabinet_specification = str(
            getattr(self, "ganged_cabinet_specification", "") or ""
        )
        self._persistent_product_selection = getattr(
            self,
            "_persistent_product_selection",
            None,
        )
        product_combo = getattr(self, "product_combo", None)
        if isinstance(product_combo, QComboBox):
            def remember_manual_product_selection(_index):
                selected = _current_product_selection(self)
                if selected not in (None, ""):
                    self._persistent_product_selection = selected

            product_combo.activated.connect(remember_manual_product_selection)
        quantity_spin = getattr(self, "quantity_spin", None)
        if quantity_spin is not None and not getattr(
            quantity_spin, "_attachment_quantity_connected", False
        ):
            quantity_spin.valueChanged.connect(lambda _value: self.update_attachment_view())
            quantity_spin._attachment_quantity_connected = True

    def resize_event_with_responsive_quote(self, event):
        original_resize_event(self, event)
        if getattr(self, "stack", None) is not None:
            QTimer.singleShot(0, lambda: _apply_quote_responsive_layout(self))

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
        formula_sum = 0.0
        quick_sum = 0.0
        table = getattr(self, "summary_table", None)
        formula_price_column = None
        quick_price_column = None
        if isinstance(table, QTableWidget):
            for column in range(table.columnCount()):
                header = table.horizontalHeaderItem(column)
                label = header.text() if header is not None else ""
                if "公式" in label and "折扣" not in label:
                    formula_price_column = column
                if "快速" in label and "折扣" not in label:
                    quick_price_column = column
            if quick_price_column is None and table.columnCount() > 8:
                quick_price_column = 8
        for row, item in enumerate(getattr(self, "draft_items", [])):
            quantity = _safe_float(item.get("quantity") or 1)
            quantity = 1.0 if quantity is None else quantity
            formula_line = _formula_order_line_breakdown(item)
            quick_line = quick_order_line_breakdown(
                item.get("quick", {}), item.get("attachments", []),
                item.get("quick_discount", 1), quantity,
                ganged_split_count(item),
            )
            formula_sum += formula_line["line_total"]
            quick_sum += quick_line["line_total"]
            if formula_price_column is not None:
                table.setItem(
                    row, formula_price_column,
                    QTableWidgetItem(f"{formula_line['equivalent_unit_total']:,.2f}"),
                )
            if quick_price_column is not None:
                table.setItem(
                    row, quick_price_column,
                    QTableWidgetItem(f"{quick_line['equivalent_unit_total']:,.2f}"),
                )
            if isinstance(table, QTableWidget) and ganged_split_count(item) > 1:
                specification = str(
                    item.get("specification") or item.get("model_code") or ""
                ).strip()
                if table.columnCount() > 2:
                    table.setItem(row, 2, QTableWidgetItem(specification))
                if table.columnCount() > 3:
                    table.setItem(row, 3, QTableWidgetItem(specification))
        formula_total_label = getattr(self, "summary_formula_total", None)
        if isinstance(formula_total_label, QLabel):
            formula_total_label.setText(f"公式法：{formula_sum:,.2f} 元")
        quick_total_label = getattr(self, "summary_quick_total", None)
        if isinstance(quick_total_label, QLabel):
            quick_total_label.setText(f"快速报价：{quick_sum:,.2f} 元")
        _sync_summary_action_state(self)
        return result

    main_window.build_ui = build_ui_with_refresh
    main_window.resizeEvent = resize_event_with_responsive_quote
    main_window._refresh_document_list = refresh_document_list_with_preview
    main_window.import_drawing_paths = import_drawing_paths_without_progress_strip
    main_window.pdf_recognition_progress = recognition_progress_without_strip
    main_window.pdf_recognition_finished = recognition_finished_without_strip
    main_window.refresh_summary = refresh_summary_with_action_state
    if callable(original_update_attachment_view):
        def update_attachment_view_with_signed_prices(self):
            original_update_attachment_view(self)
            attachment_list = getattr(self, "attachment_list", None)
            if attachment_list is None:
                return
            for row, attachment in enumerate(getattr(self, "attachments", [])):
                if not isinstance(attachment, dict):
                    continue
                try:
                    sign = -1 if int(attachment.get("attachment_price_sign", 1)) == -1 else 1
                except (TypeError, ValueError):
                    sign = 1
                list_item = attachment_list.item(row)
                if list_item is None:
                    continue
                text = list_item.text()
                if sign == -1:
                    price = _safe_float(
                        attachment.get("unit_price_override", attachment.get("matched_price"))
                    )
                    if price is not None:
                        positive_text = f"{abs(price):,.2f} 元"
                        negative_text = f"{-abs(price):,.2f} 元"
                        text = text.replace(positive_text, negative_text)
                quantity_spin = getattr(self, "quantity_spin", None)
                cabinets = quantity_spin.value() if quantity_spin is not None else 1
                final_quantity = final_attachment_quantity(
                    attachment, cabinets, _ganged_count(self)
                )
                list_item.setText(f"{text} · 最终数量 {final_quantity:g}")
        main_window.update_attachment_view = update_attachment_view_with_signed_prices
    if callable(original_product_changed):
        def product_changed_with_default_door(self, *_signal_args, **_signal_kwargs):
            previous_door_counts = getattr(
                self,
                "_attachment_default_door_counts",
                _current_door_counts(self),
            )
            material_combo = getattr(self, "material_combo", None)
            coating_combo = getattr(self, "coating_combo", None)
            material_selected = (
                material_combo.currentData() if isinstance(material_combo, QComboBox) else None
            )
            coating_selected = (
                coating_combo.currentData() if isinstance(coating_combo, QComboBox) else None
            )
            result = original_product_changed(self)
            _restore_quote_selections_after_product_change(
                self,
                material_selected,
                coating_selected,
            )
            _set_default_door_combination(self)
            _sync_door_limiter_default_quantity(self, previous_door_counts)
            _sync_door_transform_defaults(self)
            _refresh_model_suggestions(self)
            if _ganged_count(self) > 1:
                _sync_ganged_specification(
                    self,
                    str(getattr(self, "ganged_cabinet_specification", "") or ""),
                )
            return result
        main_window.product_changed = product_changed_with_default_door
    if callable(original_door_counts_changed):
        def door_counts_changed_with_product_rules(self, source):
            previous_door_counts = getattr(
                self,
                "_attachment_default_door_counts",
                None,
            )
            if _enforce_product_door_combination(self, source):
                _sync_door_limiter_default_quantity(self, previous_door_counts)
                _sync_door_transform_defaults(self)
                return None
            result = original_door_counts_changed(self, source)
            if _ganged_count(self) > 1:
                rows = _ganged_rows(self)
                current = _current_door_counts(self) or (1, 0)
                self.ganged_cabinets = cascade_door_counts(rows, 0, *current)
                _render_ganged_cabinet_table(self)
            _sync_door_limiter_default_quantity(self, previous_door_counts)
            _sync_door_transform_defaults(self)
            return result
        main_window.door_counts_changed = door_counts_changed_with_product_rules
    if callable(original_calculate):
        def calculate_with_ganged_cabinets(self):
            if _start_ganged_calculation(self, namespace.get("api_headers")):
                return None
            return original_calculate(self)
        main_window.calculate = calculate_with_ganged_cabinets
    if callable(original_product_catalog_loaded):
        def product_catalog_loaded_with_database_options(self, result):
            retained_product = getattr(
                self,
                "_persistent_product_selection",
                None,
            ) or _current_product_selection(self)
            loaded = original_product_catalog_loaded(self, result)
            _apply_database_catalog_options(self, result)
            _restore_product_selection(self, retained_product)
            return loaded
        main_window.product_catalog_loaded = product_catalog_loaded_with_database_options
    if callable(original_formula_template_loaded):
        def formula_template_loaded_with_perimeter_rule(self, *args, **kwargs):
            loaded = original_formula_template_loaded(self, *args, **kwargs)
            try:
                _apply_nonstandard_formula_ratio(self)
                _round_formula_workbook_fields(self)
            except Exception as error:
                self.weight_edit.clear()
                self.area_edit.clear()
                risk = getattr(self, "risk_label", None)
                if isinstance(risk, QLabel):
                    risk.setText(f"非标尺寸周长换算失败：{error}")
            return loaded
        main_window.formula_template_loaded = formula_template_loaded_with_perimeter_rule
    main_window._layout_refresh_installed = True
