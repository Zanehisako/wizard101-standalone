#!/usr/bin/env python3
"""Verify the staged arrival renderer/runtime with no gameplay telemetry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
from build_runtime import ROOT,sha
from build_workload import clone
from package_game_repair import unsigned_sha
from verify_workload_performance import fixture
from verify_asset_preparation import dds

def verify(work,app,data,output):
    work,app,data,output=map(lambda p:Path(p).resolve(),(work,app,data,output));output.mkdir(parents=True,exist_ok=False)
    runtime=app/'Contents/Resources/Runtime';renderer=app/'Contents/Resources/Renderer/d3d9.dll'
    native=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin/d3dx9_43.dll'
    report=dict(renderer_sha256=sha(renderer),metal_build_sha256=json.loads((work/'arrival-metal-build.json').read_text())['library_sha256'],
                installed_metal_sha256=sha(runtime/'lib/libMoltenVK.dylib'),adapter_sha256=sha(app/'Contents/Resources/Renderer/w101decompress.dll'),launcher_unsigned_sha256=unsigned_sha(app/'Contents/MacOS/Wizard101Native'),
                synthetic_only=True,gameplay_accepted=False,correctness_qualified=False,performance_qualified=False,checks={})
    checks=report['checks']
    with tempfile.TemporaryDirectory(prefix='w101-arrival-verify-') as temp:
        folder=Path(temp);prefix=folder/'Prefix';cache=folder/'known.w101assets';learned=folder/'learning';learned.mkdir()
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_','W101_'))}
        env.update(WINEPREFIX=str(prefix),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',WINEDLLPATH=str(runtime/'lib/wine'),
                   DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',WINEDLLOVERRIDES='d3d9=n;d3dx9_43=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),MVK_CONFIG_RESUME_LOST_DEVICE='1',MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',
                   DXVK_FRAME_RATE='60',DXVK_W101_LIMITER='legacy',DXVK_ASYNC='0',DXVK_W101_WARMUP='0',DXVK_W101_CATALOG='0',DXVK_W101_CACHE='1',
                   DXVK_LOG_PATH=str(folder),DXVK_LOG_LEVEL='none',W101_PERFORMANCE_TEST='1',W101_ASSET_CACHE='1',W101_ASSET_WORKERS='2',
                   W101_GPU_TEXTURE_CONVERSION='off',W101_LOCK_FIX='0',W101_PREPARE_ASSETS='0',W101_ASSET_CACHE_FILE='Z:'+str(cache).replace('/','\\'),
                   W101_ARRIVAL_PATH='Z:'+str(learned).replace('/','\\'),W101_ARRIVAL_KEY='a'*64,W101_PREPARE_PIPELINES='1',W101_SCENE_TEXTURES='1',
                   W101_GAME_REPAIR='0',W101_METAL_ARCHIVE='0',W101_SCENE_NODES='0',W101_DECOMPRESS='off',W101_WAIT_QUEUES='off',W101_NATIVE_DECODE='off')
        def run(label,mode='verify',extra=None,boot=False):
            with (output/(label+'.txt')).open('w') as out:
                result=subprocess.run([str(runtime/'bin/wine'),'wineboot.exe' if boot else str(folder/'WizardGraphicalClient.exe'),'-u' if boot else mode],
                                      cwd=folder,env=env|(extra or {}),stdout=out,stderr=subprocess.STDOUT,timeout=240)
            text=(output/(label+'.txt')).read_text(errors='replace')
            if result.returncode or (not boot and 'PASS' not in text):raise RuntimeError(label+': '+text[-2500:])
            return text
        def fields(text,label):
            line=next(x for x in text.splitlines() if x.startswith(label+' '))
            return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
        def snapshot():return {str(p.relative_to(folder)):p.read_bytes() for p in [cache,*learned.iterdir()] if p.is_file()}
        def restore(seed):
            for p in [cache,*learned.iterdir()]:
                if p.is_file():p.unlink()
            for name,bytes in seed.items():(folder/name).write_bytes(bytes)
        try:
            subprocess.run(['c++','-O2','-std=c++17','-pthread',str(ROOT/'tests/arrival_budget_probe.cpp'),'-o',str(folder/'budget-probe')],check=True)
            subprocess.run([str(folder/'budget-probe')],check=True,timeout=10,capture_output=True)
            checks['atomic_concurrent_budget_limits']=True
            clone(data/'Prefix',prefix)
            checks['installed_prefix_clone']=True
            shutil.copy2(renderer,folder/'d3d9.dll');shutil.copy2(native,folder/'d3dx9_43.dll')
            fixture(folder/'asset.jpg');dds(folder/'packed.dds');dds(folder/'compressed.dds',True)
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static','-std=c++17','-DNOMINMAX',str(ROOT/'tests/arrival_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-luser32','-o',str(folder/'WizardGraphicalClient.exe')],check=True)
            initial=run('learn-with-preparation-off',extra={'W101_PREPARE_PIPELINES':'0'});seed=snapshot()
            cold=fields(initial,'START')
            if cold['restored'] or cold['complete'] or cold['busy']:raise RuntimeError('Preparation-off cold run replayed inputs or launched workers')
            checks['pipeline_learning_with_preparation_off']=True
            if len(seed)!=3:raise RuntimeError('Orderly shutdown did not persist all three bounded input caches: '+str(seed.keys()))
            baseline=run('baseline',extra={'W101_SCENE_TEXTURES':'0','W101_PREPARE_PIPELINES':'0'})
            oracle=re.findall(r'^PIX .*$',baseline,re.M)
            for scene,pipeline in [('0','1'),('1','0'),('1','1')]:
                restore(seed);text=run('mode-'+scene+pipeline,extra={'W101_SCENE_TEXTURES':scene,'W101_PREPARE_PIPELINES':pipeline})
                if re.findall(r'^PIX .*$',text,re.M)!=oracle:raise RuntimeError('CPU/GPU/mip output differs from baseline')
                start,result=fields(text,'START'),fields(text,'RESULT')
                if scene=='1' and result['hits']<100:raise RuntimeError('Prepared scene templates were not reused')
                if pipeline=='1' and (not start['complete'] or start['busy'] or start['restored']<2 or result['pipelines']!=start['pipelines']):
                    raise RuntimeError('Exact saved states did not finish/reuse before play: '+str((start,result)))
                if start['bytes']>64*1024**2 or start['speculative']>32*1024**2:raise RuntimeError('Startup budget exceeded')
                checks['mode-'+scene+pipeline]=dict(passed=True,start=start,result=result)
            checks['cpu_gpu_every_mip_mutation_independence_concurrency_partial_errors_reset_eviction_shutdown']=True
            for fault in ('allocation','copy'):
                restore(seed);text=run('fallback-'+fault,extra={'W101_ARRIVAL_TEST':fault})
                if re.findall(r'^PIX .*$',text,re.M)!=oracle:raise RuntimeError('Failed reuse changed pixels')
                checks['fallback-'+fault]=True
            for fault in ('allocation','create','lock','upload'):
                restore(seed);text=run('prepare-fallback-'+fault,extra={'W101_ASSET_PREPARE_TEST':fault})
                if re.findall(r'^PIX .*$',text,re.M)!=oracle:raise RuntimeError('Failed preparation changed pixels')
                checks['prepare-fallback-'+fault]=True
            for path in list(seed):
                restore(seed);original=(folder/path).read_bytes();damaged=bytearray(original);damaged[len(damaged)//2]^=1;(folder/path).write_bytes(damaged)
                text=run('corrupt-'+Path(path).name)
                if re.findall(r'^PIX .*$',text,re.M)!=oracle:raise RuntimeError('Corrupt-cache fallback changed pixels')
                checks['corrupt-'+Path(path).name]=True
                for malformed in ('truncated','oversize'):
                    restore(seed)
                    target=folder/path
                    if malformed=='truncated':target.write_bytes(original[:17])
                    else:
                        limit=(16 if target.name=='arrival-states.v1' else 32)*1024**2
                        with target.open('wb') as f:f.seek(limit);f.write(b'\0')
                    text=run(malformed+'-'+target.name)
                    if re.findall(r'^PIX .*$',text,re.M)!=oracle:raise RuntimeError('Malformed-cache fallback changed pixels')
                    checks[malformed+'-'+target.name]=True
            restore(seed);text=run('identity-mismatch',extra={'W101_ARRIVAL_KEY':'b'*64})
            if fields(text,'START')['restored']:raise RuntimeError('Incompatible shader inputs restored')
            checks['identity-mismatch']=True
            restore(seed);run('unconsumed','idle');checks['unconsumed']=True
            restore(seed);run('pressure','pressure');checks['exhaustion']=True
            if cache.stat().st_size>32*1024**2 or (learned/'arrival-inputs.v1').stat().st_size>32*1024**2 or (learned/'arrival-states.v1').stat().st_size>16*1024**2:raise RuntimeError('Disk records exceeded bounds')
            checks['combined_disk_bounds']=True
            # Simulated final replacement failure must preserve the last good
            # combined asset file, including when normal play learned new pixels.
            restore(seed);saved=cache.read_bytes()
            run('asset-save-failure','pressure',{'W101_ASSET_PREPARE_TEST':'save'})
            if cache.read_bytes()!=saved:raise RuntimeError('Failed atomic save replaced good assets')
            if list(folder.glob('known.w101assets.*.tmp')):raise RuntimeError('Failed save left temporary assets')
            checks['asset_atomic_save_failure']=True
            # Existing native-D3DX correctness suite runs through the same new DLL.
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static','-std=c++17',str(ROOT/'tests/asset_preparation_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-luser32','-o',str(folder/'WizardGraphicalClient.exe')],check=True)
            run('native-d3dx',extra={'W101_PREPARE_ASSETS':'1'});checks['native_d3dx_pixels_errors_fullscreen']=True
            report['correctness_qualified']=True
            # Alternating pairs measure the actual upload+render workload, after
            # startup. No timing instrumentation is enabled in the renderer.
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static','-std=c++17','-DNOMINMAX',str(ROOT/'tests/arrival_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-luser32','-o',str(folder/'WizardGraphicalClient.exe')],check=True)
            metalDir=folder/'MetalArchive';metalDir.mkdir()
            metalEnv={'W101_METAL_ARCHIVE':'1','W101_METAL_ARCHIVE_PATH':str(metalDir),'W101_METAL_ARCHIVE_KEY':'a'*64}
            for label in ('installed-metal-cold','installed-metal-warm'):
                restore(seed);text=run(label,extra=metalEnv)
                if re.findall(r'^PIX .*$',text,re.M)!=oracle:raise RuntimeError('Installed Metal archive changed pixels')
                archives={p.name:sha(p) for p in metalDir.glob('*.metalar')}
                if not archives:raise RuntimeError('Installed Metal archive did not save')
                if label.endswith('cold'):coldArchives=archives
                elif archives!=coldArchives:raise RuntimeError('Exact Metal restart rewrote the archive')
                checks[label]=True
            restore({});run('benchmark-learn','benchmark');benchseed=snapshot()
            rows=[]
            for pair in range(5):
                row={}
                for state in (['0','1'] if pair%2==0 else ['1','0']):
                    restore(benchseed);text=run(f'benchmark-{pair}-{state}','benchmark',{'W101_SCENE_TEXTURES':state,'W101_PREPARE_PIPELINES':'0'})
                    result=fields(text,'BENCH')
                    if state=='1' and result['hits']!=result['iterations']:raise RuntimeError('Benchmark did not reuse every template')
                    row[state]=result['us']
                rows.append(row)
            fallback=[]
            for pair in range(5):
                row={}
                for state in (['0','1'] if pair%2==0 else ['1','0']):
                    restore(benchseed);text=run(f'fallback-benchmark-{pair}-{state}','fallback-benchmark',{'W101_SCENE_TEXTURES':state,'W101_PREPARE_PIPELINES':'0'})
                    result=fields(text,'BENCH')
                    if result['hits']:raise RuntimeError('Fallback benchmark accidentally reused a known texture')
                    row[state]=result['us']
                fallback.append(row)
            gain=statistics.median(100*(r['0']-r['1'])/r['0'] for r in rows)
            regression=statistics.median(100*(r['1']-r['0'])/r['0'] for r in fallback)
            report['benchmarks']=dict(alternating_pairs=rows,median_improvement_percent=gain,fallback_pairs=fallback,median_fallback_regression_percent=regression)
            report['performance_qualified']=gain>=10 and regression<=2
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=20)
    report['inputs']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'verify_arrival.py',ROOT/'tests/arrival_probe.cpp',ROOT/'tests/asset_preparation_probe.cpp',ROOT/'tests/arrival_budget_probe.cpp']}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-arrival'))
    p.add_argument('--app',type=Path,default=Path('/private/tmp/w101-arrival-candidate.app'))
    p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Metal Cache/Data')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(verify(a.work,a.app,a.data,a.output),indent=2))
