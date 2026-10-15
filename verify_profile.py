#!/usr/bin/env python3
"""Check diagnostic recording and game read hooks in a disposable Wine prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from profile_report import report

ROOT = Path(__file__).resolve().parent


def verify(app, source, build, renderer, keep, compatible_cache=None):
    app, source, build, renderer, keep = [Path(p).resolve() for p in (app, source, build, renderer, keep)]
    runtime = app/'Contents/Resources/Runtime'
    keep.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='w101-profile-isolated-') as temp:
        work = Path(temp); probes = work/'probes'; probes.mkdir()
        cache = probes/'cache'; cache.mkdir()
        env = {k:v for k,v in os.environ.items() if not k.startswith(('CX_', 'CROSSOVER', 'DYLD_', 'WINE', 'VK_', 'DXVK_', 'D9VK_'))}
        env.update(WINEPREFIX=str(work/'Prefix'), WINEARCH='win64', WINEDEBUG='-all', WINEMSYNC='1',
                   WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   WINEDLLPATH=str(runtime/'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),
                   MVK_CONFIG_RESUME_LOST_DEVICE='1', DXVK_LOG_PATH=str(probes), DXVK_LOG_LEVEL='info',
                   DXVK_FRAME_RATE='60', DXVK_W101_LIMITER='legacy', DXVK_W101_CACHE_PATH=str(cache),
                   DXVK_W101_WARMUP='0')
        def run(args, name, timeout=180):
            log = keep/(name+'.log')
            with log.open('w') as out:
                p = subprocess.run([str(runtime/'bin/wine'), *map(str,args)], cwd=probes, env=env,
                                   stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
            if p.returncode: raise RuntimeError(f'{name} failed: '+log.read_text(errors='replace')[-2000:])
            return log.read_text(errors='replace')
        flags = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-static', '-DNOMINMAX', '-msse3', '-I'+str(source/'src')]
        try:
            run(['wineboot.exe', '-u'], 'wineboot')
            subprocess.run([*flags, str(ROOT/'tests/profile_probe.cpp'), str(build/'src/util/libutil.a'),
                            '-luser32', '-lgdi32', '-o', str(probes/'profile.exe')], check=True)
            results = {}
            for mode in ('disabled', 'devices', 'time', 'contention', 'size'):
                capture = probes/(mode+'.csv')
                if mode == 'disabled': env.pop('DXVK_W101_PROFILE', None)
                else: env['DXVK_W101_PROFILE'] = str(capture)
                run([probes/'profile.exe', mode], 'profile-'+mode)
                if mode == 'disabled':
                    if capture.exists(): raise RuntimeError('Disabled profiling wrote a capture')
                    continue
                summary = report(capture)
                results[mode] = {k:summary[k] for k in ('event_count','presentations','capture_finalized','dropped_events','dropped_presentations','filtered_short_events','filtered_short_file_reads')}
                if not summary['capture_finalized']: raise RuntimeError(mode+' did not finalize')
                if summary['schema_version'] == 2:
                    if not summary['clock_sync'] or sum(summary['dropped_by_category'].values()) != summary['dropped_events']:
                        raise RuntimeError('Clock synchronization or per-category loss accounting failed')
                    if mode == 'contention' and summary['aggregated_events']['game_read_file']['count'] != 10:
                        raise RuntimeError('Short read aggregation lost counts')
                if capture.stat().st_size > 64*1024*1024: raise RuntimeError('Capture size limit exceeded')
                if mode == 'contention' and (summary['presentations'] != 128 or summary['dropped_presentations'] != 0
                                             or summary['filtered_short_events'] < 10 or summary['filtered_short_file_reads'] != 10
                                             or summary['dropped_events'] == 0):
                    raise RuntimeError('Frame recording failed under event-queue pressure')
                if mode != 'size': shutil.copy2(capture, keep/capture.name)
            if compatible_cache:
                for path in Path(compatible_cache).glob('*.vkcache'): shutil.copy2(path, cache/path.name)
            shutil.copy2(renderer, probes/'d3d9.dll')
            env['DXVK_W101_PROFILE_ALL_READS'] = '1'
            code = (ROOT/'tests/d3d9_probe.cpp').read_text()
            code = code.replace('    if (!api) throw', '''    char readBuffer[4]; DWORD bytesRead = 0;
    SetLastError(0);
    if (ReadFile(INVALID_HANDLE_VALUE, readBuffer, 4, &bytesRead, nullptr) || GetLastError() != ERROR_INVALID_HANDLE)
      throw std::runtime_error("ReadFile hook changed error semantics");
    if (!api) throw''')
            (probes/'render.cpp').write_text(code)
            subprocess.run([*flags, str(probes/'render.cpp'), '-ld3d9', '-lgdi32', '-o', str(probes/'WizardGraphicalClient.exe')], check=True)
            for name in ('render', 'render-restart'):
                env['DXVK_W101_PROFILE'] = str(probes/(name+'.csv'))
                output = run([probes/'WizardGraphicalClient.exe', '--uploads'], name)
                if 'PASS all checks' not in output: raise RuntimeError('Rendering probe incomplete')
                timing = report(probes/(name+'.csv'))
                if timing['schema_version'] == 2:
                    if not timing['shader_coverage']['new']:
                        raise RuntimeError('Programmable shader identities were not captured')
                    if not any(e.get('pipeline_id') for s in timing['largest_intervals'] for e in s['overlapping_cpu_events']):
                        # A fast run may contain no long frames; inspect all rows.
                        import csv
                        rows = csv.DictReader(line for line in (probes/(name+'.csv')).read_text().splitlines() if not line.startswith('#'))
                        if not any(r['event']=='graphics_pipeline_driver_compile' and r.get('pipeline_id') for r in rows):
                            raise RuntimeError('Driver compilation cannot be matched to pipeline requests')
                if 'game_read_file' not in timing['cpu_event_summary']: raise RuntimeError('Game read hook did not execute')
                log = (probes/'WizardGraphicalClient_d3d9.log').read_text(errors='replace')
                if compatible_cache and 'W101 pipeline cache loaded:' not in log: raise RuntimeError('Working compatible cache did not load')
                shutil.copy2(probes/(name+'.csv'), keep)
                (keep/(name+'-renderer.log')).write_text(log)
            result = {'synthetic_only':True, 'renderer_sha256':hashlib.sha256(renderer.read_bytes()).hexdigest(),
                      'queue_checks':results, 'game_read_error_semantics':True, 'render_readbacks':True,
                      'upload_readbacks_per_run':192, 'compatible_cache_reload_verified':bool(compatible_cache),
                      'gameplay_diagnosis_verified':False}
            (keep/'report.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2)); return result
        finally:
            subprocess.run([str(runtime/'bin/wineserver'), '-k'],env=env,capture_output=True,timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app','source','build','renderer','keep'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--compatible-cache',type=Path)
    args = parser.parse_args()
    verify(args.app,args.source,args.build,args.renderer,args.keep,args.compatible_cache)
