"""Prove the packaged modules contain this checkout's current fixes."""
from pathlib import Path
import sys
from types import CodeType
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader


def fingerprint(value):
    if isinstance(value, CodeType):
        return (value.co_name, value.co_argcount, value.co_posonlyargcount,
                value.co_kwonlyargcount, value.co_flags, value.co_code,
                value.co_names, value.co_varnames, value.co_freevars, value.co_cellvars,
                tuple(fingerprint(item) for item in value.co_consts))
    return value


root = Path(__file__).resolve().parents[1]
archive = ZlibArchiveReader(sys.argv[1])
for module in ('scheme2_ui', 'attachment_v2_client', 'attachment_category_browser', 'quick_discount_rules'):
    path = root / 'desktop_client' / (module + '.py')
    source = compile(path.read_text(encoding='utf-8'), str(path), 'exec', dont_inherit=True, optimize=0)
    assert fingerprint(archive.extract(module)) == fingerprint(source), module + ' differs from current source'
    print('PASS: packaged module matches current source: ' + module)
