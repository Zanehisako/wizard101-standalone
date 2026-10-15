#!/usr/bin/env python3
"""Rebuild the retained Wine Unix bridge from pinned sources for macOS 13.

Windows ntdll, renderer, Metal backend, and the user's app remain unchanged.
This rebuild avoids changing a deployment version label on existing machine code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from build_runtime import ROOT, sha

SOURCE_NAME = 'crossover-sources-26.3.0.tar.gz'

def replace(text, before, after):
    if text.count(before) != 1: raise ValueError('Wine source integration differs: ' + before[:80])
    return text.replace(before, after, 1)

def rebuild(work):
    work = Path(work).resolve()
    if any(c.isspace() for c in str(work)): raise ValueError('Build path must not contain spaces')
    work.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'cache' / SOURCE_NAME
    lock = json.loads((ROOT / 'sources.lock.json').read_text())[SOURCE_NAME]
    if sha(archive) != lock['sha256']: raise ValueError('Pinned Wine sources changed')
    source = work / 'sources/wine'
    if not (source / 'configure').is_file():
        with tarfile.open(archive) as tar:
            tar.extractall(work, members=[m for m in tar.getmembers() if m.name.startswith('sources/wine/')], filter='data')
    marker = source / '.shipping-overlay.json'
    inputs = {'rebuild_shipping_wine.py': sha(Path(__file__)), 'sources.lock.json': sha(ROOT / 'sources.lock.json')}
    for relative in ['performance/WineLockNative.h', 'decompression/NativeClient.h', 'decompression/NativeProtocol.h', 'workload/WineThreadIdentity.h']:
        inputs[relative] = sha(ROOT / relative)
    if marker.exists():
        if json.loads(marker.read_text()) != inputs: raise ValueError('Rebuild sources changed; choose a fresh work directory')
    else:
        unix = source / 'dlls/ntdll/unix'
        for relative in ['performance/WineLockNative.h', 'decompression/NativeClient.h', 'decompression/NativeProtocol.h', 'workload/WineThreadIdentity.h']:
            shutil.copy2(ROOT / relative, unix / Path(relative).name)
        lib = source / 'dlls/ntdll/unixlib.h'
        lib.write_text(replace(lib.read_text(), '    unix_pe_module_loaded,\n#endif',
            '    unix_pe_module_loaded,\n#endif\n    unix_w101_lock_begin,\n    unix_w101_lock_end,\n    unix_w101_native_decode,'))
        loader = unix / 'loader.c'
        text = replace(loader.read_text(), 'static const unixlib_entry_t unix_call_funcs[] =',
            '#include "WineLockNative.h"\n#include "NativeClient.h"\n\nstatic const unixlib_entry_t unix_call_funcs[] =')
        end = text.index('\n};', text.index('static const unixlib_entry_t unix_call_funcs[]'))
        text = text[:end] + '\n    w101_lock_begin_native,\n    w101_lock_end_native,\n    w101_native_dispatch,' + text[end:]
        loader.write_text(text)
        server = unix / 'server.c'
        text = replace(server.read_text(), 'static int get_unix_tid(void)', '#include "WineThreadIdentity.h"\n\nstatic int get_unix_tid(void)')
        text = replace(text, 'set_thread_id( NtCurrentTeb(), pid, tid );', 'set_thread_id( NtCurrentTeb(), pid, tid );\n    w101_thread_identity(tid, 1);')
        start = text.index('void server_init_thread('); end = text.index('\nNTSTATUS WINAPI NtAllocateReserveObject', start)
        text = text[:start] + replace(text[start:end], 'close( reply_pipe );', 'close( reply_pipe );\n    w101_thread_identity(HandleToULong(NtCurrentTeb()->ClientId.UniqueThread), 0);') + text[end:]
        server.write_text(text)
        marker.write_text(json.dumps(inputs, indent=2) + '\n')
    output = work / 'build-wine'; output.mkdir(exist_ok=True)
    env = dict(os.environ, PATH='/opt/homebrew/opt/bison/bin:/opt/homebrew/opt/libtool/libexec/gnubin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
               MACOSX_DEPLOYMENT_TARGET='13.0', CC='clang -arch x86_64', CXX='clang++ -arch x86_64',
               CFLAGS='-O2 -std=gnu11 -mmacosx-version-min=13.0', CXXFLAGS='-O2 -mmacosx-version-min=13.0',
               LDFLAGS='-mmacosx-version-min=13.0', PKG_CONFIG_PATH='', PKG_CONFIG_LIBDIR='/nonexistent')
    def run(command, log):
        with (work / log).open('w') as stream:
            subprocess.run(command, cwd=output, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if not (output / 'Makefile').is_file():
        run([str(source/'configure'), '--prefix=/usr/local/w101', '--host=x86_64-apple-darwin', '--build=x86_64-apple-darwin',
             '--enable-win64', '--disable-tests', '--without-x', '--without-cups', '--without-dbus', '--without-gstreamer',
             '--without-oss', '--without-pulse', '--without-alsa', '--without-sane', '--without-usb', '--without-v4l2',
             '--without-pcap', '--without-krb5', '--without-freetype', '--without-gnutls'], 'configure.log')
    run(['make', '-j4', 'dlls/ntdll/ntdll.so'], 'build.log')
    library = output / 'dlls/ntdll/ntdll.so'
    subprocess.run(['install_name_tool', '-id', '@rpath/ntdll.so', str(library)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(library)], check=True, capture_output=True)
    commands = subprocess.check_output(['otool', '-l', str(library)], text=True)
    if 'minos 13.0' not in commands: raise ValueError('Rebuilt bridge does not target macOS 13.0')
    metadata = dict(inputs=inputs, library_sha256=sha(library), target='x86_64-apple-macosx13.0',
                    source_archive_sha256=lock['sha256'], retained_unix_dispatch_order=True, game_or_renderer_changed=False)
    (work / 'shipping-wine.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(library)
    return library

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path('/private/tmp/w101-shipping-wine'))
    rebuild(parser.parse_args().work)
