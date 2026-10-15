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
    groups={w:[r for r in rows if r['workload']==w] for w in ('reuse','cold','fresh')}
    if len(rows)!=15 or any(len(g)!=5 or {r['pair'] for r in g}!=set(range(5)) for g in groups.values()):
        raise RuntimeError('Need five alternating pairs for reuse, cold and fresh resources')
    import math
    for r in rows:
        if r.get('order')!=('on/off' if r['pair']%2 else 'off/on') or r.get('operations',0)<=0:
            raise RuntimeError('Invalid paired measurement order or operation count')
        if any(not math.isfinite(r[k]) or r[k]<2000 for k in ('off_cpu_ms','on_cpu_ms')):
            raise RuntimeError('Every sample requires at least two seconds of thread CPU')
        if r['workload']=='fresh' and not r.get('fingerprint_preparation_timed'):
            raise RuntimeError('Fresh-resource measurements must include preparation')
    reductions=[100*(1-r['on_cpu_ms']/r['off_cpu_ms']) for r in groups['reuse']]
    changes={w:[100*(r['on_cpu_ms']/r['off_cpu_ms']-1) for r in groups[w]] for w in ('cold','fresh')}
    wins=sum(r['on_cpu_ms']<r['off_cpu_ms'] for r in groups['reuse'])
    savings=statistics.median(reductions)
    return {'median_layout_cpu_savings_percent':savings,'winning_pairs':wins,
            'reuse_pair_savings_percent':reductions,
            'median_cold_regression_percent':statistics.median(changes['cold']),
            'worst_cold_pair_regression_percent':max(changes['cold']),
            'cold_pair_changes_percent':changes['cold'],
            'median_fresh_regression_percent':statistics.median(changes['fresh']),
            'worst_fresh_pair_regression_percent':max(changes['fresh']),
            'fresh_pair_changes_percent':changes['fresh'],
            'threshold_savings_percent':10,'max_cold_regression_percent':2,'minimum_sample_thread_cpu_ms':2000,
            'gate_passed':savings>=10 and wins>=4 and max(changes['cold'])<=2 and max(changes['fresh'])<=2}

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
    report={'renderer_sha256':sha(dll),'baseline_renderer_sha256':sha(original),'synthetic_only':True,'gameplay_accepted':False,'revision':2,'install_qualified':False,'checks':{},'runtime':str(runtime)}
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
                result=subprocess.run([str(runtime/'bin/wine'),str(program),*args],cwd=temp,env=env|(extra or {}),stdout=out,stderr=subprocess.STDOUT,timeout=900)
            text=(keep/(label+'.log')).read_text(errors='replace')
            if result.returncode:raise RuntimeError(label+' failed: '+text[-2000:])
            return text
        try:
            run('wineboot.exe','wineboot',['-u'])
            flags=['x86_64-w64-mingw32-g++','-O3','-std=c++17','-static','-DNOMINMAX','-D_WIN32_WINNT=0xa00','-DDXVK_WSI_WIN32',
                   *['-I'+str(source/p) for p in ('src','include','include/vulkan/include','include/spirv/include')]]
            unit=temp/'unit.exe'
            subprocess.run([*flags,'-ffunction-sections','-fdata-sections',str(ROOT/'tests/draw_layout_cache_v2_probe.cpp'),str(source/'src/d3d9/d3d9_util.cpp'),str(build/'src/util/libutil.a'),'-Wl,--gc-sections','-lgdi32','-luser32','-o',str(unit)],check=True)
            text=run(unit,'cache-cpu')
            if 'PASS structural equality' not in text:raise RuntimeError('Cache boundaries incomplete')
            report['checks']['structural_collision_eviction_allocation_budget_shutdown']=True
            report['benchmark_pairs']=[json.loads(x) for x in re.findall(r'BENCH (\{.*\})',text)]
            report['components']=[json.loads(x) for x in re.findall(r'COST (\{.*\})',text)]
            if len(report['components'])!=5 or any(r['cpu_ms']<2000 for r in report['components']):raise RuntimeError('Incomplete component measurements')
            report['performance']=score(report['benchmark_pairs'])
            print(json.dumps(report['performance']),flush=True)
            probe=temp/'WizardGraphicalClient.exe'
            subprocess.run([*flags,str(ROOT/'tests/draw_layout_render_v2_probe.cpp'),'-ld3d9','-lgdi32','-luser32','-o',str(probe)],check=True)
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
            report['verified_inputs']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'tests/draw_layout_cache_v2_probe.cpp',ROOT/'tests/draw_layout_render_v2_probe.cpp',ROOT/'verify_draw_layout_v2.py']}
            report['launcher_sha256']=sha(launcher/'Contents/MacOS/Wizard101Native')
            report['runtime_inputs']={str(p.relative_to(runtime)):sha(p) for p in [runtime/'bin/wine',runtime/'lib/wine/x86_64-unix/ntdll.so',runtime/'lib/libMoltenVK.dylib'] if p.exists()}
            from verify_asset_preparation import verify as verify_assets
            from install_draw_layout import inputs
            data=Path.home()/'Library/Application Support/Wizard101 Optimizations/Data'
            for enabled in (False,True):
                destination=keep/('assets-on' if enabled else 'assets-off')
                assets=verify_assets(work,app,data,destination,draw_layout=enabled)
                if assets['renderer_sha256']!=sha(dll) or not all(bool(v) and (not isinstance(v,dict) or v.get('passed',True)) for v in assets['checks'].values()):
                    raise RuntimeError('Texture cache compatibility failed')
                report['checks']['texture_preparation_'+('on' if enabled else 'off')]={'passed':True,'report_sha256':sha(destination/'report.json')}
            before=json.loads((keep/'installed-before.json').read_text())
            _,_,after=inputs(app,data)
            report['checks']['installed_game_app_learned_cache_unchanged']={'passed':before==after,'baseline_inputs':before}
            report['install_qualified']=all(bool(v) and (not isinstance(v,dict) or v.get('passed',True)) for v in report['checks'].values()) and report['performance']['gate_passed']
            (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({'install_qualified':report['install_qualified'],'report':str(keep/'report.json')}),flush=True)
            return report
        except BaseException as error:
            report['install_qualified']=False;report['error']=str(error)
            raise
        finally:
            (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-draw-layout-v2'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-asset-preparation'))
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-layout-v2-launcher.app'))
    p.add_argument('--keep',type=Path,required=True)
    a=p.parse_args();verify(a.work,a.baseline,a.app,a.launcher,a.keep)
