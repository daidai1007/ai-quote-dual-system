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
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
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
    QVBoxLayout,
    QWidget,
)

from quote_defaults import (
    DEFAULT_COATING_TYPE,
    DEFAULT_MATERIAL_CODE,
    restore_combo_selection,
)
from quote_remark_rules import replace_door_configuration_phrase
from attachment_category_browser import (
    DEFAULT_A4_FOLDER,
    DEFAULT_DOOR_REINFORCEMENT,
    DEFAULT_DOOR_LIMITER,
    DEFAULT_FIXED_BASE,
    DEFAULT_GROUND_WIRE,
    DEFAULT_JP_SIDE_PANEL,
    DEFAULT_LIGHT_SWITCH,
    category_options,
    category_path as attachment_category_path,
    category_value as attachment_category_value,
    default_rule_for_item,
    is_base_selection,
    is_jp_product,
    match_default_a4_folder,
    match_default_door_reinforcement,
    match_default_door_limiter,
    match_default_ground_wire,
    match_default_light_switch,
    match_fixed_base,
    match_jp_side_panel,
    parse_base_specification,
    valid_selection_prefix,
)


WIDGET_MAX = 16_777_215
VALID_DOOR_COMBINATIONS = {(1, 0), (0, 1), (0, 2), (2, 0), (1, 1)}
FORMULA_MULTI_DOOR_FAMILIES = {"JS", "JP", "JA", "JE"}


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


