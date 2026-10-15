#!/usr/bin/env python3
"""Verify exact real-driver pixels and score the production layout preparation CPU path."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
from build_runtime import ROOT, sha

def score(rows):
    reuse=[r for r in rows if r['workload']=='reuse'];cold=[r for r in rows if r['workload']=='cold']
    if len(reuse)!=5 or len(cold)!=5: raise RuntimeError('Need five alternating pairs for each workload')
    reductions=[100*(1-r['on_cpu_ms']/r['off_cpu_ms']) for r in reuse]
    cold_changes=[100*(r['on_cpu_ms']/r['off_cpu_ms']-1) for r in cold]
    savings=100*(1-statistics.median(r['on_cpu_ms'] for r in reuse)/statistics.median(r['off_cpu_ms'] for r in reuse))
    regression=100*(statistics.median(r['on_cpu_ms'] for r in cold)/statistics.median(r['off_cpu_ms'] for r in cold)-1)
    wins=sum(r['on_cpu_ms'] < r['off_cpu_ms'] for r in reuse)
    return {'median_layout_cpu_savings_percent':savings,'winning_pairs':wins,
            'median_cold_regression_percent':regression,'worst_cold_pair_regression_percent':max(cold_changes),'reuse_pair_savings_percent':reductions,
            'cold_pair_changes_percent':cold_changes,'threshold_savings_percent':10,'max_cold_regression_percent':2,
            'gate_passed':savings>=10 and wins>=4 and max(cold_changes)<=2}

def verify(work,baseline,app,launcher,keep):
    work,baseline,app,launcher,keep=map(lambda p:Path(p).resolve(),(work,baseline,app,launcher,keep));keep.mkdir(parents=True,exist_ok=True)
    runtime=app/'Contents/Resources/Runtime';dll=work/'build-renderer/src/d3d9/d3d9.dll';source=work/'renderer';build=work/'build-renderer'
    original=baseline/'build-renderer/src/d3d9/d3d9.dll'
    metadata=json.loads((work/'draw-layout-build.json').read_text())
    if metadata['renderer_sha256']!=sha(dll) or metadata['baseline_renderer_sha256']!=sha(original):raise RuntimeError('Stale build')
    if sha(app/'Contents/Resources/Renderer/d3d9.dll')!=sha(original):raise RuntimeError('Installed renderer differs from measured source baseline')
    for name,digest in metadata['inputs'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Stale input: '+name)
    baseline_inputs={str(app/'Contents/MacOS/Wizard101Native'):sha(app/'Contents/MacOS/Wizard101Native'),str(app/'Contents/Resources/Renderer/d3d9.dll'):sha(app/'Contents/Resources/Renderer/d3d9.dll')}
    report={'renderer_sha256':sha(dll),'baseline_renderer_sha256':sha(original),'synthetic_only':True,'gameplay_accepted':False,'checks':{},'runtime':str(runtime)}
    with tempfile.TemporaryDirectory(prefix='w101-layout-verify-') as tmp:
        temp=Path(tmp);prefix=temp/'Prefix'
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_','W101_'))}
        env.update(WINEPREFIX=str(prefix),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),
                   MVK_CONFIG_RESUME_LOST_DEVICE='1',MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_FRAME_RATE='60',DXVK_W101_LIMITER='legacy',DXVK_ASYNC='0',
                   DXVK_W101_WARMUP='0',DXVK_W101_PIPELINE_OPT='off',DXVK_W101_CPU_OPT='off',DXVK_W101_STUTTER_FIX='0',DXVK_W101_CATALOG='0',DXVK_W101_CACHE='0',DXVK_STATE_CACHE='0',
                   DXVK_LOG_PATH=str(temp),W101_PERFORMANCE_TEST='1',W101_ASSET_CACHE='1',W101_ASSET_WORKERS='2',W101_GPU_TEXTURE_CONVERSION='off',W101_LOCK_FIX='0',
                   W101_PREPARE_ASSETS='0',W101_DECOMPRESS='off',W101_WAIT_QUEUES='off',W101_NATIVE_DECODE='off',W101_DRAW_LAYOUT_CACHE='0')
        def run(program,label,args=(),extra=None):
            with (keep/(label+'.log')).open('w') as out:
                result=subprocess.run([str(runtime/'bin/wine'),str(program),*args],cwd=temp,env=env|(extra or {}),stdout=out,stderr=subprocess.STDOUT,timeout=240)
            text=(keep/(label+'.log')).read_text(errors='replace')
            if result.returncode:raise RuntimeError(label+' failed: '+text[-2000:])
            return text
        try:
            run('wineboot.exe','wineboot',['-u'])
            flags=['x86_64-w64-mingw32-g++','-O3','-std=c++17','-static','-DNOMINMAX','-D_WIN32_WINNT=0xa00','-DDXVK_WSI_WIN32',
                   *['-I'+str(source/p) for p in ('src','include','include/vulkan/include','include/spirv/include')]]
            unit=temp/'unit.exe'
            subprocess.run([*flags,'-ffunction-sections','-fdata-sections',str(ROOT/'tests/draw_layout_cache_probe.cpp'),str(source/'src/d3d9/d3d9_util.cpp'),str(build/'src/util/libutil.a'),'-Wl,--gc-sections','-lgdi32','-luser32','-o',str(unit)],check=True)
            text=run(unit,'cache-cpu')
            if 'PASS structural equality' not in text:raise RuntimeError('Cache boundaries incomplete')
            report['checks']['structural_collision_eviction_allocation_budget_shutdown']=True
            report['benchmark_pairs']=[json.loads(x) for x in re.findall(r'BENCH (\{.*\})',text)]
            report['performance']=score(report['benchmark_pairs'])
            print(json.dumps(report['performance']),flush=True)
            probe=temp/'WizardGraphicalClient.exe'
            subprocess.run([*flags,str(ROOT/'tests/draw_layout_render_probe.cpp'),'-ld3d9','-lgdi32','-luser32','-o',str(probe)],check=True)
            for extended in [False,True]:
                expected=None
                for mode,renderer,extra in [('baseline',original,{}),('off',dll,{}),('on',dll,{'W101_DRAW_LAYOUT_CACHE':'1','W101_DRAW_LAYOUT_TEST':'stats'}),('collision',dll,{'W101_DRAW_LAYOUT_CACHE':'1','W101_DRAW_LAYOUT_TEST':'collision'}),('allocation',dll,{'W101_DRAW_LAYOUT_CACHE':'1','W101_DRAW_LAYOUT_TEST':'allocation'})]:
                    label=('ex-' if extended else '')+mode
                    shutil.copy2(renderer,temp/'d3d9.dll')
                    text=run(probe,label,['extended'] if extended else [],extra)
                    if 'PASS exact pixel artifact' not in text:raise RuntimeError('Probe did not complete')
                    artifact=temp/'pixels.bin';digest=sha(artifact)
                    if expected is None:expected=digest
                    if digest!=expected:raise RuntimeError(label+' full rendered pixels differ')
                    rendererlog=temp/'WizardGraphicalClient_d3d9.log'
                    stats=rendererlog.read_text(errors='replace') if rendererlog.exists() else ''
                    (keep/(label+'-renderer.log')).write_text(stats)
                    counters=[list(map(int,row)) for row in re.findall(r'W101 draw layouts: hits=(\d+) misses=(\d+) evictions=(\d+) failures=(\d+) entries=(\d+) retained_bytes=(\d+) process_bytes=(\d+)',stats)]
                    if mode in ('on','collision'):
                        if not counters or sum(c[0] for c in counters)<10 or sum(c[2] for c in counters)<1:raise RuntimeError('Cache hit/eviction path not exercised')
                    if mode=='allocation' and (not counters or sum(c[3] for c in counters)<10):raise RuntimeError('Allocation fallback not exercised')
                    if any(c[4]>256 or c[5]>1024**2 or c[6]>128*1024**2 for c in counters):raise RuntimeError('Renderer budget exceeded')
                    report['checks'][label]={'passed':True,'exact_pixel_sha256':digest,'pixel_bytes':artifact.stat().st_size,'counters':counters}
                    print('PASS '+label+' exact pixels',flush=True)
            result=subprocess.run([str(launcher/'Contents/MacOS/Wizard101Native'),'--self-test'],check=True,capture_output=True,text=True)
            checks=json.loads(result.stdout);(keep/'launcher-self-tests.json').write_text(result.stdout)
            report['checks']['launcher_64_options_both_fps_profiling']={'passed':True,'self_tests_passed':checks['passed']}
            report['checks']['installed_app_unchanged']=all(sha(Path(p))==digest for p,digest in baseline_inputs.items())
            report['verified_inputs']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'tests/draw_layout_cache_probe.cpp',ROOT/'tests/draw_layout_render_probe.cpp',ROOT/'verify_draw_layout.py']}
            report['launcher_sha256']=sha(launcher/'Contents/MacOS/Wizard101Native')
            report['runtime_inputs']={str(p.relative_to(runtime)):sha(p) for p in [runtime/'bin/wine',runtime/'lib/wine/x86_64-unix/ntdll.so',runtime/'lib/libMoltenVK.dylib'] if p.exists()}
            report['install_qualified']=all(bool(v) and (not isinstance(v,dict) or v.get('passed',True)) for v in report['checks'].values()) and report['performance']['gate_passed']
            (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({'install_qualified':report['install_qualified'],'report':str(keep/'report.json')}),flush=True)
            return report
        finally:subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-draw-layout'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-asset-preparation'))
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-layout-launcher.app'))
    p.add_argument('--keep',type=Path,required=True)
    a=p.parse_args();verify(a.work,a.baseline,a.app,a.launcher,a.keep)
