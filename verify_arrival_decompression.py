#!/usr/bin/env python3
"""Exercise the hash/signature-bound WAD caller in the bundled Wine runtime."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from build_decompression import adapter
from build_runtime import ROOT, sha
from build_workload import clone
from game_context import PEIdentity

def verify(app, data, output, libraries):
    app, data, output, libraries = map(lambda p: Path(p).resolve(), (app, data, output, libraries))
    output.mkdir(parents=True, exist_ok=False)
    runtime = app / 'Contents/Resources/Runtime'
    production = app / 'Contents/Resources/Renderer/w101decompress.dll'
    checks = {}
    with tempfile.TemporaryDirectory(prefix='w101-wad-scope-') as temporary:
        folder = Path(temporary)
        clone(data / 'Prefix', folder / 'Prefix')
        source = data / 'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin/zlib1v142x64.dll'
        shutil.copy2(source, folder / source.name)
        definition = folder / 'zlib.def'
        definition.write_text('LIBRARY zlib1v142x64.dll\nEXPORTS\nuncompress\ninflateInit_\ninflate\ninflateReset\ninflateEnd\n')
        subprocess.run(['x86_64-w64-mingw32-dlltool', '-d', str(definition), '-l', str(folder / 'zlib.a')], check=True)
        exe = folder / 'decompression_probe.exe'
        subprocess.run(['x86_64-w64-mingw32-gcc', '-DW101_WAD_TEST', '-std=c11', '-O3', '-static',
                        str(ROOT / 'tests/decompression_probe.c'), str(ROOT / 'tests/wad_caller.S'),
                        str(folder / 'zlib.a'), '-Wl,--section-start,.wad=0x141509000',
                        '-Wl,--section-start,.wthunk=0x142459000', '-o', str(exe)], check=True)
        pe=PEIdentity(exe)
        if pe.bytes_at(0x150934a,16).hex()!='488d942490000000488bcfe8cefff400':
            raise RuntimeError('Fixture does not reproduce the exact WAD call signature')
        dll = adapter(folder, sha(exe), native=True, libraries_work=libraries)
        shutil.copy2(production, folder / 'w101decompress.dll')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('W101_', 'WINE', 'DYLD_', 'CX_', 'CROSSOVER', 'DXVK_', 'MVK_', 'VK_'))}
        env.update(WINEPREFIX=str(folder / 'Prefix'), WINEARCH='win64', WINEDEBUG='-all', WINEMSYNC='1',
                   WINEDLLPATH=str(runtime / 'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime / 'lib') + ':/usr/lib',
                   WINEDLLOVERRIDES='zlib1v142x64=n;winemenubuilder.exe=d;winedbg.exe=d')
        try:
            for mode, kind, decoder in [('both', 'reject', 'w101decompress.dll'),
                                         ('buffer', 'compat', dll.name), ('stream', 'compat', dll.name),
                                         ('both', 'compat', dll.name), ('both', 'bad-signature', dll.name)]:
                label = mode + '-' + kind
                with (output / (label + '.txt')).open('w') as log:
                    result = subprocess.run([str(runtime / 'bin/wine'), str(exe), decoder, kind], cwd=folder,
                                            env=env | {'W101_DECOMPRESS': mode}, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                text = (output / (label + '.txt')).read_text(errors='replace')
                if result.returncode or 'PASS' not in text:
                    raise RuntimeError(label + ': ' + text[-2500:])
                if kind == 'compat' and 'PASS WAD caller' not in text:
                    raise RuntimeError('Small caller boundaries were not exercised')
                checks[label] = True
        finally:
            subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=20)
    inputs = ['verify_arrival_decompression.py', 'tests/decompression_probe.c', 'tests/wad_caller.S',
              'decompression/Adapter.c', 'decompression/Identity.h', 'build_decompression.py']
    report = dict(passed=True, synthetic_only=True, adapter_sha256=sha(production), checks=checks,
                  inputs={name: sha(ROOT / name) for name in inputs}, gameplay_accepted=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--data', type=Path, default=Path.home() / 'Library/Application Support/Wizard101 Metal Cache/Data')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--libraries', type=Path, default=Path('/private/tmp/w101-combined'))
    a = p.parse_args()
    print(json.dumps(verify(a.app, a.data, a.output, a.libraries), indent=2))
