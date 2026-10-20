"""Real current-client Qt page, offline transport, reference layout and actions."""

from copy import deepcopy
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))

from PySide6.QtCore import QDate, QPoint, QRect, QSignalBlocker, Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPushButton
import quote_scheme_center as centre
import quote_scheme_widgets as widgets
import scheme2_ui
import v3_launcher

NS = v3_launcher.load_v3_namespace()
NS['MainWindow'].load_catalogs = lambda self: None
NS['ApiWorker'].run = lambda self: self.failed.emit('offline test transport')
APP = QApplication.instance() or QApplication([])
NS['install_application_font'](APP)
# Offline catalogue matching the option-page choices in the user's reference.
PRODUCT_TYPES = ('JA', 'JC', 'JE', 'JK', 'JM', 'JP', 'JP WIDE', 'JQ', 'JS', 'JS WIDE', '操作台')
BASE_ROWS = [
    dict(scheme_no=f'BJ-20261019-{123 - index:06d}', company_name=company,
         product_summary=product, status=status, quoted_amount=amount,
         creator_name=('张三', '李四', '王五', '赵六', '孙七')[index],
         last_editor_name=('张三', '王五', '赵六', '赵六', '孙七')[index], lock_version=1,
         updated_at='2026-10-19T01:45:01+00:00', version_no=1)
    for index, (status, company, product, amount) in enumerate((
        ('DRAFT', '样例精密机械有限公司', 'JQ_EXP 1000*725*(1150+100)', None),
        ('QUOTED', '样例电子科技有限公司', 'JE_SINGLE 600*300*800', 2860),
        ('REVISING', '样例航空实业有限公司', 'JP_DOUBLE 800*600*2000', 5320),
        ('ARCHIVED', '样例五金有限公司', 'JS_SINGLE 800*600*2000', 3180),
        ('VOID', '样例电器有限公司', 'OP_TABLE_EXP 1000*600*800', 1950),
    ))
]


