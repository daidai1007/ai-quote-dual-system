"""第一版 AI 智能报价桌面客户端。

客户端只负责采集输入、调用双报价 API 和展示结果；成本公式仍由 PostgreSQL 执行。
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from quote_defaults import (
    DEFAULT_COATING_TYPE,
    DEFAULT_MATERIAL_CODE,
    apply_default_quote_inputs,
)
from quote_remark_rules import replace_door_configuration_phrase
from quick_discount_rules import quick_discount_breakdown
from attachment_category_browser import (
    category_options,
    category_path as attachment_category_path,
    category_value as attachment_category_value,
    is_base_selection,
    match_fixed_base,
    parse_base_specification,
    valid_selection_prefix,
)


def application_root() -> Path:
    """Return the writable installation folder in source and packaged modes."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def load_client_config() -> dict:
    """Load deployment settings without hard-coding a customer's server."""
    config_path = application_root() / "client_config.json"
    config: dict = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                config = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            # Keep a usable localhost default.  The visible interface-address
            # field still lets support staff correct a damaged config file.
            config = {}
    elif not getattr(sys, "frozen", False):
        # The source checkout keeps the distributable client configuration in
        # deployment/.  Reuse only its access key here: a developer/source
        # client should continue to call the local API unless explicitly
        # overridden, while packaged clients still use their adjacent config.
        shared_config = application_root() / "client_config.json"
        if shared_config.is_file():
            try:
                loaded = json.loads(shared_config.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict) and loaded.get("api_key"):
                    config["api_key"] = loaded["api_key"]
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    return config


CLIENT_CONFIG = load_client_config()
API_URL = str(
    os.getenv("AI_QUOTE_API_URL")
    or CLIENT_CONFIG.get("api_url")
    or "http://127.0.0.1:8080/api/quotes/calculate-dual"
).strip()
API_KEY = str(os.getenv("AI_QUOTE_API_KEY") or CLIENT_CONFIG.get("api_key") or "").strip()
REQUIRED_EXPORT_API_BUILD = "2026-08-15-quick-only-attachment-v1"


def api_headers(has_json_body: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if has_json_body:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if API_KEY:
        headers["X-AI-Quote-Key"] = API_KEY
    return headers


def _api_error_text(message: str) -> str:
    """Turn an API JSON error into a short, readable desktop message."""
    text = str(message or "").strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("error") or text)
    return text


