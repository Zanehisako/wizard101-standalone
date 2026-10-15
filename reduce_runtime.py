#!/usr/bin/env python3
"""Remove PE debugging data only from a staged app, with byte-level checks.

Every original changed image is retained in a separate debugging archive. No
runtime module is removed and Mach-O libraries are left intact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile

APP_BUDGET = 350 * 1024**2
INSTALLER_BUDGET = 150 * 1024**2


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def installed_bytes(app):
    # Logical regular-file bytes, rounded to filesystem blocks, including links.
    return sum(((p.lstat().st_size + 4095) // 4096) * 4096
               for p in Path(app).rglob('*') if not p.is_dir() or p.is_symlink())


def pe_snapshot(path):
    """Describe load-bearing PE bytes independently of raw-file offsets.

    Strip tools may compact file offsets, remove COFF symbols and debug
    sections, and recompute checksums/SizeOfImage. They must not alter the
    virtual addresses, bytes or protection flags of any retained section.
    Imports, exports, unwind records, relocations, TLS, resources and load
    configuration therefore have to remain byte-identical at the same RVAs.
    """
    data = Path(path).read_bytes()
    if not data.startswith(b'MZ'):
        return None
    if len(data) < 64:
        raise ValueError('Truncated DOS header: ' + str(path))
    offset = struct.unpack_from('<I', data, 60)[0]
    if data[offset:offset + 4] != b'PE\0\0':
        return None  # Wine also includes old DOS/NE utility files.
    machine, count, _, symbols, symbol_count, opt_size, flags = struct.unpack_from('<HHIIIHH', data, offset + 4)
    optional = offset + 24
    magic = struct.unpack_from('<H', data, optional)[0]
    if magic not in (0x10b, 0x20b):
        raise ValueError('Unsupported PE optional header')
    directory_offset = 112 if magic == 0x20b else 96
    directory_count = struct.unpack_from('<I', data, optional + directory_offset - 4)[0]
    directories = [struct.unpack_from('<II', data, optional + directory_offset + 8 * i)
                   for i in range(min(directory_count, 16))]
    # Authenticode is a file-offset directory, not an RVA. Never invalidate it.
    if len(directories) > 4 and directories[4] != (0, 0):
        raise ValueError('Refusing to strip an Authenticode-signed PE: ' + str(path))
    strings = symbols + symbol_count * 18 if symbols else 0
    sections = {}
    debug = []
    for i in range(count):
        entry = optional + opt_size + i * 40
        name = data[entry:entry + 8].rstrip(b'\0').decode('ascii')
        if name.startswith('/'):
            start = strings + int(name[1:])
            end = data.index(b'\0', start)
            name = data[start:end].decode('ascii')
        virtual_size, rva, size, raw = struct.unpack_from('<IIII', data, entry + 8)
        characteristics = struct.unpack_from('<I', data, entry + 36)[0]
        if name.startswith(('.debug', '.zdebug')) or name == '.gnu_debuglink':
            if characteristics & (0x20000000 | 0x80000000 | 0x20):
                raise ValueError('Debug section has executable/writable flags')
            debug.append(name)
            continue
        if name in sections:
            raise ValueError('Duplicate PE section name')
        if raw and raw + size > len(data):
            raise ValueError('Truncated PE section')
        payload = data[raw:raw + size] if raw else b''
        sections[name] = dict(rva=rva, virtual_size=virtual_size,
                              raw_size=size, flags=characteristics,
                              sha256=hashlib.sha256(payload).hexdigest())
    # Keep all loader header fields apart from sizes affected by debug removal,
    # checksum, and the debug directory (which is explicitly checked below).
    loader = bytearray(data[optional:optional + opt_size])
    for start, size in [(4, 12), (56, 8), (64, 4), (directory_offset + 6 * 8, 8)]:
        loader[start:start + size] = b'\0' * size
    return dict(dos_header_and_stub=data[:offset].hex(), machine=machine, magic=magic, flags=flags & ~0x020c,
                loader_header=loader.hex(), sections=sections,
                directories=[entry for i, entry in enumerate(directories) if i != 6],
                debug_directory=directories[6] if len(directories) > 6 else (0, 0),
                debug_sections=debug, coff_symbols=symbol_count)


def verify_preserved(before, after):
    if before is None or after is None:
        raise ValueError('Expected two PE images')
    for key in ('dos_header_and_stub', 'machine', 'magic', 'flags', 'loader_header', 'sections', 'directories'):
        if before[key] != after[key]:
            raise ValueError('Strip changed load-bearing PE data: ' + key)
    if after['debug_directory'] not in ((0, 0), before['debug_directory']):
        raise ValueError('Strip changed a PE debug directory unexpectedly')
    if after['debug_sections']:
        raise ValueError('Strip retained PE debug sections')


def strip_tool(requested=None):
    candidates = [requested] if requested else [shutil.which('x86_64-w64-mingw32-strip'),
        shutil.which('llvm-strip'), '/opt/homebrew/opt/llvm/bin/llvm-strip']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise ValueError('Install LLVM or MinGW binutils, or pass --pe-strip')


def reduce(app, debug_archive, tool=None):
    app, debug_archive = Path(app).resolve(), Path(debug_archive).resolve()
    if debug_archive.is_relative_to(app) or debug_archive.exists():
        raise ValueError('Use a new debugging archive outside the app')
    tool = strip_tool(tool)
    before_size = installed_bytes(app)
    manifest = dict(tool_version=subprocess.check_output([tool, '--version'], text=True).strip(),
                    tool_sha256=sha(tool), originals={}, stripped={}, checked_pe_files=0)
    inventory = {p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file()}
    with tarfile.open(debug_archive, 'w:gz') as archive, tempfile.TemporaryDirectory(prefix='w101-pe-') as tmp:
        for path in sorted(app.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            with path.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    continue
            before = pe_snapshot(path)
            if before is None:
                continue
            manifest['checked_pe_files'] += 1
            if not before['debug_sections'] and not before['coff_symbols']:
                continue
            staged = Path(tmp) / path.name
            subprocess.run([tool, '--strip-debug', '--strip-unneeded', str(path), '-o', str(staged)],
                           check=True, capture_output=True)
            verify_preserved(before, pe_snapshot(staged))
            if staged.stat().st_size > path.stat().st_size:
                raise ValueError('Stripping increased image size: ' + str(path))
            relative = path.relative_to(app).as_posix()
            archive.add(path, arcname=relative, recursive=False)
            manifest['originals'][relative] = sha(path)
            manifest['stripped'][relative] = sha(staged)
            shutil.copystat(path, staged)
            shutil.copyfile(staged, path)
            staged.unlink()
        archive_data = json.dumps(manifest, indent=2).encode() + b'\n'
        import io
        entry = tarfile.TarInfo('DEBUG-MANIFEST.json'); entry.size = len(archive_data)
        archive.addfile(entry, io.BytesIO(archive_data))
    if inventory != {p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file()}:
        raise ValueError('Runtime inventory changed')
    # These digests are consumed by the launcher before installing its renderer.
    for name in ('d3d9', 'w101decompress'):
        image = app / ('Contents/Resources/Renderer/' + name + '.dll')
        if image.is_file():
            image.with_suffix('.sha256').write_text(sha(image) + '\n')
    report = dict(before_bytes=before_size, after_bytes=installed_bytes(app),
                  checked_pe_files=manifest['checked_pe_files'], stripped_files=len(manifest['stripped']),
                  preservation_verified=True, modules_removed=0, debug_archive_sha256=sha(debug_archive),
                  files={name: dict(original_sha256=digest, stripped_sha256=manifest['stripped'][name])
                         for name, digest in manifest['originals'].items()})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('staged_app', type=Path)
    parser.add_argument('--debug-archive', required=True, type=Path)
    parser.add_argument('--pe-strip')
    args = parser.parse_args()
    print(json.dumps(reduce(args.staged_app, args.debug_archive, args.pe_strip), indent=2))
