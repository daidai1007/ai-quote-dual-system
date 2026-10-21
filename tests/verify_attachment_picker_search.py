"""Real picker search/filter/selection regression, with no API or database."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox,QLabel,QScrollArea,QToolButton
from dialog_style import install_dialog_style
import scheme2_ui as ui
from attachment_v2_client import match_catalog_attachment

app=QApplication.instance() or QApplication([])
app.setStyle('Fusion')
font_id=QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
families=QFontDatabase.applicationFontFamilies(font_id)
if families:
    app.setFont(QFont(families[0],10))
install_dialog_style()


class PickerSearch(unittest.TestCase):
    def setUp(self):
        self.selected=[dict(item_name='照明灯24V-0.6m',category_level1='照明灯/行程开关',quantity=1),
                       dict(custom=True,item_name='木托',quantity=1,formula_amount=20,quick_amount=24)]
        self.dialog=ui._SchemeAttachmentDialog(copy.deepcopy(self.selected),'JA')
        self.dialog.resize(420,620)
        self.dialog.show()
        app.processEvents()

    def tearDown(self):
        self.dialog.reject()
        app.processEvents()

    def search(self,text):
        self.dialog.search_edit.setText(text)
        app.processEvents()

    def visible_categories(self):
        return [category for category,card in self.dialog.category_cards.items() if not card.isHidden()]

    def test_hint_removed_and_search_fixed_above_list(self):
        self.assertFalse(any('勾选附件' in label.text() for label in self.dialog.findChildren(QLabel)))
        field=self.dialog.search_edit
        self.assertIn('搜索附件',field.placeholderText())
        scroll=self.dialog.findChild(QScrollArea)
        position=field.mapTo(self.dialog,field.rect().bottomLeft())
        self.assertLess(position.y(),scroll.mapTo(self.dialog,scroll.rect().topLeft()).y())
        field.setFocus()
        QTest.keyClick(field,Qt.Key_Return)
        app.processEvents()
        self.assertTrue(self.dialog.isVisible())

    def test_model_search_filters_options_and_mouse_select_preserves_other_selections(self):
        before=self.dialog.collect_attachments()
        self.search('风机 ｓｇ２２０６０')
        self.assertEqual(self.visible_categories(),['风机'])
        combo=self.dialog.category_combos['风机']
        visible=[row for row in range(1,combo.count()) if not combo.view().isRowHidden(row)]
        self.assertEqual(len(visible),1)
        self.assertIn('SG22060',combo.itemText(visible[0]))
        self.assertEqual(self.dialog.collect_attachments(),before)
        combo.showPopup()
        app.processEvents()
        index=combo.model().index(visible[0],0)
        QTest.mouseClick(combo.view().viewport(),Qt.LeftButton,pos=combo.view().visualRect(index).center())
        app.processEvents()
        combo.hidePopup()
        names=[row['item_name'] for row in self.dialog.collect_attachments()]
        self.assertIn(combo.itemText(visible[0]),names)
        self.assertIn('照明灯24V-0.6m',names)
        self.assertIn('木托',names)
        self.dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        self.assertEqual(self.dialog.result(),QDialog.Accepted)

    def test_category_search_no_results_and_clear_restore_without_losing_selection(self):
        before=self.dialog.collect_attachments()
        self.search('照明灯/行程开关')
        self.assertEqual(self.visible_categories(),['照明灯/行程开关'])
        combo=self.dialog.category_combos['照明灯/行程开关']
        self.assertTrue(all(not combo.view().isRowHidden(row) for row in range(combo.count())))
        self.search('不存在的附件xyz')
        self.assertEqual(self.visible_categories(),[])
        self.assertTrue(self.dialog.search_empty.isVisible())
        self.assertEqual(self.dialog.collect_attachments(),before)
        clear=next(button for button in self.dialog.search_edit.findChildren(QToolButton) if button.isVisible())
        clear.click()
        app.processEvents()
        self.assertEqual(self.dialog.search_edit.text(),'')
        self.assertEqual(self.visible_categories(),self.dialog.category_names)
        self.assertFalse(self.dialog.search_empty.isVisible())
        self.assertTrue(all(not combo.view().isRowHidden(row) for row in range(combo.count())))
        self.assertEqual(self.dialog.collect_attachments(),before)

    def test_new_ka22060_fan_order_search_selection_and_catalogue_match(self):
        name='KA22060HA2B/220V（卡固）'
        old_fans=('KA1238HA2/B(卡固)','KA1238DC/24V(卡固)','KA1725HA2/B(卡固)',
                  'KA1725DC/24V(卡固)','KA2072HA2/B(卡固)','KA1238HA2/B（国产）',
                  'KA1725HA2/B（国产）','KA1725DC/24V（国产）','KA2072HA2/B（国产）',
                  'SG22060HA2/220V（国产）')
        self.assertEqual(ui.ATTACHMENT_OPTIONS['风机'],(*old_fans,name))
        self.assertEqual(ui.ATTACHMENT_OPTIONS['风机'].count(name),1)
        self.search('KA22060')
        self.assertEqual(self.visible_categories(),['风机'])
        combo=self.dialog.category_combos['风机']
        row=combo.findText(name)
        self.assertEqual(row,combo.findText(old_fans[-1])+1)
        self.assertFalse(combo.view().isRowHidden(row))
        combo.showPopup();app.processEvents()
        index=combo.model().index(row,0)
        QTest.mouseClick(combo.view().viewport(),Qt.LeftButton,pos=combo.view().visualRect(index).center())
        app.processEvents();combo.hidePopup()
        selected=self.dialog.collect_attachments()
        fan=next(item for item in selected if item['item_name']==name)
        self.assertEqual(fan['category_level1'],'风机')
        self.assertEqual(fan['quantity'],1)
        self.assertTrue({'照明灯24V-0.6m','木托'}.issubset({item['item_name'] for item in selected}))
        fixture=json.loads((ROOT/'tests/fixtures/fan_ka22060ha2b.json').read_text(encoding='utf-8'))
        previous=dict(attachment_price_id=37,category_level1='风机',item_name='风机'+old_fans[-1],price=120)
        before=copy.deepcopy([previous,fixture])
        for query in ('KA22060',name,'风机 '+name):
            self.search(query)
            self.assertFalse(combo.view().isRowHidden(row))
        for product in ('JS','JP','JA','JE','JM','JK','JP_WIDE_EXP','JS_WIDE_EXP'):
            matched=match_catalog_attachment(fan,[previous,fixture],product_code=product)
            self.assertEqual(matched['attachment_price_id'],1237)
            self.assertIsNone(matched['model_code'])
        self.assertEqual([previous,fixture],before)
        self.assertEqual(match_catalog_attachment(dict(category_level1='风机',item_name=old_fans[-1]),
                                                [previous,fixture])['attachment_price_id'],37)
        for product in ('JS','JP','JA','JE','JM','JK','JP_WIDE_EXP','JS_WIDE_EXP'):
            dialog=ui._SchemeAttachmentDialog([],product)
            self.assertGreater(dialog.category_combos['风机'].findText(name),0)
            dialog.reject();dialog.deleteLater()
        out=ROOT/'outputs'/('attachment-picker-search-'+os.environ.get('QT_SCALE_FACTOR','1'))
        out.mkdir(parents=True,exist_ok=True)
        self.assertTrue(self.dialog.grab().save(str(out/'new-ka22060-fan.png')))

    def test_specific_option_search_can_add_beside_a_hidden_selected_option(self):
        self.search('行程')
        combo=self.dialog.category_combos['照明灯/行程开关']
        self.assertTrue(combo.view().isRowHidden(combo.findText('照明灯24V-0.6m')))
        row=combo.findText('行程开关')
        self.assertFalse(combo.view().isRowHidden(row))
        combo.showPopup()
        app.processEvents()
        index=combo.model().index(row,0)
        self.assertEqual(combo.view().currentIndex(),index)
        QTest.mouseClick(combo.view().viewport(),Qt.LeftButton,pos=combo.view().visualRect(index).center())
        app.processEvents()
        combo.hidePopup()
        self.assertEqual(set(combo.selected_texts()),{'行程开关','照明灯24V-0.6m'})
        self.search('')
        self.assertEqual(set(combo.selected_texts()),{'行程开关','照明灯24V-0.6m'})

    def test_direct_checkbox_product_scope_and_cancel_still_work(self):
        before=copy.deepcopy(self.selected)
        self.search('安装板')
        self.assertNotIn('控制柜附件',self.visible_categories())
        self.assertNotIn('侧板',self.visible_categories())
        self.assertNotIn('JK安装板',[self.dialog.category_combos['控制箱附件'].itemText(row)
                                   for row in range(self.dialog.category_combos['控制箱附件'].count())])
        self.dialog.direct_checks['安装板'].click()
        self.assertIn('安装板',[row['item_name'] for row in self.dialog.collect_attachments()])
        self.dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).click()
        self.assertEqual(self.dialog.result(),QDialog.Rejected)
        self.assertEqual(self.selected,before)

    def test_search_screenshots_and_resize_keeps_footer_visible(self):
        for size in ((380,400),(420,620)):
            self.dialog.resize(*size)
            self.search('照明')
            for button in self.dialog.findChild(QDialogButtonBox).buttons():
                self.assertLess(button.mapTo(self.dialog,button.rect().bottomRight()).y(),self.dialog.height())
        out=ROOT/'outputs'/('attachment-picker-search-'+os.environ.get('QT_SCALE_FACTOR','1'))
        out.mkdir(parents=True,exist_ok=True)
        self.assertTrue(self.dialog.grab().save(str(out/'search.png')))


if __name__=='__main__':
    unittest.main()
