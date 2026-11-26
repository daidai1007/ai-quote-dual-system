"""Explicit, transactional recovery of missing attachment costs in a draft."""
from copy import deepcopy
import math

RECOVERY_FORM_MAX_HEIGHT = 360
RECOVERY_DIALOG_RESERVED_HEIGHT = 240


def reconcile_ganged_rounding(item):
    """Repair legacy cent drift only when saved base and unchanged children agree."""
    from quick_discount_rules import money, money_sum
    formula, base = item.get('formula') or {}, item.get('formula_base') or {}
    children, originals = formula.get('ganged_cabinet_costs'), base.get('ganged_cabinet_costs')
    if not isinstance(children, list) or not isinstance(originals, list) or len(children) < 2 or len(children) != len(originals):
        return False
    changed = False
    for key in ('material_cost', 'auxiliary_cost', 'labor_cost', 'spray_cost'):
        if key in (item.get('scheme2_cost_bases') or {}):
            continue
        try:
            current, saved = formula[key], base[key]
            if any(isinstance(v, bool) or not math.isfinite(float(v)) or float(v) < 0 for v in (current, saved)):
                continue
            values = []
            for child, original in zip(children, originals):
                value, previous = child['formula_cost'][key], original['formula_cost'][key]
                if child.get('scheme2_coefficient_state') or isinstance(value, bool) or isinstance(previous, bool):
                    raise ValueError('Adjusted or invalid child')
                if not math.isfinite(float(value)) or float(value) < 0 or float(value) != float(previous):
                    raise ValueError('Changed child')
                values.append(value)
            expected = money_sum(values)
            cents = round(money(current) * 100) - round(expected * 100)
            if money(saved) == expected and abs(cents) == 1:
                formula[key] = expected
                changed = True
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    if changed:
        item.pop('cost_detail_rows', None)
    return changed


def _positive(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError, OverflowError):
        return False


def pending_rows(item):
    from attachment_v2_client import missing_manual_dimensions
    from attachment_cost_allocation import COST_PARTS, is_formula_cost, finite
    result = []
    for index, row in enumerate(item.get('attachments') or []):
        if not isinstance(row, dict) or row.get('custom') or row.get('status') == 'QUICK_ONLY':
            continue
        missing = list(dict.fromkeys([*(row.get('pending_manual_dimensions') or []),
                                      *missing_manual_dimensions(row)]))
        incomplete = is_formula_cost(row) and any(not finite(row.get(key)) for key in COST_PARTS)
        if missing or row.get('status') in ('ERROR', 'PENDING_MANUAL') or incomplete:
            result.append((index, row, missing))
    return result


def _geometry(item, row):
    children = item.get('ganged_cabinets') or []
    index = row.get('ganged_cabinet_index', row.get('ganged_fixed_base_index'))
    target = children[index] if isinstance(index, int) and 0 <= index < len(children) else item
    values = tuple(target.get(key) for key in ('width_mm', 'height_mm', 'depth_mm'))
    return tuple(float(value) for value in values) if all(_positive(v) for v in values) else None


def suggested_dimension(items, target_item, source, name):
    current = (source.get('manual_inputs') or {}).get(name)
    if _positive(current):
        return float(current)
    geometry = _geometry(target_item, source)
    if geometry is None:
        return None
    child = source.get('ganged_cabinet_index', source.get('ganged_fixed_base_index'))
    candidates = set()
    for item in items:
        if item.get('product_code') != target_item.get('product_code'):
            continue
        for donor in item.get('attachments') or []:
            if not isinstance(donor, dict) or donor.get('item_name') != source.get('item_name'):
                continue
            if donor.get('ganged_cabinet_index', donor.get('ganged_fixed_base_index')) != child:
                continue
            if _geometry(item, donor) != geometry:
                continue
            value = (donor.get('manual_inputs') or {}).get(name)
            if _positive(value):
                candidates.add(float(value))
    # A reference is offered for explicit confirmation; never silently applied.
    return candidates.pop() if len(candidates) == 1 else None


def _keep_sale(source, calculated):
    """The operator repairs cost only and explicitly keeps current sale amounts."""
    from quick_discount_rules import quick_attachment_line_amount, money
    from scheme2_ui import _popup_quick_amount
    result = deepcopy(calculated)
    amount = money(_popup_quick_amount(source))
    result.update(quick_amount=amount, quick_amount_override=amount, custom_amount_edited=True,
                  cost_recovery_preserve_sale=True)
    quantity = float(result.get('quantity', 1))
    if quantity:
        result['unit_price_override'] = abs(amount / quantity)
    assert money(quick_attachment_line_amount(result)) == amount
    return result


def sync_action(window):
    import scheme2_ui as ui
    button = getattr(window, 'scheme2_cost_recover', None)
    if button is None:
        return
    item = ui._selected_item(window)
    busy = getattr(window, '_scheme2_cost_recovery', None) is not None
    visible = not ui._received_cost_view(window) and isinstance(item, dict) and bool(pending_rows(item))
    button.setVisible(visible or busy)
    button.setText('正在核算…' if busy else '补齐成本')
    button.setEnabled(visible and not busy and not ui._quote_remark_readonly(window)
                      and not getattr(window, '_scheme2_document_busy', False))


