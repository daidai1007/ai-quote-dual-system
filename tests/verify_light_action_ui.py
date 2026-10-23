"""Approved compact controls on the real Qt client; synthetic data, offline I/O.

Run through run_quote_management_checks.py for temporary settings and network guard.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import verify_quote_management_filters as fixture
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionButton
import quote_scheme_center as schemes
from quote_scheme_widgets import LIGHT_ACTION

APP = fixture.APP
OUT = Path(os.environ.get('AI_QUOTE_LIGHT_SCREENSHOT_DIR',
                          str(fixture.ROOT / 'test-output/light-action-ui')))


class ApprovedControls(unittest.TestCase):
    setUp = fixture.QuoteFilters.setUp
    tearDown = fixture.QuoteFilters.tearDown
    loaded = fixture.QuoteFilters.loaded

    def assert_compact(self, controls):
        for control in controls:
            self.assertEqual(control.height(), LIGHT_ACTION['height'], control.text() if isinstance(control, QPushButton) else 'drafts')
            self.assertEqual(control.font().pixelSize(), LIGHT_ACTION['font_size'])
            if isinstance(control, QPushButton):
                self.assertGreaterEqual(control.width(), control.fontMetrics().horizontalAdvance(control.text()) + 20)
            self.assertTrue(control.isVisible())

    def capture(self, name):
        APP.processEvents(); QTest.qWait(60)
        OUT.mkdir(parents=True, exist_ok=True)
        self.assertTrue(self.w.grab().save(str(OUT / name)))

    def background(self, control, hover=False):
        pixmap = control.grab(); ratio = pixmap.devicePixelRatio()
        if hover:
            # Paint the production QStyle with its native hover flag: offscreen
            # cursor movement can be clamped by the emulated high-DPI screen.
            option = QStyleOptionButton(); control.initStyleOption(option)
            option.state |= QStyle.StateFlag.State_MouseOver
            pixmap = QPixmap(pixmap.size()); pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            control.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, control)
            painter.end()
        return pixmap.toImage().pixelColor(round(6*ratio), round(14*ratio)).name()

    def test_quote_controls_states_and_existing_queries(self):
        controls = (self.m.contract_button, self.m.query_button, self.m.reset_button)
        self.assert_compact(controls)
        button = self.m.query_button
        QTest.mouseMove(self.m.list_table.viewport(), QPoint(10, 100)); QTest.qWait(30)
        button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        self.assertEqual(self.background(button), LIGHT_ACTION['background'].lower())
        self.assertEqual(button.palette().color(QPalette.ColorRole.ButtonText).name(), LIGHT_ACTION['text'].lower())
        QTest.mouseMove(button, QPoint(6, 14)); QTest.qWait(30)
        self.assertEqual(self.background(button, hover=True), LIGHT_ACTION['hover'].lower())
        button.setEnabled(False); APP.processEvents()
        self.assertEqual(self.background(button), LIGHT_ACTION['disabled_background'].lower())
        self.assertEqual(button.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name(), LIGHT_ACTION['disabled_text'].lower())
        button.setEnabled(True)
        before = len(self.requests)
        self.m.filters['company'].setText('合成测试客户'); button.click(); self.loaded()
        self.assertGreater(len(self.requests), before)
        self.assertEqual(self.requests[-1]['company'], ['合成测试客户'])
        self.m.reset_button.click(); self.loaded()
        self.assertEqual(self.m.filters['company'].text(), '')
        self.capture('01-quotation-management.png')

    def test_contract_removals_feedback_and_footer_layout(self):
        p = self.w.contract_management
        # Display the production page without asking for any real contract data.
        with patch.object(p, 'reload'):
            self.w.show_section(self.w.contract_management_route)
        p.notice.clear(); p.invalidate(); APP.processEvents()
        captions = {item.text() for item in p.findChildren(QLabel)}
        removed = {
            '预览来自本次生成的实际 Word / Excel 文件。',
            '内容已变化，请重新生成后核对文件。',
            '合同价格取自所选正式报价，修改金额请先修订并确认报价。',
            '尚未选择正式报价',
            '仅使用本人有权使用的正式报价版本；请明确选择报价方式。',
            '生成记录不会自动标记成交或签约。',
            '只填写模板需要的字段；未明确的税费不能自动补为 0。',
        }
        self.assertFalse(captions & removed)
        self.assertIn('客户', captions); self.assertTrue(p.customer.isVisible())
        self.assertEqual(len(p.inputs), 7)
        self.assertEqual(p.purpose.text(), '使用客户合同模板，填入已确定报价并按原格式输出')
        self.assertFalse(p.notice.isVisible()); self.assertFalse(p.source_info.isVisible())
        self.assertFalse(p.preview_info.isVisible())
        # Removing explanatory text must still show validation, real sources and
        # actual generated-file identity; clearing must also reclaim the space.
        for label in (p.notice, p.source_info, p.preview_info):
            label.setText('合成测试反馈'); APP.processEvents(); self.assertTrue(label.isVisible())
            label.clear(); APP.processEvents(); self.assertTrue(label.isHidden())
        controls = (p.reload_button, p.upload_button, p.drafts, p.save_button,
                    p.generate_button, p.export_button)
        for width, height in ((1510, 960), (1024, 768), (910, 620)):
            self.w.setMinimumSize(0, 0); self.w.resize(width, height)
            APP.processEvents(); QTest.qWait(60)
            self.assert_compact(controls)
            self.assertGreaterEqual(p.purpose.width(), p.purpose.fontMetrics().horizontalAdvance(p.purpose.text()) + 20)
            for control in controls:
                self.assertTrue(p.rect().contains(control.mapTo(p, control.rect().bottomRight())), (width, control.geometry(), p.size()))
            self.capture(f'02-contract-management-{width}.png')
        p.notice.setText('合成测试：操作失败，可重试'); APP.processEvents()
        self.assertTrue(p.notice.isVisible())
        self.capture('03-contract-error-feedback.png')

    def test_scheme_controls_and_preserved_actions(self):
        self.w.show_section(schemes.SCHEME_ROUTE)
        fixture.wait(lambda: not self.w._quote_scheme_workers)
        controls = (self.w.quote_scheme_query, self.w.quote_scheme_reset, self.w.quote_scheme_create)
        for width, height in ((1510, 960), (1024, 768)):
            self.w.resize(width, height); APP.processEvents(); QTest.qWait(60)
            self.assert_compact(controls)
            self.assertLessEqual(max(b.width() for b in controls) - min(b.width() for b in controls), 1)
            for control in controls:
                page = self.w.quote_scheme_page
                self.assertTrue(page.rect().contains(control.mapTo(page, control.rect().bottomRight())))
            self.capture(f'04-quotation-schemes-{width}.png')
        self.w.quote_scheme_filters['company'].setText('合成测试客户')
        self.w.quote_scheme_query.click(); fixture.wait(lambda: not self.w._quote_scheme_workers)
        self.assertEqual(self.requests[-1]['company'], ['合成测试客户'])
        self.w.quote_scheme_reset.click(); fixture.wait(lambda: not self.w._quote_scheme_workers)
        self.assertEqual(self.w.quote_scheme_filters['company'].text(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
