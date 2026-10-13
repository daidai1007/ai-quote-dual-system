"""Render the installed EXE's actual picker offline; never load user orders."""
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT.parent/'AIQuoteDualSystem'
ENTRY=LIVE/'AIQuoteDualSystem_layout_v0.exe'
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['AI_QUOTE_V3_CORE_ROOT']=str(LIVE/'_internal'/'v3_core')
from PyInstaller.archive.readers import CArchiveReader
archive=CArchiveReader(str(ENTRY)).open_embedded_archive('PYZ.pyz')
names={path.stem for path in (ROOT/'desktop_client').glob('*.py')
       if path.stem in archive.toc and path.stem!='v3_launcher'}

class InstalledModules(importlib.abc.MetaPathFinder,importlib.abc.Loader):
    def find_spec(self,fullname,path=None,target=None):
        if fullname in names:
            return importlib.util.spec_from_loader(fullname,self)
    def create_module(self,spec):return None
    def exec_module(self,module):
        module.__file__=str(LIVE/'_internal'/(module.__name__+'.py'))
        exec(archive.extract(module.__name__),module.__dict__)

sys.meta_path.insert(0,InstalledModules())
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtWidgets import QApplication,QTableWidget,QPushButton,QLabel,QCheckBox,QScrollArea
from PySide6.QtGui import QFontDatabase
import v3_launcher
import scheme2_ui as ui
ns=v3_launcher.load_v3_namespace()
Window=ns['MainWindow']
Window.load_catalogs=lambda self:None
Window.refresh_formula_inputs=lambda self,*args:None
ns['ApiWorker'].run=lambda self:self.failed.emit('offline installed-UI diagnostic: no network')
app=QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
window=Window()
window.resize(1280,850)
window.attachments=[dict(item_name='安装板',category_level1='安装板',quantity=1)]
window.show_section(ui.OPTION_ROUTE)
window.show()
app.processEvents()
anchor=window.findChild(QScrollArea,'scheme2OptionScroll')
assert anchor is not None
ui._open_attachment_overlay(window,ns['AttachmentDialog'],anchor)
app.processEvents()
dialog=window._scheme2_attachment_overlay
assert isinstance(dialog,ui._SchemeAttachmentDialog)
labels=[widget.text() for cls in (QPushButton,QLabel,QCheckBox) for widget in dialog.findChildren(cls)]
price_labels=[text for text in labels if any(word in text for word in ('价格','面价','加价','扣减'))]
output=ROOT/'outputs'/'installed-2026.10.12.07-attachment-picker.png'
assert dialog.grab().save(str(output))
print(json.dumps(dict(executable=str(ENTRY),picker_class=type(dialog).__name__,
    installed_module_file=ui.__file__,price_labels=price_labels,
    tables=len(dialog.findChildren(QTableWidget)),
    installation_board_check='安装板' in dialog.direct_checks,
    screenshot=str(output),capture_kind='offline rendering of installed EXE code',
    network_requests=0),ensure_ascii=False))
dialog.reject()
window._scheme2_dirty=False
window.close()
