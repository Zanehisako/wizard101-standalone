#!/usr/bin/env python3
"""Verify a separate warm-up renderer using synthetic shaders and an isolated prefix."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from profile_report import report

ROOT = Path(__file__).resolve().parent


def verify(app, source, build, baseline, keep, compatible_cache=None, pipeline_opt='off', synchronous_submits='1', cpu_opt='off', stutter_fix='0'):
    app, source, build, baseline, keep = map(lambda p: Path(p).resolve(), (app, source, build, baseline, keep))
    runtime = app / 'Contents/Resources/Runtime'
    candidate = app / 'Contents/Resources/Renderer/d3d9.dll'
    keep.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='w101-warmup-isolated-') as temp:
        work = Path(temp); probes = work / 'probes'; probes.mkdir()
        prefix = work / 'Prefix'; cache = probes / 'cache'; cache.mkdir()
        catalog = probes / 'catalog'; catalog.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CX_', 'CROSSOVER', 'DYLD_', 'WINE', 'VK_', 'DXVK_', 'D9VK_'))}
        env.update(PATH=str(runtime / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin', WINEPREFIX=str(prefix), WINEARCH='win64',
                   WINEDEBUG='-all', WINEMSYNC='1', WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   WINEDLLPATH=str(runtime / 'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime / 'lib') + ':/usr/lib',
                   VK_ICD_FILENAMES=str(runtime / 'share/vulkan/icd.d/MoltenVK_icd.json'), MVK_CONFIG_RESUME_LOST_DEVICE='1',
                   DXVK_W101_LIMITER='legacy', DXVK_FRAME_RATE='60', DXVK_LOG_LEVEL='info', DXVK_LOG_PATH=str(probes),
                   DXVK_W101_CACHE_PATH=str(cache), DXVK_W101_CATALOG_PATH=str(catalog), DXVK_W101_CATALOG='1',
                   DXVK_W101_WARMUP='0')
        env['DXVK_W101_PROFILE_ALL_READS'] = '1'
        env['DXVK_W101_PIPELINE_OPT'] = pipeline_opt
        env['DXVK_W101_CPU_OPT'] = cpu_opt
        env['DXVK_W101_STUTTER_FIX'] = stutter_fix
        env['DXVK_ASYNC'] = '0'
        env['MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS'] = synchronous_submits
        def run(command, name, timeout=180):
            log = keep / (name + '.log')
            with log.open('w') as output:
                result = subprocess.run(command, cwd=probes, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            if result.returncode: raise RuntimeError(f'{name} failed: ' + log.read_text(errors='replace')[-2000:])
            return log.read_text(errors='replace')
        def compile(command): subprocess.run(command, check=True)
        flags = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-static', '-DNOMINMAX', '-msse3',
                 *['-I'+str(source / p) for p in ('src', 'include', 'include/vulkan/include', 'include/spirv/include')]]
        try:
            run([str(runtime/'bin/wine'), 'wineboot.exe', '-u'], 'wineboot')
            compile([*flags, str(ROOT/'tests/warmup_probe.cpp'), str(source/'src/d3d9/d3d9_warmup.cpp'),
                     *[str(source/f'src/dxso/dxso_{f}.cpp') for f in ('reader', 'header', 'code', 'decoder', 'tables')],
                     str(build/'src/util/libutil.a'), '-luser32', '-lgdi32', '-o', str(probes/'warmup.exe')])
            unit = run([str(runtime/'bin/wine'), str(probes/'warmup.exe')], 'warmup-unit')
            if 'PASS catalog limits' not in unit: raise RuntimeError('Unit checks incomplete')
            code = (ROOT/'tests/d3d9_probe.cpp').read_text()
            code = code.replace('#include <algorithm>', '#include <algorithm>\n#include <thread>\n#include <atomic>')
            code = code.replace('D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp', 'D3DCREATE_HARDWARE_VERTEXPROCESSING | D3DCREATE_MULTITHREADED, &pp')
            code = code.replace('    if (!api) throw', '''    char readBuffer[4]; DWORD bytesRead = 0;
    SetLastError(0);
    if (ReadFile(INVALID_HANDLE_VALUE, readBuffer, 4, &bytesRead, nullptr) || GetLastError() != ERROR_INVALID_HANDLE)
      throw std::runtime_error("ReadFile hook changed error semantics");
    if (!api) throw''')
            marker = '    ID3DBlob *vsBlob = nullptr, *psBlob = nullptr, *errors = nullptr;'
            # Compile the normal synthetic shaders, then issue simultaneous
            # shader creation requests before any module exists in this device.
            marker2 = '    IDirect3DVertexShader9* vs = nullptr;'
            if marker2 not in code: marker2 = '    IDirect3DVertexShader9 *vs = nullptr;'
            # The exact declaration is discovered in this allowlisted source.
            pos = code.index('    IDirect3DVertexShader9')
            parallel = '''    std::atomic<bool> concurrentFailed {false};
    std::vector<std::thread> creators;
    for (int i=0; i<16; ++i) creators.emplace_back([&] {
      IDirect3DVertexShader9* concurrent = nullptr;
      if (FAILED(dev->CreateVertexShader((DWORD*)vsBlob->GetBufferPointer(), &concurrent))) concurrentFailed = true;
      if (concurrent) concurrent->Release();
    });
    for (auto& thread : creators) thread.join();
    if (concurrentFailed) throw std::runtime_error("Concurrent shader creation failed");
'''
            code = code[:pos] + parallel + code[pos:]
            (probes/'render.cpp').write_text(code)
            compile([*flags, str(probes/'render.cpp'), '-ld3d9', '-lgdi32', '-o', str(probes/'WizardGraphicalClient.exe')])
            if compatible_cache:
                for f in Path(compatible_cache).glob('*.vkcache'): shutil.copy2(f, cache/f.name)
            shutil.copy2(baseline, probes/'d3d9.dll')
            baseline_readback = run([str(runtime/'bin/wine'), str(probes/'WizardGraphicalClient.exe')], 'baseline-render')
            baseline_log = (probes/'WizardGraphicalClient_d3d9.log').read_text(errors='replace')
            (keep/'baseline-renderer.log').write_text(baseline_log)
            if compatible_cache and 'W101 pipeline cache loaded:' not in baseline_log:
                raise RuntimeError('The current compatible driver cache did not load')
            # A baseline with the existing warm-up implementation can learn
            # these probe shaders too. The cold-on case must still start empty.
            for path in catalog.glob('*.w101shaders'): path.unlink()
            shutil.copy2(candidate, probes/'d3d9.dll')
            runs = []
            for name, warm in [('cold-on', '1'), ('learn', '0'), ('restart-off', '0'), ('restart-on', '1')]:
                env['DXVK_W101_WARMUP'] = warm
                env['DXVK_W101_PROFILE'] = str(probes/(name+'.csv'))
                output = run([str(runtime/'bin/wine'), str(probes/'WizardGraphicalClient.exe'), '--uploads'], name)
                if 'PASS all checks' not in output: raise RuntimeError(name+' rendering checks incomplete')
                timing = report(probes/(name+'.csv'))
                renderer = (probes/'WizardGraphicalClient_d3d9.log').read_text(errors='replace')
                (keep/(name+'-renderer.log')).write_text(renderer)
                shutil.copy2(probes/(name+'.csv'), keep)
                runs.append({'name': name, 'profile': timing, 'catalog_loaded': 'W101 catalog loaded:' in renderer,
                             'driver_cache_loaded': 'W101 pipeline cache loaded:' in renderer})
            cold, off, on = runs[0]['profile'], runs[2]['profile'], runs[3]['profile']
            cold_wait = cold['cpu_event_summary'].get('shader_warmup_startup_wait', {}).get('max_ms', float('inf'))
            if cold_wait > 1000 or 'shader_catalog_restore' in cold['cpu_event_summary']:
                raise RuntimeError('An empty catalog should finish startup without an idle wait')
            if not runs[3]['catalog_loaded'] or not runs[3]['driver_cache_loaded']:
                raise RuntimeError('Candidate caches did not load after restart')
            if 'shader_catalog_restore' not in on['cpu_event_summary'] or 'game_read_file' not in on['cpu_event_summary']:
                raise RuntimeError('Restore or game I/O instrumentation did not execute')
            startup = on['cpu_event_summary'].get('shader_warmup_startup_wait', {}).get('max_ms', float('inf'))
            if startup > 10100: raise RuntimeError('Startup exceeded the 10-second wait budget')
            rows = list(csv.DictReader(line for line in (keep/'restart-on.csv').read_text().splitlines() if not line.startswith('#')))
            wait = next(r for r in rows if r['event'] == 'shader_warmup_startup_wait')
            wait_end = int(wait['start_us']) + int(wait['duration_us'])
            preparation = [r for r in rows if r['event'] == 'graphics_pipeline_driver_compile' and int(r['start_us']) < wait_end]
            if not preparation or any(int(r['start_us']) + int(r['duration_us']) > wait_end for r in preparation):
                raise RuntimeError('Startup returned before queued pipeline preparation completed')
            envelope = catalog/'catalog-v1.w101shaders'
            blob = bytearray(envelope.read_bytes()); blob[-1] ^= 1; envelope.write_bytes(blob)
            env['DXVK_W101_PROFILE'] = str(probes/'corrupt-recovery.csv')
            recovery = run([str(runtime/'bin/wine'), str(probes/'WizardGraphicalClient.exe')], 'corrupt-recovery')
            if 'PASS all checks' not in recovery: raise RuntimeError('Corrupt catalog affected rendering')
            report_data = {'synthetic_only': True, 'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
                           'pipeline_optimization': pipeline_opt,
                           'cpu_optimization': cpu_opt,
                           'stutter_fix': stutter_fix,
                           'synchronous_queue_submits': synchronous_submits,
                           'baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(), 'compatible_current_cache_loaded':
                           'W101 pipeline cache loaded:' in baseline_log, 'catalog_recovery': True, 'startup_wait_ms': startup,
                           'empty_catalog_wait_ms': cold_wait, 'pipeline_preparation_completed_before_startup': True,
                           'concurrent_shader_requests': 16, 'upload_readbacks_per_run': 192,
                           'unit_checks': unit.strip(), 'runs': runs, 'gameplay_diagnosis_verified': False,
                           'three_paired_gameplay_runs_verified': False, 'user_acceptance': False, 'installed': False}
            (keep/'report.json').write_text(json.dumps(report_data, indent=2)+'\n')
            print(json.dumps({k:v for k,v in report_data.items() if k not in ('runs','unit_checks')}, indent=2))
            return report_data
        finally:
            # Only this temporary prefix is stopped; no user's game is touched.
            subprocess.run([str(runtime/'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=15)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('app', 'source', 'build', 'baseline', 'keep'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--compatible-cache', type=Path)
    p.add_argument('--pipeline-opt', choices=('off','replay','lookup','both'), default='off')
    p.add_argument('--synchronous-submits', choices=('0','1'), default='1')
    p.add_argument('--cpu-opt', choices=('off','constants','locking','both'), default='off')
    p.add_argument('--stutter-fix', choices=('0','1'), default='0')
    args = p.parse_args()
    verify(args.app, args.source, args.build, args.baseline, args.keep, args.compatible_cache, args.pipeline_opt, args.synchronous_submits, args.cpu_opt, args.stutter_fix)