def pump(predicate=lambda: True, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError('Timed out waiting for offline Qt operation')


class ReferenceSchemeUI(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.total = 5
        screen = Mock(wraps=APP.primaryScreen())
        screen.availableGeometry.return_value = QRect(0, 0, 4096, 2160)
        self.screen_patch = patch.object(NS['MainWindow'], 'screen', return_value=screen)
        self.screen_patch.start()

        def offline_run(worker):
            QThread.msleep(10)
            self.requests.append((worker.method, worker.url))
            if worker.method != 'GET':
                worker.failed.emit('Unexpected write in a UI-only test')
                return
            query = parse_qs(urlparse(worker.url).query)
            worker.succeeded.emit(dict(items=deepcopy(BASE_ROWS), total=self.total,
                page=int(query.get('page', ['1'])[0]),
                page_size=int(query.get('page_size', ['10'])[0])))

        self.worker_patch = patch.object(centre.QuoteSchemeWorker, 'run', offline_run)
        self.worker_patch.start()
        self.window = NS['MainWindow']()
        with QSignalBlocker(self.window.product_combo):
            self.window.product_combo.clear()
            for name in PRODUCT_TYPES:
                self.window.product_combo.addItem(name, name)
        self.window.resize(1553, 980)
        self.window.show()
        scheme2_ui._set_nav_collapsed(self.window, False, manual=True)
        self.window.show_section(1)
        self.window.show_section(centre.SCHEME_ROUTE)
        self.wait_loaded()
        QTest.qWait(50)

    def wait_loaded(self):
        pump(lambda: self.window._quote_scheme_list_worker is None
             and not self.window._quote_scheme_workers)

    def tearDown(self):
        self.wait_loaded()
        self.window._quote_scheme_save_timer.stop()
        self.window._quote_scheme_id = ''
        self.window._scheme2_dirty = False
        self.window.close()
        APP.processEvents()
        self.worker_patch.stop()
        self.screen_patch.stop()

    def test_reviewer_header_preserves_existing_names_and_table_style(self):
        table = self.window.quote_scheme_table
        self.assertEqual(table.horizontalHeaderItem(6).text(), '审核人')
        for row, scheme in enumerate(BASE_ROWS):
            self.assertEqual(table.item(row, 6).text(), scheme['last_editor_name'])
        self.assertEqual(table.columnCount(), 9)
        self.assertEqual(table.horizontalHeaderItem(5).text(), '创建人')
        self.assertEqual(table.horizontalHeaderItem(7).text(), '更新时间')

    def test_reference_structure_and_five_statuses(self):
        w = self.window
        self.assertEqual([b.text() for b in w.nav_buttons],
                         ['选型配置', '成本计算', '报价单', '报价方案'])
        title = w.quote_scheme_page.findChild(QLabel, 'quoteSchemeTitle')
        quote_title = w.scheme2_quote_page.findChild(QLabel, 'scheme2PageTitle')
        self.assertEqual(title.font().families(), quote_title.font().families())
        self.assertEqual(title.font().pixelSize(), quote_title.font().pixelSize())
        self.assertEqual(title.font().pointSizeF(), quote_title.font().pointSizeF())
        self.assertEqual(title.font().weight(), quote_title.font().weight())
        self.assertEqual(title.palette().color(title.foregroundRole()),
                         quote_title.palette().color(quote_title.foregroundRole()))
        self.assertTrue(w.quote_scheme_operator_name.isHidden())
        self.assertFalse(w.scheme2_action_dock.isVisibleTo(w))
        if hasattr(w, 'quote_action_dock'):
            self.assertFalse(w.quote_action_dock.isVisibleTo(w))
        grid = w.quote_scheme_filter_grid
        for name, row, column in (
            ('scheme_no', 0, 0), ('company', 0, 1), ('product', 0, 2),
            ('status', 1, 0), ('creator', 1, 1), ('updated', 1, 2),
        ):
            field = w.quote_scheme_page.findChild(widgets.QWidget, 'quoteSchemeField_' + name)
            self.assertEqual(grid.getItemPosition(grid.indexOf(field))[:2], (row, column))
            label = field.findChild(QLabel, 'quoteSchemeFieldLabel')
            self.assertIsNotNone(label)
            if name in w.quote_scheme_filters:
                editor = w.quote_scheme_filters[name]
                self.assertLess(label.mapTo(field, QPoint()).y(), editor.mapTo(field, QPoint()).y())
        table = w.quote_scheme_table
        self.assertEqual(table.rowCount(), 5)
        self.assertEqual(table.horizontalHeaderItem(2).text(), '产品')
        self.assertEqual([table.item(row, 2).text() for row in range(5)],
                         ['JQ', 'JE', 'JP', 'JS', '操作台'])
        self.assertEqual(table.item(0, 2).toolTip(), 'JQ')
        self.assertGreaterEqual(table.rowHeight(0), widgets.METRICS['row_height'])
        self.assertIsInstance(table.itemDelegateForColumn(3), widgets.StatusBadgeDelegate)
        self.assertEqual([table.item(row, 3).text() for row in range(5)],
                         ['草稿', '已报价', '修订中', '已归档', '已作废'])
        self.assertEqual(table.item(0, 7).text(), '2026-10-19 01:45')
        self.assertEqual(table.item(0, 7).toolTip(), BASE_ROWS[0]['updated_at'])
        self.assertEqual(table.item(0, 4).text(), '—')
        self.assertEqual(table.item(1, 4).text(), '¥ 2,860.00')
        self.assertEqual(table.horizontalHeader().grab().toImage().pixelColor(8, 8).name(), '#eef3f8')
        table.selectRow(0)
        self.assertEqual(w.quote_scheme_selected.text(), '已选择 1 条')
        self.assertTrue(w.quote_scheme_page_status.isHidden())
        self.assertEqual(w.quote_scheme_page_size.currentData(), 10)
        self.assertEqual([w.quote_scheme_page_size.itemData(i) for i in range(4)], [10, 20, 50, 100])
        artifacts = os.environ.get('AI_QUOTE_UI_ARTIFACT_DIR', '').strip()
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            self.assertTrue(w.grab().save(str(directory / 'reference_scheme_five_statuses.png')))
        # A vertical scrollbar reduces the viewport after rows are inserted.
        # Re-fit against that actual width so a wide page gains no stray
        # horizontal scrollbar and the action links remain inside their cell.
        centre._list_loaded(w, dict(items=deepcopy(BASE_ROWS) * 10,
                                   total=50, page=1, page_size=50))
        QTest.qWait(50)
        self.assertTrue(table.verticalScrollBar().isVisible())
        self.assertLessEqual(sum(table.columnWidth(i) for i in range(9)),
                             table.viewport().width())
        self.assertFalse(table.horizontalScrollBar().isVisible())

    def test_row_actions_preserve_status_rules_and_target(self):
        table = self.window.quote_scheme_table
        self.assertFalse(table.compact_actions)
        for row in range(5):
            actions = table.cellWidget(row, 8)
            direct = [label for label, button in actions.buttons.items() if not button.isHidden()]
            menu = [action.text() for action in actions.menu.actions()]
            self.assertLessEqual(len(direct), 3)
            self.assertFalse(set(direct) & set(menu))
            self.assertNotIn('删除', direct)
            if row != 0:
                self.assertNotIn('删除未使用草稿', menu)
            if row == 0:
                self.assertNotIn('修订', direct + menu)
                self.assertIn('删除未使用草稿', menu)
            if row == 1:
                self.assertEqual(direct, ['打开', '打印', '导出'])
                self.assertIn('归档', menu)
            if row == 3:
                self.assertIn('恢复', menu)
            if row == 4:
                self.assertNotIn('作废', menu)
        with patch.object(centre, '_open_scheme') as opened:
            table.cellWidget(1, 8).buttons['打印'].click()
            opened.assert_called_once_with(self.window, BASE_ROWS[1]['scheme_no'], 2, 'print')
        with patch.object(centre, '_scheme_action') as changed:
            actions = table.cellWidget(1, 8)
            next(action for action in actions.menu.actions() if action.text() == '修订').trigger()
            self.assertEqual(changed.call_args.args[1]['scheme_no'], BASE_ROWS[1]['scheme_no'])
            self.assertEqual(changed.call_args.args[2], 'revision')

    def test_transition_failures_name_the_action_and_preserve_confirmation(self):
        w = self.window
        for action, label, row in (('archive', '归档', BASE_ROWS[1]),
                                   ('restore', '恢复', BASE_ROWS[3]),
                                   ('void', '作废', BASE_ROWS[0])):
            with self.subTest(action=action):
                with patch.object(centre.QMessageBox, 'question', return_value=centre.QMessageBox.Yes) as question, \
                     patch.object(centre, '_require_operator', return_value='离线测试人员'), \
                     patch.object(centre, '_run') as request:
                    centre._confirm_transition(w, row, action)
                    args = request.call_args.args
                    self.assertEqual(args[1], 'POST')
                    self.assertTrue(args[2].endswith('/' + action))
                    self.assertEqual(args[3], {'expected_version': row['lock_version'], 'operator_name': '离线测试人员'})
                    self.assertEqual(question.call_args.args[-1], centre.QMessageBox.No)
                    args[5]('模拟数据库错误')
                    self.assertEqual(w.quote_scheme_page_status.text(), f'{label}失败：模拟数据库错误')
                    self.assertNotIn('保存失败', w.quote_scheme_page_status.text())
                    with patch.object(centre, '_load_list') as reload_list:
                        args[4]({'changed': True})
                        reload_list.assert_called_once_with(w, w._quote_scheme_page)
                with patch.object(centre.QMessageBox, 'question', return_value=centre.QMessageBox.No), \
                     patch.object(centre, '_run') as request:
                    centre._confirm_transition(w, row, action)
                    request.assert_not_called()

    def test_optional_dates_reset_and_query_validation(self):
        w = self.window
        start, end = (w.quote_scheme_filters[key] for key in ('updated_from', 'updated_to'))
        self.assertNotIn('updated_from', centre._filters(w, 1))
        start._show_calendar()
        APP.processEvents()
        self.assertEqual(start.text(), '')
        start._selected(QDate(2026, 10, 1))
        end._selected(QDate(2026, 10, 19))
        self.assertEqual(centre._filters(w, 1)['updated_from'], '2026-10-01')
        request_count = len(self.requests)
        QTest.keyClick(start, Qt.Key.Key_Return)
        self.wait_loaded()
        self.assertEqual(len(self.requests), request_count + 1)
        self.assertIn('updated_from=2026-10-01', self.requests[-1][1])
        start.setText('2026-02-30')
        previous_count = len(self.requests)
        w.quote_scheme_query.click()
        APP.processEvents()
        self.assertEqual(len(self.requests), previous_count)
        self.assertIn('有效日期', w.quote_scheme_page_status.text())
        start.setText('2026-10-20')
        with self.assertRaisesRegex(ValueError, '不能晚于'):
            centre._filters(w, 1)
        w.quote_scheme_reset.click()
        self.wait_loaded()
        self.assertTrue(all(not (editor.text() if isinstance(editor, QLineEdit) else editor.currentData())
                            for editor in w.quote_scheme_filters.values()))
        self.assertTrue(w.quote_scheme_page_status.isHidden())

    def test_product_filter_is_noneditable_catalogue_dropdown_and_reset_preserves_options(self):
        w = self.window
        combo = w.quote_scheme_filters['product']
        self.assertIsInstance(combo, QComboBox)
        self.assertFalse(combo.isEditable())
        self.assertIsNone(combo.lineEdit())
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ['全部', *PRODUCT_TYPES])
        self.assertNotIn('product', centre._filters(w, 1))
        source_selection = w.product_combo.currentText()
        combo.showPopup()
        APP.processEvents()
        self.assertTrue(combo.view().property('unifiedComboPopup'))
        self.assertEqual(combo.view().styleSheet(), w.product_combo.view().styleSheet())
        self.assertEqual(combo.view().sizeHintForRow(0), w.product_combo.view().sizeHintForRow(0))
        index = combo.model().index(combo.findData('JQ'), 0)
        combo.view().scrollTo(index)
        APP.processEvents()
        artifacts = os.environ.get('AI_QUOTE_UI_ARTIFACT_DIR', '').strip()
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            self.assertTrue(combo.view().window().grab().save(str(directory / 'quote_scheme_product_dropdown.png')))
        before = len(self.requests)
        QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                         pos=combo.view().visualRect(index).center())
        APP.processEvents()
        self.assertEqual(combo.currentData(), 'JQ')
        self.assertEqual(len(self.requests), before, 'Selecting a filter must not submit or change configuration')
        self.assertEqual(w.product_combo.currentText(), source_selection)
        w.quote_scheme_query.click()
        self.wait_loaded()
        self.assertEqual(parse_qs(urlparse(self.requests[-1][1]).query)['product'], ['JQ'])
        combo.setCurrentIndex(combo.findData('JP WIDE'))
        self.assertEqual(centre._filters(w, 1)['product'], 'JP WIDE')
        w.quote_scheme_reset.click()
        self.wait_loaded()
        self.assertEqual(combo.currentData(), '')
        self.assertEqual(combo.count(), len(PRODUCT_TYPES) + 1)
        self.assertNotIn('product', parse_qs(urlparse(self.requests[-1][1]).query))

    def test_product_filter_tracks_async_catalogue_refresh_without_queries(self):
        w = self.window
        source, combo = w.product_combo, w.quote_scheme_filters['product']
        combo.setCurrentIndex(combo.findData('JQ'))
        before = len(self.requests)
        with QSignalBlocker(source):
            source.clear()
            for name in reversed(PRODUCT_TYPES):
                source.addItem(name, name)
        pump(lambda: not w._quote_scheme_product_sync_timer.isActive())
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ['全部', *reversed(PRODUCT_TYPES)])
        self.assertEqual(combo.currentData(), 'JQ')
        with QSignalBlocker(source):
            source.clear()
            source.addItem('正在读取产品型号…', None)
        pump(lambda: not w._quote_scheme_product_sync_timer.isActive())
        self.assertEqual(combo.count(), 1)
        self.assertEqual(combo.currentText(), '全部')
        self.assertNotIn('product', centre._filters(w, 1))
        self.assertEqual(len(self.requests), before)

    def test_save_failure_stays_visible_without_obscuring_rows(self):
        w = self.window
        centre._set_state(w, '保存失败：离线回归测试', 'error')
        self.assertEqual(w.quote_scheme_table.rowCount(), 5)
        self.assertTrue(w.quote_scheme_page_status.isHidden())
        self.assertTrue(w.quote_scheme_operation_status.isVisibleTo(w))
        centre._set_state(w, '已保存', 'ok')
        self.assertTrue(w.quote_scheme_operation_status.isHidden())

    def test_programmatic_refresh_is_ignored_before_read_only_protection(self):
        w = self.window
        try:
            for read_only in (True, False):
                with self.subTest(read_only=read_only):
                    w._quote_scheme_read_only = read_only
                    w._scheme2_refreshing = True
                    w._scheme2_refreshing_quote = True
                    with patch.object(w, 'refresh_summary') as cost_refresh, \
                            patch.object(scheme2_ui, '_refresh_quote_page') as quote_refresh:
                        scheme2_ui._cost_cell_changed(w, 0, 4)
                        scheme2_ui._quote_name_changed(w, 10, 1)
                        scheme2_ui._quote_unit_price_changed(w, 10, 5)
                        cost_refresh.assert_not_called()
                        quote_refresh.assert_not_called()
        finally:
            w._scheme2_refreshing = False
            w._scheme2_refreshing_quote = False
            w._quote_scheme_read_only = False

    def test_product_names_without_dimensions_preserve_source(self):
        for summary, expected in (
            ('JQ_EXP 1000*480*1060；JE_DOUBLE 1200*600*2000', 'JQ；JE'),
            ('JQ_EXP 1000*725*(1150+100)', 'JQ'),
            ('JQ_EXP 1000*725*（1150+100）；JE_SINGLE；JE_DOUBLE 800*600*2000', 'JQ；JE'),
            ('JP_SINGLE (800+800)*600*(2000+100)；JP_DOUBLE 1600*600*2100', 'JP'),
            ('JC_EXP 600 x 400 x 200 mm；JP_WIDE_EXP 800*600*2100', 'JC；JP WIDE'),
            ('JS_WIDE_EXP 800*600*2100；OP_TABLE_EXP 1000*600*800', 'JS WIDE；操作台'),
            ('JQ；JE；JP；JS；JC；操作台', 'JQ；JE；JP；JS；JC；操作台'),
            ('机箱外壳', '机箱外壳'),
            ('未知名称 600×400×200mm', ''),
            ('AE-20 机箱 V2 600*400*200;JK 01 500*300*200', 'AE-20；JK'),
            ('', ''), (None, ''),
        ):
            with self.subTest(summary=summary):
                self.assertEqual(centre._display_products(self.window, summary), expected)
        row = deepcopy(BASE_ROWS[0])
        row['product_summary'] = 'JQ_EXP 1000*480*1060；JE_DOUBLE 1200*600*2000'
        original = deepcopy(row)
        centre._list_loaded(self.window, dict(items=[row], total=1, page=1, page_size=10))
        self.assertEqual(self.window.quote_scheme_table.item(0, 2).text(), 'JQ；JE')
        self.assertEqual(row, original)
        stored = self.window.quote_scheme_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(stored['product_summary'], original['product_summary'])

    def test_snapshot_product_types_follow_saved_configuration_not_specs_or_names(self):
        w = self.window
        with QSignalBlocker(w.product_combo):
            w.product_combo.clear()
            w.product_combo.addItem('JS', 'JS')
        w.draft_items = [
            dict(product_code='JQ_EXP', product_family='JQ', name='自填柜名与类型无关',
                 specification='1000*725*(1150+100)', quantity=1),
            dict(product_code='JE_SINGLE', scheme2_selected_product_name='JE',
                 product_name='不是产品类型', specification='600*300*800', quantity=2),
            dict(product_code='JE_DOUBLE', scheme2_selected_product_code='JE',
                 specification='800*300*(800+100)', quantity=1),
            dict(product_code='JP_WIDE_EXP', specification='800*600*2000', quantity=1),
            dict(product_code='OP_TABLE_EXP', specification='1000*600*800', quantity=1),
        ]
        original = deepcopy(w.draft_items)
        snapshot = centre._snapshot(w)
        self.assertEqual(snapshot['scheme_summary']['product_summary'], 'JQ；JE；JP WIDE；操作台')
        self.assertEqual(snapshot['draft_items'], original)
        self.assertEqual(w.draft_items, original)
        self.assertEqual(centre._display_products(w, snapshot['scheme_summary']['product_summary']),
                         'JQ；JE；JP WIDE；操作台')
        # Prefer an actual saved configuration label over a generic code token.
        w.product_combo.addItem('JE 产品类型', 'JE')
        self.assertEqual(centre._display_products(w, 'JE 产品类型 600*(300+50)*800'), 'JE 产品类型')
        w.product_combo.addItem('JP', 'JP')
        self.assertEqual(centre._display_products(w, 'JP WIDE；JS WIDE'), 'JP WIDE；JS WIDE')

    def test_pagination_empty_loading_failure_and_recovery(self):
        w = self.window
        self.total = 52
        w.quote_scheme_query.click()
        self.assertFalse(w.quote_scheme_query.isEnabled())
        self.assertIn('正在加载', w.quote_scheme_page_status.text())
        self.wait_loaded()
        self.assertEqual(w.quote_scheme_number_layout.count(), 5)
        self.assertFalse(w.quote_scheme_prev.isEnabled())
        w.quote_scheme_next.click()
        self.wait_loaded()
        self.assertEqual(w._quote_scheme_page, 2)
        self.assertTrue(w.quote_scheme_prev.isEnabled())
        w.quote_scheme_page_jump.setValue(4)
        QTest.keyClick(w.quote_scheme_page_jump.lineEdit(), Qt.Key.Key_Return)
        self.wait_loaded()
        self.assertEqual(w._quote_scheme_page, 4)
        w.quote_scheme_page_jump.setValue(5)
        QTest.keyClick(w.quote_scheme_page_jump, Qt.Key.Key_Return)
        self.wait_loaded()
        self.assertEqual(w._quote_scheme_page, 5)
        w.quote_scheme_page_size.setCurrentIndex(w.quote_scheme_page_size.findData(20))
        self.wait_loaded()
        self.assertEqual(w._quote_scheme_page, 1)
        self.assertIn('page_size=20', self.requests[-1][1])
        centre._list_failed(w, 'offline psql diagnostic')
        self.assertIn('加载失败', w.quote_scheme_page_status.text())
        self.assertNotIn('psql', w.quote_scheme_page_status.text())
        self.assertIn('psql', w.quote_scheme_page_status.toolTip())
        self.assertTrue(w.quote_scheme_page_status.isVisibleTo(w))
        self.assertTrue(w.quote_scheme_query.isEnabled())
        centre._list_loaded(w, dict(items=[], total=0, page=1, page_size=20))
        self.assertIn('暂无报价方案', w.quote_scheme_page_status.text())
        self.assertEqual(w.quote_scheme_table.rowCount(), 0)
        w.quote_scheme_query.click()
        self.wait_loaded()
        self.assertEqual(w.quote_scheme_table.rowCount(), 5)
        self.assertTrue(w.quote_scheme_page_status.isHidden())

    def test_resize_compacts_actions_without_other_page_changes(self):
        w = self.window
        for width, height in ((1024, 700), (1280, 800), (1553, 980)):
            w.resize(width, height)
            QTest.qWait(80)
            page = w.quote_scheme_page
            filters = page.findChild(widgets.QWidget, 'quoteSchemeFilters')
            self.assertLessEqual(filters.width(), page.width())
            buttons = (w.quote_scheme_query, w.quote_scheme_reset, w.quote_scheme_create)
            self.assertEqual(len({button.height() for button in buttons}), 1)
            self.assertLessEqual(max(b.width() for b in buttons) - min(b.width() for b in buttons), 1)
            for button in buttons:
                self.assertGreater(button.width(), button.fontMetrics().horizontalAdvance(button.text()))
            self.assertFalse(w.scheme2_action_dock.isVisibleTo(w))
            table = w.quote_scheme_table
            for row in range(table.rowCount()):
                actions = table.cellWidget(row, 8)
                if table.compact_actions:
                    direct = [text for text, b in actions.buttons.items() if not b.isHidden()]
                    self.assertEqual(direct, ['打开'])
                self.assertLessEqual(actions.more.geometry().right(), actions.width())
        w.show_section(1)
        QTest.qWait(40)
        self.assertTrue(w.scheme2_action_dock.isVisibleTo(w))
        w.show_section(centre.SCHEME_ROUTE)
        self.wait_loaded()
        self.assertFalse(w.scheme2_action_dock.isVisibleTo(w))
        w.quote_scheme_operator_name.setText('测试操作人')
        self.assertEqual(centre._operator_name(w), '测试操作人')
        self.assertIn('测试操作人', w.quote_scheme_operator_button.text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