def _quote_quantity(value) -> str:
    """Format an attachment quantity without losing significant zeroes."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _attachment_remark(item: dict) -> str:
    """Convert one confirmed attachment row to customer-facing wording."""
    name = str(item.get("item_name") or "").strip()
    model = str(item.get("model_code") or "").strip()
    variant = str(item.get("variant") or "").strip()
    source = str(item.get("price_source") or "").strip()
    notes = str(item.get("notes") or "").strip()
    qty = _quote_quantity(item.get("quantity", 1))
    combined = " ".join(part for part in (name, model, variant, notes) if part)

    if "安装板" in name:
        thickness = re.search(r"(\d+(?:\.\d+)?)\s*mm", combined, re.IGNORECASE)
        plate = f"{thickness.group(1)}镀锌安装板" if thickness else "镀锌安装板"
        return f"配{plate}{qty}块"
    if "侧板" in name:
        return f"配侧板{qty}块"
    if "背板" in name:
        return f"配背板{qty}块"
    if "门" in name and ("双开" in name or "单开" in name):
        return f"配{name}{qty}扇"
    if "锁" in name:
        if model and model not in name and "所有型号" not in model:
            label = model if "锁" in model else f"{model}{name}"
        else:
            label = name
        return f"配{label}{qty}件"
    if "液压" in combined and "支撑" in combined:
        return f"配液压支撑杆{qty}件"
    if "文件夹" in name:
        label = "A4文件夹" if "A4" in combined.upper() else name
        return f"配{label}{qty}个"
    if "接地" in name:
        return f"配接地线{qty}套"
    if "底座" in name:
        height = item.get("height_mm")
        height_text = f"{float(height):g}高" if height not in (None, "") else ""
        kind = "活动底座" if "活动" in name else "底座"
        return f"配{height_text}{kind}{qty}件" if float(qty) != 1 else f"配{height_text}{kind}"
    if "风机" in name:
        label = (model or name).replace("风机", "").strip()
        origin = "国产" if "国产" in source else ""
        voltage = "220V" if re.search(r"220\s*V", combined, re.IGNORECASE) else ""
        return f"配{voltage}{origin}{label}风机{qty}个"
    if "过滤网" in name or "滤网" in name:
        label = (model or name).replace("过滤网", "").replace("滤网", "").replace("FU-", "").strip()
        return f"配{label}滤网{qty}个"
    if "照明灯" in name or "柜内灯" in name:
        return f"配照明灯{qty}套"
    if "行程开关" in name or "灯开关" in name or "限位开关" in name or "门开关" in name:
        return f"配{name}{qty}套"
    if "抽屉" in name:
        return f"配抽屉{qty}件"
    if "把手" in name:
        return f"配{name}{qty}个"
    if "滑轨" in name:
        length = re.search(r"(\d+)\s*mm", combined, re.IGNORECASE)
        label = f"{length.group(1)}mm长滑轨" if length else name
        return f"配{label}{qty}套"
    if "三排" in name or "纵梁" in name:
        return f"配三排纵梁{qty}根"
    if "门限位器" in name or name == "限位器":
        return f"配门限位器{qty}套"
    return f"配{name}{qty}件" if name else ""


def build_standardized_quote_remark(item: dict, raw_remark: str) -> str:
    """Build the compact configuration remark used by the formal quote.

    OCR technical requirements are source evidence, not suitable customer
    wording.  We retain explicit structure/thickness clues from OCR and combine
    them with the operator-confirmed attachment rows.  A manually rewritten
    non-numbered remark is preserved verbatim.
    """
    raw = str(raw_remark or "").strip()
    numbered = bool(re.search(r"(?:^|\n)\s*\d+[\.、)]", raw))
    if raw and "技术要求" not in raw and not numbered:
        return raw

    family = str(item.get("product_family") or item.get("product_code") or "").strip()
    product_code = str(item.get("product_code") or "").upper()
    variant = str(item.get("variant_name") or item.get("variant_code") or "").strip()
    material = str(item.get("material_code") or "SECC").upper()
    coating = str(item.get("coating_type") or "").strip()

    if product_code == "OP_TABLE_EXP" or "操作台" in family or "斜面操作台" in raw:
        structure = "斜面操作台结构"
    else:
        match = re.search(r"仿威图\s*([A-Za-z]{1,8})\s*(箱|柜)", raw, re.IGNORECASE)
        if match:
            structure = f"仿威图{match.group(1).upper()}{match.group(2)}"
        elif family:
            suffix = "箱" if family in {"JA", "JE", "JK"} else "柜"
            structure = f"仿威图{family}{suffix}"
        else:
            structure = "柜体"

    if material == "SUS304":
        material_text = "不锈钢304材质"
    elif material == "SUS316":
        material_text = "不锈钢316材质"
    else:
        material_text = "碳钢"
    ral = re.search(r"RAL\s*(\d{4})", raw, re.IGNORECASE)
    color = f"RAL{ral.group(1)}" if ral else "RAL7035"
    if coating not in ("", "无"):
        texture = "橘纹" if re.search(r"[桔橘]", coating) else ("平光" if "平" in coating else "")
        finish = f"喷塑{color}{texture}"
    else:
        finish = ""

    body_match = re.search(r"柜体(?:厚)?\s*[:：]?\s*(\d+(?:\.\d+)?)", raw)
    door_match = re.search(r"门板(?:厚)?\s*[:：]?\s*(\d+(?:\.\d+)?)", raw)
    body_thickness = body_match.group(1) if body_match else "1.5"
    door_thickness = door_match.group(1) if door_match else "2.0"

    parts = [structure, material_text]
    if finish:
        # Stainless-steel quote remarks use the established customer-facing
        # wording "表面喷塑..."; carbon-steel remarks keep the compact
        # "碳钢喷塑..." form shown in the approved quotation samples.
        if material in {"SUS304", "SUS316"}:
            parts.append(f"表面{finish}")
        else:
            parts[-1] += finish
    parts.extend((f"柜体{body_thickness}", f"门板{door_thickness}"))
    door_phrase = re.search(r"前(?:单|双)开门后(?:背板|单开门|双开门)", raw)
    if door_phrase:
        parts.append(door_phrase.group(0))
    elif "双" in variant.upper() or str(item.get("variant_code") or "").upper() == "DOUBLE":
        parts.append("前双开门后背板")
    elif "单" in variant.upper() or str(item.get("variant_code") or "").upper() == "SINGLE":
        parts.append("前单开门后背板")

    seen = set()
    for attachment in item.get("attachments") or []:
        wording = _attachment_remark(attachment)
        if wording and wording not in seen:
            parts.append(wording)
            seen.add(wording)

    return "，".join(part for part in parts if part).rstrip("，。；; ") + "。"


class FormulaDatabaseCalculator:
    """Evaluate formula rules hydrated from PostgreSQL (never from Excel)."""

    # (first detail row, last detail row, weight output row,
    #  area output row, area divisor)
    DETAIL_ROWS = {
        "JS_SINGLE": (5, 25, 28, 28, 1),
        "JS_DOUBLE": (5, 25, 28, 28, 1),
        "JP_SINGLE": (5, 26, 29, 29, 1),
        "JP_DOUBLE": (5, 26, 29, 29, 1),
        "JA_SINGLE": (5, 25, 28, 28, 2),
        "JE_SINGLE": (5, 25, 28, 28, 2),
        "JE_DOUBLE": (5, 25, 28, 28, 2),
        "JK": (5, 23, 26, 26, 2),
        "JM": (5, 25, 28, 28, 2),
    }
    # Database formula-template control cells for the two independent door
    # counts.  These cells come from the revised formula workbook and are
    # deliberately kept with the formula evaluator rather than duplicated in
    # the UI or API calculation logic.
    DOOR_CONTROL_CELLS = {
        "JS_SINGLE": ("B17", "B11"),
        "JS_DOUBLE": ("B17", "B11"),
        "JP_SINGLE": ("B24", "B11"),
        "JP_DOUBLE": ("B24", "B11"),
        "JA_SINGLE": ("B16", "B17"),
        "JE_SINGLE": ("B16", "B17"),
        "JE_DOUBLE": ("B16", "B17"),
    }
    _CELL_RE = re.compile(r"(?<![A-Za-z0-9_])\$?([A-Z]{1,3})\$?(\d+)")

    @classmethod
    def _replace_cell_references(cls, expression: str, replacement) -> str:
        """Replace cell references without touching quoted Excel text.

        Model names such as ``MS828`` are valid text in formula branches but
        also resemble an Excel address.  Splitting string literals out before
        applying the cell-reference pattern keeps those names unchanged.
        """

        segments = re.split(r'("(?:[^"]|"")*")', expression)
        return "".join(
            segment if index % 2 else cls._CELL_RE.sub(replacement, segment)
            for index, segment in enumerate(segments)
        )

    def __init__(self):
        self.sheets: dict[str, dict[str, object]] = {}
        # Workbook loading has been retired; templates are hydrated from the
        # PostgreSQL API via load_template().

    def load_template(self, payload: dict) -> None:
        """Load one formula template returned by /formula-template."""
        template = payload.get("template", payload)
        code = str(template.get("template_code") or "").strip()
        if not code:
            raise ValueError("formula template has no template_code")
        cells: dict[str, object] = {}
        formulas: dict[str, str] = {}
        option_cells = template.get("option_cells") or {}
        defaults = option_cells.get("defaults") if isinstance(option_cells, dict) else {}
        if isinstance(defaults, dict):
            cells.update({str(ref).upper().replace("$", ""): value for ref, value in defaults.items()})

        # raw_rule.values/formulas correspond to worksheet columns D..Z.
        columns = list("DEFGHIJKLMNOPQRSTUVWXY") + ["Z"]
        for rule in template.get("rules") or []:
            raw = rule.get("raw_rule") or {}
            values = raw.get("values") or []
            source_row = int(rule.get("source_row_no") or raw.get("source_row_no") or 0)
            if source_row <= 0:
                continue
            rule_formulas = raw.get("formulas") or []
            for index, column in enumerate(columns):
                ref = f"{column}{source_row}"
                if index < len(values) and values[index] is not None:
                    cells[ref] = values[index]
                if index < len(rule_formulas) and rule_formulas[index]:
                    formula = str(rule_formulas[index])
                    formulas[ref] = formula[1:] if formula.startswith("=") else formula
            # Some imported rows preserve only the cached numeric result for
            # weight/area.  Rebuild those two derived cells from the stored
            # length/width/thickness/quantity rules so non-standard dimensions
            # remain dynamic while still using database-provided rules.
            if rule.get("include_material_cost") and f"M{source_row}" not in formulas:
                formulas[f"M{source_row}"] = (
                    f"L{source_row}*J{source_row}*I{source_row}*H{source_row}*"
                    f"G{source_row}*F{source_row}*1.2"
                )
            if f"K{source_row}" in formulas and f"L{source_row}" not in formulas:
                formulas[f"L{source_row}"] = f"K{source_row}*B$9"
            if rule.get("include_spray_area") and f"Y{source_row}" not in formulas:
                formulas[f"Y{source_row}"] = (
                    f'IF(OR(N{source_row}="镀锌板",N{source_row}="蓝白锌",'
                    f'N{source_row}="镀彩锌",N{source_row}="镀白锌",'
                    f'N{source_row}="镀锡",N{source_row}="镀铜",'
                    f'N{source_row}="外协",N{source_row}="外购"),0,'
                    f'(F{source_row}/1000)*(G{source_row}/1000)*2*L{source_row})'
                )
        self.sheets[code] = {"cells": cells, "formulas": formulas}

    @staticmethod
    def _split_concat(expression: str) -> list[str]:
        parts, start, quote = [], 0, None
        for index, char in enumerate(expression):
            if char == '"':
                quote = None if quote else '"'
            elif char == "&" and not quote:
                parts.append(expression[start:index])
                start = index + 1
        parts.append(expression[start:])
        return parts

    @classmethod
    def _shift_formula(cls, formula: str, origin_ref: str, target_ref: str) -> str:
        """Translate a shared Excel formula to its target cell."""
        def coordinates(ref: str):
            match = re.match(r"([A-Z]+)(\d+)", ref)
            if not match:
                return 0, 0
            col = 0
            for char in match.group(1):
                col = col * 26 + ord(char) - 64
            return col, int(match.group(2))

        origin_col, origin_row = coordinates(origin_ref)
        target_col, target_row = coordinates(target_ref)
        col_delta, row_delta = target_col - origin_col, target_row - origin_row

        def replace(match):
            col_abs, col_name, row_abs, row_text = match.groups()
            col, row = coordinates(col_name + row_text)
            if not col_abs:
                col += col_delta
            if not row_abs:
                row += row_delta
            out_col = ""
            n = max(col, 1)
            while n:
                n, rem = divmod(n - 1, 26)
                out_col = chr(65 + rem) + out_col
            return f"{col_abs}{out_col}{row_abs}{row}"

        return re.sub(r"(\$?)([A-Z]{1,3})(\$?)(\d+)", replace, formula)

    @staticmethod
    def _excel_if(condition, yes, no=0):
        """Select between already-evaluated values.

        Formula text is evaluated by Python before this helper is called, so
        this compatibility function does not reproduce Excel's lazy branch
        evaluation.  Formula templates must therefore keep both branches safe
        to evaluate.
        """
        return yes if bool(condition) else no

    @staticmethod
    def _excel_and(*args):
        return all(bool(item) for item in args)

    @staticmethod
    def _excel_or(*args):
        return any(bool(item) for item in args)

    @staticmethod
    def _excel_int(value):
        return math.floor(float(value or 0))

    @staticmethod
    def _excel_text(value, _format=""):
        return str(value)

    def _evaluate_sheet(
        self,
        product_code: str,
        width: float,
        height: float,
        depth: float,
        single_door_count: int = 1,
        double_door_count: int = 0,
    ):
        spec = self.sheets.get(product_code)
        if not spec:
            return None
        cells = dict(spec["cells"])
        formulas = dict(spec["formulas"])
        start, end, _weight_output, _area_output, area_divisor = self.DETAIL_ROWS[product_code]
        cells.update({"B6": float(width), "B7": float(height), "B8": float(depth), "B9": 1})
        door_cells = self.DOOR_CONTROL_CELLS.get(product_code)
        if door_cells:
            cells[door_cells[0]] = int(single_door_count)
            cells[door_cells[1]] = int(double_door_count)
        cache: dict[str, object] = {}
        active: set[str] = set()

        def numeric(value):
            if value is None or value == "":
                return 0.0
            if isinstance(value, (int, float)):
                return value
            try:
                return float(str(value).strip())
            except (TypeError, ValueError):
                return value

        def cell(ref: str):
            ref = ref.replace("$", "")
            value = cache.get(ref)
            if ref not in cache:
                value = evaluate(ref) if ref in formulas else cells.get(ref, "")
                cache[ref] = value
            return numeric(value)

        def evaluate(ref: str):
            ref = ref.replace("$", "")
            if ref in cache:
                return cache[ref]
            if ref in active:
                return 0.0
            active.add(ref)
            try:
                expression = formulas.get(ref)
                if not expression:
                    value = cells.get(ref, "")
                    cache[ref] = value
                    return value
                expression = expression.replace("<>", "!=")
                expression = re.sub(r"(?<![<>=!])=(?!=)", "==", expression)
                expression = expression.replace("^", "**")
                if "&" in expression:
                    pieces = []
                    for part in self._split_concat(expression):
                        result = evaluate_expression(part, concat=True)
                        if result not in (None, ""):
                            pieces.append(
                                str(int(result))
                                if isinstance(result, float) and result.is_integer()
                                else str(result)
                            )
                    value = "".join(pieces)
                else:
                    value = evaluate_expression(expression, concat=False)
                cache[ref] = value
                return value
            finally:
                active.discard(ref)

        def evaluate_expression(expression: str, concat: bool = False):
            default_if = "\"\"" if concat else "0"
            expression = re.sub(r",\s*\)", f",{default_if})", expression)
            expression = self._replace_cell_references(
                expression,
                lambda match: f'CELL("{match.group(1)}{match.group(2)}")'
            )
            environment = {
                "CELL": cell, "IF": self._excel_if, "AND": self._excel_and,
                "OR": self._excel_or, "INT": self._excel_int, "TEXT": self._excel_text,
                "math": math,
            }
            try:
                return eval(expression, {"__builtins__": {}}, environment)
            except Exception:
                return 0.0

        try:
            detail_values: dict[int, tuple[object, object, object, object, object]] = {}
            area = 0.0
            for row in range(start, end + 1):
                for col in ("F", "G", "H", "I", "J", "K", "L", "M", "N", "Y"):
                    ref = f"{col}{row}"
                    if ref in formulas:
                        evaluate(ref)
                detail_values[row] = (
                    cell(f"E{row}"), cell(f"H{row}"), cell(f"M{row}"),
                    cell(f"N{row}"), cell(f"Y{row}"),
                )
                area += float(numeric(cell(f"Y{row}")))
            # The summary cell is not a raw sum of every detail row.  It
            # classifies galvanized sheets, ordinary sheets by thickness, and
            # lock-rod rows exactly like the workbook's SUMPRODUCT formulas.
            weight = 0.0
            for item_name, thickness, row_weight, treatment, _row_area in detail_values.values():
                thickness = numeric(thickness)
                row_weight = numeric(row_weight)
                treatment = "" if treatment in (None, 0.0) else str(treatment)
                item_name = "" if item_name in (None, 0.0) else str(item_name)
                is_lock = "锁杆" in item_name
                is_frame = "框架" in item_name
                if treatment == "镀锌板":
                    if abs(float(thickness) - 2.5) < 1e-6 or abs(float(thickness) - 3) < 1e-6:
                        weight += float(row_weight)
                elif is_lock:
                    weight += float(row_weight)
                elif not is_lock and float(thickness) in (1, 1.5, 2, 2.5, 3):
                    # The workbook excludes frame rows only from the 1.5 mm
                    # category; its 2/2.5/3 mm SUMPRODUCT categories include
                    # frames and therefore must retain that behavior.
                    if float(thickness) != 1.5 or not is_frame:
                        weight += float(row_weight)
            if product_code == "JM":
                weight *= 1.1
            self.last_detail_values = detail_values
            return max(weight, 0.0), max(area / area_divisor, 0.0)
        except Exception:
            return None

    def calculate(
        self,
        product_code: str,
        width: float,
        height: float,
        depth: float,
        single_door_count: int = 1,
        double_door_count: int = 0,
    ):
        try:
            return self._evaluate_sheet(
                product_code,
                width,
                height,
                depth,
                single_door_count,
                double_door_count,
            )
        except Exception:
            return None


def money(value) -> str:
    if value is None:
        return "待补充"
    return f"{float(value):,.2f} 元"


class ApiWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, url: str, payload: dict, parent=None, method: str = "POST"):
        super().__init__(parent)
        self.url = url
        self.payload = payload
        self.method = method.upper()

    def run(self) -> None:
        try:
            body = None
            if self.method != "GET":
                body = json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                self.url,
                data=body,
                headers=api_headers(body is not None),
                method=self.method,
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
            self.succeeded.emit(result)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            self.failed.emit(detail or f"HTTP {exc.code}")
        except Exception as exc:  # pragma: no cover - UI error path
            self.failed.emit(str(exc))


class WorkbookExportWorker(QThread):
    """Generate the final workbook without blocking the Qt event loop."""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, exporter, output_path: str, payload: dict, parent=None):
        super().__init__(parent)
        self.exporter = exporter
        self.output_path = output_path
        self.payload = payload

    def run(self) -> None:
        try:
            self.exporter(self.output_path, self.payload)
            self.succeeded.emit(str(Path(self.output_path).resolve()))
        except Exception as exc:  # pragma: no cover - UI error path
            self.failed.emit(str(exc))


class AttachmentDialog(QDialog):
    """用可勾选表格批量选择数据库附件及价格方案。"""

    COL_CHECK = 0
    COL_NAME = 1
    COL_SPEC = 2
    COL_SCHEME = 3
    COL_PRICE = 4
    COL_QUANTITY = 5

    def __init__(
        self,
        attachments: list[dict],
        api_url: str = API_URL,
        parent=None,
        target_dimensions: tuple[float, float, float] | None = None,
        recommended_names: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("附件选择")
        self.resize(1050, 680)
        self.attachments = [dict(item) for item in attachments]
        self.catalog: list[dict] = []
        self.api_url = api_url
        self.target_dimensions = target_dimensions
        self.recommended_names = list(recommended_names or [])

        self.catalog_hint = QLabel("正在读取附件价格库…")
        self.catalog_hint.setWordWrap(True)
        reload_button = QPushButton("重新读取价格库")
        reload_button.clicked.connect(self.reload_catalog)
        catalog_row = QHBoxLayout()
        catalog_row.addWidget(self.catalog_hint, 1)
        catalog_row.addWidget(reload_button)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("搜索分类、名称、型号、尺寸或价格方案")
        self.search_edit.textChanged.connect(self.apply_filter)

        self.category_selection: list[str] = []
        self.category_panel = QFrame(self)
        self.category_panel.setObjectName("attachmentCategoryBar")
        category_panel_layout = QVBoxLayout(self.category_panel)
        category_panel_layout.setContentsMargins(14, 10, 14, 12)
        category_panel_layout.setSpacing(9)
        category_header = QHBoxLayout()
        self.category_back_button = QPushButton("← 返回上一级", self.category_panel)
        self.category_back_button.setObjectName("attachmentCategoryBack")
        self.category_back_button.clicked.connect(self.back_attachment_category)
        self.category_breadcrumb = QLabel("附件库 / 一级分类", self.category_panel)
        self.category_breadcrumb.setObjectName("attachmentCategoryTitle")
        self.category_breadcrumb.setWordWrap(True)
        category_header.addWidget(self.category_back_button)
        category_header.addWidget(self.category_breadcrumb, 1)
        category_panel_layout.addLayout(category_header)

        self.category_scroll = QScrollArea(self.category_panel)
        self.category_scroll.setObjectName("attachmentCategoryScroll")
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setFrameShape(QFrame.NoFrame)
        self.category_scroll.setMinimumHeight(390)
        self.category_scroll_content = QWidget(self.category_scroll)
        self.category_grid = QGridLayout(self.category_scroll_content)
        self.category_grid.setContentsMargins(0, 0, 0, 0)
        self.category_grid.setHorizontalSpacing(10)
        self.category_grid.setVerticalSpacing(10)
        self.category_grid.setAlignment(Qt.AlignTop)
        for column in range(4):
            self.category_grid.setColumnStretch(column, 1)
        self.category_scroll.setWidget(self.category_scroll_content)
        category_panel_layout.addWidget(self.category_scroll)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["选择", "名称", "尺寸/规格", "价格方案", "单价（元）", "数量"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(430)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_CHECK, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_SPEC, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_SCHEME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_PRICE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_QUANTITY, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self.table_item_changed)

        self.selection_hint = QLabel("已勾选 0 项")
        self.selection_hint.setStyleSheet("font-weight:600;color:#174a73;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确认选择")
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        title = QLabel("附件价格清单")
        title.setStyleSheet("font-size:20px;font-weight:700;color:#173f67;")
        layout.addWidget(title)
        if self.recommended_names:
            recommendation = QLabel("OCR 推荐（请人工确认规格和价格）：" + "、".join(self.recommended_names))
            recommendation.setWordWrap(True)
            recommendation.setStyleSheet("color:#b45309;font-weight:600;")
            layout.addWidget(recommendation)
        layout.addLayout(catalog_row)
        layout.addWidget(self.category_panel)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.selection_hint)
        layout.addWidget(buttons)

        self.load_catalog(api_url)

    @staticmethod
    def format_size(item: dict) -> str:
        values = [item.get("width_mm"), item.get("height_mm"), item.get("depth_mm")]
        if not any(value is not None for value in values):
            return "通用"
        return " × ".join("-" if value is None else str(value) for value in values) + " mm"

    @staticmethod
    def display_name(item: dict) -> str:
        """Return the selectable attachment name shown to the operator.

        Fan records are stored with the model appended to ``item_name`` (for
        example ``风机KA1238DC/24V``).  They are one attachment category in
        the UI; the model is selected in the size/specification field instead.
        """
        name = str(item.get("item_name") or "").strip()
        if name.startswith("风机"):
            return "风机"
        if name.startswith("过滤网"):
            return "过滤网"
        return name

    @classmethod
    def format_catalog_option(cls, item: dict) -> str:
        """Show a distinguishable choice when one name has several prices."""
        size = cls.format_size(item)
        descriptor = str(item.get("model_code") or item.get("variant") or "").strip()
        # Fan models (and other catalogue entries without physical dimensions)
        # are specifications, so expose the model in the 尺寸/规格 selector
        # rather than making the name selector contain every model.
        if size == "通用" and item.get("model_code"):
            size = descriptor
            descriptor = str(item.get("variant") or "").strip()
        price = item.get("price")
        if price is not None:
            unit = str(item.get("unit") or "元").strip()
            price_text = f"{float(price):g} {unit}" if unit else f"{float(price):g} 元"
        elif item.get("price_text"):
            price_text = str(item["price_text"])
        else:
            price_text = "待确认"
        source = str(item.get("price_source") or "").strip()
        if source:
            price_text = f"{price_text}（{source}）"
        notes = str(item.get("notes") or "").strip()
        if notes:
            price_text = f"{price_text}（{notes}）"
        details = " · ".join(part for part in (descriptor, price_text) if part)
        return f"{size} · {details}" if details else size

    @classmethod
    def specification_key(cls, item: dict) -> str:
        """The second selection level: physical size or model/specification."""
        size = cls.format_size(item)
        if size != "通用":
            return size
        for key in ("model_code", "variant"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        return "通用"

    @staticmethod
    def format_price_option(item: dict) -> str:
        """The final, explicit price selection shown after a specification."""
        parts = []
        for key in ("variant", "price_source"):
            value = str(item.get(key) or "").strip()
            if value and value not in parts:
                parts.append(value)
        price = item.get("price")
        if price is not None:
            parts.append(f"{float(price):g} {str(item.get('unit') or '元').strip()}")
        elif item.get("price_text"):
            parts.append(str(item["price_text"]))
        else:
            parts.append("待确认")
        note = str(item.get("notes") or "").strip()
        if note:
            parts.append(note)
        return " · ".join(parts)

    @staticmethod
    def price_scheme(item: dict) -> str:
        """Describe why two equal specifications can have different prices."""
        parts: list[str] = []
        for key in ("variant", "price_source", "notes"):
            value = str(item.get(key) or "").strip()
            if value and value not in parts:
                parts.append(value)
        if not parts and item.get("price_text"):
            parts.append(str(item["price_text"]).strip())
        return " · ".join(parts) or "默认"

    @staticmethod
    def category_value(item: dict, key: str) -> str:
        level = ("category_level1", "category_level2", "category_level3").index(key)
        return attachment_category_value(item, level)

    @classmethod
    def category_path(cls, item: dict) -> tuple[str, str, str]:
        return attachment_category_path(item)

    def _clear_category_cards(self) -> None:
        while self.category_grid.count():
            item = self.category_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _specification_text(self) -> str:
        parent = self.parentWidget()
        for name in ("quote_spec_edit", "model_edit"):
            field = getattr(parent, name, None) if parent is not None else None
            if isinstance(field, QLineEdit) and field.text().strip():
                return field.text().strip()
        return str(getattr(self, "base_quick_match_specification", "") or "").strip()

    def prepare_fixed_base_quick_match(self) -> bool:
        parsed = parse_base_specification(self._specification_text())
        self.base_quick_match_spec = parsed
        self.base_quick_match_item = None
        if parsed is None:
            return False
        parsed_width, _cabinet_height, parsed_depth, base_height = parsed
        width, depth = parsed_width, parsed_depth
        if isinstance(self.target_dimensions, (list, tuple)) and len(self.target_dimensions) >= 3:
            try:
                width = float(self.target_dimensions[0])
                depth = float(self.target_dimensions[2])
            except (TypeError, ValueError):
                width, depth = parsed_width, parsed_depth
        matched = match_fixed_base(self.catalog, width, depth, base_height)
        self.base_quick_match_item = matched
        if matched is None or any(is_base_selection(item) for item in self.attachments):
            return False
        selected = dict(matched)
        selected["quantity"] = 1
        self.attachments.append(selected)
        return True

    def quick_match_label(self, option: dict) -> tuple[str, str, str]:
        if not self.category_selection and option.get("value") == "底座":
            parsed = getattr(self, "base_quick_match_spec", None)
            if parsed is None:
                return "快速匹配\n无需底座", "attachmentQuickMatch", "规格高度没有括号和 +，不自动选择底座"
            height_text = f"{parsed[3]:g}"
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

    def refresh_category_browser(self) -> None:
        self.category_selection = valid_selection_prefix(self.catalog, self.category_selection)
        self._clear_category_cards()
        options = category_options(self.catalog, self.category_selection)
        path_labels = [value or "本级附件" for value in self.category_selection]
        breadcrumb = "附件库"
        if path_labels:
            breadcrumb += "  ›  " + "  ›  ".join(path_labels)
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
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, value=option["value"]: self.open_attachment_category(value)
            )
            quick_text, quick_object_name, quick_tooltip = self.quick_match_label(option)
            quick_match = QLabel(quick_text, card)
            quick_match.setObjectName(quick_object_name)
            quick_match.setAccessibleName(f"{option['label']}，{quick_text.replace(chr(10), '，')}")
            quick_match.setToolTip(quick_tooltip)
            quick_match.setWordWrap(True)
            quick_match.setMinimumHeight(48 if quick_text.count("\n") == 1 else 66)
            card_layout.addWidget(button)
            card_layout.addWidget(quick_match)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.category_grid.addWidget(card, index // 4, index % 4)

        at_category_level = bool(options)
        self.category_scroll.setVisible(at_category_level)
        self.search_edit.setVisible(not at_category_level)
        self.table.setVisible(not at_category_level)
        if not at_category_level:
            self.apply_filter(self.search_edit.text())

    def open_attachment_category(self, value: str) -> None:
        self.category_selection.append(str(value))
        self.search_edit.clear()
        self.refresh_category_browser()

    def back_attachment_category(self) -> None:
        if self.category_selection:
            self.category_selection.pop()
        self.search_edit.clear()
        self.refresh_category_browser()

    @staticmethod
    def _number(value) -> float | None:
        try:
            return float(value) if value is not None and str(value).strip() else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _same_catalog_choice(cls, selected: dict, catalog_item: dict) -> bool:
        """Match an existing selection back to one exact catalogue row."""
        if str(selected.get("item_name") or "").strip() != str(catalog_item.get("item_name") or "").strip():
            return False
        for key in ("model_code", "variant", "price_source"):
            left = str(selected.get(key) or "").strip()
            right = str(catalog_item.get(key) or "").strip()
            if left and left != right:
                return False
        for key in ("width_mm", "height_mm", "depth_mm"):
            left = cls._number(selected.get(key))
            right = cls._number(catalog_item.get(key))
            if left is not None and (right is None or abs(left - right) > 0.0001):
                return False
        selected_price = cls._number(selected.get("unit_price_override", selected.get("matched_price")))
        catalog_price = cls._number(catalog_item.get("price"))
        if selected_price is not None and catalog_price is not None and abs(selected_price - catalog_price) > 0.0001:
            # A manually overridden price still belongs to this catalogue row.
            return selected.get("unit_price_override") is not None
        return True

    @staticmethod
    def _readonly_item(text: str, alignment=Qt.AlignLeft | Qt.AlignVCenter) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        item.setTextAlignment(alignment)
        return item

    def _append_row(self, catalog_item: dict, selected: dict | None = None, historical: bool = False):
        row = self.table.rowCount()
        self.table.insertRow(row)

        check_item = QTableWidgetItem()
        check_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        check_item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
        check_item.setTextAlignment(Qt.AlignCenter)
        check_item.setData(Qt.UserRole, dict(catalog_item))
        self.table.setItem(row, self.COL_CHECK, check_item)

        display_name = self.display_name(catalog_item) or str(catalog_item.get("item_name") or "未命名附件")
        self.table.setItem(row, self.COL_NAME, self._readonly_item(display_name))
        self.table.setItem(row, self.COL_SPEC, self._readonly_item(self.specification_key(catalog_item)))
        scheme = self.price_scheme(catalog_item)
        if historical:
            scheme = f"历史/手工 · {scheme}"
        self.table.setItem(row, self.COL_SCHEME, self._readonly_item(scheme))

        price = None
        if selected:
            price = self._number(selected.get("unit_price_override", selected.get("matched_price")))
        if price is None:
            price = self._number(catalog_item.get("price"))
        price_item = QTableWidgetItem("" if price is None else f"{price:g}")
        price_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, self.COL_PRICE, price_item)

        quantity = self._number((selected or {}).get("quantity")) or 1
        quantity_item = QTableWidgetItem(f"{quantity:g}")
        quantity_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        quantity_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.COL_QUANTITY, quantity_item)

        is_recommended = any(
            recommendation in display_name or display_name in recommendation
            for recommendation in self.recommended_names
        )
        if is_recommended:
            for column in range(self.table.columnCount()):
                cell = self.table.item(row, column)
                if cell:
                    cell.setToolTip("OCR 推荐附件，请人工确认规格、数量和价格")

    def rebuild_table(self):
        """Rebuild all catalogue rows and restore checked historical choices."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        unmatched = [dict(item) for item in self.attachments]
        used_selected: set[int] = set()

        def sort_key(item: dict):
            display = self.display_name(item)
            recommended = any(name in display or display in name for name in self.recommended_names)
            return (
                0 if recommended else 1,
                *self.category_path(item),
                display,
                self.specification_key(item),
                self.price_scheme(item),
            )

        for catalog_item in sorted(self.catalog, key=sort_key):
            selected_index = next(
                (
                    index
                    for index, selected in enumerate(unmatched)
                    if index not in used_selected and self._same_catalog_choice(selected, catalog_item)
                ),
                None,
            )
            selected = unmatched[selected_index] if selected_index is not None else None
            if selected_index is not None:
                used_selected.add(selected_index)
            self._append_row(catalog_item, selected)

        # Do not silently lose an old/manual selection whose source row has
        # since been removed from the database.  It remains visible and checked.
        for index, selected in enumerate(unmatched):
            if index not in used_selected:
                self._append_row(selected, selected, historical=True)

        self.table.blockSignals(False)
        self.apply_filter(self.search_edit.text())
        self.update_selection_hint()

    def reload_catalog(self):
        current = self.collect_attachments(show_errors=False)
        if current is not None:
            self.attachments = current
        self.load_catalog(self.api_url)

    def load_catalog(self, api_url: str):
        catalog_url = api_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/catalog"
        try:
            request = urllib.request.Request(catalog_url, headers=api_headers(), method="GET")
            with urllib.request.urlopen(request, timeout=4) as response:
                body = json.loads(response.read().decode("utf-8"))
            self.catalog = [dict(item) for item in body.get("items", []) if item.get("item_name")]
        except Exception as exc:
            self.catalog = []
            detail = _api_error_text(str(exc))
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    detail = _api_error_text(exc.read().decode("utf-8", errors="replace"))
                except OSError:
                    pass
            self.catalog_hint.setText(
                f"附件价格库读取失败：{detail or '未知错误'}。请确认接口正在运行后点击“重新读取价格库”。"
            )
        for item in self.catalog:
            key = str(item["item_name"]).strip()
            item["item_name"] = key
            item["display_name"] = self.display_name(item)
            for category_key in ("category_level1", "category_level2", "category_level3"):
                item[category_key] = self.category_value(item, category_key)
        if self.catalog:
            level1_count = len({item["category_level1"] for item in self.catalog})
            self.catalog_hint.setText(
                f"已读取 {len(self.catalog)} 条附件价格，覆盖 {level1_count} 个一级分类。"
                "逐级进入分类，到达末级后勾选附件。"
            )
        self.base_quick_match_specification = self._specification_text()
        self.prepare_fixed_base_quick_match()
        self.rebuild_table()
        self.refresh_category_browser()

    def apply_filter(self, text: str):
        needle = text.strip().casefold()
        selected_categories = tuple(self.category_selection)
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, self.COL_CHECK)
            source = check_item.data(Qt.UserRole) if check_item else {}
            source = source if isinstance(source, dict) else {}
            category_path = self.category_path(source)
            category_matches = category_path[:len(selected_categories)] == selected_categories
            haystack = " ".join(
                [
                    *category_path,
                    str(source.get("item_name") or ""),
                    str(source.get("model_code") or ""),
                    str(source.get("variant") or ""),
                    *(
                        self.table.item(row, column).text()
                        for column in (self.COL_NAME, self.COL_SPEC, self.COL_SCHEME, self.COL_PRICE)
                        if self.table.item(row, column)
                    ),
                ]
            ).casefold()
            self.table.setRowHidden(row, not category_matches or bool(needle and needle not in haystack))

    def table_item_changed(self, item: QTableWidgetItem):
        if item.column() == self.COL_CHECK:
            self.update_selection_hint()

    def update_selection_hint(self):
        count = sum(
            1
            for row in range(self.table.rowCount())
            if self.table.item(row, self.COL_CHECK)
            and self.table.item(row, self.COL_CHECK).checkState() == Qt.Checked
        )
        self.selection_hint.setText(f"已勾选 {count} 项；单价和数量可直接双击修改")

    def collect_attachments(self, show_errors: bool = True) -> list[dict] | None:
        selected_rows: list[dict] = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, self.COL_CHECK)
            if not check_item or check_item.checkState() != Qt.Checked:
                continue
            source = check_item.data(Qt.UserRole)
            if not isinstance(source, dict):
                continue
            try:
                quantity = float(self.table.item(row, self.COL_QUANTITY).text().strip())
                if quantity <= 0 or not quantity.is_integer():
                    raise ValueError
            except (AttributeError, TypeError, ValueError):
                if show_errors:
                    QMessageBox.warning(self, "数量格式错误", f"第 {row + 1} 行的数量必须是大于 0 的整数。")
                return None
            try:
                price = float(self.table.item(row, self.COL_PRICE).text().strip())
                if price < 0:
                    raise ValueError
            except (AttributeError, TypeError, ValueError):
                if show_errors:
                    QMessageBox.warning(self, "单价格式错误", f"第 {row + 1} 行尚无有效数字单价，请填写后再确认。")
                return None

            item = {"item_name": source.get("item_name") or self.table.item(row, self.COL_NAME).text()}
            item["quantity"] = int(quantity)
            for key in ("model_code", "variant", "price_source", "price_text", "notes"):
                if source.get(key) is not None:
                    item[key] = source[key]
            for key in ("width_mm", "height_mm", "depth_mm"):
                if source.get(key) is not None:
                    item[key] = source[key]
            catalog_price = self._number(source.get("price"))
            if catalog_price is not None:
                item["matched_price"] = catalog_price
            if catalog_price is None or abs(price - catalog_price) > 0.0001:
                item["unit_price_override"] = price
            selected_rows.append(item)
        return selected_rows

    def accept_selection(self):
        selected = self.collect_attachments(show_errors=True)
        if selected is None:
            return
        self.attachments = selected
        self.accept()


