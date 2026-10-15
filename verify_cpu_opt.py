#!/usr/bin/env python3
"""Verify the real CPU candidate in an isolated prefix and benchmark four modes."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
MODES = ('off', 'constants', 'locking', 'both')


def evaluate(runs):
    medians = {mode: {work: statistics.median(r['cpu_ms'] for r in runs if r['mode']==mode and r['workload']==work)
                      for work in ('unchanged','changing','recursive','contended')} for mode in MODES}
    changes = {mode: {work: (medians[mode][work]/medians['off'][work]-1)*100 for work in medians[mode]} for mode in MODES[1:]}
    qualified = {}
    for mode in MODES[1:]:
        targets = ('unchanged','recursive') if mode=='both' else (('unchanged',) if mode=='constants' else ('recursive',))
        qualified[mode] = all(changes[mode][work] <= -10 for work in targets) and all(changes[mode][work] <= 5 for work in ('changing','contended'))
    recommended = next((mode for mode in ('both','constants','locking') if qualified[mode]), 'off')
    return {'median_cpu_ms': medians, 'cpu_change_percent': changes, 'synthetic_qualified': qualified,
            'ordinary_play_trial_mode': recommended, 'target_reduction_min_percent':10, 'regression_max_percent':5}


def verify(app, source, build, keep, checks_only=False):
    app, source, build, keep = map(lambda p: Path(p).resolve(), (app,source,build,keep))
    keep.mkdir(parents=True,exist_ok=True)
    runtime=app/'Contents/Resources/Runtime'; renderer=app/'Contents/Resources/Renderer/d3d9.dll'
    provenance=json.loads((renderer.parent/'cpu-build.json').read_text())
    if provenance['renderer_sha256']!=hashlib.sha256(renderer.read_bytes()).hexdigest(): raise RuntimeError('Renderer provenance mismatch')
    with tempfile.TemporaryDirectory(prefix='w101-cpu-isolated-') as temp:
        work=Path(temp); prefix=work/'Prefix'
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_'))}
        env.update(PATH=str(runtime/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin',WINEPREFIX=str(prefix),WINEARCH='win64',
                   WINEDEBUG='-all',WINEMSYNC='1',WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),MVK_CONFIG_RESUME_LOST_DEVICE='1',
                   MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_ASYNC='0',DXVK_W101_PIPELINE_OPT='off',
                   DXVK_W101_CACHE='0',DXVK_W101_CATALOG='0',DXVK_STATE_CACHE='0',DXVK_W101_WARMUP='0',
                   DXVK_FRAME_RATE='60',DXVK_W101_LIMITER='legacy',DXVK_LOG_PATH=str(work))
        def run(args,label,timeout=180):
            log=keep/(label+'.log')
            with log.open('w') as f:
                p=subprocess.run([str(runtime/'bin/wine'),*map(str,args)],cwd=work,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
            output=log.read_text(errors='replace')
            if p.returncode: raise RuntimeError(label+' failed: '+output[-3500:])
            return output
        flags=['x86_64-w64-mingw32-g++','-std=c++17','-O2','-static','-DNOMINMAX','-msse3',
               *['-I'+str(source/p) for p in ('src','include','include/vulkan/include','include/spirv/include')]]
        try:
            run(['wineboot.exe','-u'],'wineboot')
            subprocess.run([*flags,str(ROOT/'tests/cpu_opt_probe.cpp'),str(source/'src/d3d9/d3d9_multithread.cpp'),str(build/'src/util/libutil.a'),'-lgdi32','-luser32','-o',str(work/'unit.exe')],check=True)
            subprocess.run([*flags,str(ROOT/'tests/cpu_render_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-o',str(work/'WizardGraphicalClient.exe')],check=True)
            shutil.copy2(renderer,work/'d3d9.dll')
            checks=[]
            for mode in (*MODES,'invalid'):
                env['DXVK_W101_CPU_OPT']=mode
                capture=work/(mode+'-unit.csv'); env['DXVK_W101_PROFILE']=str(capture)
                out=run([work/'unit.exe'],'unit-'+mode)
                expected=mode if mode in MODES else 'off'
                if 'PASS all CPU unit checks' not in out or 'MODE '+expected not in out: raise RuntimeError('Unit mode not verified')
                samples=[json.loads(line.split('=',1)[1]) for line in capture.read_text().splitlines() if line.startswith('# process_cpu_sample=')]
                counters=[json.loads(line.split('=',1)[1]) for line in capture.read_text().splitlines() if line.startswith('# cpu_counters=')]
                if len(samples)<3 or any(b['relative_us']-a['relative_us']<900000 or b['cpu_us']<a['cpu_us'] for a,b in zip(samples,samples[1:])):
                    raise RuntimeError('Process CPU samples are missing, too frequent or nonmonotonic')
                if not counters or counters[-1]['overflow_calls'] or counters[-1]['device_locks']<100000: raise RuntimeError('Aggregate lock counters incomplete')
                if (counters[-1]['recursive_fast_locks']>0) != (expected in ('locking','both')): raise RuntimeError('Fast recursion mode/counters wrong')
                shutil.copy2(capture,keep/capture.name)
                if mode in MODES:
                    env['DXVK_W101_PROFILE']=str(work/(mode+'-render.csv'))
                    out=run([work/'WizardGraphicalClient.exe'],'render-'+mode)
                    if 'PASS all checks' not in out or 'PASS constants, state blocks' not in out: raise RuntimeError('Render probe incomplete')
                    timing=(work/(mode+'-render.csv')).read_text()
                    render_counters=[json.loads(line.split('=',1)[1]) for line in timing.splitlines() if line.startswith('# cpu_counters=')][-1]
                    if (render_counters['overflow_calls'] or not render_counters['constant_sets'] or not render_counters['constant_uploads']
                        or (render_counters['constant_unchanged']>0)!=(mode in ('constants','both'))
                        or (render_counters['recursive_fast_locks']>0)!=(mode in ('locking','both'))):
                        raise RuntimeError('Actual render constant/lock aggregate counters are missing or inconsistent')
                    if 'private-test-name' in timing: raise RuntimeError('Texture asset name recorded')
                    events={r['event'] for r in csv.DictReader(line for line in timing.splitlines() if not line.startswith('#'))}
                    if len([e for e in events if e.startswith('game_d3dx_texture_D3DX')])!=8: raise RuntimeError('Eight texture hooks did not execute')
                    log=(work/'WizardGraphicalClient_d3d9.log').read_text(errors='replace')
                    if 'installed 8 game D3DX texture hooks' not in log or 'W101 CPU optimizations: '+mode not in log: raise RuntimeError('Hook installation or selected CPU mode missing')
                    shutil.copy2(work/(mode+'-render.csv'),keep)
                    (keep/(mode+'-renderer.log')).write_text(log)
                checks.append({'mode':mode,'passed':True,'cpu_samples':len(samples),'counters':counters[-1],
                               'render_counters':render_counters if mode in MODES else None})
                print('Verified CPU mode:',mode,flush=True)
            env.pop('DXVK_W101_PROFILE',None)
            runs=[]
            for trial in range(0 if checks_only else 5):
                order=MODES if trial%2==0 else tuple(reversed(MODES))
                for mode in order:
                    env['DXVK_W101_CPU_OPT']=mode
                    for workload in ('unchanged','changing','recursive','contended'):
                        args=[work/'WizardGraphicalClient.exe','--'+workload] if workload in ('unchanged','changing') else [work/'unit.exe',workload]
                        output=run(args,f'bench-{trial+1}-{mode}-{workload}')
                        row=next(json.loads(line[6:]) for line in output.splitlines() if line.startswith('BENCH '))
                        if row['cpu_ms']<=0: raise RuntimeError('CPU measurement has inadequate resolution')
                        row.update(trial=trial+1,mode=mode); runs.append(row)
                    print('Benchmarked round',trial+1,'mode',mode,flush=True)
            result={'synthetic_only':True,'checks':checks,'runs':runs,**(evaluate(runs) if runs else {}),
                    'renderer_sha256':provenance['renderer_sha256'],'translation_source_sha256':provenance['translation_source_sha256'],
                    'default_mode':'off','gameplay_cpu_savings_verified':False,'stutter_reduction_verified':False,'installed_working_app_replaced':False}
            (keep/'report.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k not in ('runs','checks')},indent=2)); return result
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('app','source','build','keep'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--checks-only',action='store_true',help='Recheck semantics without repeating a completed benchmark of the same renderer')
    a=p.parse_args(); verify(a.app,a.source,a.build,a.keep,a.checks_only)
