"""Real Qt wheel/click events across recovered-client and dynamic editors."""
import copy
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDoubleSpinBox, QPushButton, QScrollArea,
    QSlider, QSpinBox, QStyle, QStyleOptionSpinBox, QTableWidget, QTableWidgetItem,
    QTimeEdit, QVBoxLayout, QWidget,
)
import scheme2_ui as ui
import v3_launcher
from quote_drawing_preview import QuoteDrawingPreview
from wheel_edit_guard import install_wheel_edit_guard

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
ns = v3_launcher.load_v3_namespace()
ns["install_application_font"](app)
Window = ns["MainWindow"]
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
ns["ApiWorker"].run = lambda self: self.failed.emit("offline wheel test")


def wheel(widget, angle=-120, *, pixels=None, modifiers=Qt.KeyboardModifier.NoModifier):
    position = widget.rect().center()
    event = QWheelEvent(QPointF(position), QPointF(widget.mapToGlobal(position)),
                        pixels or QPoint(), QPoint(0, angle), Qt.MouseButton.NoButton,
                        modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    app.processEvents()


class WheelEditing(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window._scheme2_loading_order = True
        self.window._scheme2_dirty = False
        self.addCleanup(self.window.close)
        self.assertIsNotNone(getattr(app, "_wheel_edit_guard", None), "runtime did not install the wheel policy")

    def show_widget(self, widget):
        self.addCleanup(widget.close)
        widget.show()
        widget.activateWindow()
        app.processEvents()
        return widget

    def test_runtime_installation_is_application_wide_and_idempotent(self):
        self.assertIs(install_wheel_edit_guard(), app._wheel_edit_guard)
        self.assertIs(install_wheel_edit_guard(), install_wheel_edit_guard())

    def test_focused_unfocused_spins_and_child_editors_never_step(self):
        for factory in (QSpinBox, QDoubleSpinBox):
            with self.subTest(factory=factory.__name__):
                spin = self.show_widget(factory())
                spin.setRange(0, 100)
                spin.setValue(20)
                spy = QSignalSpy(spin.valueChanged)
                for focused in (False, True):
                    spin.setFocus() if focused else spin.clearFocus()
                    for receiver in (spin, spin.lineEdit()):
                        for angle in (-120, 120):
                            wheel(receiver, angle)
                        wheel(receiver, 0, pixels=QPoint(0, -24))
                        wheel(receiver, modifiers=Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(spin.value(), 20)
                self.assertEqual(spy.count(), 0)

    def test_closed_combos_do_not_change_even_when_editable_and_focused(self):
        for editable in (False, True):
            with self.subTest(editable=editable):
                combo = self.show_widget(QComboBox())
                combo.addItems(["型号一", "型号二", "型号三"])
                combo.setEditable(editable)
                combo.setCurrentIndex(1)
                combo.setFocus()
                changed, activated = QSignalSpy(combo.currentIndexChanged), QSignalSpy(combo.activated)
                wheel(combo, 120)
                wheel(combo, -120)
                if editable:
                    wheel(combo.lineEdit(), -120)
                self.assertEqual(combo.currentIndex(), 1)
                self.assertEqual(changed.count(), 0)
                self.assertEqual(activated.count(), 0)

    def test_dates_times_and_slider_values_do_not_change(self):
        for control, getter in ((QDateEdit(), "date"), (QTimeEdit(), "time"), (QSlider(), "value")):
            with self.subTest(control=type(control).__name__):
                self.show_widget(control)
                control.setFocus()
                before = getattr(control, getter)()
                wheel(control, -120)
                wheel(control, 120)
                self.assertEqual(getattr(control, getter)(), before)

    def test_hovered_input_forwards_wheel_to_the_page_once(self):
        scroll = QScrollArea()
        body = QWidget()
        body.setMinimumHeight(1400)
        layout = QVBoxLayout(body)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(20)
        layout.addWidget(spin)
        layout.addStretch()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.resize(300, 240)
        self.show_widget(scroll)
        bar = scroll.verticalScrollBar()
        bar.setValue(100)
        wheel(scroll.viewport())
        normal_step = bar.value() - 100
        self.assertGreater(normal_step, 0)
        for focused in (False, True):
            bar.setValue(100)
            spin.setFocus() if focused else spin.clearFocus()
            wheel(spin)
            self.assertEqual(bar.value() - 100, normal_step)
            self.assertEqual(spin.value(), 20)
        before = bar.value()
        wheel(bar)
        self.assertGreater(bar.value(), before, "scrollbars must keep native wheel behavior")

    def test_dynamic_table_editor_scrolls_rows_without_changing_value(self):
        table = QTableWidget(60, 1)
        for row in range(60):
            table.setItem(row, 0, QTableWidgetItem(str(row)))
        table.resize(300, 220)
        self.show_widget(table)
        editor = QDoubleSpinBox()
        editor.setValue(35)
        table.setCellWidget(0, 0, editor)
        editor.setFocus()
        before = table.verticalScrollBar().value()
        wheel(editor.lineEdit())
        self.assertEqual(editor.value(), 35)
        self.assertGreater(table.verticalScrollBar().value(), before)

    def test_open_combo_list_scrolls_but_selection_requires_left_click(self):
        combo = QComboBox()
        combo.addItems([f"附件型号 {number}" for number in range(80)])
        combo.resize(240, 32)
        self.show_widget(combo)
        combo.showPopup()
        app.processEvents()
        view = combo.view()
        changed = QSignalSpy(combo.activated)
        bar = view.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        wheel(view.viewport())
        self.assertGreater(bar.value(), 0)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(changed.count(), 0)
        target = combo.model().index(25, 0)
        view.scrollTo(target)
        app.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(target).center())
        self.assertEqual(combo.currentIndex(), 25)
        self.assertEqual(changed.count(), 1)

    def test_left_click_spin_buttons_still_work(self):
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(20)
        spin.resize(150, 36)
        self.show_widget(spin)
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        up = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
                                         QStyle.SubControl.SC_SpinBoxUp, spin)
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=up.center())
        self.assertEqual(spin.value(), 21)

    def test_attachment_amount_stays_fixed_after_double_click_then_wheel(self):
        item = dict(quantity=1, attachments=[dict(custom=True, item_name="人工附件", quantity=1,
                    formula_amount=10, quick_amount=12)],
                    quick=dict(attachment_fee=12, total_cost=112),
                    formula=dict(attachment_fee=10, total_cost=110))
        # Start with a normalized persisted remark, not a legacy row whose
        # first editor construction intentionally adds remark metadata.
        ui._quote_item_remark(item)
        before = copy.deepcopy(item)
        dialog = self.show_widget(ui.AttachmentEditor(self.window, item))
        for column in (dialog.COL_QUANTITY, dialog.COL_UNIT_COST, dialog.COL_UNIT_AMOUNT):
            control = dialog.table.cellWidget(0, column)
            original = control.value()
            if column != dialog.COL_QUANTITY:
                QTest.mouseDClick(control.lineEdit(), Qt.MouseButton.LeftButton)
            wheel(control)
            wheel(control.lineEdit(), 120)
            self.assertEqual(control.value(), original)
        self.assertEqual(item, before)
        amount = dialog.table.cellWidget(0, dialog.COL_UNIT_AMOUNT)
        QTest.mouseDClick(amount.lineEdit(), Qt.MouseButton.LeftButton)
        QTest.keyClicks(amount.lineEdit(), "90")
        QTest.keyClick(amount.lineEdit(), Qt.Key.Key_Return)
        self.assertEqual(amount.value(), 90)
        dialog.accept()
        self.assertEqual(item["attachments"][0]["quick_amount_override"], 90)

    def test_workbench_values_and_draft_are_unchanged_by_wheel(self):
        fields = [self.window.quantity_spin, self.window.freight_spin, self.window.product_combo,
                  self.window.material_combo, self.window.coating_combo,
                  *self.window.scheme2_cost_controls.values()]
        draft = copy.deepcopy(self.window.draft_items)
        for field in fields:
            getter = field.currentIndex if isinstance(field, QComboBox) else field.value
            before = getter()
            wheel(field)
            wheel(field, 120)
            self.assertEqual(getter(), before)
        self.assertEqual(self.window.draft_items, draft)

    def test_drawing_wheel_pans_without_zoom_and_toolbar_click_zoom_works(self):
        preview = QuoteDrawingPreview(None, None)
        canvas = preview.canvas
        canvas.fit_mode = False
        canvas.setSceneRect(0, 0, 3000, 3000)
        preview.resize(650, 500)
        self.show_widget(preview)
        canvas.verticalScrollBar().setValue(100)
        before = canvas.current_scale()
        zoom = QSignalSpy(canvas.zoomed)
        wheel(canvas.viewport())
        self.assertEqual(canvas.current_scale(), before)
        self.assertEqual(zoom.count(), 0)
        self.assertGreater(canvas.verticalScrollBar().value(), 100)
        plus = next(button for button in preview.findChildren(QPushButton) if button.text() == "+")
        QTest.mouseClick(plus, Qt.MouseButton.LeftButton)
        self.assertGreater(canvas.current_scale(), before)


if __name__ == "__main__":
    unittest.main()
