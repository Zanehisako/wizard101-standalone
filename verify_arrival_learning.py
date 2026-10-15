#!/usr/bin/env python3
"""Verify saved pipeline replay/reuse and alternating workloads in disposable clones."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import statistics
import struct
import subprocess
import tempfile
from build_runtime import ROOT, sha
from build_workload import clone

HEADER = struct.Struct('<IIQ20s20s')
REUSE_EXPORT = 'W101VerifyArrivalPipelineReuse'


def compatibility_key(app, data):
    """Same file order and Foundation OS version string as LaunchPlan."""
    runtime = app / 'Contents/Resources/Runtime'
    bin_dir = data / 'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin'
    files = [bin_dir / 'd3d9.dll', runtime / 'lib/libMoltenVK.dylib',
             bin_dir / 'WizardGraphicalClient.exe', bin_dir / 'd3dx9_43.dll']
    os_version = subprocess.check_output(
        ['swift', '-e', 'import Foundation; print(ProcessInfo.processInfo.operatingSystemVersionString)'],
        text=True).strip()
    hashes = {str(p): sha(p) for p in files}
    key = hashlib.sha256((''.join(hashes.values()) + os_version).encode()).hexdigest()
    return key, hashes, os_version


def envelope(path, key):
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise RuntimeError('Truncated saved input: ' + str(path))
    magic, version, size, identity, checksum = HEADER.unpack_from(data)
    payload = data[HEADER.size:]
    if (magic, version, size, checksum) != (0x31435057, 1, len(payload), hashlib.sha1(payload).digest()):
        raise RuntimeError('Invalid saved input: ' + str(path))
    if identity != hashlib.sha1(key.encode()).digest():
        raise RuntimeError('Saved input does not match the candidate compatibility key: ' + str(path))
    return dict(bytes=len(data), records=struct.unpack_from('<I', payload)[0]
                if path.name.endswith('inputs.v1') else None, sha256=sha(path))


def verification_renderer(work, folder, renderer, build_log):
    """Relink one instrumented TU; production DLL, source and ABI stay untouched."""
    if sha(work / 'build-renderer/src/d3d9/d3d9.dll') != sha(renderer):
        raise RuntimeError('Source build does not match the delivered renderer')
    source, output = folder / 'renderer', folder / 'build-renderer'
    clone(work / 'renderer', source)
    clone(work / 'build-renderer', output)
    for name, declaration in [
        ('dxvk_device.h', 'class DxvkDevice : public RcObject {'),
        ('dxvk_pipemanager.h', 'class DxvkPipelineManager {'),
        ('dxvk_graphics.h', 'class DxvkGraphicsPipeline {'),
        ('dxvk_state_cache.h', 'class DxvkStateCache : public RcObject {'),
    ]:
        path = source / 'src/dxvk' / name
        text = path.read_text()
        if text.count(declaration) != 1:
            raise RuntimeError('Verification friendship target changed: ' + name)
        path.write_text(text.replace(declaration, declaration + '\n    friend struct ArrivalPipelineVerificationProbe;'))
    shutil.copy2(ROOT / 'tests/arrival_pipeline_reuse.h', source / 'src/d3d9/arrival_pipeline_reuse.h')
    with (source / 'src/d3d9/d3d9_device.cpp').open('a') as out:
        out.write('\n#include "arrival_pipeline_reuse.h"\n')
    commands = subprocess.check_output(
        ['ninja', '-C', str(work / 'build-renderer'), '-t', 'commands', 'src/d3d9/d3d9.dll'], text=True)
    commands = commands.replace('../workload-d9vk', '../renderer').replace(str(work / 'renderer'), str(source))
    command = next(shlex.split(c) for c in commands.splitlines() if ' -c ' in c and 'd3d9_device.cpp' in c)
    with build_log.open('w') as log:
        subprocess.run(command, cwd=output, stdout=log, stderr=log, check=True)
        link = shlex.split(commands.splitlines()[-1])
        link.extend(str(work / ('mh-' + name + '.o')) for name in ('buffer', 'hook', 'trampoline', 'hde64'))
        subprocess.run(link, cwd=output, stdout=log, stderr=log, check=True)
    return output / 'src/d3d9/d3d9.dll'


def fields(text, label):
    lines = [line for line in text.splitlines() if line.startswith(label + ' ')]
    if len(lines) != 1:
        raise RuntimeError('Missing/duplicate ' + label + ': ' + text[-1500:])
    return {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', lines[0])}


def verify(app, data, output, work):
    app, data, output, work = (Path(p).resolve() for p in (app, data, output, work))
    output.mkdir(parents=True, exist_ok=False)
    runtime = app / 'Contents/Resources/Runtime'
    renderer = app / 'Contents/Resources/Renderer/d3d9.dll'
    bin_dir = data / 'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin'
    base = data / 'Prefix/drive_c/graphics-patch-cache/Wizard101'
    saved = base / 'Arrival'
    key, identities, os_version = compatibility_key(app, data)
    if identities[str(bin_dir / 'd3d9.dll')] != sha(renderer):
        raise RuntimeError('Installed and bundled renderers differ')
    inputs = [saved / 'arrival-inputs.v1', saved / 'arrival-states.v1',
              base / 'catalog-v1.w101shaders', bin_dir / 'WizardGraphicalClient.dxvk-cache']
    inputs = [p for p in inputs if p.exists()]
    input_info = {p.name: envelope(p, key) for p in inputs if p.parent == saved}
    if len(input_info) != 2:
        raise RuntimeError('Both latest saved Arrival input files are required')
    originals = list(dict.fromkeys([renderer, *map(Path, identities), *inputs,
                  work / 'build-renderer/src/d3d9/d3d9.dll',
                  *[work / 'renderer/src/dxvk' / p for p in (
                      'dxvk_device.h', 'dxvk_pipemanager.h', 'dxvk_graphics.h', 'dxvk_state_cache.h')],
                  work / 'renderer/src/d3d9/d3d9_device.cpp']))
    before = {str(p): sha(p) for p in originals}
    report = dict(renderer_sha256=sha(renderer), compatibility_key=key,
                  compatibility_files=identities, operating_system_version=os_version,
                  saved_inputs=input_info, synthetic_only=True, gameplay_accepted=False,
                  correctness_qualified=False, performance_qualified=False, runs=[])
    try:
        with tempfile.TemporaryDirectory(prefix='w101-pipeline-verify-') as temporary:
            folder = Path(temporary)
            prefix = folder / 'Prefix'
            clone(data / 'Prefix', prefix)
            learning = prefix / 'drive_c/graphics-patch-cache/Wizard101/Arrival'
            seed = {p.name: p.read_bytes() for p in learning.iterdir() if p.is_file()}
            helper = verification_renderer(work, folder, renderer, output / 'reuse-build.txt')
            report['verification_renderer_sha256'] = sha(helper)
            shutil.copy2(bin_dir / 'd3dx9_43.dll', folder / 'd3dx9_43.dll')
            shutil.copy2(bin_dir / 'WizardGraphicalClient.dxvk-cache', folder / 'WizardGraphicalClient.dxvk-cache')
            subprocess.run(['x86_64-w64-mingw32-g++', '-O2', '-static', '-std=c++17', '-DNOMINMAX',
                            str(ROOT / 'tests/arrival_probe.cpp'), '-ld3d9', '-ld3dx9_43', '-lgdi32', '-luser32',
                            '-o', str(folder / 'WizardGraphicalClient.exe')], check=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith(
                ('W101_', 'WINE', 'DYLD_', 'DXVK_', 'D9VK_', 'VK_', 'MVK_', 'CX_', 'CROSSOVER'))}
            env.update(WINEPREFIX=str(prefix), WINEARCH='win64', WINEDEBUG='-all', WINEMSYNC='1',
                       WINEDLLPATH=str(runtime / 'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime / 'lib') + ':/usr/lib',
                       WINEDLLOVERRIDES='d3d9=n;d3dx9_43=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                       VK_ICD_FILENAMES=str(runtime / 'share/vulkan/icd.d/MoltenVK_icd.json'),
                       MVK_CONFIG_RESUME_LOST_DEVICE='1', MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',
                       DXVK_LOG_PATH=str(folder), DXVK_LOG_LEVEL='none', DXVK_FRAME_RATE='60',
                       DXVK_W101_LIMITER='legacy', DXVK_ASYNC='0', DXVK_W101_CATALOG='0', DXVK_W101_WARMUP='0',
                       W101_PERFORMANCE_TEST='1', W101_PREPARE_PIPELINES='1', W101_SCENE_TEXTURES='0',
                       W101_ASSET_CACHE='0', W101_PREPARE_ASSETS='0', W101_METAL_ARCHIVE='0', W101_SCENE_NODES='0',
                       W101_GAME_REPAIR='0', W101_DECOMPRESS='off', W101_NATIVE_DECODE='off', W101_WAIT_QUEUES='off',
                       W101_ARRIVAL_PATH='C:\\graphics-patch-cache\\Wizard101\\Arrival', W101_ARRIVAL_KEY=key)

            def restore(records):
                for p in learning.iterdir():
                    if p.is_file(): p.unlink()
                for name, content in records.items(): (learning / name).write_bytes(content)

            def run(label, mode='idle', extra=None, instrumented=True):
                print('Checking ' + label, flush=True)
                shutil.copy2(helper if instrumented else renderer, folder / 'd3d9.dll')
                overrides = {'W101_VERIFY_PIPELINE_REUSE': '1'} if instrumented else {}
                with (output / (label + '.txt')).open('w') as log:
                    result = subprocess.run([str(runtime / 'bin/wine'), str(folder / 'WizardGraphicalClient.exe'), mode],
                                            cwd=folder, env=env | overrides | (extra or {}),
                                            stdout=log, stderr=subprocess.STDOUT, timeout=300)
                text = (output / (label + '.txt')).read_text(errors='replace')
                if result.returncode or 'PASS' not in text: raise RuntimeError(label + ': ' + text[-2000:])
                start = fields(text, 'START')
                enabled = (extra or {}).get('W101_PREPARE_PIPELINES', '1') == '1'
                if start['busy'] or enabled and not start['complete']:
                    raise RuntimeError('Preparation continued past device creation: ' + label)
                row = dict(label=label, start=start)
                if instrumented:
                    reuse = fields(text, 'REUSE'); row['reuse'] = reuse
                    if any(reuse[k] for k in ('created', 'pending', 'busy', 'workers', 'queued')):
                        raise RuntimeError('Reuse compiled a new pipeline or workers remain: ' + label)
                    if enabled and not reuse['stopped']:
                        raise RuntimeError('Preparation worker was not stopped: ' + label)
                    if reuse['covered'] != reuse['reused'] or reuse['missing'] or reuse['null']:
                        raise RuntimeError('Existing non-null pipeline handles were not reused: ' + label)
                report['runs'].append(row)
                return text, row

            try:
                restore(seed)
                _, first = run('fresh-saved-replay')
                if first['start']['restored'] < 2 or first['reuse']['reused'] < 100:
                    raise RuntimeError('Latest learned inputs did not prepare a representative workload')
                _, restart = run('compatible-restart')
                if restart['reuse'] != first['reuse'] or restart['start'] != first['start']:
                    raise RuntimeError('Compatible restart did not reproduce preparation/reuse')
                restore(seed)
                baseline, _ = run('rendering-baseline', 'verify', {'W101_PREPARE_PIPELINES': '0'}, instrumented=False)
                oracle = re.findall(r'^PIX .*$', baseline, re.M)
                if not oracle: raise RuntimeError('Rendering oracle is empty')
                for label, fault in [('prepared-rendering', None), ('corrupt-inputs', 'arrival-inputs.v1'),
                                     ('corrupt-states', 'arrival-states.v1'), ('incompatible', 'key')]:
                    restore(seed); extra = {}
                    if fault == 'key':
                        extra['W101_ARRIVAL_KEY'] = hashlib.sha256((key + '-incompatible').encode()).hexdigest()
                    elif fault:
                        damaged = bytearray(seed[fault]); damaged[-1] ^= 1
                        (learning / fault).write_bytes(damaged)
                    text, row = run(label, 'verify', extra)
                    if re.findall(r'^PIX .*$', text, re.M) != oracle:
                        raise RuntimeError('Preparation/fallback changed rendered pixels: ' + label)
                    if fault in ('arrival-inputs.v1', 'key') and row['start']['restored']:
                        raise RuntimeError('Rejected shader inputs were restored: ' + label)
                    if fault in ('arrival-states.v1', 'key') and (row['reuse']['entries'] or row['start']['pipelines']):
                        raise RuntimeError('Rejected pipeline states were restored: ' + label)
                restore(seed)
                text, _ = run('production-rendering', 'verify', instrumented=False)
                if re.findall(r'^PIX .*$', text, re.M) != oracle:
                    raise RuntimeError('Production rendering differs from the verification clone')
                # Learn the existing fixture alongside real inputs. Timings use
                # the UNMODIFIED delivered DLL, with startup excluded.
                restore(seed)
                run('workload-learn', 'benchmark', {'W101_PREPARE_PIPELINES': '0'}, instrumented=False)
                benchseed = {p.name: p.read_bytes() for p in learning.iterdir() if p.is_file()}
                restore(benchseed)
                _, fixture_reuse = run('workload-handle-reuse')
                if fixture_reuse['reuse']['reused'] <= first['reuse']['reused']:
                    raise RuntimeError('Workload first-draw state was not added/prepared')
                pairs, fallback = [], []
                for kind, records, rows in [('known', benchseed, pairs), ('fallback', {}, fallback)]:
                    for pair in range(5):
                        row = {}
                        for state in (['0', '1'] if pair % 2 == 0 else ['1', '0']):
                            restore(records)
                            if kind == 'fallback':
                                # Present truncated files reject legacy import.
                                for name in seed: (learning / name).write_bytes(b'bad')
                            text, result = run(f'{kind}-pair-{pair}-{state}', 'benchmark',
                                               {'W101_PREPARE_PIPELINES': state}, instrumented=False)
                            bench = fields(text, 'BENCH')
                            if bench['hits']: raise RuntimeError('Pipeline-only workload reused a texture')
                            if kind == 'fallback' and (result['start']['restored'] or result['start']['pipelines']):
                                raise RuntimeError('Fallback workload accidentally prepared inputs')
                            row[state] = bench['us']
                        rows.append(row)
                gain = statistics.median(100 * (r['0'] - r['1']) / r['0'] for r in pairs)
                regression = statistics.median(100 * (r['1'] - r['0']) / r['0'] for r in fallback)
                report['benchmarks'] = dict(alternating_pairs=pairs, median_improvement_percent=gain,
                                           fallback_pairs=fallback, median_fallback_regression_percent=regression,
                                           startup_excluded=True, production_renderer=True, texture_reuse=False,
                                           workload='120 texture uploads and first synchronous draw/GPU readback')
                report['performance_qualified'] = gain >= 10 and regression <= 2
                report['correctness_qualified'] = True
            finally:
                subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=20)
    finally:
        report['original_inputs_unchanged'] = before == {str(p): sha(p) for p in originals}
        report['inputs'] = {str(p.relative_to(ROOT)): sha(p) for p in
                            [ROOT / 'verify_arrival_learning.py', ROOT / 'tests/arrival_probe.cpp',
                             ROOT / 'tests/arrival_pipeline_reuse.h', ROOT / 'tests/asset_preparation_probe.cpp']}
        report['passed'] = (report['correctness_qualified'] and report['performance_qualified']
                            and report['original_inputs_unchanged'])
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['original_inputs_unchanged']: raise RuntimeError('Original inputs/source/artifacts changed')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, default=Path.home() / 'Desktop/Wizard101 Arrival Candidate.app')
    p.add_argument('--data', type=Path, default=Path.home() / 'Library/Application Support/Wizard101 Arrival Candidate/Data')
    p.add_argument('--work', type=Path, default=Path('/private/tmp/w101-arrival-v2'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = verify(a.app, a.data, a.output, a.work)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
