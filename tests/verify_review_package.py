"""Verify an isolated review EXE contains the current source and unchanged core."""
import hashlib
import json
import marshal
from pathlib import Path
import sys
import tempfile
import types
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def normalized(code):
    return code.replace(co_filename='', co_consts=tuple(
        normalized(value) if isinstance(value, types.CodeType) else value for value in code.co_consts))


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory):
    directory = Path(directory).resolve()
    current = ROOT.parent / 'AIQuoteDualSystem'
    entry = directory / 'AIQuoteDualSystem_layout_v6.exe'
    reader = CArchiveReader(str(entry))
    checked = []
    with tempfile.TemporaryDirectory(prefix='quote-package-check-') as folder:
        pyz_path = Path(folder) / 'bundle.pyz'
        pyz_path.write_bytes(reader.extract('PYZ.pyz'))
        pyz = ZlibArchiveReader(str(pyz_path))
        for name in ('drawing_workflow', 'quote_drawing_preview', 'freight_state', 'freight_export', 'layout_refresh',
                     'attachment_v2_client', 'attachment_category_browser', 'quick_discount_rules', 'scheme2_ui'):
            expected = compile((ROOT / 'desktop_client' / f'{name}.py').read_text(encoding='utf-8'), '', 'exec')
            actual = pyz.extract(name)
            assert normalized(expected) == normalized(actual), f'Packaged source differs: {name}'
            checked.append(name)
        for name in ('ezdxf.addons.drawing.svg', 'PIL.Image', 'fontTools.ttLib', 'pypdf'):
            assert name in pyz.toc, f'Missing renderer module: {name}'
        actual = marshal.loads(reader.extract('v3_launcher'))
        expected = compile((ROOT / 'desktop_client/v3_launcher.py').read_text(encoding='utf-8'), '', 'exec')
        assert normalized(expected) == normalized(actual), 'Packaged launcher differs'
    assert hash_file(current / 'client_config.json') == hash_file(directory / 'client_config.json')
    for source in (current / '_internal/v3_core').rglob('*'):
        if source.is_file():
            target = directory / '_internal/v3_core' / source.relative_to(current / '_internal/v3_core')
            assert target.is_file() and hash_file(source) == hash_file(target), f'Runtime core differs: {source.name}'
    assert list((directory / 'runtime').rglob('pdftoppm.exe')), 'Missing PDF renderer'
    assert list((directory / '_internal/PySide6').rglob('QtSvg.pyd')), 'Missing Qt SVG module'
    return {'current_source_in_exe': checked + ['v3_launcher'], 'config_identical': True,
            'all_recovered_core_files_identical': True, 'render_dependencies_present': True,
            'sha256': hash_file(entry)}


if __name__ == '__main__':
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=False, indent=2))
