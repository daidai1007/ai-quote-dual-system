"""Run offline Qt restore regressions using modules embedded in the new EXE."""
import importlib.abc
import importlib.util
import marshal
import os
from pathlib import Path
import runpy
import sys

from PyInstaller.archive.readers import CArchiveReader

root = Path(__file__).resolve().parents[1]
entry = Path(sys.argv[1]).resolve()
archive = CArchiveReader(str(entry))
pyz = archive.open_embedded_archive('PYZ.pyz')
local_names = {path.stem for path in (root / 'desktop_client').glob('*.py')}
loaded = set()


class EmbeddedClient(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path=None, target=None):
        if name in local_names and (name == 'v3_launcher' or name in pyz.toc):
            return importlib.util.spec_from_loader(name, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        module.__file__ = str(entry.parent / '_internal' / f'{name}.py')
        code = marshal.loads(archive.extract(name)) if name == 'v3_launcher' else pyz.extract(name)
        loaded.add(name)
        exec(code, module.__dict__)


os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['AI_QUOTE_V3_CORE_ROOT'] = str(entry.parent / '_internal' / 'v3_core')
sys.meta_path.insert(0, EmbeddedClient())
sys.path.insert(0, str(root / 'tests'))
test = str(root / 'tests' / 'verify_quote_scheme_restore.py')
sys.argv = [test, '--worker']
try:
    runpy.run_path(test, run_name='__main__')
except SystemExit as error:
    if error.code not in (None, 0):
        raise
required = {'v3_launcher', 'scheme2_ui', 'quote_scheme_center', 'quote_scheme_widgets'}
assert required <= loaded, f'Not tested from embedded archive: {required - loaded}'
print('EMBEDDED_EXE_RESTORE_REGRESSION=PASS')
print('EMBEDDED_MODULE_COUNT=' + str(len(loaded)))