def dimension_dialog(window, fields, initial):
    import scheme2_ui as ui
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QFrame, QScrollArea, QWidget
    dialog = ui._SchemeDimensionEditor(window, '补齐成本尺寸', fields, initial)
    hint = next((label for label in dialog.findChildren(QLabel)
                 if label.objectName() == 'scheme2DimensionHint'), None)
    if hint is not None:
        hint.setWordWrap(True)
        hint.setText('参考尺寸来自当前清单的相同子柜，请核对。\n仅重算成本，现有面价、报价和折扣保持不变。')
    if len(fields) > 8:
        shell = dialog.findChild(QFrame, 'scheme2DimensionShell')
        layout = shell.layout()
        form = layout.takeAt(1).layout()
        form.setParent(None)
        content = QWidget()
        content.setLayout(form)
        scroll = QScrollArea()
        scroll.setObjectName('scheme2RecoveryDimensionScroll')
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        scroll.setFixedHeight(min(RECOVERY_FORM_MAX_HEIGHT,
                                  max(100, window.height() - RECOVERY_DIALOG_RESERVED_HEIGHT)))
        layout.insertWidget(1, scroll)
    return dialog


def recover_selected(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QMessageBox
    from shiboken6 import isValid
    from name_login import identity_epoch
    import scheme2_ui as ui
    if (ui._received_cost_view(window) or ui._quote_remark_readonly(window)
            or getattr(window, '_scheme2_document_busy', False)
            or getattr(window, '_scheme2_cost_recovery', None) is not None):
        return
    item = ui._selected_item(window)
    pending = pending_rows(item) if isinstance(item, dict) else []
    if not pending:
        return
    mapping, initial = {}, {}
    for index, source, names in pending:
        child = source.get('ganged_cabinet_index', source.get('ganged_fixed_base_index'))
        for name in names:
            field = f'柜体{child + 1} · {name}' if isinstance(child, int) else str(name)
            if field in mapping:
                field = f'{field}（附件{index + 1}）'
            mapping[field] = (index, name)
            initial[field] = suggested_dimension(window.draft_items, item, source, name)
    original = deepcopy(item)
    if mapping:
        dialog = dimension_dialog(window, list(mapping), initial)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        entered = dialog.values()
        if not all(_positive(entered.get(field)) for field in mapping):
            return
    else:
        if QMessageBox.question(window, '重新核算成本', '仅重新核算所选行缺失的附件成本，现有报价和折扣保持不变。是否继续？',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        entered = {}
    if item != original:
        return
    working = deepcopy(original)
    for field, (index, name) in mapping.items():
        row = working['attachments'][index]
        row['manual_inputs'] = {**(row.get('manual_inputs') or {}), name: entered[field]}
    reprice = getattr(window, 'recalculate_draft_attachment', None)
    if not callable(reprice):
        QMessageBox.warning(window, '成本未恢复', '附件成本核算功能不可用，请重新启动客户端。')
        return
    epoch, job = identity_epoch(), object()
    window._scheme2_cost_recovery = job
    sync_action(window)
    controller = getattr(window, '_scheme2_document_controller', None)
    if controller is not None:
        controller.sync_buttons()
    position = 0

    def current():
        return (isValid(window) and getattr(window, '_scheme2_cost_recovery', None) is job
                and identity_epoch() == epoch and not ui._quote_remark_readonly(window)
                and any(row is item for row in getattr(window, 'draft_items', [])) and item == original)

    def finish(message=None):
        if isValid(window) and getattr(window, '_scheme2_cost_recovery', None) is job:
            window._scheme2_cost_recovery = None
            sync_action(window)
            if controller is not None:
                controller.sync_buttons()
            if message:
                QMessageBox.warning(window, '成本未恢复', message + '\n原报价及附件数据已保留，可重试。')

    def next_row():
        nonlocal position
        if not current():
            finish()
            return
        if position == len(pending):
            working.pop('quote_display', None)
            working.pop('cost_detail_rows', None)
            working['attachment_snapshot_dirty'] = True
            try:
                from freight_state import sync_item_freight
                from quick_discount_rules import quick_freight_fee, QUICK_FREIGHT_BASIS
                saved_sale_freight = quick_freight_fee(original)
                sync_item_freight(working)
                if quick_freight_fee(working) != saved_sale_freight:
                    working.update(quick_freight_basis=QUICK_FREIGHT_BASIS,
                                   quick_freight_mode='MANUAL', quick_freight_fee=saved_sale_freight)
                ui._recalculate_item_management(working)
            except (ValueError, TypeError, KeyError) as error:
                finish(str(error))
                return
            allocation = ui._formula(working).get('cost_allocation') or {}
            if not allocation.get('complete'):
                finish('；'.join(allocation.get('errors') or ['附件成本分项仍不完整']))
                return
            if ui._row_values(working)[15:17] != ui._row_values(deepcopy(original))[15:17]:
                finish('核算结果改变了现有报价，已停止应用。')
                return
            item.clear()
            item.update(working)
            finish()
            window.refresh_summary()
            ui._set_dirty(window, True)
            return
        index = pending[position][0]
        source = deepcopy(working['attachments'][index])
        expected = position
        def succeeded(calculated):
            nonlocal position
            if not current():
                finish()
                return
            if position != expected:
                return
            if calculated.get('status') in ('ERROR', 'PENDING_MANUAL') or calculated.get('pending_manual_dimensions'):
                finish(str(calculated.get('error') or '附件成本尚未算出'))
                return
            try:
                working['attachments'][index] = _keep_sale(original['attachments'][index], calculated)
            except (ValueError, TypeError, KeyError, AssertionError) as error:
                finish(str(error) or '无法保留现有附件面价')
                return
            position += 1
            QTimer.singleShot(0, next_row)
        def failed(message):
            if current():
                finish(str(message))
            else:
                finish()
        try:
            reprice(working, source, succeeded, failed)
        except Exception as error:
            failed(str(error))
    next_row()