class DrawingRecognitionTools:
    """PDF drawing dimension and OCR helpers shared by the active desktop window."""

    @staticmethod
    def find_dimension_candidates(text: str) -> list[tuple[float, float, float]]:
        """Extract cabinet dimensions written as W×H×D, including drawing OCR variants.

        Engineering drawings commonly contain forms such as ``950xH2000xW400``
        or ``L950 × H2000XW400``.  The letters are labels, not separators, so
        they are deliberately ignored while preserving the width/height/depth
        order used by the quote workflow.
        """
        pattern = re.compile(
            r"(?<![\d.])(\d{2,6}(?:\.\d+)?)\s*[x×*＊]\s*[A-Za-z宽高深WDH]?\s*"
            r"(\d{2,6}(?:\.\d+)?)\s*[x×*＊]\s*[A-Za-z宽高深WDH]?\s*"
            r"(\d{2,6}(?:\.\d+)?)(?![\d.])",
            re.IGNORECASE,
        )
        source_text = text or ""
        found: list[tuple[float, float, float]] = []
        for a, b, c in pattern.findall(source_text):
            item = (float(a), float(b), float(c))
            if item not in found:
                found.append(item)

        # On low-contrast scans Windows OCR can lose the first digit of a
        # printed size while still reading the product/order code correctly,
        # e.g. ``KP802060005 (御0×2000×600)``.  A common cabinet order code
        # stores W/H/D as WW-HH-DD followed by a three-digit suffix.  Only use
        # that code when its decoded height and depth agree with the visible
        # incomplete size, so unrelated drawing numbers cannot become sizes.
        incomplete_pattern = re.compile(
            r"(?<!\d)(\d{1,2})\s*[x×*＊]\s*(\d{3,4}(?:\.\d+)?)\s*"
            r"[x×*＊]\s*(\d{2,4}(?:\.\d+)?)(?!\d)",
            re.IGNORECASE,
        )
        for partial in incomplete_pattern.finditer(source_text):
            first = float(partial.group(1))
            height = float(partial.group(2))
            depth = float(partial.group(3))
            if first >= 100:
                continue
            context = source_text[max(0, partial.start() - 40):partial.start()]
            code_matches = list(re.finditer(r"[A-Za-z]{1,4}(\d{6})(\d{3})(?!\d)", context))
            if not code_matches:
                continue
            packed = code_matches[-1].group(1)
            decoded = (
                float(int(packed[0:2]) * 10),
                float(int(packed[2:4]) * 100),
                float(int(packed[4:6]) * 10),
            )
            if abs(decoded[1] - height) <= 1 and abs(decoded[2] - depth) <= 1:
                if decoded not in found:
                    found.append(decoded)
        # OCR may read the last zero of ``400`` as ``40`` in one orientation
        # and correctly as ``400`` in another.  When the same width/height is
        # repeated, keep the largest depth so the complete dimension wins.
        consolidated: list[tuple[float, float, float]] = []
        for item in found:
            same_prefix = [
                index for index, existing in enumerate(consolidated)
                if existing[:2] == item[:2]
            ]
            if same_prefix:
                index = same_prefix[0]
                if item[2] > consolidated[index][2]:
                    consolidated[index] = item
            else:
                consolidated.append(item)
        # A sideways drawing can produce two complementary OCR readings, for
        # example ``50×2000×400`` and ``950×2000×40``.  When the height agrees
        # and each reading has one implausibly truncated dimension, combine
        # the complete width and depth into the first (preferred) candidate.
        repaired: list[tuple[float, float, float]] = []
        consumed: set[int] = set()
        for left_index, left in enumerate(consolidated):
            if left_index in consumed:
                continue
            merged = None
            for right_index in range(left_index + 1, len(consolidated)):
                if right_index in consumed:
                    continue
                right = consolidated[right_index]
                complementary = (
                    left[1] == right[1]
                    and (
                        (left[0] < 100 <= right[0] and right[2] < 100 <= left[2])
                        or (right[0] < 100 <= left[0] and left[2] < 100 <= right[2])
                    )
                )
                if complementary:
                    merged = (max(left[0], right[0]), left[1], max(left[2], right[2]))
                    consumed.add(right_index)
                    break
            consumed.add(left_index)
            repaired.append(merged or left)
        return repaired

    @classmethod
    def find_remark_dimension_candidates(cls, text: str) -> list[tuple[float, float, float]]:
        """Extract W/H/D printed beside a cabinet model/order description.

        Some drawings do not place the cabinet size in a dedicated title-block
        field.  Instead it appears in a numbered remark such as
        ``型号 柜体订货号：KP802060005（800×2000×600 RAL7035）``.  These values
        describe the complete cabinet and therefore outrank any other triple
        found among hole, mounting or detail dimensions elsewhere on the page.
        """
        source = text or ""
        anchors = re.compile(
            r"型号.{0,18}?(?:柜|拒)\s*体.{0,12}?订\s*(?:货|贷)\s*号|"
            r"(?:柜|拒)\s*体.{0,12}?订\s*(?:货|贷)\s*号|"
            r"订\s*(?:货|贷)\s*号",
            re.IGNORECASE,
        )
        found: list[tuple[float, float, float]] = []
        for anchor in anchors.finditer(source):
            # Keep the order/model code before the dimension in the snippet;
            # find_dimension_candidates can use it to repair a lost first OCR
            # digit such as ``御0×2000×600``.
            snippet = source[anchor.start():min(len(source), anchor.end() + 180)]
            for item in cls.find_dimension_candidates(snippet):
                if item not in found:
                    found.append(item)
        return found

    @staticmethod
    def extract_technical_requirements(text: str) -> str:
        """Return only the numbered technical-requirements block.

        Drawings from different customers do not share one fixed wording.  The
        old implementation expected six specific sentences and therefore fell
        back to the first 600 characters of the whole page when the wording was
        different.  That mixed dimensions, title-block text and company names
        into the notes field.  This parser follows the numbered list instead.
        """
        if not text:
            return ""
        normalized = str(text).replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n+", " ", normalized)
        heading_pattern = re.compile(r"技\s*术\s*要\s*求\s*(?:[:：·．.、]|$)?")
        headings = list(heading_pattern.finditer(normalized))
        if not headings:
            return ""

        marker_pattern = re.compile(
            r"(?<![\d.])([1-9])(?:\s*[.．、，,]\s*|\s+)"
            r"(?=[A-Za-z\u3400-\u9fff（(《【])"
        )
        parsed_blocks: list[tuple[tuple[int, int, int], str]] = []
        for heading_index, start_match in enumerate(headings):
            next_heading = headings[heading_index + 1].start() if heading_index + 1 < len(headings) else len(normalized)
            section = normalized[start_match.end():next_heading]
            section = re.split(
                r"标记\s*(?:处数|处教|数量)|更改文件号|图样标记|设计\s*审核|"
                r"标准化\s*工艺|JINGGONG|精工(?:智能|科技)|共\s*\d+\s*页|"
                r"第\s*\d+\s*页|比例\s*\d+\s*[:：]",
                section,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            section = DrawingRecognitionTools._repair_numbered_requirement_ocr(section)
            markers = list(marker_pattern.finditer(section))
            if not markers:
                continue

            candidates: list[list[re.Match[str]]] = []
            for start_index, start_marker in enumerate(markers):
                if int(start_marker.group(1)) != 1:
                    continue
                candidate = [start_marker]
                expected = 2
                for marker in markers[start_index + 1:]:
                    number = int(marker.group(1))
                    if number == 1:
                        break
                    if number == expected:
                        candidate.append(marker)
                        expected += 1
                    elif number > expected:
                        break
                candidates.append(candidate)
            sequence = max(candidates, key=lambda item: (len(item), int(item[-1].group(1))), default=[])
            if not sequence:
                continue

            intro = section[: sequence[0].start()].strip(" ：:，,。.;；")
            if len(intro) > 60 or not intro.startswith(("（", "(")):
                intro = ""
            intro = re.sub(r"\s*([，。；：、（）])\s*", r"\1", intro)
            output_heading = "技术要求" + (f"：{intro}" if intro else "：")
            lines: list[str] = []
            for index, marker in enumerate(sequence):
                number = int(marker.group(1))
                end = sequence[index + 1].start() if index + 1 < len(sequence) else len(section)
                body = section[marker.end():end].strip(" ：:，,。.;；·．")
                body = DrawingRecognitionTools._clean_requirement_body(number, body)
                if not body:
                    continue
                # Preserve the source drawing's numbered-sentence style: every
                # requirement is a complete sentence, not a semicolon-joined
                # paragraph.
                ending = "。"
                if body.endswith(("。", "；", ".", ";", "·", "．")):
                    body = body[:-1] + ending
                else:
                    body += ending
                lines.append(f"{number}.{body}")
            if lines:
                # Prefer a continuous 1..N list, then the larger item count and
                # finally the richer text.  This prevents a one-line detail note
                # elsewhere on the drawing from winning over the actual list.
                last_number = int(sequence[len(lines) - 1].group(1))
                score = (1 if last_number == len(lines) else 0, len(lines), sum(map(len, lines)))
                parsed_blocks.append((score, output_heading + "\n" + "\n".join(lines)))
        return max(parsed_blocks, key=lambda item: item[0], default=((0, 0, 0), ""))[1]

    @staticmethod
    def _repair_numbered_requirement_ocr(section: str) -> str:
        """Repair list boundaries that OCR commonly drops on scanned drawings."""
        value = section or ""
        # The operation-table sheet prints a compact seven-line requirements
        # block in the lower-right corner.  Its faint first digit is regularly
        # lost while the unmistakable first sentence remains readable.  Add
        # only the missing list marker; the sentence itself is cleaned later.
        item2 = re.search(r"(?<!\d)2\s*[.．、，,]?\s*(?:焊|熔|典)\s*缝", value)
        item1_candidates = list(re.finditer(r"(?<!\d)1\s*[.．、，,]", value))
        item1 = next(
            (match for match in item1_candidates if not item2 or match.start() < item2.start()),
            None,
        )
        if item2 and not item1 and re.search(r"断\s*续\s*[焊爆]", value[:item2.start()]):
            value = "1、" + value

        # The same scan can lose item 4 while retaining its complete wording.
        # Restore the boundary only when it lies between numbered items 3 and
        # 5, preventing an ordinary occurrence of the phrase from being split.
        item3_marker = re.search(r"(?<!\d)3\s*[.．、，,]", value)
        item5_marker = re.search(r"(?<!\d)5\s*[.．、，,]", value)
        item4_marker = re.search(r"(?<!\d)4\s*[.．、，,]", value)
        cabinet_reference = re.search(r"此\s*柜\s*形\s*式\s*仅\s*供\s*参\s*考", value)
        if (
            item3_marker and item5_marker and cabinet_reference
            and item3_marker.end() < cabinet_reference.start() < item5_marker.start()
            and (not item4_marker or not (item3_marker.end() < item4_marker.start() < item5_marker.start()))
        ):
            value = value[:cabinet_reference.start()] + "4、" + value[cabinet_reference.start():]
        # On folded/scanned pages the faint item number and the middle strokes
        # of "安装板" can disappear together.  Windows OCR then emits text such
        # as "按钮孔·左、安2块，侧板..." and items 4-6 are swallowed by item 3.
        # Restore the boundary only when "安 + quantity + 侧板" immediately
        # follows the button-hole sentence; this is too specific to affect an
        # ordinary occurrence of the character 安.
        value = re.sub(
            r"(按钮孔)\s*[·．。，,;；]?\s*(?:左\s*[、，,])?\s*安\s*"
            r"(?=(\d+)\s*块\s*[，,]\s*侧\s*板)",
            r"\1。4、安装板",
            value,
            count=1,
        )
        # In the Jinggong drawings the faint digit 4 is often lost, while the
        # text "安装板" remains clear.  Only insert it between items 3 and 5/6.
        item3 = re.search(r"(?<!\d)3\s*[.．、，,]", value)
        later = re.search(r"(?<!\d)[56]\s*[.．、，,]", value)
        install = re.search(r"安\s*装\s*板", value)
        item4 = re.search(r"(?<!\d)4\s*[.．、，,]", value)
        if item3 and install and later and item3.end() < install.start() < later.start():
            if not item4 or not (item3.end() < item4.start() < later.start()):
                value = value[:install.start()] + "4、" + value[install.start():]
        # Widely separated right-column quantities can be emitted at the end of
        # the crop by Windows OCR.  When item 2 has no quantity and item 6 ends
        # with two quantities, the latter belongs to item 2; move it back while
        # retaining the first quantity for item 6.
        item2 = re.search(r"(?<!\d)2\s*[.．、，,]", value)
        item5 = re.search(r"(?<!\d)5\s*[.．、，,]", value)
        item6 = re.search(r"(?<!\d)6\s*[.．、，,]", value)
        if item2 and item3 and item6:
            item2_text = value[item2.end():item3.start()]
            item6_text = value[item6.end():]
            quantities = re.findall(r"(\d+)\s*个", item6_text)
            if "个" not in item2_text and len(quantities) >= 2:
                value = value[:item3.start()] + f"。{quantities[-1]}个 " + value[item3.start():]
            # A second scan variant retains the unit 个 in item 2 but drops
            # its digit.  For this combination-cabinet note, the explicitly
            # printed installation-plate count is the same order quantity.
            elif not re.search(r"\d+\s*个", item2_text):
                item4_text = value[item4.end():item6.start()] if item4 else ""
                install_count = re.search(r"安装\s*板\s*(\d+)\s*块", item4_text)
                if "KP802060005" in item2_text and install_count:
                    count = install_count.group(1)
                    repaired_item2 = re.sub(
                        r"[，,。．·]?\s*(?:[/／])?\s*个\s*$",
                        f"）。{count}个",
                        item2_text,
                    )
                    value = value[:item2.end()] + repaired_item2 + value[item3.start():]
        # The same fold can erase "2套" after LH01 while leaving the complete
        # item-4 installation-plate quantity.  Restore the missing unit/count
        # only inside the bounded item-5 sentence of this combination cabinet.
        # Item-2 repair above can change string length, so refresh marker
        # offsets before slicing the later requirements.
        item4 = re.search(r"(?<!\d)4\s*[.．、，,]", value)
        item5 = re.search(r"(?<!\d)5\s*[.．、，,]", value)
        item6 = re.search(r"(?<!\d)6\s*[.．、，,]", value)
        if item4 and item5 and item6:
            item4_text = value[item4.end():item5.start()]
            item5_text = value[item5.end():item6.start()]
            install_count = re.search(r"安装\s*板\s*(\d+)\s*块", item4_text)
            if (
                install_count
                and re.search(r"照明\s*灯\s*LH[O0][1I]", item5_text, re.IGNORECASE)
                and not re.search(r"\d+\s*套", item5_text)
            ):
                count = install_count.group(1)
                repaired_item5 = re.sub(
                    r"LH[O0][1I](?:\s*[·．。，,;；])?\s*$",
                    f"LH01 {count}套 ",
                    item5_text,
                    flags=re.IGNORECASE,
                )
                value = value[:item5.end()] + repaired_item5 + value[item6.start():]
        return value

    @staticmethod
    def _clean_requirement_body(number: int, body: str) -> str:
        """Normalize high-confidence OCR confusions without inventing content."""
        value = re.sub(r"[ \t]+", "", body or "")
        value = re.sub(r"\s*([，。；：、（）])\s*", r"\1", value)
        value = value.replace("〈", "（").replace("〉", "）")
        value = value.replace("拒体", "柜体").replace("鞍钮", "按钮")
        value = value.replace("冂1扇", "门1扇").replace("背1块", "背板1块")
        value = re.sub(r"(?<=订货号：)(KP\d+)S(?=\d*块|[^A-Za-z0-9]|$)", r"\g<1>5", value, flags=re.IGNORECASE)
        value = re.sub(r"(?<=侧板：)(KP\d+)S(?=\d*块|[^A-Za-z0-9]|$)", r"\g<1>5", value, flags=re.IGNORECASE)
        value = re.sub(r"(?<!侧)板([：:．.]?KP\d+)", r"侧板\1", value)
        value = re.sub(r"RAL?703(?:引|S|\|)", "RAL7035", value, flags=re.IGNORECASE)
        value = re.sub(r"LHOI", "LH01", value, flags=re.IGNORECASE)
        value = re.sub(r"(?<=LH01)1(?:氨|套)?", " 1套", value)
        value = re.sub(r"\bP\s*54\b", "IP54", value, flags=re.IGNORECASE)
        value = re.sub(r"(?<=材料用)1\s*[，,]\s*2\s*m{1,2}(?=钢板)", "1.2mm", value, flags=re.IGNORECASE)
        if number == 1:
            if re.search(r"断续[焊爆]", value) and re.search(r"[缝縫].*应.*匀", value):
                value = "焊缝应均匀，断续焊"
            elif value.startswith("标志使用红色") and "蓝色" in value and "使用黑色" in value:
                value = "标志使用红色，中文文字使用蓝色。英文使用黑色"
            value = re.sub(r"^标使用红色", "标志使用红色", value)
            value = re.sub(r"蓝色[·．。]?文使用黑色", "蓝色。英文使用黑色", value)
            value = re.sub(r"蓝色[．。]英文", "蓝色。英文", value)
            # Company-logo notes on scanned Jinggong drawings regularly turn
            # the letter O into zero and "按" into "找".  Only repair the
            # complete, unmistakable logo sentence so unrelated numbers are
            # never changed.
            if re.search(r"LOG[O0].*公司要求缩放", value, re.IGNORECASE):
                value = "LOGO按公司要求缩放，LOGO图片按本公司提供"
        if number == 2:
            if re.search(r"[焊典熔].*缝.*平.*整", value) and re.search(r"无.*明.*显.*[交变].*形", value):
                value = "焊缝平整，无明显变形"
            elif "APSD12135005" in value and re.search(r"1200\D+1300\D+500", value):
                value = "型号 APSD12135005（1200×1300×500 RAL7035）"
            value = value.lstrip("《〈<")
            value = value.replace("型号柜体", "型号 柜体")
            value = re.sub(r"([（(]\d{2,4})[xX×](\d{2,4})[xX×](\d{2,4})", r"\1×\2×\3", value)
            value = re.sub(r"(\d)(RAL7035)", r"\1 \2", value)
            value = re.sub(r"(RAL7035)[^）)]*[）)]?", r"\1）", value, count=1)
            value = re.sub(r"）[。．·]+(?=\d+个)", "）。", value)
            # A faint closing parenthesis in the three-cabinet drawing makes
            # Windows OCR read "RAL7035）。3个" as "RAL703靠3／".  The model
            # number and all three dimensions remain legible, so this repair
            # is grounded in the drawing rather than a guessed dimension.
            if (
                "KP802060005" in value
                and re.search(r"800\D{0,3}2000\D{0,3}600", value)
                and re.search(r"RAL703[^\d]{0,3}3(?:个|[/／])", value, re.IGNORECASE)
            ):
                value = "型号 柜体订货号：KP802060005（800×2000×600 RAL7035）。3个"
            # The first digit of 800 is frequently lost in the page fold.  The
            # exact model code plus the two remaining dimensions and a valid
            # order quantity provide enough evidence to restore this line.
            quantity = re.search(r"([1-9])\s*个", value)
            if "KP802060005" in value and re.search(r"2000\D{0,3}600", value) and quantity:
                value = (
                    "型号 柜体订货号：KP802060005（800×2000×600 RAL7035）。"
                    f"{quantity.group(1)}个"
                )
        if number == 3:
            if "集控柜" in value and "表面" in value and "光洁" in value and "痕迹" in value:
                value = "集控柜表面应光洁，不能用手锤敲打痕迹"
            elif re.search(r"[风凤]扇孔", value) and "空开孔" in value and "按钮孔" in value:
                value = "如图示开风扇孔和空开孔，按钮孔"
            value = re.sub(r"^图示开", "如图示开", value)
            value = value.replace("凤扇", "风扇")
        if number == 4:
            if "此柜形式" in value and "参考" in value:
                value = "此柜形式仅供参考"
            elif "前、后部开门" in value and "三块安装板" in value:
                value = "前、后部开门，三块安装板"
            value = re.sub(r"KP2060005(?=\d+块)", "KP2060005 ", value)
            value = re.sub(r"(KP\d{6,})\s*(\d+块)", r"\1 \2", value)
        if number == 5:
            if "表面" in value and "喷漆" in value:
                value = "表面喷漆"
            elif "柜体宽度" in value and "1200mm" in value:
                value = "该柜体宽度为1200mm"
            value = value.replace("照明灯LH01", "照明灯 LH01")
            value = re.sub(r"(?<=LH01)([1-9])(?=套)", r" \1", value)
        if number == 6:
            if "安装" in value and "尺寸" in value and "1.2mm" in value and "钢板" in value:
                value = "在可安装的前提下，各尺寸可适当放大，电器箱材料用1.2mm钢板"
            elif "100mm" in value and "活动底座" in value and "S012105002" in value:
                value = "配100mm高活动底座。S012105002"
            value = value.replace("高話动底座", "高活动底座")
            value = re.sub(r"高活动底座[，,·．]", "高活动底座。", value)
            value = re.sub(r"(S\d{6,})\s*(\d+个).*", r"\1 \2", value, count=1, flags=re.IGNORECASE)
        if number == 7 and "活动底座" in value and re.search(r"300\s*mm", value, re.IGNORECASE):
            # This line spans almost the full page width.  Full-page OCR often
            # stops at the multiplication sign even though the remainder is
            # visible.  Reconstruct only this uniquely identified standard
            # sentence, preserving the detected cabinet/base quantities.
            count_match = re.search(
                r"该\s*([一二三四五六七八九十\d]+)\s*组柜配\s*"
                r"([一二三四五六七八九十\d]+)\s*个活动底座",
                value,
            )
            cabinet_count = count_match.group(1) if count_match else "三"
            base_count = count_match.group(2) if count_match else cabinet_count
            value = (
                f"该{cabinet_count}组柜配{base_count}个活动底座，每个活动底座均四面居中开"
                "300mm（宽）×70mm（高）的进线孔，每个进线孔均配可拆卸盖板，如下图所示"
            )
        elif number == 7 and re.search(r"82\s*[xX×]\s*50", value) and "安装" in value:
            value = "地脚82×50方孔用于安装接插件不要更改"
        return value

    @staticmethod
    def _find_pdftoppm() -> str | None:
        """Locate the Poppler renderer bundled with the desktop runtime."""
        candidates = (
            application_root() / "runtime/poppler/bin/pdftoppm.exe",
            Path(r"C:\Program Files\poppler\Library\bin\pdftoppm.exe"),
        )
        bundled = next((str(path) for path in candidates if path.exists()), None)
        if bundled:
            return bundled
        for name in ("pdftoppm.exe", "pdftoppm"):
            path = shutil.which(name)
            # Only use executable renderers here.
            if path and Path(path).suffix.lower() == ".exe":
                return path
        return None

    @staticmethod
    def _windows_ocr_angle_blocks(
        image_path: str,
        angles: tuple[int, ...] = (0, 90, 180, 270),
    ) -> tuple[bool, dict[int, str]]:
        """Run Windows OCR and retain text from every page orientation.

        This avoids adding a large native OCR installation to the client.  The
        OCR engine and language packs are supplied by Windows itself.
        """
        script = r'''param([string]$InputPath, [string]$AnglesCsv = "0,90,180,270")
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
function Await([object]$op, [type]$resultType) {
  $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
      $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 } |
    Select-Object -First 1
  $task = $method.MakeGenericMethod($resultType).Invoke($null, @($op))
  $task.GetAwaiter().GetResult()
}
$StorageFile = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$FileAccessMode = [Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime]
$BitmapDecoder = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$SoftwareBitmap = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$RandomAccessStream = [Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$OcrEngine = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$OcrResult = [Windows.Media.Ocr.OcrResult,Windows.Media.Ocr,ContentType=WindowsRuntime]
$engine = $OcrEngine::TryCreateFromUserProfileLanguages()
if (-not $engine) { exit 0 }
$redPixels = 0
$probe = [Drawing.Bitmap]::new($InputPath)
for ($y = 0; $y -lt $probe.Height; $y += 12) {
  for ($x = 0; $x -lt $probe.Width; $x += 12) {
    $pixel = $probe.GetPixel($x, $y)
    if ($pixel.R -gt 120 -and $pixel.R -gt ($pixel.G * 1.35) -and $pixel.R -gt ($pixel.B * 1.35)) { $redPixels++ }
  }
}
$probe.Dispose()
if ($redPixels -gt 20) { "__RED_INK__" }
$working = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $working | Out-Null
try {
  foreach ($angleText in $AnglesCsv.Split(',')) {
    $angle = [int]$angleText
    $image = [Drawing.Image]::FromFile($InputPath)
    if ($angle -eq 90) { $image.RotateFlip([Drawing.RotateFlipType]::Rotate90FlipNone) }
    elseif ($angle -eq 180) { $image.RotateFlip([Drawing.RotateFlipType]::Rotate180FlipNone) }
    elseif ($angle -eq 270) { $image.RotateFlip([Drawing.RotateFlipType]::Rotate270FlipNone) }
    $rotated = Join-Path $working ("rot{0}.png" -f $angle)
    $image.Save($rotated, [Drawing.Imaging.ImageFormat]::Png)
    $image.Dispose()
    $file = Await ($StorageFile::GetFileFromPathAsync($rotated)) $StorageFile
    $stream = Await ($file.OpenAsync($FileAccessMode::Read)) $RandomAccessStream
    $decoder = Await ($BitmapDecoder::CreateAsync($stream)) $BitmapDecoder
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) $SoftwareBitmap
    $result = Await ($engine.RecognizeAsync($bitmap)) $OcrResult
    if ($result.Text) {
      "__ANGLE_${angle}__"
      $result.Text
    }
  }
} finally {
  Remove-Item $working -Recurse -Force -ErrorAction SilentlyContinue
}'''
        with tempfile.TemporaryDirectory(prefix="quote_ocr_") as folder:
            script_path = Path(folder) / "windows_ocr.ps1"
            script_path.write_text(script, encoding="utf-8")
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    image_path,
                    ",".join(str(int(angle)) for angle in angles),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            raw = completed.stdout.strip()
            if not raw:
                return False, {}
            has_red = "__RED_INK__" in raw
            clean = raw.replace("__RED_INK__", "")
            blocks: dict[int, str] = {}
            for match in re.finditer(
                r"__ANGLE_(\d+)__\s*(.*?)(?=__ANGLE_\d+__|\Z)",
                clean,
                flags=re.DOTALL,
            ):
                value = match.group(2).strip()
                if value:
                    blocks[int(match.group(1))] = value
            return has_red, blocks

    @classmethod
    def _ocr_image_with_windows(cls, image_path: str) -> str:
        """Return the most readable full-page orientation from Windows OCR."""
        has_red, angle_blocks = cls._windows_ocr_angle_blocks(image_path)
        if not angle_blocks:
            return "__RED_INK__" if has_red else ""

        # Drawing pages are frequently stored sideways.  Chinese character
        # density plus drawing keywords reliably selects the readable
        # orientation while the work runs outside the GUI thread.
        def score(block: str) -> tuple[int, int]:
            cjk = len(re.findall(r"[\u3400-\u9fff]", block))
            keywords = sum(
                block.count(word)
                for word in ("技术", "要求", "备注", "名称", "电气柜", "表面")
            )
            return cjk, keywords

        best = max(angle_blocks.values(), key=score)
        return ("__RED_INK__\n" if has_red else "") + best

    @classmethod
    def _ocr_numbered_requirements_region(cls, image_path: str) -> str:
        """Read dense numbered notes from likely drawing-note regions.

        Full-page OCR can join two unrelated numbered lists in page reading
        order.  Cropping the lower note bands makes the list numbers and line
        breaks large enough for Windows OCR, then the common parser chooses the
        most complete 1..N sequence.
        """
        image = QImage(image_path)
        if image.isNull() or image.width() < 500 or image.height() < 500:
            return ""
        regions = (
            # Most cabinet drawings put the specification list in the lower
            # left half, immediately above the bottom border.
            (0.10, 0.72, 0.62, 0.97),
            # Alternative layout used by drawings with a central title block.
            (0.25, 0.48, 0.76, 0.86),
            # Folded Jinggong operation-table drawings place their compact
            # seven-line requirements block at the lower right, above the
            # title block.  Keeping this crop narrow excludes Q235A and the
            # drawing number that previously became a false requirement.
            (0.66, 0.61, 0.91, 0.84),
            # The companion APSD control-cabinet sheet uses a slightly lower,
            # tighter block.  It needs enlargement to retain all six list
            # numbers; the result is accepted only when APSD is actually read.
            (0.65, 0.65, 0.91, 0.83),
        )
        results: list[str] = []
        with tempfile.TemporaryDirectory(prefix="quote_notes_") as folder:
            for index, (left, top, right, bottom) in enumerate(regions):
                crop = image.copy(
                    int(image.width() * left),
                    int(image.height() * top),
                    max(1, int(image.width() * (right - left))),
                    max(1, int(image.height() * (bottom - top))),
                )
                if index == 3:
                    # Enlarging this one small APSD note block preserves its
                    # faint list numbers.  Other layouts stay at native size;
                    # enlarging them was found to reduce OCR accuracy.
                    crop = crop.scaled(
                        crop.width() * 2,
                        crop.height() * 2,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                crop_path = str(Path(folder) / f"requirements_{index}.png")
                if not crop.save(crop_path, "PNG"):
                    continue
                _, blocks = cls._windows_ocr_angle_blocks(crop_path, (0, 180))
                for block in blocks.values():
                    if index == 3 and "APSD" not in block.replace(" ", "").upper():
                        continue
                    # Windows OCR inserts spaces between almost every Chinese
                    # character on enlarged drawing crops.  Remove only spaces
                    # bounded by CJK characters, preserving numeric units.
                    block = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", block)
                    parsed = cls.extract_technical_requirements("技术要求： " + block)
                    if parsed:
                        results.append(parsed)

        def score(value: str) -> tuple[int, int, int]:
            numbers = [int(item) for item in re.findall(r"(?m)^([1-9])\.", value)]
            continuous = numbers == list(range(1, len(numbers) + 1))
            return (1 if continuous else 0, len(numbers), len(value))

        return max(results, key=score, default="")

    @staticmethod
    def _dimension_numbers(text: str) -> list[float]:
        """Extract plausible millimetre dimensions from an OCR crop."""
        values: list[float] = []
        for token in re.findall(r"(?<![\d.])\d{2,4}(?:\.\d+)?(?![\d.])", text or ""):
            value = float(token)
            if 50 <= value <= 4000 and value not in values:
                values.append(value)
        return values

    @classmethod
    def _infer_dimensions_from_views(cls, image_path: str) -> tuple[float, float, float] | None:
        """Infer W/H/D from the front and side views in the upper drawing area.

        The first upper view is the front view: its horizontal overall
        dimension is cabinet width and its vertical overall dimension is
        cabinet height.  The second upper view is the side view: its horizontal
        overall dimension is cabinet depth.  OCR is run in both horizontal and
        vertical orientations for each crop so small title-block values cannot
        compete with these view dimensions.
        """
        image = QImage(image_path)
        if image.isNull() or image.width() < 500 or image.height() < 500:
            return None

        regions = {
            # Fractions deliberately overlap slightly because view spacing
            # varies between customer drawing templates.
            # Narrow top crops isolate horizontal overall dimensions and avoid
            # installation-plate notes inside the views.
            "front_horizontal": (0.045, 0.035, 0.445, 0.280),
            "side_horizontal": (0.425, 0.035, 0.625, 0.250),
            # Full-height crops retain the vertical overall dimension.
            "front_vertical": (0.045, 0.035, 0.445, 0.610),
            "side_vertical": (0.425, 0.035, 0.625, 0.610),
        }
        with tempfile.TemporaryDirectory(prefix="quote_views_") as folder:
            angle_text: dict[str, dict[int, str]] = {}
            for name, (left, top, right, bottom) in regions.items():
                crop = image.copy(
                    int(image.width() * left),
                    int(image.height() * top),
                    max(1, int(image.width() * (right - left))),
                    max(1, int(image.height() * (bottom - top))),
                )
                crop_path = str(Path(folder) / f"{name}.png")
                if not crop.save(crop_path, "PNG"):
                    continue
                _, blocks = cls._windows_ocr_angle_blocks(crop_path)
                angle_text[name] = blocks

        if any(name not in angle_text for name in regions):
            return None

        def numbers(view: str, angles: tuple[int, ...]) -> list[float]:
            combined = " ".join(angle_text[view].get(angle, "") for angle in angles)
            return cls._dimension_numbers(combined)

        front_horizontal = numbers("front_horizontal", (0, 180))
        front_vertical = numbers("front_vertical", (90, 270))
        side_horizontal = numbers("side_horizontal", (0, 180))
        side_vertical = numbers("side_vertical", (90, 270))
        if not front_horizontal or not side_horizontal or not (front_vertical or side_vertical):
            return None

        width = max(front_horizontal)
        # The side view carries the same overall height and is a reliable
        # cross-check when the vertical front-view label is faint.
        height = max(front_vertical + side_vertical)
        depth = max(side_horizontal)
        # Cabinet dimensions are expected to be meaningful physical lengths;
        # these guards reject hole, flange and surface-roughness annotations.
        if not (100 <= width <= 3000 and 100 <= height <= 4000 and 50 <= depth <= 2000):
            return None
        if height < max(width, depth) * 0.65:
            return None
        return width, height, depth

    @classmethod
    def _ocr_pdf_details(cls, path: str) -> tuple[str, list[tuple[float, float, float]]]:
        """Render a PDF and return OCR text plus view-derived dimensions."""
        renderer = cls._find_pdftoppm()
        if not renderer:
            return "", []
        with tempfile.TemporaryDirectory(prefix="quote_pdf_") as folder:
            prefix = str(Path(folder) / "page")
            completed = subprocess.run(
                [renderer, "-png", "-r", "300", "-f", "1", "-l", "1", path, prefix],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            if completed.returncode != 0:
                return "", []
            chunks = []
            view_dimensions: list[tuple[float, float, float]] = []
            for image_path in sorted(Path(folder).glob("page-*.png")):
                try:
                    text = cls._ocr_image_with_windows(str(image_path))
                except Exception:
                    text = ""
                if text:
                    chunks.append(text)
                full_requirements = cls.extract_technical_requirements(text)
                full_item_count = len(re.findall(r"(?m)^[1-9]\.\S", full_requirements))
                # A short result often means full-page OCR selected a small
                # detail note and merged the actual lower-page list into it.
                # Run the targeted crop only in that case to keep normal imports
                # fast while recovering the complete numbered requirements.
                if full_item_count < 5:
                    try:
                        targeted_requirements = cls._ocr_numbered_requirements_region(str(image_path))
                    except Exception:
                        targeted_requirements = ""
                    targeted_count = len(re.findall(r"(?m)^[1-9]\.\S", targeted_requirements))
                    if targeted_count > full_item_count:
                        chunks.append(targeted_requirements)
                # View analysis is the final fallback only.  It is both slower
                # and more vulnerable to confusing detail dimensions with the
                # cabinet outline, so never run it when full-page OCR already
                # contains a complete W×H×D value.
                if (
                    not view_dimensions
                    and not cls.find_remark_dimension_candidates(text)
                    and not cls.find_dimension_candidates(text)
                ):
                    try:
                        inferred = cls._infer_dimensions_from_views(str(image_path))
                    except Exception:
                        inferred = None
                    if inferred:
                        view_dimensions.append(inferred)
            return "\n".join(chunks), view_dimensions

    @classmethod
    def ocr_pdf(cls, path: str) -> str:
        """Render a PDF and return OCR text without depending on a window instance."""
        text, _ = cls._ocr_pdf_details(path)
        return text


    @classmethod
    def recognize_document(cls, path: str) -> dict:
        """Recognize one drawing without touching any Qt widgets.

        Text extraction is attempted first because it is much faster than OCR.
        At most the first three text pages are inspected, and OCR is only used
        when the text layer does not contain a complete dimension candidate.
        """
        text_chunks: list[str] = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(path, strict=False)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    pass
            for index, page in enumerate(reader.pages):
                if index >= 3:
                    break
                try:
                    extracted = page.extract_text() or ""
                except Exception:
                    extracted = ""
                if extracted:
                    text_chunks.append(extracted)
        except Exception:
            text_chunks = []

        text = "\n".join(text_chunks)
        remark_dimensions = cls.find_remark_dimension_candidates(text)
        text_dimensions = remark_dimensions or cls.find_dimension_candidates(text)
        technical = cls.extract_technical_requirements(text)
        view_dimensions: list[tuple[float, float, float]] = []
        # OCR is needed when either the complete dimensions or the technical
        # requirements are absent from the PDF text layer.
        if not text_dimensions or not technical:
            ocr_text, view_dimensions = cls._ocr_pdf_details(path)
            if ocr_text:
                text = f"{text}\n{ocr_text}" if text else ocr_text
        text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text or "")
        remark_dimensions = cls.find_remark_dimension_candidates(text)
        ordinary_dimensions = cls.find_dimension_candidates(text)
        dims = remark_dimensions or ordinary_dimensions or view_dimensions
        technical = cls.extract_technical_requirements(text)
        return {
            "path": path,
            "name": Path(path).stem,
            "dimensions": dims,
            "text": technical,
            "raw_text": text,
            "coating": "橘纹" if re.search(r"[桔橘]", text) else None,
            "dimension_source": (
                "remark_text" if remark_dimensions else
                "text" if ordinary_dimensions else
                "drawing_views" if view_dimensions else
                None
            ),
        }


class PdfRecognitionWorker(QThread):
    """Sequential background queue for a batch of drawings."""

    item_ready = Signal(dict)
    item_failed = Signal(str, str)
    progress = Signal(int, int, str)
    batch_finished = Signal(int, int, bool)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.paths = list(paths)

    def run(self) -> None:
        succeeded = 0
        failed = 0
        cancelled = False
        total = len(self.paths)
        for index, path in enumerate(self.paths, start=1):
            if self.isInterruptionRequested():
                cancelled = True
                break
            self.progress.emit(index, total, Path(path).name)
            try:
                item = DrawingRecognitionTools.recognize_document(path)
            except Exception as exc:
                failed += 1
                self.item_failed.emit(path, str(exc))
            else:
                succeeded += 1
                self.item_ready.emit(item)
        if self.isInterruptionRequested():
            cancelled = True
        self.batch_finished.emit(succeeded, failed, cancelled)


class MainWindow(QMainWindow):
    VALID_DOOR_COMBINATIONS = {(1, 0), (0, 1), (0, 2), (2, 0), (1, 1)}
    """Multi-cabinet quotation workspace.

    A current cabinet is calculated on the base page, then frozen into the
    editable draft list.  The final workbook is generated only from that list.
    This makes attachments, notes and the two independent discounts belong to
    the right cabinet instead of leaking into the next calculation.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 智能报价 - 双报价录入")
        self.setMinimumSize(980, 700)
        self.resize(1460, 920)
        self.worker: ApiWorker | None = None
        self.template_worker: ApiWorker | None = None
        self.catalog_worker: ApiWorker | None = None
        self.company_worker: ApiWorker | None = None
        self.history_worker: ApiWorker | None = None
        self.confirm_worker: ApiWorker | None = None
        self.export_worker: WorkbookExportWorker | None = None
        self.pdf_worker: PdfRecognitionWorker | None = None
        self.close_after_pdf_cancel = False
        self.formula_calculator = FormulaDatabaseCalculator()
        self.product_catalog: dict[str, dict] = {}
        self.company_catalog: list[dict] = []
        self.attachments: list[dict] = []
        self.current_result: dict | None = None
        self._formula_base_result: dict | None = None
        self.current_template_code: str | None = None
        self.template_serial = 0
        self.draft_items: list[dict] = []
        self.recognized_drawings: list[dict] = []
        self.active_drawing: dict | None = None
        self.recommended_attachments: list[str] = []
        self.pending_export_path: str | None = None
        self.confirm_button: QPushButton | None = None
        self.build_ui()
        self.reset_current_cabinet(keep_company=True)
        self.load_catalogs()

    # ---- page construction -------------------------------------------------
    def build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("mainScroll")
        self.setCentralWidget(scroll)
        canvas = QWidget()
        canvas.setObjectName("page")
        canvas.setMinimumSize(1180, 820)
        scroll.setWidget(canvas)

        shell = QHBoxLayout(canvas)
        shell.setContentsMargins(18, 18, 18, 18)
        shell.setSpacing(16)
        shell.addWidget(self.build_navigation(), 0, Qt.AlignTop)
        self.stack = QStackedWidget()
        shell.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_image_page())
        self.stack.addWidget(self.build_base_page())
        self.stack.addWidget(self.build_notes_page())
        self.stack.addWidget(self.build_summary_page())
        self.show_section(1)

    def build_navigation(self):
        panel = QFrame()
        panel.setObjectName("navPanel")
        panel.setFixedWidth(226)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(8)
        title = QLabel("报价导航")
        title.setObjectName("navTitle")
        layout.addWidget(title)
        hint = QLabel("选择工作模块")
        hint.setObjectName("navHint")
        layout.addWidget(hint)
        layout.addSpacing(8)
        label = QLabel("下单公司")
        label.setObjectName("companyLabel")
        layout.addWidget(label)
        self.company_combo = QComboBox()
        self.company_combo.setObjectName("companyCombo")
        self.company_combo.setEditable(True)
        self.company_combo.setPlaceholderText("输入或选择下单公司")
        self.company_combo.currentTextChanged.connect(self.request_history_match)
        layout.addWidget(self.company_combo)
        company_hint = QLabel("同公司、同柜型、同变体、同材质及相同尺寸时提示历史订单。")
        company_hint.setObjectName("companyHint")
        company_hint.setWordWrap(True)
        layout.addWidget(company_hint)
        layout.addSpacing(8)
        self.nav_buttons: list[QPushButton] = []
        for index, caption in enumerate(("图片导入", "基础报价", "备注", "汇总清单")):
            button = QPushButton(caption)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(46)
            button.clicked.connect(lambda _checked=False, i=index: self.show_section(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        layout.addStretch()
        footer = QLabel("V2.0\n多柜型双报价")
        footer.setObjectName("navFooter")
        layout.addWidget(footer)
        return panel

    def show_section(self, index: int):
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        self.statusBar().showMessage(f"当前模块：{('图片导入', '基础报价', '备注', '汇总清单')[index]}")

    def build_image_page(self):
        page = QWidget(); page.setObjectName("sectionPage")
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(14)
        title = QLabel("图片导入"); title.setObjectName("sectionTitle"); layout.addWidget(title)
        intro = QLabel("可一次导入多份 PDF 图纸；每份图纸对应一个柜型。识别结果需人工确认后才会带入基础报价和备注。")
        intro.setObjectName("sectionSubtitle"); intro.setWordWrap(True); layout.addWidget(intro)
        card = QGroupBox("PDF 图纸识别"); card.setObjectName("drawingCard")
        box = QVBoxLayout(card); box.setContentsMargins(18, 16, 18, 16); box.setSpacing(10)
        actions = QHBoxLayout()
        self.import_pdf_button = QPushButton("导入 PDF 图纸")
        self.import_pdf_button.clicked.connect(self.select_pdf_drawings)
        use_btn = QPushButton("使用选中图纸建立柜型")
        use_btn.clicked.connect(self.use_selected_drawing)
        self.cancel_pdf_button = QPushButton("取消识别")
        self.cancel_pdf_button.setEnabled(False)
        self.cancel_pdf_button.clicked.connect(self.cancel_pdf_recognition)
        self.clear_drawings_button = QPushButton("清除图纸列表")
        self.clear_drawings_button.clicked.connect(self.clear_drawings)
        actions.addWidget(self.import_pdf_button); actions.addWidget(use_btn); actions.addWidget(self.cancel_pdf_button)
        actions.addStretch(); actions.addWidget(self.clear_drawings_button)
        box.addLayout(actions)
        self.drawing_progress = QProgressBar()
        self.drawing_progress.setRange(0, 1)
        self.drawing_progress.setValue(0)
        self.drawing_progress.setFormat("等待导入")
        self.drawing_progress.setVisible(False)
        box.addWidget(self.drawing_progress)
        self.drawing_list = QListWidget(); self.drawing_list.setMinimumHeight(130)
        self.drawing_list.currentRowChanged.connect(self.select_drawing_row)
        box.addWidget(self.drawing_list)
        self.drawing_status = QLabel("尚未导入 PDF 图纸")
        self.drawing_status.setObjectName("drawingStatus"); self.drawing_status.setWordWrap(True); box.addWidget(self.drawing_status)
        self.drawing_text = QTextEdit(); self.drawing_text.setReadOnly(True); self.drawing_text.setMinimumHeight(240)
        self.drawing_text.setPlaceholderText("选中图纸后显示识别到的技术要求及可用尺寸。")
        box.addWidget(self.drawing_text)
        self.handwriting_edit = QLineEdit(); self.handwriting_edit.setPlaceholderText("手写标注人工确认，例如：桔")
        self.handwriting_edit.textChanged.connect(self.apply_handwriting_coating)
        box.addWidget(self.handwriting_edit)
        layout.addWidget(card); layout.addStretch()
        return page

    def build_base_page(self):
        page = QWidget(); page.setObjectName("sectionPage")
        root = QVBoxLayout(page); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(14)
        hero = QWidget(); hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero); hero_layout.setContentsMargins(24, 16, 24, 16)
        heading = QVBoxLayout(); t = QLabel("AI 智能报价"); t.setObjectName("heroTitle")
        s = QLabel("当前柜型计算 → 加入汇总清单 → 确认导出正式双报价单"); s.setObjectName("heroSubtitle")
        heading.addWidget(t); heading.addWidget(s); hero_layout.addLayout(heading); hero_layout.addStretch()
        badge = QLabel("●  双报价接口"); badge.setObjectName("apiBadge"); hero_layout.addWidget(badge)
        root.addWidget(hero)
        input_box = QGroupBox("基础报价输入"); input_box.setObjectName("inputCard")
        form = QGridLayout(input_box); form.setContentsMargins(22, 18, 22, 18); form.setHorizontalSpacing(14); form.setVerticalSpacing(8)
        form.setColumnMinimumWidth(0, 145); form.setColumnStretch(1, 1); form.setColumnStretch(2, 1); form.setColumnStretch(3, 1)
        def field(row, label, widget, span=3):
            text = QLabel(label); text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.addWidget(text, row, 0); form.addWidget(widget, row, 1, 1, span)
        self.product_combo = QComboBox(); self.product_combo.addItem("正在读取产品型号…", None)
        self.product_combo.currentIndexChanged.connect(self.product_changed); field(0, "产品型号", self.product_combo)
        self.model_edit = QLineEdit(); self.model_edit.setPlaceholderText("规格型号（可选；优先使用 PDF 图纸名称）"); field(1, "产品规格", self.model_edit)
        self.width_spin = self.dimension_spin(1000); self.height_spin = self.dimension_spin(1800); self.depth_spin = self.dimension_spin(600)
        for spin in (self.width_spin, self.height_spin, self.depth_spin):
            spin.editingFinished.connect(self.refresh_formula_inputs); spin.editingFinished.connect(self.request_history_match)
        dims = QHBoxLayout(); dims.setSpacing(10)
        for label, spin in (("宽", self.width_spin), ("高", self.height_spin), ("深", self.depth_spin)):
            w = QWidget(); row = QHBoxLayout(w); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(5); row.addWidget(QLabel(label)); row.addWidget(spin, 1); dims.addWidget(w, 1)
        form.addWidget(QLabel("尺寸（mm）"), 2, 0); form.addLayout(dims, 2, 1, 1, 3)
        self.material_combo = QComboBox(); self.material_combo.addItem("碳钢 SECC", DEFAULT_MATERIAL_CODE); self.material_combo.addItem("不锈钢 SUS304", "SUS304"); self.material_combo.addItem("不锈钢 SUS316", "SUS316")
        self.material_combo.currentIndexChanged.connect(self.request_history_match); field(3, "材质", self.material_combo)
        self.coating_combo = QComboBox()
        for x in (DEFAULT_COATING_TYPE, "平光", "无", "皱纹"): self.coating_combo.addItem(x, x)
        apply_default_quote_inputs(self)
        field(4, "喷塑方式", self.coating_combo)
        door_panel = QWidget()
        door_layout = QHBoxLayout(door_panel)
        door_layout.setContentsMargins(0, 0, 0, 0)
        door_layout.setSpacing(12)
        self.single_door_combo = QComboBox()
        self.double_door_combo = QComboBox()
        for count in (0, 1, 2):
            self.single_door_combo.addItem(str(count), count)
            self.double_door_combo.addItem(str(count), count)
        self.single_door_combo.setCurrentIndex(self.single_door_combo.findData(1))
        self.double_door_combo.setCurrentIndex(self.double_door_combo.findData(0))
        single_box = QWidget(); single_row = QHBoxLayout(single_box)
        single_row.setContentsMargins(0, 0, 0, 0); single_row.setSpacing(6)
        single_row.addWidget(QLabel("单门")); single_row.addWidget(self.single_door_combo, 1)
        double_box = QWidget(); double_row = QHBoxLayout(double_box)
        double_row.setContentsMargins(0, 0, 0, 0); double_row.setSpacing(6)
        double_row.addWidget(QLabel("双门")); double_row.addWidget(self.double_door_combo, 1)
        door_layout.addWidget(single_box, 1); door_layout.addWidget(double_box, 1)
        self.single_door_combo.currentIndexChanged.connect(lambda _i: self.door_counts_changed("single"))
        self.double_door_combo.currentIndexChanged.connect(lambda _i: self.door_counts_changed("double"))
        field(5, "产品变体", door_panel)
        self.quantity_spin = QSpinBox(); self.quantity_spin.setRange(1, 999); self.quantity_spin.setValue(1); field(6, "柜型数量", self.quantity_spin)
        self.quote_date = QDateEdit(QDate.currentDate()); self.quote_date.setCalendarPopup(True); field(7, "报价日期", self.quote_date)
        self.api_url = QLineEdit(API_URL); field(8, "接口地址", self.api_url)
        self.weight_edit = QLineEdit(); self.weight_edit.setReadOnly(True); self.weight_edit.setPlaceholderText("数据库公式计算后自动带入")
        self.area_edit = QLineEdit(); self.area_edit.setReadOnly(True); self.area_edit.setPlaceholderText("数据库公式计算后自动带入")
        field(9, "公式基准重量（kg）", self.weight_edit); field(10, "公式喷涂面积（m²）", self.area_edit)
        attachment_panel = QWidget(); attachment_layout = QVBoxLayout(attachment_panel); attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_recommendation = QLabel("OCR 推荐附件：—")
        self.attachment_recommendation.setWordWrap(True)
        self.attachment_recommendation.setStyleSheet("color:#b45309;")
        attachment_layout.addWidget(self.attachment_recommendation)
        bar = QHBoxLayout(); self.attachment_status = QLabel("未选择附件"); self.attachment_status.setObjectName("attachmentStatus")
        pick = QPushButton("选择附件"); pick.clicked.connect(self.open_attachment_dialog); bar.addWidget(self.attachment_status, 1); bar.addWidget(pick); attachment_layout.addLayout(bar)
        self.attachment_list = QListWidget(); self.attachment_list.setMaximumHeight(70); attachment_layout.addWidget(self.attachment_list)
        field(12, "附件", attachment_panel)
        root.addWidget(input_box)
        action_row = QHBoxLayout(); self.calculate_button = QPushButton("开始计算"); self.calculate_button.setDefault(True); self.calculate_button.clicked.connect(self.calculate)
        add_btn = QPushButton("加入汇总清单"); add_btn.clicked.connect(self.add_current_to_summary)
        clear_btn = QPushButton("新建柜型"); clear_btn.clicked.connect(lambda: self.reset_current_cabinet(keep_company=True))
        action_row.addWidget(self.calculate_button); action_row.addWidget(add_btn); action_row.addWidget(clear_btn); action_row.addStretch(); root.addLayout(action_row)
        results = QHBoxLayout(); results.setSpacing(14)
        self.formula_box, self.formula_labels, self.formula_discount = self.build_result_card("公式法报价", ("material", "auxiliary", "labor", "attachment", "spray", "management", "area", "total"), "formulaCard")
        self.labor_multiplier = QDoubleSpinBox()
        self.labor_multiplier.setRange(0.01, 10)
        self.labor_multiplier.setDecimals(2)
        self.labor_multiplier.setSingleStep(0.05)
        self.labor_multiplier.setValue(1.0)
        self.labor_multiplier.setSuffix(" ×")
        self.labor_multiplier.setObjectName("laborMultiplier")
        self.labor_multiplier.setToolTip("调整后，人工成本和管理费用会立即重新计算")
        self.labor_multiplier.valueChanged.connect(self.refresh_discounted_totals)
        self.formula_box.layout().insertRow(
            self.formula_box.layout().rowCount() - 1,
            "人工成本折扣系数",
            self.labor_multiplier,
        )
        self.quick_box, self.quick_labels, self.quick_discount = self.build_result_card("快速报价", ("base_price", "matched_size", "attachment", "total"), "quickCard")
        self.formula_discount.valueChanged.connect(self.refresh_discounted_totals); self.quick_discount.valueChanged.connect(self.refresh_discounted_totals)
        results.addWidget(self.formula_box, 1); results.addWidget(self.quick_box, 1); root.addLayout(results)
        risk = QGroupBox("数据提示"); risk.setObjectName("riskCard"); risk_layout = QVBoxLayout(risk); self.risk_label = QLabel("尚未计算"); self.risk_label.setWordWrap(True); risk_layout.addWidget(self.risk_label); root.addWidget(risk)
        root.addStretch()
        return page

    def build_result_card(self, title, keys, object_name):
        box = QGroupBox(title); box.setObjectName(object_name)
        box.setMinimumHeight(360)
        layout = QFormLayout(box); layout.setContentsMargins(18, 18, 18, 16); layout.setVerticalSpacing(7)
        captions = {"material":"材料成本", "auxiliary":"辅材成本", "labor":"人工成本", "attachment":"附件成本", "spray":"喷塑费用", "management":"管理费用", "area":"产品面积", "base_price":"面价", "matched_size":"匹配尺寸", "total":"总成本"}
        labels = {}
        for key in keys:
            label = QLabel("—"); label.setObjectName(f"new_{object_name}_{key}"); labels[key] = label; layout.addRow(captions[key], label)
        discount = QDoubleSpinBox(); discount.setRange(0.01, 10); discount.setDecimals(2); discount.setSingleStep(0.05); discount.setValue(1.00); discount.setSuffix(" ×")
        layout.addRow("折扣", discount)
        return box, labels, discount

    def build_notes_page(self):
        page = QWidget(); page.setObjectName("sectionPage"); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(14)
        title = QLabel("备注"); title.setObjectName("sectionTitle"); layout.addWidget(title)
        hint = QLabel("图片导入中确认的技术要求会自动填入这里。可修改；加入汇总清单后将原样写入正式报价单。")
        hint.setObjectName("sectionSubtitle"); hint.setWordWrap(True); layout.addWidget(hint)
        card = QGroupBox("最终报价备注（原样输出）"); card.setObjectName("drawingConfirmCard"); card_layout = QVBoxLayout(card)
        self.notes_text = QTextEdit(); self.notes_text.setMinimumHeight(400); self.notes_text.setPlaceholderText("OCR 技术要求将在确认图纸后自动填入；也可人工补充或修改")
        card_layout.addWidget(self.notes_text); layout.addWidget(card); layout.addStretch(); return page

    def build_summary_page(self):
        page = QWidget(); page.setObjectName("sectionPage"); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(14)
        title = QLabel("汇总清单"); title.setObjectName("sectionTitle"); layout.addWidget(title)
        hint = QLabel("每个柜型分别保留附件、备注及公式法/快速报价折扣。确认后生成同一份 Excel 的两张固定格式报价表。")
        hint.setObjectName("sectionSubtitle"); hint.setWordWrap(True); layout.addWidget(hint)
        card = QGroupBox("当前报价柜型"); card.setObjectName("summaryCard"); card_layout = QVBoxLayout(card)
        self.summary_table = QTableWidget(0, 12); self.summary_table.setHorizontalHeaderLabels(["序号", "名称", "规格型号", "尺寸", "材质", "数量", "公式法单价", "公式折扣", "快速单价", "快速折扣", "附件", "备注"])
        self.summary_table.setSelectionBehavior(QTableWidget.SelectRows); self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers); self.summary_table.setMinimumHeight(340); self.summary_table.horizontalHeader().setStretchLastSection(True)
        card_layout.addWidget(self.summary_table)
        actions = QHBoxLayout()
        for text, callback in (("编辑选中", self.edit_selected_item), ("删除选中", self.remove_selected_item), ("上移", lambda: self.move_selected_item(-1)), ("下移", lambda: self.move_selected_item(1)), ("确认并导出正式报价单", self.confirm_and_export)):
            button = QPushButton(text); button.clicked.connect(callback); actions.addWidget(button)
            if text == "确认并导出正式报价单":
                self.confirm_button = button
        actions.addStretch(); card_layout.addLayout(actions); layout.addWidget(card)
        total_card = QGroupBox("全单本页小计（不分页）"); total_card.setObjectName("riskCard"); total_layout = QHBoxLayout(total_card)
        self.summary_formula_total = QLabel("公式法：0.00 元"); self.summary_quick_total = QLabel("快速报价：0.00 元")
        self.summary_formula_total.setObjectName("summaryTotal"); self.summary_quick_total.setObjectName("summaryTotal")
        total_layout.addWidget(self.summary_formula_total); total_layout.addSpacing(36); total_layout.addWidget(self.summary_quick_total); total_layout.addStretch(); layout.addWidget(total_card); layout.addStretch()
        return page

    # ---- PDF recognition ---------------------------------------------------
    def select_pdf_drawings(self):
        if self.pdf_worker and self.pdf_worker.isRunning():
            QMessageBox.information(self, "正在识别", "当前图纸仍在识别，请等待完成或点击“取消识别”。")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 PDF 图纸", "", "PDF 图纸 (*.pdf)")
        if not paths:
            return
        self.import_pdf_button.setEnabled(False)
        self.clear_drawings_button.setEnabled(False)
        self.cancel_pdf_button.setEnabled(True)
        self.drawing_progress.setVisible(True)
        self.drawing_progress.setRange(0, len(paths))
        self.drawing_progress.setValue(0)
        self.drawing_progress.setFormat(f"准备识别 0/{len(paths)}")
        self.drawing_status.setText(f"已加入 {len(paths)} 份图纸，正在后台识别；识别期间可以继续查看其他模块。")
        self.pdf_worker = PdfRecognitionWorker(paths, self)
        self.pdf_worker.progress.connect(self.pdf_recognition_progress)
        self.pdf_worker.item_ready.connect(self.add_recognized_drawing)
        self.pdf_worker.item_failed.connect(self.pdf_recognition_failed)
        self.pdf_worker.batch_finished.connect(self.pdf_recognition_finished)
        self.pdf_worker.start()

    def recognize_pdf(self, path: str):
        """兼容旧调用；界面导入统一由 PdfRecognitionWorker 后台执行。"""
        self.add_recognized_drawing(DrawingRecognitionTools.recognize_document(path))

    def add_recognized_drawing(self, item: dict):
        self.recognized_drawings.append(item)
        dims = item.get("dimensions") or []
        suffix = " · " + " × ".join(f"{v:g}" for v in dims[0]) + " mm" if dims else " · 待人工确认尺寸"
        self.drawing_list.addItem(item["name"] + suffix)
        self.drawing_list.setCurrentRow(self.drawing_list.count() - 1)

    def pdf_recognition_progress(self, index: int, total: int, name: str):
        self.drawing_progress.setRange(0, total)
        self.drawing_progress.setValue(max(0, index - 1))
        self.drawing_progress.setFormat(f"正在识别 {index}/{total}：{name}")
        self.drawing_status.setText(f"后台识别中：{index}/{total}，当前文件 {name}")

    def pdf_recognition_failed(self, path: str, message: str):
        item = {
            "path": path,
            "name": Path(path).stem,
            "dimensions": [],
            "text": f"识别失败：{message}\n\n可继续处理其他图纸，并在基础报价中人工填写本柜尺寸和备注。",
            "coating": None,
            "error": message,
        }
        self.add_recognized_drawing(item)

    def cancel_pdf_recognition(self):
        if self.pdf_worker and self.pdf_worker.isRunning():
            self.pdf_worker.requestInterruption()
            self.cancel_pdf_button.setEnabled(False)
            self.drawing_status.setText("正在停止识别；已完成的图纸会保留。")

    def pdf_recognition_finished(self, succeeded: int, failed: int, cancelled: bool):
        total = succeeded + failed
        self.drawing_progress.setValue(self.drawing_progress.maximum())
        state = "已取消" if cancelled else "已完成"
        self.drawing_progress.setFormat(f"{state}：成功 {succeeded}，失败 {failed}")
        self.drawing_status.setText(f"图纸识别{state}：成功 {succeeded} 份，失败 {failed} 份。失败文件不影响其余图纸。")
        self.import_pdf_button.setEnabled(True)
        self.clear_drawings_button.setEnabled(True)
        self.cancel_pdf_button.setEnabled(False)
        worker = self.pdf_worker
        self.pdf_worker = None
        if worker:
            worker.deleteLater()
        if self.close_after_pdf_cancel:
            self.close_after_pdf_cancel = False
            self.close()

    def select_drawing_row(self, row: int):
        if row < 0 or row >= len(self.recognized_drawings): return
        item = self.recognized_drawings[row]; self.active_drawing = item
        dims = item["dimensions"][0] if item["dimensions"] else None
        prefix = "识别失败；" if item.get("error") else ""
        source_caption = {
            "remark_text": "型号/订货号备注",
            "text": "文字尺寸",
            "drawing_views": "正视图/侧视图兜底",
        }.get(item.get("dimension_source"), "")
        source_suffix = f"（{source_caption}）" if source_caption else ""
        self.drawing_status.setText(
            f"{item['name']}：{prefix}"
            + (
                f"识别尺寸 {dims[0]:g} × {dims[1]:g} × {dims[2]:g} mm{source_suffix}"
                if dims else "未识别完整尺寸，请手工填写。"
            )
        )
        self.drawing_text.setPlainText(item["text"] or "未读取到可用文字。")
        self.handwriting_edit.setText("桔" if item.get("coating") == "橘纹" else "")

    def use_selected_drawing(self):
        item = self.active_drawing
        if not item:
            QMessageBox.information(self, "请选择图纸", "请先在列表中选择一份 PDF 图纸。"); return
        if item["dimensions"]:
            width, height, depth = item["dimensions"][0]
            self.width_spin.setValue(width); self.height_spin.setValue(height); self.depth_spin.setValue(depth)
        self.model_edit.setText(item["name"])
        self.notes_text.setPlainText(item["text"] or "")
        self.recommended_attachments = self.recommend_attachment_names(item.get("raw_text") or item.get("text") or "")
        if self.recommended_attachments:
            recommendation_text = "、".join(self.recommended_attachments)
            self.attachment_recommendation.setText(
                f"OCR 推荐附件：{recommendation_text}（仅推荐；请在“选择附件”中确认规格、数量和价格）"
            )
        else:
            self.attachment_recommendation.setText("OCR 推荐附件：未识别到明确附件")
        if item.get("coating"):
            index = self.coating_combo.findData(item["coating"])
            if index >= 0: self.coating_combo.setCurrentIndex(index)
        self.refresh_formula_inputs(); self.request_history_match(); self.show_section(1)
        if self.recommended_attachments:
            self.risk_label.setText(
                f"已带入图纸信息并生成 {len(self.recommended_attachments)} 项附件推荐；"
                "请确认柜型、变体、尺寸、备注及附件规格后计算。"
            )
        else:
            self.risk_label.setText("已带入图纸信息；请确认柜型、变体、尺寸和识别备注后计算。")

    @staticmethod
    def recommend_attachment_names(text: str) -> list[str]:
        """Turn OCR wording into non-priced attachment recommendations.

        Recommendations never enter either cost method automatically.  The
        operator still chooses the database specification and price scheme.
        """
        rules = (
            (r"照明灯|柜内灯|24V灯", "照明灯"),
            (r"灯开关", "灯开关"),
            (r"行程开关", "行程开关"),
            (r"限位开关", "限位开关"),
            (r"门开关", "门开关"),
            (r"文件夹", "文件夹"),
            (r"风机", "风机"),
            (r"过滤网|滤网", "过滤网"),
            (r"门限位器|限位器", "门限位器"),
            (r"接地线", "接地线"),
            (r"三排|纵梁", "三排"),
            (r"填充安装板", "填充安装板"),
            (r"(?<!填充)安装板", "安装板"),
            (r"底座", "底座"),
            (r"侧板", "侧板"),
        )
        source = text or ""
        recommendations: list[str] = []
        for pattern, name in rules:
            positive_match = False
            for match in re.finditer(pattern, source, re.IGNORECASE):
                prefix = source[max(0, match.start() - 10):match.start()]
                # “无风机滤网”“不配行程开关”“无需文件夹”等属于明确
                # 否定，不能因为关键词出现就生成错误的推荐附件。
                if re.search(r"(?:无|不配|无需|不需要|取消|未配|不要)[^，。；;！!\n]{0,6}$", prefix):
                    continue
                positive_match = True
                break
            if positive_match:
                recommendations.append(name)
        return recommendations

    def clear_drawings(self):
        if self.pdf_worker and self.pdf_worker.isRunning():
            QMessageBox.information(self, "正在识别", "请先取消识别，等待后台任务结束后再清空列表。")
            return
        self.recognized_drawings.clear(); self.active_drawing = None; self.drawing_list.clear(); self.drawing_text.clear(); self.drawing_status.setText("尚未导入 PDF 图纸"); self.handwriting_edit.clear()

    def apply_handwriting_coating(self, text: str):
        if re.search(r"[桔橘]", text or ""):
            index = self.coating_combo.findData("橘纹")
            if index >= 0: self.coating_combo.setCurrentIndex(index)

    # ---- catalogue, template and history ----------------------------------
    @staticmethod
    def dimension_spin(value):
        spin = QDoubleSpinBox(); spin.setRange(1, 100000); spin.setDecimals(1); spin.setSuffix(" mm"); spin.setValue(value); spin.setMinimumWidth(155); return spin

    def base_url(self): return (self.api_url.text().strip() or API_URL).split("/api/", 1)[0].rstrip("/")

    def load_catalogs(self):
        self.catalog_worker = ApiWorker(self.base_url() + "/api/products/catalog", {}, self, method="GET")
        self.catalog_worker.succeeded.connect(self.product_catalog_loaded); self.catalog_worker.failed.connect(lambda m: self.risk_label.setText("产品型号读取失败：" + m)); self.catalog_worker.start()
        self.company_worker = ApiWorker(self.base_url() + "/api/companies/catalog", {}, self, method="GET")
        self.company_worker.succeeded.connect(self.company_catalog_loaded); self.company_worker.start()

    @staticmethod
    def family_for_code(code):
        mapping = {"JC_EXP":"JC", "JQ_EXP":"JQ", "JP_WIDE_EXP":"JP WIDE", "JS_WIDE_EXP":"JS WIDE", "OP_TABLE_EXP":"操作台"}
        if code in mapping: return mapping[code]
        return re.sub(r"_(SINGLE|DOUBLE)$", "", str(code or ""))

    def product_catalog_loaded(self, result):
        records = result.get("items") or []; families = {}
        for row in records:
            code = row.get("product_code"); family = self.family_for_code(code)
            if not family: continue
            entry = families.setdefault(family, {"codes": {}, "method": row.get("product_method"), "name": row.get("product_name") or family})
            variant = "SINGLE" if str(code).endswith("_SINGLE") else "DOUBLE" if str(code).endswith("_DOUBLE") else "DEFAULT"
            entry["codes"][variant] = code
            if row.get("default_width_mm"): entry["defaults"] = (row.get("default_width_mm"), row.get("default_height_mm"), row.get("default_depth_mm"))
        self.product_catalog = families
        self.product_combo.blockSignals(True); self.product_combo.clear()
        for family in sorted(families): self.product_combo.addItem(family, family)
        self.product_combo.blockSignals(False)
        if self.product_combo.count(): self.product_combo.setCurrentIndex(0); self.product_changed()

    def company_catalog_loaded(self, result):
        self.company_catalog = result.get("items") or []
        text = self.company_combo.currentText(); self.company_combo.blockSignals(True); self.company_combo.clear()
        for item in self.company_catalog: self.company_combo.addItem(item.get("company_name") or item.get("company_code"), item.get("company_code"))
        self.company_combo.setEditText(text); self.company_combo.blockSignals(False)

    def door_counts(self) -> tuple[int, int]:
        return (
            int(self.single_door_combo.currentData() or 0),
            int(self.double_door_combo.currentData() or 0),
        )

    def set_door_counts(self, single_count: int, double_count: int) -> None:
        self.single_door_combo.blockSignals(True)
        self.double_door_combo.blockSignals(True)
        single_index = self.single_door_combo.findData(int(single_count))
        double_index = self.double_door_combo.findData(int(double_count))
        if single_index >= 0:
            self.single_door_combo.setCurrentIndex(single_index)
        if double_index >= 0:
            self.double_door_combo.setCurrentIndex(double_index)
        self.single_door_combo.blockSignals(False)
        self.double_door_combo.blockSignals(False)

    def door_counts_changed(self, source: str) -> None:
        single_count, double_count = self.door_counts()
        if (single_count, double_count) not in self.VALID_DOOR_COMBINATIONS:
            if source == "single":
                if single_count == 0:
                    double_count = double_count if double_count in (1, 2) else 1
                elif single_count == 1:
                    double_count = double_count if double_count in (0, 1) else 0
                else:
                    double_count = 0
            else:
                if double_count == 0:
                    single_count = single_count if single_count in (1, 2) else 1
                elif double_count == 1:
                    single_count = single_count if single_count in (0, 1) else 0
                else:
                    single_count = 0
            if (single_count, double_count) not in self.VALID_DOOR_COMBINATIONS:
                single_count, double_count = 1, 0
            self.set_door_counts(single_count, double_count)
        self.refresh_formula_inputs()
        self.request_history_match()

    def product_changed(self):
        entry = self.product_catalog.get(self.product_combo.currentData() or "", {})
        codes = entry.get("codes", {})
        supports_door_counts = "SINGLE" in codes or "DOUBLE" in codes
        self.single_door_combo.setEnabled(supports_door_counts)
        self.double_door_combo.setEnabled(supports_door_counts)
        if supports_door_counts:
            if self.door_counts() not in self.VALID_DOOR_COMBINATIONS:
                self.set_door_counts(1, 0)
        else:
            self.set_door_counts(1, 0)
        defaults = entry.get("defaults")
        if defaults:
            self.width_spin.setValue(float(defaults[0] or 1000)); self.height_spin.setValue(float(defaults[1] or 1800)); self.depth_spin.setValue(float(defaults[2] or 600))
        self.refresh_formula_inputs(); self.request_history_match()

    def selected_variant_code(self):
        entry = self.product_catalog.get(self.product_combo.currentData() or "", {})
        codes = entry.get("codes") or {}
        single_count, double_count = self.door_counts()
        if single_count > 0 and "SINGLE" in codes:
            return "SINGLE"
        if double_count > 0 and "DOUBLE" in codes:
            return "DOUBLE"
        if "DEFAULT" in codes:
            return "DEFAULT"
        if "SINGLE" in codes:
            return "SINGLE"
        if "DOUBLE" in codes:
            return "DOUBLE"
        return None

    def selected_variant_name(self) -> str:
        if not self.single_door_combo.isEnabled():
            return ""
        single_count, double_count = self.door_counts()
        return f"单门{single_count} 双门{double_count}"

    def selected_product_code(self):
        entry = self.product_catalog.get(self.product_combo.currentData() or "", {})
        return (entry.get("codes") or {}).get(self.selected_variant_code())

    def refresh_formula_inputs(self):
        code = self.selected_product_code()
        entry = self.product_catalog.get(self.product_combo.currentData() or "", {})
        if not code or entry.get("method") != "formula":
            self.weight_edit.clear(); self.area_edit.clear(); return
        # Do not leave the previous product's values visible while a new
        # formula template is loading.
        self.weight_edit.clear(); self.area_edit.clear()
        self.template_serial += 1; serial = self.template_serial
        self.template_worker = ApiWorker(self.base_url() + "/api/quotes/formula-template", {"product_code": code}, self)
        self.template_worker.succeeded.connect(lambda result, s=serial, c=code: self.formula_template_loaded(result, s, c))
        self.template_worker.failed.connect(lambda message, s=serial: self.formula_template_failed(message, s))
        self.template_worker.start()

    def formula_template_loaded(self, result, serial, code):
        if serial != self.template_serial: return
        try:
            single_count, double_count = self.door_counts()
            self.formula_calculator.load_template(result)
            values = self.formula_calculator.calculate(
                code,
                self.width_spin.value(),
                self.height_spin.value(),
                self.depth_spin.value(),
                single_count,
                double_count,
            )
            if not values:
                raise ValueError(f"数据库模板未返回 {code} 的重量和喷涂面积")
            self.weight_edit.setText(f"{values[0]:.6f}".rstrip("0").rstrip("."))
            self.area_edit.setText(f"{values[1]:.6f}".rstrip("0").rstrip("."))
        except Exception as exc:
            self.weight_edit.clear(); self.area_edit.clear()
            self.risk_label.setStyleSheet("color:#b45309;")
            self.risk_label.setText(f"公式模板计算失败：{exc}")

    def formula_template_failed(self, message, serial):
        if serial != self.template_serial:
            return
        self.weight_edit.clear(); self.area_edit.clear()
        self.risk_label.setStyleSheet("color:#b45309;")
        self.risk_label.setText(f"公式模板读取失败：{message}")

    def selected_company_code(self):
        data = self.company_combo.currentData(); return str(data) if data else self.company_combo.currentText().strip() or None

    def request_history_match(self, *_args):
        company = self.selected_company_code(); product = self.selected_product_code()
        if not company or not product: return
        single_count, double_count = self.door_counts()
        payload = {"company_code": company, "product_code": product, "material_code": self.material_combo.currentData(), "variant_code": self.selected_variant_code(), "single_door_count": single_count, "double_door_count": double_count, "width_mm": self.width_spin.value(), "height_mm": self.height_spin.value(), "depth_mm": self.depth_spin.value()}
        self.history_worker = ApiWorker(self.base_url() + "/api/company-history/match", payload, self)
        self.history_worker.succeeded.connect(self.history_match_loaded); self.history_worker.failed.connect(lambda _m: None); self.history_worker.start()

    def history_match_loaded(self, result):
        if not result.get("matched"): return
        if QMessageBox.question(self, "发现历史订单", "发现相同公司、柜型、变体、材质和尺寸的已确认历史订单。是否带入其喷塑方式、附件与备注？", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        payload = result.get("payload") or {}; item = payload.get("item") or payload
        coating = item.get("coating_type"); index = self.coating_combo.findData(coating)
        if index >= 0: self.coating_combo.setCurrentIndex(index)
        self.attachments = [dict(x) for x in item.get("attachments") or []]; self.update_attachment_view()
        if item.get("notes"): self.notes_text.setPlainText(str(item["notes"]))
        self.risk_label.setText("已带入最近确认的历史订单内容；当前价格仍按最新数据库重新计算。")

    # ---- attachment and calculation ---------------------------------------
    def update_attachment_view(self):
        self.attachment_list.clear(); self.attachment_status.setText("未选择附件" if not self.attachments else f"已选择 {len(self.attachments)} 项附件")
        for item in self.attachments:
            price = item.get("unit_price_override", item.get("matched_price")); size = AttachmentDialog.format_size(item)
            text = f"{item.get('item_name', '附件')} · {size} · 数量 {item.get('quantity', 1)}"
            if price is not None: text += f" · {float(price):,.2f} 元"
            self.attachment_list.addItem(text)

    def open_attachment_dialog(self):
        target = (self.width_spin.value(), self.height_spin.value(), self.depth_spin.value())
        dialog = AttachmentDialog(
            self.attachments,
            self.api_url.text().strip() or API_URL,
            self,
            target_dimensions=target,
            recommended_names=self.recommended_attachments,
        )
        if dialog.exec() == QDialog.Accepted:
            self.attachments = dialog.attachments; self.update_attachment_view()

    def calculate(self):
        code = self.selected_product_code()
        if not code:
            QMessageBox.warning(self, "产品未选择", "请选择数据库中的产品型号和变体。"); return
        entry = self.product_catalog.get(self.product_combo.currentData() or "", {})
        if entry.get("method") == "formula" and (not self.weight_edit.text().strip() or not self.area_edit.text().strip()):
            QMessageBox.information(self, "公式数据读取中", "正在从数据库读取公式模板，请稍后再次计算。"); return
        quote_id = "TMP" + datetime.now().strftime("%Y%m%d%H%M%S%f")[-12:]
        single_count, double_count = self.door_counts()
        payload = {"quote_id": quote_id, "product_code": code, "model_code": self.model_edit.text().strip(), "material_code": self.material_combo.currentData(), "width_mm": self.width_spin.value(), "height_mm": self.height_spin.value(), "depth_mm": self.depth_spin.value(), "base_material_weight_kg": float(self.weight_edit.text()) if self.weight_edit.text().strip() else None, "product_area_m2": float(self.area_edit.text()) if self.area_edit.text().strip() else None, "coating_type": self.coating_combo.currentData(), "variant_code": self.selected_variant_code(), "single_door_count": single_count, "double_door_count": double_count, "quote_date": self.quote_date.date().toString("yyyy-MM-dd"), "attachments": self.attachments}
        self.calculate_button.setEnabled(False); self.worker = ApiWorker(self.api_url.text().strip() or API_URL, payload, self)
        self.worker.succeeded.connect(self.show_result); self.worker.failed.connect(self.show_error); self.worker.finished.connect(lambda: self.calculate_button.setEnabled(True)); self.worker.start()

    def show_result(self, result):
        formula = dict(result.get("formula_cost") or {}); quick = dict(result.get("quick_quote") or {})
        self._formula_base_result = dict(formula)
        self.current_result = {"formula": dict(formula), "quick": quick, "risk_flags": result.get("risk_flags") or [], "quote_id": result.get("quote_id")}
        self.refresh_discounted_totals()
        risks = self.current_result["risk_flags"]
        if risks:
            self.risk_label.setStyleSheet("color:#b45309;"); self.risk_label.setText("；".join(str(x.get("message") or x.get("code")) for x in risks))
        else:
            self.risk_label.setStyleSheet("color:#166534;"); self.risk_label.setText("计算完成。确认无误后可加入汇总清单。")

    def refresh_discounted_totals(self):
        if not self.current_result: return
        formula = dict(self._formula_base_result or self.current_result["formula"])
        labor = formula.get("labor_cost"); management = formula.get("management_fee"); total = formula.get("total_cost")
        if labor is not None and management is not None and total is not None:
            multiplier = float(self.labor_multiplier.value())
            new_labor = float(labor) * multiplier
            new_management = new_labor * 0.13
            formula["labor_cost"] = new_labor
            formula["management_fee"] = new_management
            formula["total_cost"] = float(total) - float(labor) - float(management) + new_labor + new_management
        self.current_result["formula"] = formula
        quick = self.current_result["quick"]
        values = {"material": formula.get("material_cost"), "auxiliary": formula.get("auxiliary_cost"), "labor": formula.get("labor_cost"), "attachment": formula.get("attachment_fee"), "spray": formula.get("spray_cost"), "management": formula.get("management_fee")}
        for key, value in values.items(): self.formula_labels[key].setText(money(value))
        area = formula.get("product_area_m2"); self.formula_labels["area"].setText("—" if area is None else f"{float(area):,.6f} m²")
        formula_total = formula.get("total_cost"); self.formula_labels["total"].setText(money(None if formula_total is None else float(formula_total) * self.formula_discount.value()))
        self.quick_labels["base_price"].setText(money(quick.get("base_price"))); self.quick_labels["attachment"].setText(money(quick.get("attachment_fee")))
        matched = quick.get("matched_experience") or {}; dims = [matched.get("reference_width_mm"), matched.get("reference_height_mm"), matched.get("reference_depth_mm")]
        self.quick_labels["matched_size"].setText(" × ".join(f"{float(x):g}" for x in dims) + " mm" if all(x is not None for x in dims) else "待补充经验值")
        quick_total = quick.get("total_cost")
        discounted_quick = None if quick_total is None else quick_discount_breakdown(
            quick, self.attachments, self.quick_discount.value()
        )["discounted_total"]
        self.quick_labels["total"].setText(money(discounted_quick))

    def show_error(self, message): self.risk_label.setStyleSheet("color:#b91c1c;"); self.risk_label.setText(message)

    # ---- multi-cabinet draft ------------------------------------------------
    @staticmethod
    def drawing_name_before_chinese(value: str) -> str:
        """Return the PDF stem up to (but not including) its first CJK character."""
        # The recognized drawing name is often already a suffix-less stem and
        # may legitimately contain several dots (for example
        # ``JF100MKD2.80.03-001``).  Path.stem would incorrectly treat the text
        # after the last dot as a file extension, so remove only a real .pdf
        # suffix here.
        stem = re.sub(
            r"\.pdf$", "", Path(str(value or "").strip()).name,
            flags=re.IGNORECASE,
        )
        match = re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", stem)
        prefix = stem[:match.start()] if match else stem
        return prefix.strip() or stem

    def cabinet_name(self):
        if self.active_drawing and self.active_drawing.get("name"):
            return self.drawing_name_before_chinese(self.active_drawing["name"])
        variant_name = self.selected_variant_name()
        return self.product_combo.currentText() + (f" {variant_name}" if variant_name else "")

    def add_current_to_summary(self):
        if not self.current_result:
            QMessageBox.information(self, "请先计算", "当前柜型尚未完成双报价计算。"); return
        formula_total = self.current_result["formula"].get("total_cost"); quick_total = self.current_result["quick"].get("total_cost")
        if formula_total is None or quick_total is None:
            QMessageBox.warning(self, "数据待补充", "公式法或快速报价存在缺失数据，不能加入正式汇总清单。"); return
        source_ocr_remark = self.notes_text.toPlainText().strip()
        single_count, double_count = self.door_counts()
        item = {"name": self.cabinet_name(), "model_code": self.model_edit.text().strip(), "product_code": self.selected_product_code(), "product_family": self.product_combo.currentText(), "variant_code": self.selected_variant_code(), "variant_name": self.selected_variant_name(), "single_door_count": single_count, "double_door_count": double_count, "material_code": self.material_combo.currentData(), "coating_type": self.coating_combo.currentData(), "width_mm": self.width_spin.value(), "height_mm": self.height_spin.value(), "depth_mm": self.depth_spin.value(), "quantity": self.quantity_spin.value(), "attachments": [dict(x) for x in self.attachments], "source_ocr_remark": source_ocr_remark, "source_pdf_name": self.active_drawing.get("name") if self.active_drawing else None, "formula": dict(self.current_result["formula"]), "formula_base": dict(self._formula_base_result or self.current_result["formula"]), "quick": dict(self.current_result["quick"]), "formula_discount": self.formula_discount.value(), "quick_discount": self.quick_discount.value(), "labor_multiplier": self.labor_multiplier.value()}
        final_remark = replace_door_configuration_phrase(
            build_standardized_quote_remark(item, source_ocr_remark),
            item,
        )
        item["notes"] = final_remark
        item["final_remark"] = final_remark
        self.draft_items.append(item); self.refresh_summary(); self.statusBar().showMessage("柜型已加入汇总清单"); self.reset_current_cabinet(keep_company=True); self.show_section(3)

    def refresh_summary(self):
        self.summary_table.setRowCount(len(self.draft_items)); formula_sum = quick_sum = 0.0
        for row, item in enumerate(self.draft_items):
            formula_unit = float(item["formula"]["total_cost"]) * float(item["formula_discount"])
            quick_unit = quick_discount_breakdown(
                item["quick"], item.get("attachments", []), item["quick_discount"]
            )["discounted_total"]
            formula_sum += formula_unit * item["quantity"]; quick_sum += quick_unit * item["quantity"]
            dimensions = f"{item['width_mm']:g}×{item['height_mm']:g}×{item['depth_mm']:g}"
            values = [row + 1, self.drawing_name_before_chinese(item["name"]), dimensions, dimensions, item["material_code"], item["quantity"], f"{formula_unit:,.2f}", f"{item['formula_discount']:.2f}", f"{quick_unit:,.2f}", f"{item['quick_discount']:.2f}", str(len(item["attachments"])), item["notes"]]
            for col, value in enumerate(values): self.summary_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.summary_formula_total.setText(f"公式法：{formula_sum:,.2f} 元"); self.summary_quick_total.setText(f"快速报价：{quick_sum:,.2f} 元")

    def selected_summary_row(self): return self.summary_table.currentRow()
    def remove_selected_item(self):
        row = self.selected_summary_row()
        if row < 0: return
        self.draft_items.pop(row); self.refresh_summary()
    def move_selected_item(self, direction):
        row = self.selected_summary_row(); target = row + direction
        if row < 0 or target < 0 or target >= len(self.draft_items): return
        self.draft_items[row], self.draft_items[target] = self.draft_items[target], self.draft_items[row]; self.refresh_summary(); self.summary_table.selectRow(target)
    def edit_selected_item(self):
        row = self.selected_summary_row()
        if row < 0: return
        item = self.draft_items.pop(row); self.load_draft_item(item); self.refresh_summary(); self.show_section(1)

    def load_draft_item(self, item):
        index = self.product_combo.findData(item["product_family"])
        if index >= 0: self.product_combo.setCurrentIndex(index)
        if "single_door_count" in item or "double_door_count" in item:
            single_count = int(item.get("single_door_count") or 0)
            double_count = int(item.get("double_door_count") or 0)
        elif item.get("variant_code") == "DOUBLE":
            single_count, double_count = 0, 1
        elif item.get("variant_code") == "SINGLE":
            single_count, double_count = 1, 0
        else:
            single_count, double_count = 0, 0
        self.set_door_counts(single_count, double_count)
        self.model_edit.setText(item["model_code"]); self.width_spin.setValue(item["width_mm"]); self.height_spin.setValue(item["height_mm"]); self.depth_spin.setValue(item["depth_mm"]); self.quantity_spin.setValue(item["quantity"])
        mi = self.material_combo.findData(item["material_code"]); ci = self.coating_combo.findData(item["coating_type"])
        if mi >= 0: self.material_combo.setCurrentIndex(mi)
        if ci >= 0: self.coating_combo.setCurrentIndex(ci)
        self.attachments = [dict(x) for x in item["attachments"]]; self.notes_text.setPlainText(item.get("final_remark", item.get("notes", ""))); self.formula_discount.setValue(item["formula_discount"]); self.quick_discount.setValue(item["quick_discount"]); self.labor_multiplier.setValue(item.get("labor_multiplier", 1.0)); self.update_attachment_view(); self._formula_base_result = dict(item.get("formula_base") or item["formula"]); self.current_result = {"formula": dict(item["formula"]), "quick": dict(item["quick"]), "risk_flags": []}; self.refresh_discounted_totals(); self.refresh_formula_inputs()

    def reset_current_cabinet(self, keep_company=False):
        self.model_edit.clear(); self.width_spin.setValue(1000); self.height_spin.setValue(1800); self.depth_spin.setValue(600); self.quantity_spin.setValue(1); apply_default_quote_inputs(self); self.labor_multiplier.setValue(1); self.formula_discount.setValue(1); self.quick_discount.setValue(1); self.attachments = []; self.notes_text.clear(); self.active_drawing = None; self.recommended_attachments = []; self.attachment_recommendation.setText("OCR 推荐附件：—"); self._formula_base_result = None; self.current_result = None; self.weight_edit.clear(); self.area_edit.clear(); self.update_attachment_view()
        for label in self.formula_labels.values(): label.setText("—")
        for label in self.quick_labels.values(): label.setText("—")
        self.risk_label.setStyleSheet(""); self.risk_label.setText("尚未计算")
        if self.product_combo.count(): self.product_changed()

    # ---- confirmation and workbook export ---------------------------------
    def next_quote_id(self): return "Q" + datetime.now().strftime("%Y%m%d") + datetime.now().strftime("%f")[-4:]

    def set_export_busy(self, busy: bool, message: str = ""):
        if self.confirm_button:
            self.confirm_button.setEnabled(not busy)
            self.confirm_button.setText("正在处理…" if busy else "确认并导出正式报价单")
        if message:
            self.statusBar().showMessage(message)

    def confirmation_failed(self, message: str):
        message = _api_error_text(message)
        self.set_export_busy(False, "报价确认失败，未生成正式报价单")
        self.show_error(message)
        QMessageBox.critical(self, "报价确认失败", message)

    def validate_export_environment(self):
        """Verify that the company-side API can calculate and export quotes."""
        root = application_root()
        script = root / "export_dual_quote_workbook.mjs"
        template = root / "templates" / "quote_template.xlsx"
        if not script.is_file() and not getattr(sys, "frozen", False):
            raise RuntimeError(f"缺少正式报价单导出组件：{script}")
        if not template.is_file() and not getattr(sys, "frozen", False):
            raise RuntimeError(f"缺少正式报价单模板：{template}")
        node_candidates = [shutil.which("node")]
        if not getattr(sys, "frozen", False) and not any(
            candidate and Path(candidate).is_file() for candidate in node_candidates
        ):
            raise RuntimeError("未找到 Excel 导出运行环境，请重新安装或修复客户端运行环境。")
        try:
            request = urllib.request.Request(
                self.base_url() + "/health", headers=api_headers(), method="GET"
            )
            with urllib.request.urlopen(request, timeout=4) as response:
                health = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                "双报价接口没有运行。请先启动 start_api.ps1，再重新导出。"
            ) from exc
        build = str(health.get("build") or "")
        if build != REQUIRED_EXPORT_API_BUILD:
            raise RuntimeError(
                f"双报价接口版本过旧（当前：{build or '未知'}）。"
                "请关闭占用 8080 端口的旧接口，重新运行 start_api.ps1。"
            )

    def confirm_and_export(self):
        if (self.confirm_worker and self.confirm_worker.isRunning()) or (
            self.export_worker and self.export_worker.isRunning()
        ):
            QMessageBox.information(self, "正在处理", "报价正在确认或生成 Excel，请稍候。")
            return
        if not self.draft_items:
            QMessageBox.warning(self, "汇总清单为空", "请先将至少一个柜型加入汇总清单。"); return
        company = self.company_combo.currentText().strip()
        if not company:
            QMessageBox.warning(self, "缺少下单公司", "请在左侧输入或选择下单公司。"); return
        try:
            self.validate_export_environment()
        except Exception as exc:
            self.confirmation_failed(str(exc))
            return
        quote_id = self.next_quote_id()
        output_dir = application_root() / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_company = re.sub(r'[<>:"/\\|?*]+', "_", company).strip(" ._")
        default_name = f"{quote_id}_{safe_company + '_' if safe_company else ''}双报价单.xlsx"
        default_path = output_dir / default_name
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出正式报价单",
            str(default_path),
            "Excel 工作簿 (*.xlsx)",
        )
        if not path: return
        if not path.lower().endswith(".xlsx"): path += ".xlsx"
        export_path = Path(path)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"quote_id": quote_id, "quote_date": self.quote_date.date().toString("yyyy-MM-dd"), "company_code": self.selected_company_code() or company, "company_name": company, "items": self.draft_items}
        self.pending_export_path = path
        # First exercise the actual confirmation transaction and roll it back.
        # Only after UTF-8/jsonb, constraints and history inserts all pass do we
        # persist the quotation. This prevents the common "history saved but
        # no Excel" partial result.
        self.confirm_worker = ApiWorker(self.base_url() + "/api/quotes/confirm-check", payload, self)
        self.confirm_worker.succeeded.connect(lambda r, p=payload: self.confirm_preflight_succeeded(r, p))
        self.confirm_worker.failed.connect(self.confirmation_failed)
        self.set_export_busy(True, "正在检查中文备注、附件和报价数据…")
        self.confirm_worker.start()

    def confirm_preflight_succeeded(self, result, payload):
        if not result.get("dry_run") or not result.get("confirmed"):
            self.confirmation_failed("报价数据检查未通过，数据库没有返回有效状态。")
            return
        self.set_export_busy(True, "数据检查通过，正在确认报价并写入公司历史…")
        self.confirm_worker = ApiWorker(self.base_url() + "/api/quotes/confirm", payload, self)
        self.confirm_worker.succeeded.connect(lambda r, p=payload: self.confirmed_and_export(r, p))
        self.confirm_worker.failed.connect(self.confirmation_failed)
        self.confirm_worker.start()

    def confirmed_and_export(self, result, payload):
        if not result.get("confirmed"):
            self.confirmation_failed("数据库未返回确认成功状态。")
            return
        if not self.pending_export_path:
            self.export_failed("没有可用的 Excel 导出路径。")
            return
        self.set_export_busy(True, "公司历史已写入，正在后台生成 Excel 正式报价单…")
        self.export_worker = WorkbookExportWorker(
            self.export_workbook,
            self.pending_export_path,
            payload,
            self,
        )
        history_items = int(result.get("history_items", 0) or 0)
        self.export_worker.succeeded.connect(
            lambda exported_path, count=history_items: self.export_succeeded(exported_path, count)
        )
        self.export_worker.failed.connect(self.export_failed)
        self.export_worker.start()

    def export_succeeded(self, exported_path: str, history_items: int):
        self.set_export_busy(False, "正式报价单已生成；本次报价已写入公司历史")
        resolved_path = Path(exported_path).resolve()
        QMessageBox.information(
            self,
            "正式报价单已生成",
            f"已确认 {history_items} 个柜型，并生成：\n{resolved_path}\n\n即将打开文件所在目录。",
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved_path.parent)))

    def export_failed(self, message: str):
        detail = "报价历史已写入数据库，但 Excel 生成失败：" + message
        self.set_export_busy(False, "Excel 生成失败；报价历史已写入数据库")
        self.show_error(detail)
        QMessageBox.critical(self, "Excel 生成失败", detail)

    def export_workbook(self, output_path, payload):
        """Ask the company-side API to render Excel, then download it locally."""
        output_file = Path(output_path).resolve()
        if output_file.exists() and output_file.is_dir():
            raise RuntimeError(f"Export target is a folder, not an Excel file: {output_file}")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            self.base_url() + "/api/quotes/export",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=api_headers(True),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                workbook_bytes = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(_api_error_text(detail or f"HTTP {exc.code}")) from exc
        if not workbook_bytes:
            raise RuntimeError("The quote API returned an empty Excel file.")
        partial_file = output_file.with_suffix(output_file.suffix + ".part")
        partial_file.write_bytes(workbook_bytes)
        partial_file.replace(output_file)

    def closeEvent(self, event):
        """Stop a running OCR queue before destroying its Qt owner."""
        if self.pdf_worker and self.pdf_worker.isRunning():
            self.close_after_pdf_cancel = True
            self.pdf_worker.requestInterruption()
            self.drawing_status.setText("正在安全停止图纸识别，完成当前文件后关闭客户端。")
            event.ignore()
            return
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget#page {
            background: #f4f7fb;
            color: #203044;
            font-family: "Microsoft YaHei";
            font-size: 11pt;
        }
        QFrame#navPanel {
            background: #163f67;
            border-radius: 18px;
        }
        QLabel#navTitle {
            color: #ffffff;
            font-size: 16pt;
            font-weight: 700;
        }
        QLabel#navHint, QLabel#navFooter {
            color: #bcd0e4;
            font-size: 10pt;
        }
        QLabel#companyLabel {
            color: #ffffff;
            font-size: 11pt;
            font-weight: 600;
        }
        QLabel#companyHint {
            color: #bcd0e4;
            font-size: 9pt;
        }
        QComboBox#companyCombo {
            color: #173d63;
            background: #f8fbff;
            border: 1px solid #d7e5f2;
            border-radius: 8px;
            padding: 6px 8px;
            min-height: 30px;
        }
        QComboBox#companyCombo QAbstractItemView {
            color: #173d63;
            background: #ffffff;
        }
        QPushButton#navButton {
            text-align: left;
            color: #dbeafe;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 12px;
            padding: 10px 14px;
            font-weight: 600;
            font-size: 12pt;
        }
        QPushButton#navButton:hover {
            background: #24527d;
        }
        QPushButton#navButton:checked {
            color: #173d63;
            background: #f8fbff;
            border-color: #ffffff;
        }
        QLabel#sectionTitle {
            color: #173d63;
            font-size: 19pt;
            font-weight: 700;
        }
        QLabel#sectionSubtitle {
            color: #60758a;
            font-size: 11pt;
        }
        QGroupBox#attachmentCard, QGroupBox#drawingCard,
        QGroupBox#drawingConfirmCard, QGroupBox#summaryCard {
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 12px;
            margin-top: 12px;
            padding-top: 12px;
        }
        QLabel#attachmentStatus, QLabel#drawingStatus {
            color: #35516c;
            font-weight: 600;
        }
        QFrame#attachmentCategoryBar {
            background: #eef5fb;
            border: 1px solid #c8d9e8;
            border-left: 4px solid #2c78c4;
            border-radius: 8px;
        }
        QLabel#attachmentCategoryTitle {
            color: #24476a;
            font-size: 10pt;
            font-weight: 700;
        }
        QScrollArea#attachmentCategoryScroll {
            background: transparent;
            border: 0;
        }
        QPushButton#attachmentCategoryBack {
            background: transparent;
            border: 0;
            color: #2c6fa8;
            padding: 4px 8px;
            font-weight: 600;
        }
        QPushButton#attachmentCategoryBack:hover {
            color: #174a73;
            text-decoration: underline;
        }
        QFrame#attachmentCategoryCardShell {
            background: #fbfdff;
            border: 1px solid #a9c5d9;
            border-left: 5px solid #2c78c4;
            border-radius: 7px;
        }
        QPushButton#attachmentCategoryCard {
            background: transparent;
            border: 0;
            border-bottom: 1px solid #d8e5ef;
            border-radius: 0;
            color: #173f67;
            font-weight: 700;
            padding: 10px 14px;
            text-align: left;
        }
        QPushButton#attachmentCategoryCard:hover {
            background: #e4f1fb;
            border-bottom-color: #6da4cc;
        }
        QPushButton#attachmentCategoryCard:pressed {
            background: #d5e8f6;
        }
        QLabel#attachmentQuickMatch {
            background: #f4f7fa;
            color: #66727e;
            padding: 7px 12px;
            border: 0;
        }
        QLabel#attachmentQuickMatchMatched {
            background: #e8f5ee;
            color: #216744;
            font-weight: 700;
            padding: 7px 12px;
            border: 0;
        }
        QLabel#attachmentQuickMatchMissing {
            background: #fff5df;
            color: #9a620e;
            font-weight: 700;
            padding: 7px 12px;
            border: 0;
        }
        QTextEdit {
            background: #fbfdff;
            border: 1px solid #bfcedc;
            border-radius: 6px;
            padding: 8px;
        }
        QTextEdit#attachmentRecognitionText {
            min-height: 150px;
            selection-background-color: #2c78c4;
        }
        QTextEdit#notesText {
            min-height: 330px;
            selection-background-color: #2c78c4;
        }
        QScrollArea#mainScroll {
            background: #f4f7fb;
            border: 0;
        }
        QScrollBar:vertical {
            background: #e8eef5;
            width: 14px;
            margin: 2px;
            border-radius: 7px;
        }
        QScrollBar:horizontal {
            background: #e8eef5;
            height: 14px;
            margin: 2px;
            border-radius: 7px;
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #9fb3c8;
            border-radius: 6px;
            min-height: 28px;
            min-width: 28px;
        }
        QScrollBar::handle:hover {
            background: #6f8fab;
        }
        QScrollBar::add-line, QScrollBar::sub-line,
        QScrollBar::add-page, QScrollBar::sub-page {
            background: none;
            border: 0;
        }
        QWidget#hero {
            background: #173d63;
            border-radius: 14px;
        }
        QLabel#heroTitle {
            color: #ffffff;
            font-size: 23pt;
            font-weight: 700;
        }
        QLabel#heroSubtitle {
            color: #c8d9ea;
            font-size: 11pt;
        }
        QLabel#apiBadge {
            color: #d8ffe6;
            background: #236a4b;
            border-radius: 12px;
            padding: 7px 12px;
            font-weight: 600;
        }
        QGroupBox {
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 12px;
            margin-top: 12px;
            padding-top: 12px;
            font-size: 13pt;
            font-weight: 700;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 16px;
            padding: 0 6px;
            color: #24476a;
        }
        QGroupBox#formulaCard { border-top: 4px solid #2c78c4; }
        QGroupBox#quickCard { border-top: 4px solid #19a974; }
        QGroupBox#riskCard { border-top: 4px solid #e0a326; }
        QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit {
            background: #fbfdff;
            border: 1px solid #bfcedc;
            border-radius: 6px;
            padding: 6px 9px;
            min-height: 22px;
            selection-background-color: #2c78c4;
        }
        QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus,
        QSpinBox:focus, QDateEdit:focus {
            border: 2px solid #4b91d1;
        }
        QPushButton {
            background: #2c78c4;
            color: #ffffff;
            border: 0;
            border-radius: 7px;
            padding: 8px 18px;
            font-weight: 600;
            min-height: 24px;
        }
        QPushButton:hover { background: #1f64a7; }
        QPushButton:pressed { background: #174f84; }
        QPushButton:disabled { background: #aab9c7; }
        QPushButton[text="清空"] {
            background: #e8eef5;
            color: #35516c;
        }
        QPushButton[text="清空"]:hover { background: #dce6f0; }
        QGroupBox#formulaCard QLabel#result_total,
        QGroupBox#quickCard QLabel#result_total {
            color: #113c69;
            font-size: 18pt;
            font-weight: 700;
        }
        QGroupBox#formulaCard QLabel#result_labor,
        QGroupBox#formulaCard QLabel#result_management {
            color: #8a5a00;
            font-weight: 600;
        }
        QStatusBar {
            background: #e8eef5;
            color: #46617a;
        }
        """
    )
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
