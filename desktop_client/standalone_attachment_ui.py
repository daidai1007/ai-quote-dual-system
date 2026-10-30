"""Reuse the name picker and existing attachment/parameter window shells."""
from copy import deepcopy
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QLabel, QMessageBox
from standalone_attachment import new_item, request, update_item, ready, is_standalone


def open_picker(window):
    import scheme2_ui as ui
    if (ui._received_cost_view(window) or getattr(window, '_quote_scheme_read_only', False)
            or getattr(window, '_name_scope_foreign', False) or getattr(window, '_scheme2_document_busy', False)):
        return
    current = getattr(window, '_standalone_name_picker', None)
    if current is not None:
        current.raise_()
        return
    dialog = ui._SchemeAttachmentDialog([], 'standalone_attachment', window)
    dialog.resize(min(660, window.width() - 40), min(720, window.height() - 60))
    dialog.setModal(True)
    window._standalone_name_picker = dialog

    def accepted():
        selections = dialog.collect_attachments()
        if not selections:
            return
        settings = {key:control.value() for key,control in window.scheme2_cost_controls.items()}
        additions = [new_item(source, settings) for source in selections]
        tokens = [item['standalone_reprice_token'] for item in additions]
        window.draft_items.extend(additions)
        ui._set_dirty(window, True)
        window.refresh_summary()
        window.summary_table.selectRow(len(window.draft_items) - len(additions))
        def loaded(rows):
            if len(rows) != len(additions):
                failed('附件服务返回数量不完整，请重新读取')
                return
            for item, row, token in zip(additions, rows, tokens):
                if any(current is item for current in window.draft_items) and item.get('standalone_reprice_token') == token:
                    update_item(item, row)
            window.refresh_summary()
        def failed(message):
            changed = False
            for item, token in zip(additions, tokens):
                if any(current is item for current in window.draft_items) and item.get('standalone_reprice_token') == token:
                    changed = True
                    item['standalone_error'] = str(message)
                    item['attachments'][0]['pending_manual_dimensions'] = ['重新读取附件规格']
            window.refresh_summary()
            if changed:
                QMessageBox.warning(window, '独立附件读取失败', str(message))
        request(window, [item['attachments'][0] for item in additions], loaded, failed)
    def finished():
        window._standalone_name_picker = None
        dialog.deleteLater()
    dialog.accepted.connect(accepted)
    dialog.finished.connect(finished)
    dialog.show()


def edit_parameters(editor, row):
    import scheme2_ui as ui
    cell = editor.table.item(row, editor.COL_NAME)
    source = deepcopy(cell.data(ui.ROLE_ROW) or {})
    if row in getattr(editor, '_pending_reprices', {}):
        return
    pending = source.get('pending_manual_dimensions') or []
    if pending in (['读取附件规格'], ['重新读取附件规格'], ['重新计算']):
        editor._reprice_row(row, source)
        return
    choices = source.get('standalone_parameter_choices') or {}
    names = list(pending)
    for parameter in source.get('required_parameters') or []:
        if parameter['name'] not in names and parameter['name'] not in ('材质密度','材质单价','喷塑单价'):
            names.append(parameter['name'])
    for name in choices:
        if name not in names:
            names.insert(0, name)
    if not names:
        return
    manual = deepcopy(source.get('manual_inputs') or {})
    if source.get('custom'):
        for name, key in {'成本单价':'formula_unit_cost_override','面价单价':'unit_price_override'}.items():
            if source.get(key) is not None:
                manual[name] = source[key]
    own = source.get('standalone_environment') or source.get('environment') or {}
    for name, key in {'宽度':'width_mm','高度':'height_mm','深度':'depth_mm','材质密度':'density_g_cm3',
                      '材质单价':'material_unit_price','喷塑单价':'spray_unit_price'}.items():
        if name not in manual and own.get(key) is not None:
            manual[name] = own[key]

    class Parameters(ui._SchemeDimensionEditor):
        def __init__(self):
            super().__init__(editor, f"{source.get('item_name', '附件')} · 独立附件参数", names, manual)
            form = self.findChild(QFormLayout)
            self.combo_values = {}
            selected = {'目录规格':source.get('attachment_price_id'), '适用柜型':source.get('standalone_rule_id'),
                        '材质':source.get('standalone_material_code')}
            for name, values in choices.items():
                field = self.fields[name]
                combo = QComboBox()
                combo.setObjectName('scheme2AttachmentModelCombo')
                combo.addItem('请选择', '')
                for option in values:
                    combo.addItem(option['label'], str(option['value']))
                combo.setCurrentIndex(max(0, combo.findData(str(selected.get(name) or ''))))
                form.replaceWidget(field, combo)
                field.hide()
                field.deleteLater()
                self.fields[name] = combo
                combo.currentIndexChanged.connect(self._refresh_validity)
            units = {'材质密度':'g/cm³', '材质单价':'元/kg', '喷塑单价':'元/㎡', '成本单价':'元', '面价单价':'元'}
            for name, field in self.fields.items():
                if isinstance(field, QComboBox):
                    continue
                field.setPlaceholderText('请输入'+units.get(name, 'mm'))
                if name in manual:
                    field.setText(str(manual[name]))
                label = form.labelForField(field)
                if label:
                    label.setText(name+'（'+units.get(name, 'mm')+'）')
            self.findChild(QLabel, 'scheme2DimensionHint').setText('尺寸以本次输入为准；材料及喷塑单价取“修改系数”')
            self._refresh_validity()

        def _refresh_validity(self):
            try:
                valid = bool(self.fields) and all(
                    bool(field.currentData()) if isinstance(field, QComboBox)
                    else (math.isfinite(float(field.text())) and
                          (float(field.text()) >= 0 if name in ('喷塑单价','成本单价','面价单价') else float(field.text()) > 0))
                    for name, field in self.fields.items())
            except ValueError:
                valid = False
            self.confirm_button.setEnabled(valid)

        def values(self):
            return {name: field.currentData() if isinstance(field, QComboBox) else float(field.text())
                    for name, field in self.fields.items()}

    dialog = Parameters()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    values = dialog.values()
    for name, key in {'目录规格':'attachment_price_id','适用柜型':'standalone_rule_id','材质':'standalone_material_code'}.items():
        if name in values:
            source[key] = values.pop(name)
    source['manual_inputs'] = {**manual, **values}
    if source.get('custom'):
        if '成本单价' in values:
            source.update(formula_unit_cost_override=values['成本单价'],custom_cost_edited=True)
        if '面价单价' in values:
            source.update(unit_price_override=values['面价单价'],custom_amount_edited=True)
    cell.setData(ui.ROLE_ROW, source)
    editor._reprice_row(row, source)
