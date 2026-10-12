"""Prove the packaged modules contain this checkout's current fixes."""
from pathlib import Path
import sys
import tempfile
from types import CodeType
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader


def fingerprint(value):
    if isinstance(value, CodeType):
        return (value.co_name, value.co_argcount, value.co_posonlyargcount,
                value.co_kwonlyargcount, value.co_flags, value.co_code,
                value.co_names, value.co_varnames, value.co_freevars, value.co_cellvars,
                tuple(fingerprint(item) for item in value.co_consts))
    return value


root = Path(__file__).resolve().parents[1]
archive_path = Path(sys.argv[1])
temporary_archive = None
try:
    try:
        archive = ZlibArchiveReader(str(archive_path))
    except Exception as direct_error:
        # A one-folder client stores the PYZ inside its executable CArchive.
        container = CArchiveReader(str(archive_path))
        embedded_pyz = container.extract('PYZ.pyz')
        temporary_archive = tempfile.NamedTemporaryFile(suffix='.pyz', delete=False)
        temporary_archive.write(embedded_pyz)
        temporary_archive.close()
        archive = ZlibArchiveReader(temporary_archive.name)
except Exception:
    if temporary_archive is not None:
        Path(temporary_archive.name).unlink(missing_ok=True)
    raise
for module in ('scheme2_ui', 'layout_refresh', 'attachment_v2_client', 'attachment_category_browser', 'quick_discount_rules', 'quote_document_progress'):
    path = root / 'desktop_client' / (module + '.py')
    source = compile(path.read_text(encoding='utf-8'), str(path), 'exec', dont_inherit=True, optimize=0)
    assert fingerprint(archive.extract(module)) == fingerprint(source), module + ' differs from current source'
    print('PASS: packaged module matches current source: ' + module)
if temporary_archive is not None:
    Path(temporary_archive.name).unlink(missing_ok=True)