def _configure_quote_rule_interactions(window, parser=None) -> None:
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
        double.setToolTip("双门数量；快速报价会将 0/1、0/2 视为双门，其余批准组合视为单门")
    _set_default_door_combination(window)

    specification = getattr(window, "quote_spec_edit", None)
    if isinstance(specification, QLineEdit):
        specification.setPlaceholderText("例如 760*500*(960+100)；无底座则不写括号和 +100")
        specification.setToolTip(
            "输入宽×深×高；需要底座时写成宽×深×(柜高+底座高)，例如 760×500×(960+100)"
        )
        if not getattr(specification, "_manual_dimension_sync_connected", False):
            specification.textEdited.connect(
                lambda value: _sync_manual_specification_to_dimensions(window, value, parser)
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
    window.weight_edit.setText(f"{float(values[0]) * ratio:.6f}".rstrip("0").rstrip("."))
    window.area_edit.setText(f"{float(values[1]) * ratio:.6f}".rstrip("0").rstrip("."))
    source = getattr(window, "quote_parameter_source", None)
    if isinstance(source, QLabel):
        source.setText("来源：数据库标准尺寸·周长比例")
        source.setToolTip(
            f"非标尺寸按输入周长÷匹配周长换算，当前比例 {ratio:.6f}"
        )
    window._nonstandard_perimeter_ratio = ratio
    return True


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
            self.attachment_default_opt_outs = set()
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


def _install_attachment_classification_filters(namespace: dict) -> None:
    """Add a four-column drill-down browser to the V3 attachment dialog."""

    dialog_class = namespace.get("AttachmentDialog")
    if dialog_class is None or getattr(dialog_class, "_classification_filters_installed", False):
        return

    original_init = dialog_class.__init__
    original_apply_filter = dialog_class.apply_filter
    original_rebuild_table = dialog_class.rebuild_table

    def specification_text(self) -> str:
        parent = self.parentWidget()
        for name in ("quote_spec_edit", "model_edit"):
            field = getattr(parent, name, None) if parent is not None else None
            if isinstance(field, QLineEdit) and field.text().strip():
                return field.text().strip()
        return str(getattr(self, "base_quick_match_specification", "") or "").strip()

    def prepare_fixed_base_quick_match(self) -> bool:
        """Preselect one fixed base only for an explicit W*D*(H+base) spec."""

        parsed = parse_base_specification(specification_text(self))
        self.base_quick_match_spec = parsed
        self.base_quick_match_item = None
        self.base_quick_match_auto_selected = False
        if parsed is None:
            return False
        parsed_width, _cabinet_height, parsed_depth, base_height = parsed
        target = getattr(self, "target_dimensions", None)
        width = parsed_width
        depth = parsed_depth
        if isinstance(target, (list, tuple)) and len(target) >= 3:
            try:
                width = float(target[0])
                depth = float(target[2])
            except (TypeError, ValueError):
                width, depth = parsed_width, parsed_depth
        matched = match_fixed_base(
            getattr(self, "catalog", []),
            width,
            depth,
            base_height,
        )
        self.base_quick_match_item = matched
        if matched is None:
            return False
        if any(is_base_selection(item) for item in getattr(self, "attachments", [])):
            return False
        selected = dict(matched)
        selected["quantity"] = 1
        self.attachments.append(selected)
        self.base_quick_match_auto_selected = True
        return True

    def quick_match_label(self, option: dict) -> tuple[str, str, str]:
        if not getattr(self, "category_selection", []) and option.get("value") == "底座":
            parsed = getattr(self, "base_quick_match_spec", None)
            if parsed is None:
                return "快速匹配\n无需底座", "attachmentQuickMatch", "规格高度没有括号和 +，不自动选择底座"
            base_height = parsed[3]
            height_text = f"{base_height:g}"
            if getattr(self, "base_quick_match_item", None) is not None:
                return (
                    f"快速匹配\n类型：固定\n高度：{height_text} mm",
                    "attachmentQuickMatchMatched",
                    "已按柜体宽度、深度和底座高度自动选择固定底座",
                )
            return (
                f"快速匹配\n类型：固定\n高度：{height_text} mm（未匹配）",
                "attachmentQuickMatchMissing",
                "附件库中没有与当前宽度、深度和底座高度完全一致的固定底座",
            )
        return "快速匹配\n待配置", "attachmentQuickMatch", "该分类尚未配置快速匹配规则"

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
            table_text = []
            for column in (self.COL_NAME, self.COL_SPEC, self.COL_SCHEME, self.COL_PRICE):
                cell = table.item(row, column)
                if cell is not None:
                    table_text.append(cell.text())
            haystack = " ".join(
                [
                    *path,
                    str(source.get("item_name") or ""),
                    str(source.get("model_code") or ""),
                    str(source.get("variant") or ""),
                    *table_text,
                ]
            ).casefold()
            table.setRowHidden(
                row,
                not category_matches or bool(needle and needle not in haystack),
            )

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
        self.category_selection = valid_selection_prefix(
            catalog,
            getattr(self, "category_selection", []),
        )
        clear_category_cards(self)
        options = category_options(catalog, self.category_selection)
        labels = [value or "本级附件" for value in self.category_selection]
        breadcrumb = "附件库"
        if labels:
            breadcrumb += "  ›  " + "  ›  ".join(labels)
        if options:
            breadcrumb += f"  /  选择{'一二三'[len(self.category_selection)]}级分类"
        else:
            breadcrumb += "  /  选择具体附件"
        self.category_breadcrumb.setText(breadcrumb)
        self.category_back_button.setVisible(bool(self.category_selection))
        self.category_back_button.setEnabled(bool(self.category_selection))

        for index, option in enumerate(options):
            card = QFrame(self.category_scroll_content)
            card.setObjectName("attachmentCategoryCardShell")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)
            button = QPushButton(
                f"{option['label']}\n{option['count']} 项",
                card,
            )
            button.setObjectName("attachmentCategoryCard")
            button.setAccessibleName(f"{option['label']}，{option['count']}项")
            button.setToolTip(f"进入“{option['label']}”")
            button.setMinimumHeight(64)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda _checked=False, value=option["value"]: open_attachment_category(self, value)
            )
            quick_text, quick_object_name, quick_tooltip = quick_match_label(self, option)
            quick_match = QLabel(quick_text, card)
            quick_match.setObjectName(quick_object_name)
            quick_match.setAccessibleName(f"{option['label']}，{quick_text.replace(chr(10), '，')}")
            quick_match.setToolTip(quick_tooltip)
            quick_match.setWordWrap(True)
            quick_match.setMinimumHeight(48 if quick_text.count("\n") == 1 else 66)
            card_layout.addWidget(button)
            card_layout.addWidget(quick_match)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.category_grid.addWidget(card, index // 4, index % 4)

        at_category_level = bool(options)
        self.category_scroll.setVisible(at_category_level)
        self.search_edit.setVisible(not at_category_level)
        self.table.setVisible(not at_category_level)
        if not at_category_level:
            apply_classification_filter(self, self.search_edit.text())
        hint = getattr(self, "catalog_hint", None)
        if catalog and isinstance(hint, QLabel):
            level1_count = len({attachment_category_value(item, 0) for item in catalog})
            hint.setText(
                f"已读取 {len(catalog)} 条附件价格，覆盖 {level1_count} 个一级分类。"
                "逐级进入分类，到达末级后勾选附件。"
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

    def rebuild_table_with_classification(self):
        if hasattr(self, "category_selection"):
            prepare_fixed_base_quick_match(self)
        result = original_rebuild_table(self)
        if hasattr(self, "category_selection"):
            refresh_category_browser(self)
        return result

    def init_with_classification_filters(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.category_selection = []
        panel = QFrame(self)
        panel.setObjectName("attachmentCategoryBar")
        panel.setStyleSheet(
            "QFrame#attachmentCategoryBar {"
            "background:#eef5fb;border:1px solid #c8d9e8;"
            "border-left:4px solid #2c78c4;border-radius:8px;"
            "}"
            "QLabel#attachmentCategoryTitle {color:#174a73;font-weight:700;}"
            "QScrollArea#attachmentCategoryScroll {background:transparent;border:0;}"
            "QPushButton#attachmentCategoryBack {background:transparent;border:0;"
            "color:#2c6fa8;padding:4px 8px;font-weight:600;}"
            "QFrame#attachmentCategoryCardShell {background:#fbfdff;"
            "border:1px solid #a9c5d9;border-left:5px solid #2c78c4;"
            "border-radius:7px;}"
            "QPushButton#attachmentCategoryCard {background:transparent;"
            "border:0;border-bottom:1px solid #d8e5ef;border-radius:0;"
            "color:#173f67;font-weight:700;"
            "padding:10px 14px;text-align:left;}"
            "QPushButton#attachmentCategoryCard:hover {background:#e4f1fb;"
            "border-bottom-color:#6da4cc;}"
            "QPushButton#attachmentCategoryCard:pressed {background:#d5e8f6;}"
            "QLabel#attachmentQuickMatch {background:#f4f7fa;color:#66727e;"
            "padding:7px 12px;border:0;}"
            "QLabel#attachmentQuickMatchMatched {background:#e8f5ee;color:#216744;"
            "font-weight:700;padding:7px 12px;border:0;}"
            "QLabel#attachmentQuickMatchMissing {background:#fff5df;color:#9a620e;"
            "font-weight:700;padding:7px 12px;border:0;}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 10, 14, 12)
        panel_layout.setSpacing(9)
        category_header = QHBoxLayout()
        self.category_back_button = QPushButton("← 返回上一级", panel)
        self.category_back_button.setObjectName("attachmentCategoryBack")
        self.category_back_button.clicked.connect(lambda: back_attachment_category(self))
        self.category_breadcrumb = QLabel("附件库 / 一级分类", panel)
        self.category_breadcrumb.setObjectName("attachmentCategoryTitle")
        self.category_breadcrumb.setWordWrap(True)
        category_header.addWidget(self.category_back_button)
        category_header.addWidget(self.category_breadcrumb, 1)
        panel_layout.addLayout(category_header)

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
            search_index = layout.indexOf(search) if search is not None else -1
            layout.insertWidget(search_index if search_index >= 0 else 1, panel)
        elif layout is not None:
            layout.addWidget(panel)
        self.attachment_category_panel = panel
        if isinstance(search, QLineEdit):
            search.setPlaceholderText("搜索当前分类中的名称、型号、尺寸或价格方案")
        self.base_quick_match_specification = specification_text(self)
        prepare_fixed_base_quick_match(self)
        original_rebuild_table(self)
        refresh_category_browser(self)

    dialog_class.__init__ = init_with_classification_filters
    dialog_class.rebuild_table = rebuild_table_with_classification
    dialog_class.apply_filter = apply_classification_filter
    dialog_class.refresh_category_browser = refresh_category_browser
    dialog_class.open_attachment_category = open_attachment_category
    dialog_class.back_attachment_category = back_attachment_category
    dialog_class.prepare_fixed_base_quick_match = prepare_fixed_base_quick_match
    dialog_class.quick_match_label = quick_match_label
    dialog_class._classification_filters_installed = True


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

    category_rules = {
        "底座": DEFAULT_FIXED_BASE,
        "侧板": DEFAULT_JP_SIDE_PANEL,
        "灯开关": DEFAULT_LIGHT_SWITCH,
        "文件夹": DEFAULT_A4_FOLDER,
        "门限位器": DEFAULT_DOOR_LIMITER,
        "门加强筋": DEFAULT_DOOR_REINFORCEMENT,
        "接地线": DEFAULT_GROUND_WIRE,
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

    def build_default_matches(self) -> dict[str, dict | None]:
        catalog = [item for item in getattr(self, "catalog", []) if isinstance(item, dict)]
        parsed = parse_base_specification(specification_text(self))
        dimensions = target_dimensions(self)
        base = None
        if parsed is not None:
            width, _height, depth = dimensions or parsed[:3]
            base = match_fixed_base(catalog, width, depth, parsed[3])
        side = None
        product_code = selected_product_code(self)
        if is_jp_product(product_code) and dimensions is not None:
            side = match_jp_side_panel(catalog, dimensions[1], dimensions[2])
        matches = {
            DEFAULT_FIXED_BASE: base,
            DEFAULT_LIGHT_SWITCH: match_default_light_switch(catalog),
            DEFAULT_A4_FOLDER: match_default_a4_folder(catalog),
            DEFAULT_DOOR_LIMITER: match_default_door_limiter(catalog),
            DEFAULT_DOOR_REINFORCEMENT: match_default_door_reinforcement(catalog),
            DEFAULT_GROUND_WIRE: match_default_ground_wire(catalog),
            DEFAULT_JP_SIDE_PANEL: side,
        }
        self.default_match_spec = parsed
        self.default_match_dimensions = dimensions
        self.default_match_product_code = product_code
        self.default_matches = matches
        return matches

    def prepare_default_selections(self) -> int:
        matches = build_default_matches(self)
        opt_outs = getattr(self, "default_selection_opt_outs", set())
        selected_items = [item for item in getattr(self, "attachments", []) if isinstance(item, dict)]
        added = 0
        for rule, candidate in matches.items():
            if candidate is None or rule in opt_outs:
                continue
            if any(default_rule_for_item(item) == rule for item in selected_items):
                continue
            selected = dict(candidate)
            selected["quantity"] = 1
            self.attachments.append(selected)
            selected_items.append(selected)
            added += 1
        return added

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

    def default_card_state(self, option: dict) -> tuple[str, str, str, str | None, bool]:
        if getattr(self, "category_selection", []):
            return "快速匹配\n待配置", "attachmentQuickMatch", "该分类尚未配置快速匹配规则", None, False
        rule = category_rules.get(str(option.get("value") or ""))
        if rule is None:
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
            detail = f"类型：固定 · 高度：{parsed[3]:g} mm"
            missing_tip = "附件库中没有与当前宽度、深度和底座高度完全一致的固定底座"
        elif rule == DEFAULT_LIGHT_SWITCH:
            detail = "灯开关"
        elif rule == DEFAULT_A4_FOLDER:
            detail = "A4资料盒"
        elif rule == DEFAULT_DOOR_LIMITER:
            detail = "门限位器"
        elif rule == DEFAULT_DOOR_REINFORCEMENT:
            detail = "门加强筋"
        elif rule == DEFAULT_GROUND_WIRE:
            detail = "红绿线"
        elif rule == DEFAULT_JP_SIDE_PANEL:
            if not is_jp_product(product_code):
                return "快速匹配\n仅 JP 默认匹配", "attachmentQuickMatch", "当前产品不是 JP，不自动选择侧板", rule, False
            if dimensions is not None:
                detail = f"JP侧板 · 高度：{dimensions[1]:g} · 深度：{dimensions[2]:g} mm"
            else:
                detail = "JP侧板 · 尺寸无效"
            missing_tip = "附件库中没有与当前柜体高度、深度完全一致的唯一侧板"

        if candidate is None:
            return f"默认选择未匹配\n{detail}", "attachmentQuickMatchMissing", missing_tip, rule, False
        selected = checked_sources(self, rule)
        if any(same_choice(self, item, candidate) for item in selected):
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
                check_item.setCheckState(Qt.CheckState.Checked if should_check else Qt.CheckState.Unchecked)
        finally:
            table.blockSignals(False)
            self._default_selection_guard = False
        self.update_selection_hint()

    def sync_attachments_from_table(self) -> None:
        collector = getattr(self, "collect_attachments", None)
        if not callable(collector):
            return
        current = collector(show_errors=False)
        if current is not None:
            self.attachments = current

    def toggle_default_selection(self, rule: str) -> None:
        candidate = getattr(self, "default_matches", {}).get(rule)
        if candidate is None:
            return
        selected = checked_sources(self, rule)
        default_is_selected = any(same_choice(self, item, candidate) for item in selected)
        if default_is_selected:
            set_checked_for_rule(self, rule, None)
            self.default_selection_opt_outs.add(rule)
        else:
            set_checked_for_rule(self, rule, candidate)
            self.default_selection_opt_outs.discard(rule)
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
        breadcrumb += f"  /  选择{'一二三'[len(self.category_selection)]}级分类" if options else "  /  选择具体附件"
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
            card_layout.addWidget(quick_button)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.category_grid.addWidget(card, index // 4, index % 4)

        at_category_level = bool(options)
        self.category_scroll.setVisible(at_category_level)
        self.search_edit.setVisible(not at_category_level)
        self.table.setVisible(not at_category_level)
        if not at_category_level:
            apply_classification_filter(self, self.search_edit.text())
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

    def rebuild_table_with_defaults(self):
        if hasattr(self, "category_selection"):
            prepare_default_selections(self)
        result = original_rebuild_table(self)
        if hasattr(self, "category_selection"):
            refresh_category_browser(self)
        return result

    def table_item_changed_with_defaults(self, item):
        if getattr(self, "_default_selection_guard", False):
            return original_table_item_changed(self, item)
        if item.column() == self.COL_CHECK:
            source = item.data(Qt.ItemDataRole.UserRole)
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
                else:
                    self.default_selection_opt_outs.add(rule)
                sync_attachments_from_table(self)
        return original_table_item_changed(self, item)

    def accept_selection_with_defaults(self):
        original_accept_selection(self)
        if self.result() == QDialog.DialogCode.Accepted:
            parent = self.parentWidget()
            if parent is not None:
                parent.attachment_default_opt_outs = set(self.default_selection_opt_outs)

    def init_with_default_filters(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.category_selection = []
        parent = self.parentWidget()
        self.default_selection_opt_outs = set(getattr(parent, "attachment_default_opt_outs", set()))
        self._default_selection_guard = False
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
            layout.insertWidget(index if index >= 0 else 1, panel)
        elif layout is not None:
            layout.addWidget(panel)
        self.attachment_category_panel = panel
        if isinstance(search, QLineEdit):
            search.setPlaceholderText("搜索当前分类中的名称、型号、尺寸或价格方案")
        self.default_match_specification = specification_text(self)
        prepare_default_selections(self)
        original_rebuild_table(self)
        refresh_category_browser(self)

    dialog_class.__init__ = init_with_default_filters
    dialog_class.rebuild_table = rebuild_table_with_defaults
    dialog_class.apply_filter = apply_classification_filter
    dialog_class.table_item_changed = table_item_changed_with_defaults
    dialog_class.accept_selection = accept_selection_with_defaults
    dialog_class.refresh_category_browser = refresh_category_browser
    dialog_class.open_attachment_category = open_attachment_category
    dialog_class.back_attachment_category = back_attachment_category
    dialog_class.prepare_default_selections = prepare_default_selections
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
    original_refresh_document_list = main_window._refresh_document_list
    original_import_drawing_paths = main_window.import_drawing_paths
    original_recognition_progress = main_window.pdf_recognition_progress
    original_recognition_finished = main_window.pdf_recognition_finished
    original_refresh_summary = main_window.refresh_summary
    original_product_changed = getattr(main_window, "product_changed", None)
    original_door_counts_changed = getattr(main_window, "door_counts_changed", None)
    original_product_catalog_loaded = getattr(main_window, "product_catalog_loaded", None)
    original_formula_template_loaded = getattr(main_window, "formula_template_loaded", None)

    def build_ui_with_refresh(self):
        original_build_ui(self)
        apply_layout_refresh(self)
        _configure_quote_rule_interactions(self, namespace.get("parse_review_specification"))

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
    if callable(original_product_changed):
        def product_changed_with_default_door(self, *_signal_args, **_signal_kwargs):
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
            _refresh_model_suggestions(self)
            return result
        main_window.product_changed = product_changed_with_default_door
    if callable(original_door_counts_changed):
        def door_counts_changed_with_product_rules(self, source):
            if _enforce_product_door_combination(self, source):
                return None
            return original_door_counts_changed(self, source)
        main_window.door_counts_changed = door_counts_changed_with_product_rules
    if callable(original_product_catalog_loaded):
        def product_catalog_loaded_with_database_options(self, result):
            loaded = original_product_catalog_loaded(self, result)
            _apply_database_catalog_options(self, result)
            return loaded
        main_window.product_catalog_loaded = product_catalog_loaded_with_database_options
    if callable(original_formula_template_loaded):
        def formula_template_loaded_with_perimeter_rule(self, *args, **kwargs):
            loaded = original_formula_template_loaded(self, *args, **kwargs)
            try:
                _apply_nonstandard_formula_ratio(self)
            except Exception as error:
                self.weight_edit.clear()
                self.area_edit.clear()
                risk = getattr(self, "risk_label", None)
                if isinstance(risk, QLabel):
                    risk.setText(f"非标尺寸周长换算失败：{error}")
            return loaded
        main_window.formula_template_loaded = formula_template_loaded_with_perimeter_rule
    main_window._layout_refresh_installed = True
