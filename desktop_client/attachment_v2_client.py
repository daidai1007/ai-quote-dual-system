"""Shared V2 attachment integration for source MainWindow and recovered V3 classes.

The existing catalogue browser and ganged workflow retain their layout/rules.
Single-cabinet and ganged V2 selections share server previews and immutable quote rows.
"""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from uuid import uuid4
from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QTableWidgetItem, QVBoxLayout, QHeaderView, QInputDialog, QWidget
from shiboken6 import isValid

from attachment_category_browser import parse_base_specification

PREVIEW_DELAY_MS = 350
EXTRA_HEADERS = ("快速金额", "公式状态", "公式单位成本", "公式金额", "人工尺寸")
COST_KEYS = ("error", "rule_id", "rule_version", "rule_materials", "rule_source_row", "formulas", "calculation_notes", "weight_kg", "material_cost", "spray_area_m2", "spray_cost", "auxiliary_cost", "auxiliary_list", "labor_cost", "attachment_selection_id", "quote_line_id", "environment")


def attachment_image_match_key(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def attachment_images_for_name(image_catalog, item_name):
    wanted = attachment_image_match_key(item_name)
    if not wanted:
        return []
    for entry in image_catalog if isinstance(image_catalog, list) else []:
        if not isinstance(entry, dict):
            continue
        candidate = attachment_image_match_key(entry.get("item_name"))
        mode = "PREFIX" if entry.get("match_mode") == "PREFIX" else "EXACT"
        if candidate and ((mode == "PREFIX" and wanted.startswith(candidate)) or wanted == candidate):
            return [dict(image) for image in entry.get("images", []) if isinstance(image, dict)]
    return []

def merge_cost(source, cost, automatic_base_height=None):
    merged = {**{key: value for key, value in source.items() if key not in COST_KEYS}, **cost}
    if automatic_base_height is not None:
        manual = copy.deepcopy(merged.get("manual_inputs") or {})
        manual.pop("底座高度", None)
        merged["manual_inputs"] = manual
    return merged

def price_sign(source):
    return -1 if source.get("attachment_price_sign") == -1 else 1

def installation_board(source):
    identity = " ".join(str(source.get(key) or "") for key in ("category_level1", "category_level2", "category_level3", "item_name", "model_code"))
    return "安装板" in identity and "安装板单发" not in identity

def ganged(window):
    control = getattr(window, "ganged_count_spin", None)
    if control is None:
        control = getattr(window, "ganged_cabinet_count_spin", None)
    try:
        from layout_refresh import _ganged_count
        return _ganged_count(window) > 1
    except (ImportError, AttributeError, TypeError):
        return bool(control and control.value() > 1)

def base_height(window):
    """Return the base height already entered in the visible cabinet specification."""
    rows = [dict(row) for row in getattr(window, "ganged_cabinets", []) if isinstance(row, dict)]
    if len(rows) > 1:
        values = [row.get("base_height_mm") for row in rows]
        if values and all(value not in (None, "") for value in values):
            return float(values[0])
    for name in ("quote_spec_edit", "model_edit"):
        control = getattr(window, name, None)
        text = control.text().strip() if control is not None and hasattr(control, "text") else ""
        parsed = parse_base_specification(text)
        if parsed is not None:
            return float(parsed[3])
    return None

def environment(window, attachments):
    ganged_rows = [dict(row) for row in getattr(window, "ganged_cabinets", []) if isinstance(row, dict)]
    if len(ganged_rows) <= 1:
        ganged_rows = []
    child_inputs = []
    if ganged_rows:
        product_key = getattr(getattr(window, "product_combo", None), "currentData", lambda: None)() or ""
        codes = (getattr(window, "product_catalog", {}).get(product_key, {}) or {}).get("codes") or {}
        fallback_code = window.selected_product_code()
        for row in ganged_rows:
            wanted = "SINGLE" if int(row.get("single_door_count") or 0) > 0 else "DOUBLE"
            code = next((codes.get(key) for key in (wanted, "DEFAULT", "SINGLE", "DOUBLE") if codes.get(key)), fallback_code)
            child_inputs.append({**row, "product_code": code})
    return {"quote_id": "PREVIEW", "product_code": window.selected_product_code(), "model_code": window.model_edit.text().strip() if hasattr(window, "model_edit") else "",
            "material_code": window.material_combo.currentData(),
            "width_mm": window.width_spin.value(), "height_mm": window.height_spin.value(), "depth_mm": window.depth_spin.value(),
            "coating_type": window.coating_combo.currentData(), "quote_date": window.quote_date.date().toString("yyyy-MM-dd"),
            "attachments": attachments, "attachment_contract": 2,
            "ganged_cabinet_count": len(ganged_rows) if ganged_rows else 1, "ganged_cabinets": ganged_rows,
            "ganged_cabinet_inputs": child_inputs}

def uses_base_height(item):
    identity = " ".join(str(item.get(key) or "") for key in ("category_level1", "category_level2", "item_name"))
    if "底座" in identity:
        return True
    if any(parameter.get("name") == "底座高度" for parameter in item.get("required_parameters", [])):
        return True
    formulas = [item.get("formulas")]
    formulas.extend(rule.get("formulas") for rule in item.get("rules", []) if isinstance(rule, dict))
    return any("底座高度" in json.dumps(value, ensure_ascii=False) for value in formulas if value)

def selected_input(item, automatic_base_height=None):
    manual_inputs = copy.deepcopy(item.get("manual_inputs") or {})
    # Compatibility for the currently deployed V2 API, where 底座高度 was
    # classified as MANUAL.  The value still comes exclusively from the
    # visible cabinet specification; users never enter it in the attachment row.
    if automatic_base_height is not None and uses_base_height(item):
        manual_inputs["底座高度"] = automatic_base_height
    selected = {"attachment_price_id": item.get("attachment_price_id"), "quantity": item.get("quantity", 1),
                "attachment_price_sign": item.get("attachment_price_sign", 1), "manual_inputs": manual_inputs}
    if item.get("unit_price_override") is not None:
        selected["unit_price_override"] = item.get("unit_price_override")
    ganged_index = item.get("ganged_cabinet_index", item.get("ganged_fixed_base_index"))
    if ganged_index is not None:
        selected["ganged_cabinet_index"] = int(ganged_index)
    return selected

def install_attachment_v2(namespace):
    window_class, dialog_class, worker_class = (namespace.get(n) for n in ("MainWindow", "AttachmentDialog", "ApiWorker"))
    if not window_class or not dialog_class or not worker_class or getattr(window_class, "_attachment_v2_installed", False):
        return
    window_class._attachment_v2_installed = True
    originals = {name: getattr(dialog_class, name) for name in ("__init__", "load_catalog", "rebuild_table", "collect_attachments", "accept_selection")}
    same_choice = dialog_class._same_catalog_choice
    @classmethod
    def same_choice_v2(cls, selected, catalog_item):
        if selected.get("catalog_version") or catalog_item.get("catalog_version") or catalog_item.get("data_version"):
            return selected.get("attachment_price_id") is not None and str(selected["attachment_price_id"]) == str(catalog_item.get("attachment_price_id"))
        return same_choice(selected, catalog_item)
    dialog_class._same_catalog_choice = same_choice_v2

    def checked(dialog):
        rows = []
        for row in range(dialog.table.rowCount()):
            cell = dialog.table.item(row, dialog.COL_CHECK)
            if cell and cell.checkState() == Qt.CheckState.Checked:
                rows.append((row, cell, cell.data(Qt.ItemDataRole.UserRole) or {}))
        return rows

    def collect(dialog, show_errors=True):
        result = originals["collect_attachments"](dialog, show_errors=show_errors)
        if result is not None and getattr(dialog, "_v2_mode", False):
            for index, (item, (_, _, source)) in enumerate(zip(result, checked(dialog))):
                result[index] = item = {**copy.deepcopy(source), **item}
                item.pop("rules", None)
            decorate(dialog)
        return result

    def decorate(dialog):
        if not getattr(dialog, "_v2_mode", False):
            return
        table = dialog.table
        first = dialog.COL_QUANTITY + 1
        table.blockSignals(True)
        try:
            table.setColumnCount(first + len(EXTRA_HEADERS))
            table.setHorizontalHeaderItem(dialog.COL_PRICE, QTableWidgetItem("面价（元）"))
            table.setHorizontalHeaderItem(dialog.COL_SCHEME, QTableWidgetItem("单位"))
            table.setHorizontalHeaderItem(dialog.COL_NAME, QTableWidgetItem("一级分类 / 名称"))
            table.horizontalHeader().setSectionResizeMode(dialog.COL_NAME, QHeaderView.ResizeMode.Interactive)
            table.horizontalHeader().resizeSection(dialog.COL_NAME, 250)
            table.verticalHeader().setMinimumSectionSize(64)
            table.verticalHeader().setDefaultSectionSize(64)
            dialog.catalog_hint.setText("面价按Excel原值；金额＝选择数量×单价×加减符号。双击人工尺寸填写参数。")
            for i, name in enumerate(EXTRA_HEADERS):
                table.setHorizontalHeaderItem(first + i, QTableWidgetItem(name))
                table.horizontalHeader().setSectionResizeMode(first + i, QHeaderView.ResizeMode.ResizeToContents)
            for row in range(table.rowCount()):
                price = table.item(row, dialog.COL_PRICE)
                if price:
                    price.setFlags(price.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cell = table.item(row, dialog.COL_CHECK)
                source = dict(cell.data(Qt.ItemDataRole.UserRole) or {}) if cell else {}
                name_item = table.item(row, dialog.COL_NAME)
                if source and name_item:
                    name_cell = table.cellWidget(row, dialog.COL_NAME)
                    if name_cell is None or name_cell.objectName() != "attachmentCategoryNameCell":
                        name_cell = QWidget(table)
                        name_cell.setObjectName("attachmentCategoryNameCell")
                        name_cell.setMinimumHeight(60)
                        name_layout = QVBoxLayout(name_cell)
                        name_layout.setContentsMargins(6, 3, 6, 3)
                        name_layout.setSpacing(1)
                        category_label = QLabel(name_cell)
                        category_label.setObjectName("attachmentPrimaryCategoryCell")
                        category_label.setStyleSheet("color:#5c6b78;font-size:9pt;")
                        item_label = QLabel(name_cell)
                        item_label.setObjectName("attachmentItemNameCell")
                        item_label.setStyleSheet("color:#173f67;font-weight:600;")
                        name_layout.addWidget(category_label)
                        name_layout.addWidget(item_label)
                        table.setCellWidget(row, dialog.COL_NAME, name_cell)
                    category_label = name_cell.findChild(QLabel, "attachmentPrimaryCategoryCell")
                    item_label = name_cell.findChild(QLabel, "attachmentItemNameCell")
                    category = str(source.get("category_level1") or "未分类").strip() or "未分类"
                    # The catalogue row already owns the primary category.  Some
                    # historical ``display_name`` values contain the category
                    # path as an extra line, which made the custom two-line cell
                    # render three overlapping labels.  Keep the table contract
                    # explicit: one category line and one item-name line.
                    name = " ".join(
                        str(source.get("item_name") or name_item.text() or "未命名附件").split()
                    )
                    name_item.setText("")
                    category_label.setText(f"一级分类：{category}")
                    item_label.setText(f"名称：{name}")
                    name_cell.setAccessibleName(f"一级分类：{category}，名称：{name}")
                    table.setRowHeight(row, max(64, table.rowHeight(row)))
                scheme = table.item(row, dialog.COL_SCHEME)
                if scheme:
                    scheme.setText(source.get("unit") or "")
                face = source.get("face_price", source.get("price", source.get("matched_price")))
                if price and face is not None:
                    price.setText(str(abs(float(face)) * price_sign(source)))
                    price.setToolTip("Excel面价；仅安装板可双击切换加价/扣减")
                source.setdefault("selection_key", str(uuid4()))
                if cell:
                    cell.setData(Qt.ItemDataRole.UserRole, source)
                for i in range(len(EXTRA_HEADERS)):
                    if table.item(row, first + i) is None:
                        value = QTableWidgetItem("—")
                        value.setFlags(value.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row, first + i, value)
        finally:
            table.blockSignals(False)

    def rebuild(dialog):
        result = originals["rebuild_table"](dialog)
        decorate(dialog)
        if hasattr(dialog, "_v2_timer"):
            dialog._v2_timer.start()
        return result

    def load(dialog, api_url):
        parent = dialog.parentWidget()
        dialog._v2_mode = parent is not None and all(hasattr(parent, key) for key in ("material_combo", "width_spin", "height_spin", "depth_spin", "coating_combo", "quote_date"))
        if not dialog._v2_mode:
            return originals["load_catalog"](dialog, api_url)
        dialog.catalog_hint.setText("正在读取附件面价及成本规则…")
        generation = getattr(dialog, "_v2_catalog_generation", 0) + 1
        dialog._v2_catalog_generation = generation
        url = api_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/catalog?v=2"
        worker = worker_class(url, {}, parent, method="GET")
        dialog._v2_catalog_worker = worker
        def loaded(body):
            if not isValid(dialog) or dialog._v2_catalog_generation != generation:
                return
            image_catalog = [dict(entry) for entry in body.get("attachment_images", []) if isinstance(entry, dict)]
            dialog._attachment_image_catalog = image_catalog
            if parent is not None:
                parent._attachment_image_catalog = image_catalog
            dialog.catalog = [
                dict(
                    x,
                    catalog_version=body["data_version"],
                    display_name=dialog.display_name(x),
                    attachment_images=attachment_images_for_name(image_catalog, x.get("item_name")),
                )
                for x in body.get("items", [])
            ]
            add_button = getattr(dialog, "add_attachment_catalog_button", None)
            if add_button is not None:
                write_supported = body.get("catalog_write_supported") is True
                add_button.setEnabled(write_supported)
                add_button.setToolTip(
                    "新增到当前启用的附件目录；未配置成本规则时作为仅快速报价附件"
                    if write_supported
                    else "当前线上服务尚未启用V2附件新增接口"
                )
            dialog.catalog_hint.setText(f"已读取 {len(dialog.catalog)} 项附件；面价固定，公式成本随当前产品环境计算。")
            prepare = getattr(dialog, "prepare_fixed_base_quick_match", None)
            if callable(prepare):
                spec = getattr(dialog, "_specification_text", None)
                dialog.base_quick_match_specification = spec() if callable(spec) else ""
                prepare()
            dialog.rebuild_table()
            dialog.refresh_category_browser()
        worker.succeeded.connect(loaded)
        worker.failed.connect(lambda message: dialog.catalog_hint.setText(f"附件读取失败：{message}；可点击重新读取价格库重试") if isValid(dialog) else None)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def preview(dialog):
        if not getattr(dialog, "_v2_mode", False):
            return
        selected = dialog.collect_attachments(show_errors=False)
        if selected is None:
            return
        automatic_base = base_height(dialog.parentWidget())
        payload = environment(dialog.parentWidget(), [selected_input(x, automatic_base) for x in selected])
        signature = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        dialog._v2_signature = signature
        old = getattr(dialog, "_v2_preview_worker", None)
        if old and old.isRunning():
            dialog._v2_timer.start()
            return
        if not selected:
            dialog._v2_ready = True
            return
        dialog._v2_ready = False
        url = dialog.api_url.split("/api/", 1)[0].rstrip("/") + "/api/attachments/preview"
        worker = worker_class(url, payload, dialog.parentWidget())
        dialog._v2_preview_worker = worker
        def loaded(body):
            if not isValid(dialog):
                return
            latest = dialog.collect_attachments(show_errors=False)
            if latest is None or json.dumps(environment(dialog.parentWidget(), [selected_input(x, automatic_base) for x in latest]), sort_keys=True, ensure_ascii=False) != signature:
                dialog._v2_timer.start()
                return
            dialog.table.blockSignals(True)
            try:
                for (row, cell, source), cost in zip(checked(dialog), body.get("attachments", [])):
                    source = merge_cost(source, cost, automatic_base)
                    cell.setData(Qt.ItemDataRole.UserRole, source)
                    manual = [p["name"] for p in cost.get("required_parameters", []) if p["source"] == "MANUAL" and not (p["name"] == "底座高度" and automatic_base is not None)]
                    values = [cost.get("quick_amount"), cost.get("status_text"), cost.get("formula_unit_cost"), cost.get("formula_amount"), "、".join(manual) or "无需填写"]
                    for i, value in enumerate(values):
                        item = dialog.table.item(row, dialog.COL_QUANTITY + 1 + i)
                        if item:
                            item.setText("—" if value is None else (f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)))
                            item.setToolTip((cost.get("error") or "") + "\n辅材清单：\n" + cost.get("auxiliary_list", ""))
                dialog._v2_ready = not body.get("errors")
                dialog.selection_hint.setText("成本已更新；双击人工尺寸列填写参数" if dialog._v2_ready else "请补充人工尺寸或处理公式错误；双击人工尺寸列填写")
            finally:
                dialog.table.blockSignals(False)
            decorate(dialog)
        worker.succeeded.connect(loaded)
        worker.failed.connect(lambda message: dialog.selection_hint.setText(f"附件计算失败：{message}") if isValid(dialog) else None)
        def finished():
            if isValid(dialog) and getattr(dialog, "_v2_preview_worker", None) is worker:
                dialog._v2_preview_worker = None
            worker.deleteLater()
        worker.finished.connect(finished)
        worker.start()

    def edit_parameters(dialog, row, column):
        if not getattr(dialog, "_v2_mode", False):
            return
        source_cell = dialog.table.item(row, dialog.COL_CHECK)
        source = dict(source_cell.data(Qt.ItemDataRole.UserRole) or {})
        if column == dialog.COL_PRICE and installation_board(source):
            choice, accepted = QInputDialog.getItem(dialog, "安装板加减", "面价固定，选择金额方向", ["加价", "扣减"], 0 if price_sign(source) > 0 else 1, False)
            if accepted:
                source["attachment_price_sign"] = -1 if choice == "扣减" else 1
                if hasattr(dialog, "installation_board_sign"):
                    dialog.installation_board_sign = source["attachment_price_sign"]
                    for _, cell, item in checked(dialog):
                        if installation_board(item):
                            cell.setData(Qt.ItemDataRole.UserRole, {**item, "attachment_price_sign": source["attachment_price_sign"]})
                source_cell.setData(Qt.ItemDataRole.UserRole, source)
                decorate(dialog)
                dialog._v2_ready = False
                dialog._v2_timer.start()
            return
        if column != dialog.COL_QUANTITY + len(EXTRA_HEADERS):
            return
        automatic_base = base_height(dialog.parentWidget())
        parameters = [p for p in source.get("required_parameters", []) if p["source"] == "MANUAL" and not (p["name"] == "底座高度" and automatic_base is not None)]
        if not parameters:
            return
        editor = QDialog(dialog)
        editor.setWindowTitle(f"{source.get('item_name', '附件')} · 人工尺寸（mm）")
        layout, form, fields = QVBoxLayout(editor), QFormLayout(), {}
        for parameter in parameters:
            name = parameter["name"]
            fields[name] = QLineEdit(str((source.get("manual_inputs") or {}).get(name, "")))
            fields[name].setPlaceholderText("必填，不自动使用产品尺寸")
            form.addRow(name, fields[name])
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(editor.accept)
        buttons.rejected.connect(editor.reject)
        layout.addWidget(buttons)
        if editor.exec() == QDialog.DialogCode.Accepted:
            source["manual_inputs"] = {name: field.text().strip() for name, field in fields.items()}
            # V3's legacy itemChanged handler rematches dimensions. Metadata edits
            # must not trigger that handler and discard this selection's inputs.
            blocked = dialog.table.blockSignals(True)
            try:
                source_cell.setData(Qt.ItemDataRole.UserRole, source)
            finally:
                dialog.table.blockSignals(blocked)
            dialog._v2_ready = False
            dialog._v2_timer.start()

    def init(dialog, *args, **kwargs):
        originals["__init__"](dialog, *args, **kwargs)
        if not getattr(dialog, "_v2_mode", False):
            return
        decorate(dialog)
        add_button = getattr(dialog, "add_attachment_catalog_button", None)
        if add_button is not None:
            add_button.setEnabled(False)
            add_button.setToolTip("正在检查V2附件新增接口…")
        dialog._v2_ready = False
        dialog._v2_timer = QTimer(dialog)
        dialog._v2_timer.setSingleShot(True)
        dialog._v2_timer.setInterval(PREVIEW_DELAY_MS)
        dialog._v2_timer.timeout.connect(lambda: preview(dialog))
        def changed(*_):
            dialog._v2_ready = False
            dialog._v2_timer.start()
        dialog.table.itemChanged.connect(changed)
        dialog.table.cellDoubleClicked.connect(lambda row, column: edit_parameters(dialog, row, column))
        dialog._v2_timer.start()

    def accept(dialog):
        if getattr(dialog, "_v2_mode", False) and not getattr(dialog, "_v2_ready", False) and checked(dialog):
            QMessageBox.information(dialog, "附件成本未完成", "请等待计算完成，并填写提示的人工尺寸或处理错误。")
            return
        return originals["accept_selection"](dialog)

    dialog_class.__init__, dialog_class.load_catalog, dialog_class.rebuild_table = init, load, rebuild
    dialog_class.collect_attachments, dialog_class.accept_selection = collect, accept
    item_changed = getattr(dialog_class, "table_item_changed", None)
    if item_changed is not None:
        def item_changed_v2(dialog, item):
            remembered = [(row, source.get("attachment_price_id"), source.get("selection_key"), {key: copy.deepcopy(source[key]) for key in ("manual_inputs", "selection_key") if key in source}) for row, _, source in checked(dialog)] if getattr(dialog, "_v2_mode", False) else []
            result = item_changed(dialog, item)
            blocked = dialog.table.blockSignals(True)
            try:
                for row, cell, source in checked(dialog):
                    candidates = [entry for entry in remembered if entry[1] == source.get("attachment_price_id")]
                    match = next((entry for entry in candidates if entry[2] and entry[2] == source.get("selection_key")), None)
                    match = match or next((entry for entry in candidates if entry[0] == row), None)
                    if match is None and len(candidates) == 1:
                        match = candidates[0]
                    if match:
                        cell.setData(Qt.ItemDataRole.UserRole, {**source, **match[3]})
            finally:
                dialog.table.blockSignals(blocked)
            return result
        dialog_class.table_item_changed = item_changed_v2
    refresh_browser = dialog_class.refresh_category_browser
    def refresh_browser_v2(dialog):
        result = refresh_browser(dialog)
        if getattr(dialog, "_v2_mode", False) and hasattr(dialog, "_v2_timer"):
            decorate(dialog)
            dialog._v2_ready = False
            dialog._v2_timer.start()
        return result
    dialog_class.refresh_category_browser = refresh_browser_v2

    # ApiWorker handles ordinary requests. The existing ganged worker keeps its
    # child-cabinet flow and commits one aggregate V2 attachment snapshot.
    worker_init = worker_class.__init__
    def init_worker(worker, url, payload, parent=None, *args, **kwargs):
        if str(url).endswith("/api/quotes/calculate-dual") and parent is not None and not ganged(parent) and (payload.get("attachment_contract") == 2 or any(row.get("catalog_version") for row in payload.get("attachments", []))):
            automatic_base = base_height(parent)
            payload = {**payload, "attachment_contract": 2, "attachments": [selected_input(x, automatic_base) for x in payload.get("attachments", [])]}
            parent._v2_request_quote_id = payload.get("quote_id")
            parent._v2_request_environment = json.dumps(environment(parent, payload["attachments"]), sort_keys=True)
        elif str(url).endswith("/api/quotes/calculate-dual") and parent is not None:
            parent._v2_request_environment = None
        worker_init(worker, url, payload, parent, *args, **kwargs)
    worker_class.__init__ = init_worker

    show = window_class.show_result
    def show_result(window, result, *args, **kwargs):
        if getattr(window, "_v2_request_environment", None) and result.get("attachment_contract") != 2:
            window.current_result = None
            window._attachment_v2_line_id = None
            window.risk_label.setText("当前API尚未返回附件V2结果，请更新API后重新计算。")
            return
        if result.get("attachment_contract") == 2 and getattr(window, "_v2_request_environment", None):
            automatic_base = base_height(window)
            latest = json.dumps(environment(window, [selected_input(x, automatic_base) for x in window.attachments]), sort_keys=True)
            if latest != window._v2_request_environment or result.get("quote_id") != window._v2_request_quote_id:
                return
        previous = getattr(window, "current_result", None)
        original_rows = getattr(window, "attachments", [])
        window._v2_render_rows = result.get("attachments") if result.get("attachment_contract") == 2 else None
        try:
            rendered = show(window, result, *args, **kwargs)
        finally:
            window._v2_render_rows = None
        if result.get("attachment_contract") == 2 and getattr(window, "current_result", None) is not previous:
            automatic_base = base_height(window)
            window.attachments = [merge_cost(original_rows[i] if i < len(original_rows) else {}, row, automatic_base) for i, row in enumerate(result.get("attachments", []))]
            window._attachment_v2_line_id = result.get("quote_line_id")
            window.update_attachment_view()
            window.refresh_discounted_totals()
        elif result.get("attachment_contract") == 2:
            window.attachments = original_rows
        return rendered
    window_class.show_result = show_result

    refresh = window_class.refresh_discounted_totals
    def refresh_v2(window):
        pending = getattr(window, "_v2_render_rows", None)
        if pending is not None:
            rows = window.attachments
            window.attachments, window._v2_render_rows = pending, None
            try:
                return refresh_v2(window)
            finally:
                window.attachments, window._v2_render_rows = rows, pending
        errors = [row for row in getattr(window, "attachments", []) if row.get("status") == "ERROR"]
        if errors and getattr(window, "current_result", None):
            window.current_result["formula"]["total_cost"] = None
            window.current_result["formula"]["attachment_fee"] = None
            for label in window.formula_labels.values():
                label.setText("—")
            window.formula_labels["attachment"].setText("附件成本错误")
            from quick_discount_rules import quick_discount_breakdown
            quick = window.current_result["quick"]
            value = quick_discount_breakdown(quick, window.attachments, window.quick_discount.value())["discounted_total"] if quick.get("total_cost") is not None else None
            window.quick_labels["total"].setText("—" if value is None else f"{value + window.freight_spin.value():,.2f}")
            window.quick_labels["attachment"].setText(str(quick.get("attachment_fee", "—")))
            return
        return refresh(window)
    window_class.refresh_discounted_totals = refresh_v2

    open_dialog = window_class.open_attachment_dialog
    def open_dialog_v2(window, *args, **kwargs):
        automatic_base = base_height(window)
        before = json.dumps([selected_input(x, automatic_base) for x in window.attachments], sort_keys=True)
        result = open_dialog(window, *args, **kwargs)
        if before != json.dumps([selected_input(x, automatic_base) for x in window.attachments], sort_keys=True):
            window._attachment_v2_line_id = None
            window.current_result = None
            for labels in (window.formula_labels, window.quick_labels):
                labels["total"].setText("—")
            window.risk_label.setText("附件选择已变化，请重新计算整柜报价。")
        return result
    window_class.open_attachment_dialog = open_dialog_v2

    add = window_class.add_current_to_summary
    def add_to_summary(window, *args, **kwargs):
        before = len(window.draft_items)
        line_id = getattr(window, "_attachment_v2_line_id", None)
        quote_date = window.quote_date.date().toString("yyyy-MM-dd")
        result = add(window, *args, **kwargs)
        if line_id and len(window.draft_items) == before + 1:
            window.draft_items[-1].update(attachment_contract=2, quote_line_id=line_id, quote_date=quote_date)
        return result
    window_class.add_current_to_summary = add_to_summary
    load_item, reset, update = window_class.load_draft_item, window_class.reset_current_cabinet, window_class.update_attachment_view
    def load_item_v2(window, item):
        window._attachment_v2_restoring = True
        try:
            if item.get("attachment_contract") == 2 and item.get("quote_date"):
                window.quote_date.setDate(QDate.fromString(item["quote_date"], "yyyy-MM-dd"))
            result = load_item(window, item)
            window._attachment_v2_line_id = item.get("quote_line_id")
            return result
        finally:
            window._attachment_v2_restoring = False
    def reset_v2(window, *args, **kwargs):
        window._attachment_v2_line_id = None
        return reset(window, *args, **kwargs)
    def update_v2(window):
        result = update(window)
        for i, item in enumerate(getattr(window, "attachments", [])):
            cell = window.attachment_list.item(i)
            if cell and item.get("status"):
                cell.setText(cell.text() + f" · 快速 {item.get('quick_amount', '—')} · 公式 {item.get('formula_amount') if item.get('formula_amount') is not None else item.get('status_text', '—')}")
                cell.setToolTip("辅材清单：\n" + str(item.get("auxiliary_list") or ""))
        return result
    window_class.load_draft_item, window_class.reset_current_cabinet, window_class.update_attachment_view = load_item_v2, reset_v2, update_v2

    window_init = window_class.__init__
    def init_window(window, *args, **kwargs):
        window_init(window, *args, **kwargs)
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.setInterval(PREVIEW_DELAY_MS)
        window._v2_environment_timer = timer
        def changed(*_):
            if getattr(window, "_attachment_v2_restoring", False) or not any(row.get("catalog_version") for row in getattr(window, "attachments", [])):
                return
            window._attachment_v2_line_id = None
            window.current_result = None
            window.risk_label.setText("附件环境已变化，正在重新计算成本；整柜报价请重新计算。")
            for labels in (window.formula_labels, window.quick_labels):
                labels["total"].setText("—")
            timer.start()
        def recalculate():
            rows = getattr(window, "attachments", [])
            if not any(row.get("catalog_version") for row in rows):
                return
            old = getattr(window, "_v2_environment_worker", None)
            if old and old.isRunning():
                timer.start()
                return
            automatic_base = base_height(window)
            payload = environment(window, [selected_input(x, automatic_base) for x in rows])
            signature = json.dumps(payload, sort_keys=True)
            worker = worker_class(window.base_url() + "/api/attachments/preview", payload, window)
            window._v2_environment_worker = worker
            def received(body):
                if not isValid(window):
                    return
                now = environment(window, [selected_input(x, base_height(window)) for x in window.attachments])
                if json.dumps(now, sort_keys=True) != signature:
                    return
                window.attachments = [merge_cost(rows[i], cost, base_height(window)) for i, cost in enumerate(body.get("attachments", []))]
                window.update_attachment_view()
                window.risk_label.setText("；".join(x.get("error", "") for x in body.get("errors", [])) or "附件成本已更新；请重新计算整柜报价。")
            worker.succeeded.connect(received)
            worker.failed.connect(lambda text: window.risk_label.setText(f"附件重新计算失败：{text}") if isValid(window) else None)
            def finished():
                if isValid(window) and getattr(window, "_v2_environment_worker", None) is worker:
                    window._v2_environment_worker = None
                worker.deleteLater()
            worker.finished.connect(finished)
            worker.start()
        timer.timeout.connect(recalculate)
        for name, signal in (("product_combo", "currentIndexChanged"), ("variant_combo", "currentIndexChanged"), ("single_door_combo", "currentIndexChanged"), ("double_door_combo", "currentIndexChanged"), ("material_combo", "currentIndexChanged"), ("coating_combo", "currentIndexChanged"), ("width_spin", "valueChanged"), ("height_spin", "valueChanged"), ("depth_spin", "valueChanged"), ("quote_date", "dateChanged"), ("model_edit", "textChanged")):
            control = getattr(window, name, None)
            if control is not None:
                getattr(control, signal).connect(changed)
    window_class.__init__ = init_window
