#!/usr/bin/env python3
"""Replay a private learned catalog in an isolated device, without game sign-in."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def verify(app, learned_data, keep, pipeline_opt='off', cpu_opt='off'):
    app, learned_data, keep = [Path(p).resolve() for p in (app, learned_data, keep)]
    runtime = app / 'Contents/Resources/Runtime'
    dll = app / 'Contents/Resources/Renderer/d3d9.dll'
    drive = learned_data / 'Prefix/drive_c'
    learned = drive / 'graphics-patch-cache/Wizard101'
    state = drive / 'ProgramData/KingsIsle Entertainment/Wizard101/Bin/WizardGraphicalClient.dxvk-cache'
    catalog = learned / 'catalog-v1.w101shaders'
    blob = catalog.read_bytes()
    if len(blob) < 60 or len(blob) > 32 * 1024 * 1024 + 56:
        raise RuntimeError('Learned catalog has an invalid size')
    payload = blob[56:]
    if struct.unpack_from('<IIQ', blob) != (0x31435057, 1, len(payload)) or hashlib.sha1(payload).digest() != blob[36:56]:
        raise RuntimeError('Learned catalog envelope is damaged')
    count = struct.unpack_from('<I', payload)[0]
    if not 0 < count <= 2048:
        raise RuntimeError('No bounded learned shaders to verify')
    inputs = [catalog, state, *learned.glob('*.vkcache')]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    keep.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='w101-learned-isolated-') as temp:
        work = Path(temp); probes = work/'probes'; probes.mkdir()
        prefix = work/'Prefix'; cache = probes/'cache'; cache.mkdir()
        env = {k:v for k,v in os.environ.items() if not k.startswith(('CX_', 'CROSSOVER', 'DYLD_', 'WINE', 'VK_', 'DXVK_', 'D9VK_'))}
        env.update(PATH=str(runtime/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin', WINEPREFIX=str(prefix), WINEARCH='win64',
                   WINEDEBUG='-all', WINEMSYNC='1', WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   WINEDLLPATH=str(runtime/'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'), MVK_CONFIG_RESUME_LOST_DEVICE='1',
                   DXVK_W101_LIMITER='legacy', DXVK_FRAME_RATE='60', DXVK_ASYNC='0', DXVK_LOG_LEVEL='info',
                   DXVK_LOG_PATH=str(probes), DXVK_STATE_CACHE_PATH=str(cache),
                   DXVK_W101_CACHE_PATH=str(cache), DXVK_W101_CATALOG_PATH=str(cache), DXVK_W101_CATALOG='1')
        env['DXVK_W101_PIPELINE_OPT'] = pipeline_opt
        env['DXVK_W101_CPU_OPT'] = cpu_opt
        env['MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS'] = '1'
        def run(command, name):
            with (keep/(name+'.log')).open('w') as log:
                result = subprocess.run(command, cwd=probes, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
            if result.returncode:
                raise RuntimeError(f'{name} failed; inspect {keep/(name+".log")}')
        try:
            run([str(runtime/'bin/wine'), 'wineboot.exe', '-u'], 'wineboot')
            subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-static',
                            str(ROOT/'tests/learned_warmup_probe.cpp'), '-ld3d9', '-lgdi32',
                            '-o', str(probes/'WizardGraphicalClient.exe')], check=True)
            shutil.copy2(dll, probes/'d3d9.dll')
            runs = []
            for mode in ('off', 'on'):
                # Each run starts from identical learned inputs; originals are read only.
                for p in cache.iterdir(): p.unlink()
                for p in inputs: shutil.copy2(p, cache/p.name)
                timing = probes/(mode+'.csv')
                env.update(DXVK_W101_WARMUP='1' if mode == 'on' else '0', DXVK_W101_PROFILE=str(timing))
                run([str(runtime/'bin/wine'), str(probes/'WizardGraphicalClient.exe')], mode)
                log = (probes/'WizardGraphicalClient_d3d9.log').read_text(errors='replace')
                (keep/(mode+'-renderer.log')).write_text(log)
                shutil.copy2(timing, keep)
                lines = timing.read_text().splitlines()
                footer = dict(line[2:].split('=', 1) for line in lines if line.startswith('# ') and '=' in line)
                rows = list(csv.DictReader(line for line in lines if not line.startswith('#')))
                waits = [r for r in rows if r['event'] == 'shader_warmup_startup_wait']
                end = max((int(r['start_us'])+int(r['duration_us']) for r in waits), default=0)
                compiled = [r for r in rows if r['event'] == 'graphics_pipeline_driver_compile' and int(r['start_us'])+int(r['duration_us']) <= end]
                prepared = re.search(r'W101 pipelines prepared before gameplay: (\d+)', log)
                runs.append({'mode': mode, 'catalog_loaded': f'W101 catalog loaded: {count} shaders' in log,
                             'driver_cache_loaded': 'W101 pipeline cache loaded:' in log,
                             'restored_shaders': sum(r['event'] == 'shader_catalog_restore' for r in rows),
                             'startup_wait_ms': sum(int(r['duration_us'])/1000 for r in waits),
                             'driver_compiles_before_startup': len(compiled),
                             'pipelines_prepared_before_gameplay': int(prepared[1]) if prepared else 0,
                             'startup_completed': 'W101 startup warm-up complete' in log,
                             'dropped_events': int(footer.get('dropped_events', '-1')),
                             'dropped_presentations': int(footer.get('dropped_presentations', '-1')),
                             'ignored_shaders': log.count('W101 catalog shader ignored')})
            off, on = runs
            if not all(r['catalog_loaded'] and r['driver_cache_loaded'] for r in runs):
                raise RuntimeError('The current learned catalog/cache was not compatible with this device')
            if off['restored_shaders'] or on['restored_shaders'] != count or on['ignored_shaders']:
                raise RuntimeError('The on/off catalog replay did not restore all learned shaders')
            if not on['driver_compiles_before_startup'] or not on['pipelines_prepared_before_gameplay']:
                raise RuntimeError('Shader replay did not prepare recorded pipelines')
            if on['startup_wait_ms'] > 10100:
                raise RuntimeError('Startup exceeded its wait budget')
            after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
            if after != before: raise RuntimeError('The original learned caches changed during verification')
            result = {'isolated_device_only': True, 'gameplay_improvement_verified': False,
                      'pipeline_optimization': pipeline_opt,
                      'cpu_optimization': cpu_opt,
                      'renderer_sha256': hashlib.sha256(dll.read_bytes()).hexdigest(),
                      'learned_shaders': count, 'source_caches_unchanged': True, 'runs': runs}
            (keep/'report.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result, indent=2))
            return result
        finally:
            subprocess.run([str(runtime/'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app', 'learned-data', 'keep'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--pipeline-opt', choices=('off','replay','lookup','both'), default='off')
    parser.add_argument('--cpu-opt', choices=('off','constants','locking','both'), default='off')
    args = parser.parse_args()
    verify(args.app, args.learned_data, args.keep, args.pipeline_opt, args.cpu_opt)
