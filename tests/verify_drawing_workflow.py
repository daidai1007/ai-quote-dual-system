"""Offline Qt integration tests. No online quote records are created."""
import copy
import hashlib
import os
from pathlib import Path
import sys
import time
import unittest
from decimal import Decimal
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QPdfWriter, QTabletEvent, QPointingDevice, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
import v3_launcher
import drawing_workflow as workflow
from freight_state import FreightState, billable_weight
from quote_drawing_preview import resolve_document

OUT = ROOT / 'outputs' / 'drawing-workflow-20260915'
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
ns['MainWindow'].load_catalogs = lambda self: None
# Any accidental API use fails closed instead of reaching production.
ns['ApiWorker'].run = lambda self: self.failed.emit('offline test transport')
ns['install_application_font'](app)
QMessageBox.warning = lambda *a, **k: QMessageBox.StandardButton.Ok
QMessageBox.information = lambda *a, **k: QMessageBox.StandardButton.Ok
QMessageBox.critical = lambda *a, **k: QMessageBox.StandardButton.Ok


def pump(predicate=lambda: True, seconds=12):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(15)
    raise AssertionError('Timed out waiting for Qt operation')


def fixture_files():
    image = QImage(1000, 800, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.black)
    painter.drawRect(150, 100, 450, 550)
    painter.drawLine(375, 100, 375, 650)
    painter.drawText(180, 60, 'QA CABINET 600 x 300 x 1800')
    painter.end()
    for suffix in ('png', 'jpg', 'jpeg'):
        assert image.save(str(OUT / f'fixture.{suffix}'))
    pdf = QPdfWriter(str(OUT / 'fixture.pdf'))
    pdf.setResolution(96)
    painter = QPainter(pdf)
    painter.drawImage(0, 0, image)
    pdf.newPage()
    painter.drawText(100, 100, 'SECOND PAGE')
    painter.drawRect(100, 150, 600, 500)
    painter.end()
    import ezdxf
    doc = ezdxf.new()
    model = doc.modelspace()
    model.add_lwpolyline([(0, 0), (600, 0), (600, 1800), (0, 1800)], close=True)
    model.add_line((300, 0), (300, 1800))
    model.add_circle((280, 900), 12)
    model.add_text('QA CABINET', dxfattribs={'height': 40, 'insert': (0, 1850)})
    doc.saveas(OUT / 'fixture.dxf')


def candidate(suffix='pdf', name='柜体 A', key='candidate-a'):
    return {'candidate_id': key, 'name': name, 'source_path': str(OUT / f'fixture.{suffix}'),
            'path': str(OUT / f'fixture.{suffix}'), 'source_document_name': f'fixture.{suffix}',
            'classification': 'cabinet', 'specification': '600*300*1800',
            'dimensions': [(600, 1800, 300)], 'review_status': 'confirmed',
            'manual_reviewed': True, 'manual_confirmation_checked': True,
            'manual_reviewed_at': '2026-09-15T12:00:00',
            'remark_review_required': False, 'reviewed_remark': '前单开门', 'raw_text': ''}


def response(weight=66.1):
    return {'quote_id': 'offline-fixture', 'formula_cost': {
        'material_cost': 100, 'auxiliary_cost': 10, 'labor_cost': 20, 'spray_cost': 30,
        'management_fee': 2.6, 'attachment_fee': 0, 'total_cost': 162.6,
        'product_area_m2': 4, 'corrected_material_weight_kg': weight,
        'net_material_weight_kg': 55.08333333},
        'quick_quote': {'base_price': 200, 'attachment_fee': 0, 'total_cost': 200,
                        'matched_experience': {}, 'match_method': 'exact'}, 'risk_flags': []}


class DrawingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_files()

    def setUp(self):
        self.w = ns['MainWindow']()
        self.w.resize(1519, 987)
        self.w.show()
        self.w.show_section(1)
        self.w.refresh_formula_inputs = lambda: None
        self.w.request_history_match = lambda *a: None
        self.w._history_price_timer.stop()
        self.w._formula_template_debounce_timer.stop()
        pump()

    def tearDown(self):
        pump(lambda: not self.w.quote_drawing_preview._workers)
        self.w.close()
        app.processEvents()

    def bind(self, item):
        self.w.recognized_drawings = [item]
        self.w.recognized_documents = [item]
        self.w.active_drawing = item
        self.w.use_selected_drawing()
        p = self.w.quote_drawing_preview
        pump(lambda: not p._workers)
        return p

    def accept(self, payload):
        self.w.pending_quote_signature = self.w.quote_input_signature()
        self.w.show_result(payload)
        pump()

    def stroke(self, preview):
        c = preview.canvas
        c.set_ink(True)
        point = c.mapFromScene(QPointF(400, 500))
        QTest.mousePress(c.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(c.viewport(), point + QPoint(60, 30))
        QTest.mouseRelease(c.viewport(), Qt.MouseButton.LeftButton, pos=point + QPoint(90, 60))
        self.assertEqual(len(c.strokes), 1)

    def test_navigation_and_shared_candidate(self):
        self.assertEqual([b.text() for b in self.w.nav_buttons], ['图纸识别', '柜体汇总', '报价计算', '报价清单'])
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        self.assertFalse(self.w.formula_box.isVisible())
        self.assertFalse(self.w.history_price_card.isVisible())
        preview = self.w.quote_drawing_preview
        self.assertEqual(preview.back.text(), '返回图纸识别')
        self.assertEqual(preview.back_to_quote.text(), '返回报价计算')
        self.assertGreater(preview.back_to_quote.geometry().left(), preview.back.geometry().left())
        preview.back_to_quote.click()
        app.processEvents()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 1)
        self.assertIsNone(self.w.current_result)
        self.assertEqual(self.w.return_to_drawing_button.text(), '返回当前柜体图纸')
        self.assertTrue(self.w.return_to_drawing_button.isVisible())
        state = self.w.quote_result_state
        self.assertTrue(state.wordWrap())
        self.assertEqual(state.parentWidget().layout().indexOf(state), 1)
        state.setText('双报价计算失败：dual_quote_failure_with_a_long_service_message')
        self.w.resize(1100, 800)
        app.processEvents()
        self.assertGreaterEqual(
            state.mapTo(self.w, QPoint(0, 0)).y(),
            self.w.return_to_drawing_button.mapTo(
                self.w, QPoint(0, self.w.return_to_drawing_button.height())
            ).y(),
        )
        self.assertGreater(state.width(), self.w.return_to_drawing_button.width())
        self.w.return_to_drawing_button.click()
        app.processEvents()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        self.w.calculate_button.setEnabled(True)
        self.w.calculate_button.click()
        app.processEvents()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 1)
        self.assertIsNone(self.w.current_result)
        self.w.return_to_drawing_button.click()
        app.processEvents()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        item = candidate('png')
        item['quantity'] = 3
        self.w.recognized_drawings = [item]
        self.w.show_section(workflow.CABINET_SUMMARY_ROUTE)
        self.assertEqual(self.w.cabinet_summary_table.rowCount(), 1)
        self.assertEqual(self.w.cabinet_summary_table.horizontalHeaderItem(3).text(), '数量')
        self.assertEqual(self.w.cabinet_summary_table.item(0, 3).text(), '3')
        self.w.cabinet_summary_table.selectRow(0)
        workflow.open_cabinet(self.w, True)
        pump(lambda: not self.w.quote_drawing_preview._workers)
        self.assertIs(self.w._quote_drawing, item)
        self.assertEqual(self.w.quantity_spin.value(), 3)
        self.w.quantity_spin.setValue(4)
        self.w.show_section(workflow.CABINET_SUMMARY_ROUTE)
        self.assertEqual(self.w.cabinet_summary_table.item(0, 3).text(), '4')
        self.assertEqual(item['quantity'], 4)
        self.w.model_edit.setText('人工填写保持')
        for route in (0, 4, 3, 1):
            self.w.show_section(route)
        self.assertEqual(self.w.model_edit.text(), '人工填写保持')
        self.assertIs(self.w.active_drawing, item)
        self.w.show_section(4)

    def test_cabinet_summary_drag_reorders_shared_candidates(self):
        first = candidate('png', name='柜体一', key='candidate-one')
        second = candidate('jpg', name='柜体二', key='candidate-two')
        third = candidate('jpeg', name='柜体三', key='candidate-three')
        first['quantity'], second['quantity'], third['quantity'] = 2, 3, 4
        self.w.recognized_drawings = [first, second, third]
        self.w.recognized_documents = [first, second, third]
        self.w.active_drawing = first
        self.w._quote_drawing = second
        self.w.show_section(workflow.CABINET_SUMMARY_ROUTE)
        table = self.w.cabinet_summary_table
        self.assertEqual(table.dragDropMode(), table.DragDropMode.InternalMove)
        self.assertTrue(table.dragEnabled())
        self.assertTrue(table.acceptDrops())
        self.assertEqual([table.item(row, 1).text() for row in range(3)], ['柜体一', '柜体二', '柜体三'])

        drop_point = QPoint()

        class TestDrag:
            def __init__(drag_self, source):
                drag_self.source = source

            def setMimeData(drag_self, mime_data):
                drag_self.mime_data = mime_data

            def exec(drag_self, *_args):
                position = Mock()
                position.toPoint.return_value = drop_point
                event = Mock()
                event.position.return_value = position
                drag_self.source.dropEvent(event)
                event.acceptProposedAction.assert_called_once()
                return Qt.DropAction.MoveAction

        real_drag = workflow.QDrag
        workflow.QDrag = TestDrag
        try:
            def drag_row(source, target, lower_half=False):
                nonlocal drop_point
                table.selectRow(source)
                rect = table.visualRect(table.model().index(target, 0))
                y = rect.bottom() - 1 if lower_half else rect.top() + 1
                drop_point = QPoint(rect.center().x(), y)
                table.startDrag(Qt.DropAction.MoveAction)
                app.processEvents()
                self.assertEqual(table.rowCount(), 3)
                self.assertTrue(all(table.item(row, column) is not None
                                    for row in range(3) for column in range(6)))

            # First to last, last to first, and a same-position drop must all
            # retain every visible row and every shared candidate.
            drag_row(0, 2, lower_half=True)
            self.assertEqual(self.w.recognized_drawings, [second, third, first])
            drag_row(2, 0)
            self.assertEqual(self.w.recognized_drawings, [first, second, third])
            drag_row(1, 1)
            self.assertEqual(self.w.recognized_drawings, [first, second, third])
        finally:
            workflow.QDrag = real_drag

        self.assertEqual([table.item(row, 0).text() for row in range(3)], ['1', '2', '3'])
        self.assertEqual([table.item(row, 1).text() for row in range(3)], ['柜体一', '柜体二', '柜体三'])
        self.assertEqual([table.item(row, 3).text() for row in range(3)], ['2', '3', '4'])
        self.assertEqual(table.currentRow(), 1)
        self.assertIs(self.w.active_drawing, first)
        self.assertIs(self.w._quote_drawing, second)

    def test_attachment_categories_are_vertical_and_show_category_with_name(self):
        dialog_class = ns['AttachmentDialog']
        original_load = dialog_class.load_catalog
        dialog_class.load_catalog = lambda dialog, _url: setattr(dialog, '_v2_mode', True)
        try:
            dialog = dialog_class([], api_url='http://127.0.0.1:1', parent=self.w,
                                  target_dimensions=(600, 1800, 300))
        finally:
            dialog_class.load_catalog = original_load
        dialog._v2_timer.stop()
        desired = ('侧板', '安装板', '安装附件', '底座', '灯开关',
                   '资料盒', '风机', '滤网', '门变形', '并柜件')
        dialog.catalog = [
            {'attachment_price_id': index, 'category_level1': category,
             'item_name': f'{category}名称', 'display_name': f'{category}\n{category}名称',
             'price': index, 'unit': '件'}
            for index, category in enumerate(reversed(desired), 1)
        ] + [{'attachment_price_id': 100, 'category_level1': '历史分类',
              'item_name': '保留附件', 'display_name': '保留附件', 'price': 1, 'unit': '件'}]
        dialog.rebuild_table()
        dialog.refresh_category_browser()
        dialog._v2_timer.stop()
        dialog.show()
        app.processEvents()
        expected_width, expected_height = workflow_target = (
            min(1120, dialog.screen().availableGeometry().width() - 32),
            min(820, dialog.screen().availableGeometry().height() - 32),
        )
        self.assertEqual((dialog.width(), dialog.height()), workflow_target)
        self.assertGreaterEqual(expected_width, dialog.minimumWidth())
        self.assertGreaterEqual(expected_height, dialog.minimumHeight())
        buttons = [button for button in dialog.findChildren(QPushButton, 'attachmentCategoryCard')
                   if button.isVisible()]
        values = [button.property('attachmentCategoryValue') for button in buttons]
        self.assertEqual(values[:len(desired)], list(desired))
        self.assertEqual(values[-1], '历史分类')
        self.assertTrue(all('一级分类：' in button.text() and '名称：' in button.text()
                            for button in buttons))
        positions = [dialog.category_grid.getItemPosition(
            dialog.category_grid.indexOf(button.parentWidget()))[:2] for button in buttons]
        self.assertEqual(positions, [(index, 0) for index in range(len(buttons))])
        selection_buttons = [
            button for button in dialog.findChildren(QPushButton)
            if button.isVisible()
            and button.property('attachmentSelectionLayout') == 'horizontal'
        ]
        self.assertTrue(selection_buttons)
        self.assertTrue(all('\n' not in button.text() for button in selection_buttons))
        self.assertTrue(all(button.maximumHeight() <= 46 for button in selection_buttons))
        first_selection = selection_buttons[0]
        first_card_button = next(
            button for button in buttons
            if button.parentWidget() is first_selection.parentWidget().parentWidget()
        )
        card_button_right = first_card_button.mapTo(
            dialog, QPoint(first_card_button.width(), 0)
        ).x()
        selection_left = first_selection.mapTo(dialog, QPoint(0, 0)).x()
        self.assertGreaterEqual(selection_left, card_button_right)
        self.assertEqual(first_selection.parentWidget().objectName(), 'attachmentSelectionPane')

        target = buttons[0]
        target.click()
        app.processEvents()
        visible_row = next(row for row in range(dialog.table.rowCount())
                           if not dialog.table.isRowHidden(row))
        cell = dialog.table.cellWidget(visible_row, dialog.COL_NAME)
        self.assertIsNotNone(cell)
        self.assertEqual(cell.findChild(QLabel, 'attachmentPrimaryCategoryCell').text(), '一级分类：侧板')
        self.assertEqual(cell.findChild(QLabel, 'attachmentItemNameCell').text(), '名称：侧板名称')
        self.assertEqual(dialog.table.item(visible_row, dialog.COL_NAME).text(), '')
        self.assertEqual(dialog.table.horizontalHeaderItem(dialog.COL_NAME).text(), '一级分类 / 名称')
        self.assertGreaterEqual(dialog.table.rowHeight(visible_row), 64)
        category_label = cell.findChild(QLabel, 'attachmentPrimaryCategoryCell')
        name_label = cell.findChild(QLabel, 'attachmentItemNameCell')
        self.assertLess(category_label.geometry().bottom(), name_label.geometry().top())

        self.w.quantity_spin.setValue(2)
        self.w._attachment_image_catalog = [{
            'item_name': '照明灯/行程开关', 'match_mode': 'EXACT',
            'images': [{
                'image_order': 1, 'mime_type': 'image/png', 'image_sha256': 'a' * 64,
                'data_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
            }],
        }]
        self.w.attachments = [{
            'category_level1': '灯开关', 'item_name': '照明灯/行程开关',
            'model_code': '通用', 'quantity': 1, 'matched_price': 50,
            'quick_amount': 50, 'formula_unit_cost': 27.56, 'formula_amount': 27.56,
        }]
        self.w.update_attachment_view()
        summary = self.w.attachment_summary_table
        self.assertEqual(summary.horizontalHeaderItem(0).text(), '图片')
        self.assertEqual(summary.horizontalHeaderItem(1).text(), '一级分类')
        self.assertEqual(summary.horizontalHeaderItem(2).text(), '名称')
        self.assertEqual(summary.rowCount(), 1)
        self.assertIsNotNone(summary.cellWidget(0, 0))
        self.assertEqual(summary.item(0, 1).text(), '灯开关')
        self.assertEqual(summary.item(0, 2).text(), '照明灯/行程开关')
        self.assertEqual(summary.horizontalHeaderItem(4).text(), '数量')
        self.assertEqual(summary.horizontalHeaderItem(5).text(), '快速金额')
        self.assertEqual(summary.item(0, 4).text(), '1')
        self.assertEqual(summary.item(0, 5).text(), '50.00')
        self.assertEqual(summary.item(0, 6).text(), '27.56')
        self.assertEqual(summary.item(0, 4).background().color().name(), '#eaf3fa')
        self.assertEqual(summary.item(0, 5).background().color().name(), '#eaf3fa')
        summary.item(0, 4).setText('2')
        app.processEvents()
        self.assertEqual(self.w.attachments[0]['quantity'], 2)
        self.assertEqual(self.w.attachments[0]['quick_amount'], 100.0)
        self.assertEqual(self.w.attachments[0]['formula_amount'], 55.12)
        self.assertEqual(summary.item(0, 5).text(), '100.00')
        self.assertEqual(summary.item(0, 6).text(), '55.12')
        summary.item(0, 5).setText('65.50')
        app.processEvents()
        self.assertEqual(self.w.attachments[0]['quick_amount_override'], 65.5)
        self.assertEqual(self.w.attachments[0]['quick_amount'], 65.5)
        self.assertEqual(self.w.attachments[0]['formula_amount'], 55.12)
        self.assertEqual(summary.item(0, 5).text(), '65.50')
        self.assertEqual(summary.item(0, 6).text(), '55.12')
        summary.item(0, 4).setText('3')
        app.processEvents()
        self.assertEqual(self.w.attachments[0]['quantity'], 3)
        self.assertEqual(self.w.attachments[0]['quick_amount'], 65.5)
        self.assertEqual(self.w.attachments[0]['formula_amount'], 82.68)

        # A fresh service result is adjusted locally so the manually entered
        # line amount replaces the attachment fee in the quick quote total.
        self.w.current_result = {'quick': {'attachment_fee': 150.0, 'total_cost': 1000.0}}
        workflow_window_update = self.w.update_attachment_view
        workflow_window_update()
        self.assertEqual(self.w.current_result['quick']['attachment_fee'], 65.5)
        self.assertEqual(self.w.current_result['quick']['total_cost'], 915.5)
        self.assertFalse(self.w.attachment_list.isVisible())
        dialog._v2_timer.stop()
        dialog.close()

    def test_attachment_primary_categories_follow_product_family(self):
        dialog_class = ns['AttachmentDialog']
        original_load = dialog_class.load_catalog
        dialog_class.load_catalog = lambda dialog, _url: setattr(dialog, '_v2_mode', True)
        try:
            dialog = dialog_class([], api_url='http://127.0.0.1:1', parent=self.w,
                                  target_dimensions=(600, 1800, 300))
        finally:
            dialog_class.load_catalog = original_load
        dialog._v2_timer.stop()
        categories = ('侧板', '控制箱附件', '控制柜附件', '安装板')
        dialog.catalog = [
            {'attachment_price_id': index, 'category_level1': category,
             'item_name': f'{category}测试附件', 'price': 10, 'unit': '件'}
            for index, category in enumerate(categories, 1)
        ]
        dialog.rebuild_table()
        dialog.show()
        product_cases = (
            ('JP', 'JP_SINGLE', {'侧板', '控制柜附件', '安装板'}),
            ('JP WIDE', 'JP_WIDE_EXP', {'侧板', '控制柜附件', '安装板'}),
            ('JM', 'JM', {'控制箱附件', '安装板'}),
            ('JA', 'JA_SINGLE', {'控制箱附件', '安装板'}),
            ('JE', 'JE_SINGLE', {'控制箱附件', '安装板'}),
            ('JK', 'JK', {'控制箱附件', '安装板'}),
            ('JS', 'JS_SINGLE', {'控制柜附件', '安装板'}),
            ('JS WIDE', 'JS_WIDE_EXP', {'控制柜附件', '安装板'}),
        )
        for family, code, expected in product_cases:
            self.w.product_catalog = {
                family: {'codes': {'DEFAULT': code, 'SINGLE': code, 'DOUBLE': code}}
            }
            self.w.product_combo.blockSignals(True)
            self.w.product_combo.clear()
            self.w.product_combo.addItem(family, family)
            self.w.product_combo.blockSignals(False)
            dialog.category_selection = []
            dialog.search_edit.clear()
            dialog.refresh_category_browser()
            app.processEvents()
            visible = {
                str(button.property('attachmentCategoryValue'))
                for button in dialog.findChildren(QPushButton, 'attachmentCategoryCard')
                if button.isVisible()
            }
            self.assertEqual(visible, expected, family)

        # Searching from the root must not reveal categories hidden for JP.
        family, code = 'JP', 'JP_SINGLE'
        self.w.product_catalog = {
            family: {'codes': {'DEFAULT': code, 'SINGLE': code, 'DOUBLE': code}}
        }
        self.w.product_combo.blockSignals(True)
        self.w.product_combo.clear()
        self.w.product_combo.addItem(family, family)
        self.w.product_combo.blockSignals(False)
        dialog.category_selection = []
        dialog.search_edit.setText('测试附件')
        dialog.apply_filter(dialog.search_edit.text())
        visible_rows = {
            dialog.table.item(row, dialog.COL_CHECK).data(Qt.ItemDataRole.UserRole)['category_level1']
            for row in range(dialog.table.rowCount()) if not dialog.table.isRowHidden(row)
        }
        self.assertEqual(visible_rows, {'侧板', '控制柜附件', '安装板'})
        dialog._v2_timer.stop()
        dialog.close()

    def test_quote_workspace_expands_with_window(self):
        page = self.w.stack.widget(1)
        workspace = page.findChild(workflow.QSplitter, 'quoteWorkspace')
        self.w.resize(1400, 820)
        pump()
        compact = (workspace.widget(0).width(), workspace.widget(1).width(),
                   workspace.widget(0).height(), workspace.widget(1).height())
        self.w.resize(2048, 1050)
        pump()
        expanded = (workspace.widget(0).width(), workspace.widget(1).width(),
                    workspace.widget(0).height(), workspace.widget(1).height())
        self.assertGreater(expanded[0], compact[0])
        self.assertGreater(expanded[1], compact[1])
        self.assertGreater(expanded[2], compact[2])
        self.assertGreater(expanded[3], compact[3])

    def test_pdf_pages_ink_alignment_and_result_round_trip(self):
        p = self.bind(candidate())
        self.assertEqual(p.page_count, 2, p.message.text())
        self.assertTrue(p.canvas.isEnabled(), p.message.text())
        self.stroke(p)
        original = copy.deepcopy(p.canvas.strokes)
        original_path = p.canvas._items[0].path()
        original_scene_point = QPointF(original_path.elementAt(0).x, original_path.elementAt(0).y)
        original_view_point = p.canvas.mapFromScene(original_scene_point)
        p.rotate_left_button.click()
        self.assertEqual(p.canvas.rotation_degrees, 270)
        self.assertEqual(p.rotations[(p.document_key, 0)], 270)
        self.assertEqual(p.canvas.strokes, original)
        self.assertNotEqual(p.canvas.mapFromScene(original_scene_point), original_view_point)
        self.assertGreater(p.canvas.current_scale(), 0)
        p.canvas.zoom(1.5)
        self.assertEqual(p.canvas.strokes, original)
        self.assertEqual(p.canvas._items[0].path().elementAt(0).x, original[0]['points'][0][0])
        p.set_page(1)
        pump(lambda: not p._workers)
        self.assertEqual(p.canvas.strokes, [])
        self.assertEqual(p.canvas.rotation_degrees, 0)
        p.rotate_right_button.click()
        self.assertEqual(p.canvas.rotation_degrees, 90)
        p.set_page(0)
        pump(lambda: not p._workers)
        self.assertEqual(p.canvas.strokes, original)
        self.assertEqual(p.canvas.rotation_degrees, 270)
        p.rotate_right_button.click()
        self.assertEqual(p.canvas.rotation_degrees, 0)
        logical_rect = p.canvas.scene().sceneRect()
        p.canvas.zoom(6)
        app.processEvents()
        detailed_transform = p.canvas.transform()
        detailed_center = p.canvas.mapToScene(p.canvas.viewport().rect().center())
        pump(lambda: not p._workers and p.current_render_edge > 2400)
        self.assertGreater(p.current_render_edge, 2400)
        self.assertEqual(p.canvas.scene().sceneRect(), logical_rect)
        self.assertEqual(p.canvas.strokes, original)
        self.assertEqual(p.canvas.transform(), detailed_transform)
        restored_center = p.canvas.mapToScene(p.canvas.viewport().rect().center())
        self.assertLess(abs(restored_center.x() - detailed_center.x()), 1)
        self.assertLess(abs(restored_center.y() - detailed_center.y()), 1)
        pixmaps = [item.pixmap() for item in p.canvas.scene().items() if hasattr(item, 'pixmap')]
        self.assertTrue(pixmaps)
        self.assertGreater(max(max(pixmap.width(), pixmap.height()) for pixmap in pixmaps), 2400)
        self.accept(response())
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 1)
        self.assertFalse(p.isVisible())
        self.assertTrue(self.w.history_price_card.isVisible())
        self.w.show_section(0)
        self.w.active_drawing = self.w._quote_drawing
        self.w.use_selected_drawing()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        self.assertEqual(p.canvas.strokes, original)
        current_result = self.w.current_result
        p.back_to_quote.click()
        app.processEvents()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 1)
        self.assertIs(self.w.current_result, current_result)
        self.assertTrue(self.w.history_price_card.isVisible())
        self.w.return_to_drawing_button.click()
        app.processEvents()
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        self.assertIs(self.w.current_result, current_result)
        self.assertEqual(p.canvas.strokes, original)
        p.color_combo.setCurrentIndex(1)
        p.width_spin.setValue(8)
        self.assertEqual(p.canvas.color, '#1769aa')
        self.assertEqual(p.canvas.stroke_width, 8)
        p.canvas.undo()
        self.assertEqual(p.canvas.strokes, [])
        self.stroke(p)
        p.canvas.clear_ink()
        self.assertEqual(p.canvas.strokes, [])

    def test_box_select_moves_styles_deletes_and_undoes_ink(self):
        preview = self.bind(candidate('png'))
        canvas = preview.canvas
        self.stroke(preview)
        canvas.set_ink(True)
        second_start = canvas.mapFromScene(QPointF(700, 200))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=second_start)
        QTest.mouseMove(canvas.viewport(), second_start + QPoint(40, 30))
        QTest.mouseRelease(
            canvas.viewport(), Qt.MouseButton.LeftButton,
            pos=second_start + QPoint(70, 50),
        )
        self.assertEqual(len(canvas.strokes), 2)

        preview.select_button.click()
        app.processEvents()
        self.assertTrue(canvas.select_enabled)
        self.assertFalse(canvas.ink_enabled)
        self.assertFalse(preview.pen_button.isChecked())
        select_from = canvas.mapFromScene(QPointF(350, 450))
        select_to = canvas.mapFromScene(QPointF(520, 650))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=select_from)
        QTest.mouseMove(canvas.viewport(), select_to)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=select_to)
        self.assertEqual(canvas.selected_indices, {0})
        self.assertTrue(preview.delete_selection_button.isEnabled())

        selected_before = copy.deepcopy(canvas.strokes[0]['points'])
        other_before = copy.deepcopy(canvas.strokes[1])
        bounds_center = canvas.mapFromScene(canvas._selection_bounds().center())
        moved_to = bounds_center + QPoint(45, 25)
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=bounds_center)
        QTest.mouseMove(canvas.viewport(), moved_to)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=moved_to)
        self.assertNotEqual(canvas.strokes[0]['points'], selected_before)
        self.assertEqual(canvas.strokes[1], other_before)

        preview.color_combo.setCurrentIndex(1)
        preview.width_spin.setValue(7)
        self.assertEqual(canvas.strokes[0]['color'], '#1769aa')
        self.assertAlmostEqual(canvas.strokes[0]['width'], 7 / canvas.current_scale())
        self.assertEqual(canvas.strokes[1], other_before)

        preview.delete_selection_button.click()
        self.assertEqual(len(canvas.strokes), 1)
        self.assertEqual(canvas.strokes[0], other_before)
        preview.undo_button.click()
        self.assertEqual(len(canvas.strokes), 2)
        self.assertEqual(canvas.strokes[1], other_before)

        preview.pen_button.click()
        self.assertTrue(canvas.ink_enabled)
        self.assertFalse(canvas.select_enabled)
        self.assertFalse(preview.select_button.isChecked())

    def test_images_cad_and_source_immutability(self):
        for suffix in ('png', 'jpg', 'jpeg', 'dxf'):
            with self.subTest(suffix=suffix):
                path = OUT / f'fixture.{suffix}'
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                p = self.bind(candidate(suffix, key=suffix))
                self.assertTrue(p.canvas.isEnabled(), p.message.text())
                self.assertEqual(p.page_count, 1)
                p.canvas.zoom(4)
                p.canvas.set_ink(False)
                scroll = p.canvas.horizontalScrollBar()
                previous = scroll.value()
                QTest.mousePress(p.canvas.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(220, 240))
                QTest.mouseMove(p.canvas.viewport(), QPoint(300, 240))
                QTest.mouseRelease(p.canvas.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(300, 240))
                self.assertNotEqual(scroll.value(), previous)
                p.canvas.fit()
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_freight_accepted_weight_manual_and_reset(self):
        self.assertEqual(self.w.freight_spin.value(), 0)
        self.accept(response(66.1))
        self.assertEqual(self.w.freight_spin.value(), 66.1)
        self.assertIn('66.10', self.w.freight_spin.text())
        self.assertEqual(self.w.freight_state.mode, 'AUTO')
        self.assertEqual(self.w.formula_labels['freight'].text(), '66.10 元')
        self.assertEqual(self.w.quick_labels['freight'].text(), '66.10 元')
        self.assertEqual(self.w.formula_labels['total'].text(), '228.70 元')
        self.assertEqual(self.w.quick_labels['total'].text(), '266.10 元')
        self.accept(response(72.33))
        self.assertEqual(self.w.freight_spin.value(), 72.33)
        self.w.freight_spin.setFocus()
        self.w.freight_spin.selectAll()
        QTest.keyClicks(self.w.freight_spin, '123.45')
        QTest.keyClick(self.w.freight_spin, Qt.Key.Key_Return)
        self.assertEqual(self.w.freight_spin.value(), 123.45)
        self.assertEqual(self.w.freight_state.mode, 'MANUAL')
        self.w.width_spin.setValue(750)
        self.accept(response(99.9))
        self.assertEqual(self.w.freight_spin.value(), 123.45)
        self.w.freight_auto_button.click()
        self.assertEqual(self.w.freight_spin.value(), 99.9)
        self.assertEqual(self.w.freight_state.mode, 'AUTO')
        self.w.reset_current_cabinet()
        self.assertEqual(self.w.freight_spin.value(), 0)
        self.assertEqual(self.w.freight_state.mode, 'AUTO')
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)

    def test_failure_and_late_response_keep_drawing_and_params(self):
        p = self.bind(candidate('png'))
        self.stroke(p)
        self.w.model_edit.setText('保留输入')
        self.w.show_error('测试连接失败')
        self.assertEqual(self.w.model_edit.text(), '保留输入')
        self.assertEqual(len(p.canvas.strokes), 1)
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        self.w.pending_quote_signature = self.w.quote_input_signature()
        self.w.reset_current_cabinet()
        self.w.show_result(response(100))
        self.assertEqual(self.w.quote_right_stack.currentIndex(), 0)
        self.assertIsNone(self.w.current_result)
        self.assertEqual(self.w.freight_spin.value(), 0)
        self.bind(candidate('png'))
        self.assertEqual(len(p.canvas.strokes), 1)

    def test_resolver_and_stale_render(self):
        item = candidate('dxf')
        item['preview_path'] = str(OUT / 'fixture.pdf')
        self.assertEqual(resolve_document(item, [])[1], item['preview_path'])
        p = self.bind(item)
        old_serial = p.serial
        p.set_document('none', '', '')
        p.ready(old_serial, QImage(100, 100, QImage.Format.Format_RGB32), 1, '图片', 2400)
        self.assertFalse(p.canvas.isEnabled())
        self.assertEqual(p.page_count, 0)

    def test_dwg_without_converter_is_an_explicit_failure(self):
        # A sentinel file tests the missing converter branch, not DWG parsing.
        (OUT / 'fixture.dwg').write_bytes(b'converter-unavailable-test')
        p = self.w.quote_drawing_preview
        p.convert_dwg = None
        p.set_document('dwg-missing', str(OUT / 'fixture.dwg'), str(OUT / 'fixture.dwg'))
        pump(lambda: not p._workers)
        self.assertFalse(p.canvas.isEnabled())
        self.assertIn('DWG 转换组件', p.message.text())
        self.assertEqual(p.page_count, 0)

    def test_billable_policy_never_uses_net_or_theoretical_weight(self):
        for value in ({}, {'formula_cost': {'net_material_weight_kg': 66.1}},
                      {'ganged_weight_kg': 66.1}, response(float('nan')), response(-1)):
            self.assertIsNone(billable_weight(value))
        self.assertEqual(billable_weight({'ganged_cabinet_results': [response(20.1), response(46)]}), Decimal('66.1'))
        state = FreightState()
        state.update_weight(Decimal('66.105'))
        self.assertEqual(state.value, Decimal('66.11'))
        state.manual(50)
        state.update_weight(100)
        self.assertEqual(state.value, Decimal('50.00'))

    def test_tablet_and_touch_events_and_pen_pan_exclusion(self):
        p = self.bind(candidate('png'))
        canvas = p.canvas
        canvas.set_ink(True)
        device = QPointingDevice('test pen', 1, QInputDevice.DeviceType.Stylus,
                                 QPointingDevice.PointerType.Pen,
                                 QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 1)
        point = QPointF(canvas.mapFromScene(QPointF(400, 400)))
        scroll = canvas.horizontalScrollBar().value()
        for kind, pos in ((QEvent.Type.TabletPress, point),
                          (QEvent.Type.TabletMove, point + QPointF(20, 20)),
                          (QEvent.Type.TabletRelease, point + QPointF(40, 40))):
            event = QTabletEvent(kind, device, pos, pos, .7, 0, 0, 0, 0, 0,
                                 Qt.KeyboardModifier.NoModifier, Qt.MouseButton.LeftButton,
                                 Qt.MouseButton.LeftButton)
            QApplication.sendEvent(canvas.viewport(), event)
        self.assertEqual(len(canvas.strokes), 1)
        self.assertEqual(canvas.horizontalScrollBar().value(), scroll)
        self.assertEqual(canvas.dragMode(), canvas.DragMode.NoDrag)
        # The offscreen platform has no native touch-device dispatcher. Check
        # the touch handler contract here; physical-device acceptance is manual.
        for kind, pos in ((QEvent.Type.TouchBegin, point),
                          (QEvent.Type.TouchUpdate, point + QPointF(40, 20)),
                          (QEvent.Type.TouchEnd, point + QPointF(60, 20))):
            sample, touch_point = Mock(), Mock()
            sample.type.return_value = kind
            touch_point.position.return_value = pos
            sample.points.return_value = [touch_point]
            self.assertTrue(canvas.eventFilter(canvas.viewport(), sample))
            sample.accept.assert_called_once()
        pump()
        self.assertEqual(len(canvas.strokes), 2)
        canvas.set_ink(False)
        self.assertEqual(canvas.dragMode(), canvas.DragMode.ScrollHandDrag)


if __name__ == '__main__':
    unittest.main(verbosity=2)
