"""Verify the versioned V3 core without executing it or starting the client."""
import argparse
import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import struct
import sys
import types
import zlib


DEFAULT_CORE = Path(__file__).resolve().parents[1] / 'desktop_client' / 'v3_core'


def verify_core(root=DEFAULT_CORE):
    if sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 12):
        raise ValueError('V3 core requires CPython 3.12 for bytecode verification')
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported V3 core manifest version')
    records = manifest.get('files') or []
    names = [row['path'] for row in records]
    expected = {'main.raw', 'bundled_api.raw', 'drawing_assembly.raw', 'drawing_features.raw',
                'drawing_review.raw', 'drawing_specification.raw', 'ocr_consensus.raw',
                'workbench_ui.raw', 'original.pyz'}
    if len(names) != len(expected) or set(names) != expected:
        raise ValueError('V3 core manifest must contain exactly the nine required files')
    actual = {p.name for p in root.iterdir() if p.suffix in ('.raw', '.pyz')}
    if actual != expected:
        raise ValueError('V3 core file inventory differs from manifest')
    for row in records:
        path = root / row['path']
        data = path.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError(f'V3 core size/SHA-256 mismatch: {path.name}')
        if path.suffix == '.raw' and not isinstance(marshal.loads(data), types.CodeType):
            raise ValueError(f'Invalid CPython code object: {path.name}')
    archive = (root / 'original.pyz').read_bytes()
    if archive[:4] != b'PYZ\0' or archive[4:8] != importlib.util.MAGIC_NUMBER:
        raise ValueError('V3 dependency archive has incompatible Python magic')
    offset = struct.unpack('!i', archive[8:12])[0]
    if not 12 <= offset < len(archive):
        raise ValueError('Invalid V3 dependency archive table offset')
    toc = dict(marshal.loads(archive[offset:]))
    if len(toc) != manifest['archive_modules']:
        raise ValueError('V3 dependency archive module count mismatch')
    for name, (kind, position, length) in toc.items():
        # Namespace packages have a TOC entry and no compressed code payload.
        if kind == 3:
            if length != 0:
                raise ValueError(f'Invalid archived namespace package: {name}')
            continue
        if kind not in (0, 1):
            raise ValueError(f'Unexpected archived module type: {name}')
        if not 12 <= position < position + length <= offset:
            raise ValueError(f'Invalid archived module offset: {name}')
        if not isinstance(marshal.loads(zlib.decompress(archive[position:position + length])), types.CodeType):
            raise ValueError(f'Invalid archived code object: {name}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, default=DEFAULT_CORE)
    args = parser.parse_args()
    try:
        manifest = verify_core(args.core)
    except (OSError, ValueError, KeyError, TypeError, EOFError, zlib.error, struct.error) as error:
        parser.exit(1, f'V3 core verification failed: {error}\n')
    print(f"PASS: {len(manifest['files'])} core files and {manifest['archive_modules']} archived modules; SHA-256 and CPython 3.12 bytecode verified")


if __name__ == '__main__':
    main()
