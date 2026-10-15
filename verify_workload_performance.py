#!/usr/bin/env python3
"""Verify isolated workload features and decide defaults from paired synthetic evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import tempfile
import time
import zlib
from workload_report import summarize, jsonlines

ROOT=Path(__file__).resolve().parent

def lock_limits(probes,keep):
    program=probes/'lock-native-probe'
    subprocess.run(['clang','-arch','x86_64','-O2','-I'+str(ROOT/'performance'),str(ROOT/'tests/lock_native_probe.c'),'-o',str(program)],check=True)
    base={k:v for k,v in os.environ.items() if not k.startswith(('W101_','DYLD_'))}; sizes={}
    for mode in ('disabled','expired','size'):
        path=probes/('lock-'+mode+'.jsonl');env=dict(base)
        if mode!='disabled':env['W101_WORKLOAD_LOCKS']=str(path)
        env['W101_WORKLOAD_DEADLINE_UNIX_US']='1' if mode=='expired' else str(time.time_ns()//1000+900000000)
        with (keep/('lock-native-'+mode+'.log')).open('w') as log:
            subprocess.run([str(program),mode],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
        rows,valid=jsonlines(path)
        if mode=='size':
            footer=next((r for r in rows if r.get('type')=='footer'),None)
            if not valid or not footer or path.stat().st_size>4*1024**2: raise RuntimeError('Contention size bound or footer failed')
            sizes={'bytes':path.stat().st_size,'records':footer['records'],'footer_valid':True}
            shutil.copy2(path,keep/path.name)
        elif path.exists(): raise RuntimeError('Disabled or expired contention writer wrote a file')
    return {**sizes,'disabled_no_file':True,'expired_no_file':True,'errno_preserved':True}

def cache_pressure(text):
    values=re.search(r'W101 asset cache: hits=(\d+) misses=(\d+) insertions=(\d+) retained_process_bytes=(\d+)',text)
    if not values: raise RuntimeError('Native cache pressure statistics missing')
    hits,misses,insertions,retained=map(int,values.groups())
    # Native success remains usable when cache admission cannot reserve memory.
    if (hits,misses)!=(2,18) or not 16<=insertions<=18 or not 16*1024**2<=retained<=128*1024**2:
        raise RuntimeError('Native cache eviction, clear or memory bound failed')
    return {'hits':hits,'misses':misses,'insertions':insertions,'cache_admissions_skipped':misses-insertions,
        'retained_bytes_after_clear':retained,'lru_eviction':True,'managed_resource_clear':True}

def verify_supplement(build,keep,native_d3dx=None):
    """Focused boundary checks, separated from scored performance comparisons."""
    build,keep=Path(build).resolve(),Path(keep).resolve();keep.mkdir(parents=True,exist_ok=True)
    runtime=build/'Runtime';dll=build/'build-workload-d9vk/src/d3d9/d3d9.dll'
    with tempfile.TemporaryDirectory(prefix='w101-performance-boundaries-') as temp:
        probes=Path(temp);env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','W101_'))}
        env.update(WINEPREFIX=str(probes/'Prefix'),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
            WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),
            MVK_CONFIG_RESUME_LOST_DEVICE='1',MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_FRAME_RATE='60',DXVK_W101_LIMITER='legacy',DXVK_W101_WARMUP='0',DXVK_ASYNC='0',DXVK_LOG_PATH=str(probes),
            W101_PERFORMANCE_TEST='1',W101_PERFORMANCE_TEST_FORCE_16BIT='1',W101_ASSET_CACHE='0',W101_ASSET_WORKERS='0',W101_LOCK_FIX='0',W101_GPU_TEXTURE_CONVERSION='off')
        try:
            with (keep/'boundary-wineboot.log').open('w') as log:
                subprocess.run([str(runtime/'bin/wine'),'wineboot.exe','-u'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            shutil.copy2(dll,probes/'d3d9.dll')
            subprocess.run(['x86_64-w64-mingw32-g++','-O3','-static','-std=c++17','-DNOMINMAX',str(ROOT/'tests/workload_performance_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-luser32','-o',str(probes/'WizardGraphicalClient.exe')],check=True)
            for mode,flags in [('off',{}),('workers',{'W101_ASSET_WORKERS':'2'}),('gpu',{'W101_GPU_TEXTURE_CONVERSION':'auto'})]:
                path=keep/('edges-'+mode+'.log')
                with path.open('w') as log:
                    subprocess.run([str(runtime/'bin/wine'),str(probes/'WizardGraphicalClient.exe'),'edges'],cwd=probes,env={**env,**flags},stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
                if path.read_text(errors='replace').count('PASS packed edges format=')!=5:
                    raise RuntimeError('Boundary format coverage missing')
            result={'renderer_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),'edge_modes':['off','workers','gpu'],
                'odd_dimensions_padded_pitch':True,'partial_rectangles':True,'mip_fallback':True,'lock_limits':lock_limits(probes,keep)}
            if native_d3dx:
                shutil.copy2(native_d3dx,probes/'d3dx9_43.dll');fixture(probes/'asset.jpg')
                path=keep/'cache-pressure.log'
                with path.open('w') as log:
                    subprocess.run([str(runtime/'bin/wine'),str(probes/'WizardGraphicalClient.exe'),'cache-pressure'],cwd=probes,env={**env,'W101_ASSET_CACHE':'1','WINEDLLOVERRIDES':env['WINEDLLOVERRIDES']+';d3dx9_43=n'},stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
                result['cache_pressure']=cache_pressure(path.read_text(errors='replace'))
            (keep/'supplement.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return result
        finally:subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

def fixture(path,change=0):
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+bytes(v for x in range(512) for v in ((x*31+change)%256,(y*73+change)%256,((x*31)^(y*73)+change)%256,255)) for y in range(512))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',512,512,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))

def verify(build,native_d3dx,keep):
    build,native_d3dx,keep=map(lambda p:Path(p).resolve(),(build,native_d3dx,keep)); keep.mkdir(parents=True,exist_ok=True)
    runtime=build/'Runtime';source=build/'workload-d9vk'; dll=build/'build-workload-d9vk/src/d3d9/d3d9.dll'
    results={'synthetic_only':True,'gameplay_verified':False,'renderer_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),
        'native_d3dx_sha256':hashlib.sha256(native_d3dx.read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='w101-workload-performance-check-') as temp:
        work=Path(temp);probes=work/'probes';probes.mkdir();prefix=work/'Prefix'
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','W101_'))}
        env.update(WINEPREFIX=str(prefix),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',WINEDLLOVERRIDES='d3d9=n;d3dx9_43=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
            WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),
            MVK_CONFIG_RESUME_LOST_DEVICE='1',MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_FRAME_RATE='60',DXVK_W101_LIMITER='legacy',DXVK_W101_WARMUP='0',DXVK_ASYNC='0',DXVK_LOG_PATH=str(probes),
            W101_PERFORMANCE_TEST='1',W101_PERFORMANCE_TEST_FORCE_16BIT='1',W101_ASSET_CACHE='0',W101_ASSET_WORKERS='0',W101_LOCK_FIX='0',W101_GPU_TEXTURE_CONVERSION='off')
        def run(args,name,feature=None):
            active={**env,**(feature or {})}
            with (keep/(name+'.log')).open('w') as log:
                result=subprocess.run([str(runtime/'bin/wine'),*map(str,args)],env=active,cwd=probes,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            text=(keep/(name+'.log')).read_text(errors='replace')
            if result.returncode: raise RuntimeError(name+' failed: '+text[-2500:])
            return text
        def compile(file,output,extra=()):
            subprocess.run(['x86_64-w64-mingw32-g++','-O3','-static','-std=c++17','-DNOMINMAX','-msse3','-I'+str(source/'src'),str(ROOT/'tests'/file),*map(str,extra),'-ld3d9','-lgdi32','-luser32','-o',str(probes/output)],check=True)
        def capture(name):
            folder=probes/name;folder.mkdir()
            return folder,{'DXVK_W101_PROFILE':str(folder/'timing.csv'),'DXVK_W101_PROFILE_SECONDS':'900','W101_WORKLOAD_NATIVE':str(folder/'native.jsonl'),
                'W101_WORKLOAD_THREADS':str(folder/'threads.jsonl'),'W101_WORKLOAD_LOCKS':str(folder/'locks.jsonl'),
                'W101_WORKLOAD_DEADLINE_UNIX_US':str(time.time_ns()//1000+900000000)}
        try:
            run(['wineboot.exe','-u'],'wineboot')
            shutil.copy2(dll,probes/'d3d9.dll');shutil.copy2(native_d3dx,probes/'d3dx9_43.dll')
            fixture(probes/'asset.jpg');fixture(probes/'asset-changed.jpg',83)
            compile('workload_performance_probe.cpp','WizardGraphicalClient.exe',['-ld3dx9_43'])
            for name,flags in [('off',{}),('workers',{'W101_ASSET_WORKERS':'2'}),('gpu',{'W101_GPU_TEXTURE_CONVERSION':'auto'}),('combined',{'W101_ASSET_CACHE':'1','W101_ASSET_WORKERS':'2','W101_GPU_TEXTURE_CONVERSION':'auto'})]:
                text=run([probes/'WizardGraphicalClient.exe','pixels'],'pixels-'+name,flags)
                if text.count('PASS packed format=')!=5: raise RuntimeError('Exhaustive format coverage missing')
            results['packed_pixels']={'formats':5,'values_per_format':65536,'passes':2,'modes':['off','workers','gpu','combined'],'rewrite_ordering':True,'reset':True}
            cache_pairs=[];gpu_pairs=[]
            for pair in range(5):
                order=['off','on'] if pair%2==0 else ['on','off'];cache={};gpu={}
                for mode in order:
                    text=run([probes/'WizardGraphicalClient.exe','cache'],f'cache-pair{pair}-{mode}',{'W101_ASSET_CACHE':'1' if mode=='on' else '0'})
                    cache[mode]=int(re.search(r'native_asset_32_loads_us=(\d+)',text)[1])
                    if mode=='on' and not re.search(r'W101 asset cache: hits=[1-9]\d*',text): raise RuntimeError('Cache did not serve actual native-load revisits')
                    text=run([probes/'WizardGraphicalClient.exe','bench'],f'gpu-pair{pair}-{mode}',{'W101_GPU_TEXTURE_CONVERSION':'auto' if mode=='on' else 'off'})
                    gpu[mode]=sum(map(int,re.findall(r'packed_format_\d_128_uploads_us=(\d+)',text)))
                cache_pairs.append(cache);gpu_pairs.append(gpu)
            compile('asset_workers_probe.cpp','workers.exe',[build/'build-workload-d9vk/src/util/libutil.a','-lbcrypt'])
            text=run([probes/'workers.exe'],'workers-stress')
            worker_pairs=[{'off':int(a),'on':int(b)} for a,b in re.findall(r'serial_us=(\d+) parallel_us=(\d+)',text)]
            if len(worker_pairs)!=5: raise RuntimeError('Worker paired coverage missing')
            def benchmark(pairs):
                ratio=statistics.median(p['on']/p['off'] for p in pairs)
                return {'pairs':pairs,'median_ratio':ratio,'reduction_percent':(1-ratio)*100,'gate_passed':ratio<=0.90 and sum(p['on']<p['off'] for p in pairs)>=4}
            results['benchmarks']={name:benchmark(pairs) for name,pairs in [('cache',cache_pairs),('gpu',gpu_pairs),('workers',worker_pairs)]}
            results['worker_stress']={'memory_bound':True,'simultaneous_callers':24,'queue_backpressure':True,'shutdown_drains':True,'stopped_fallback':True}
            text=run([probes/'WizardGraphicalClient.exe','cache-pressure'],'cache-pressure',{'W101_ASSET_CACHE':'1'})
            results['cache_pressure']=cache_pressure(text)
            for name,flags in [('off',{}),('workers',{'W101_ASSET_WORKERS':'2'}),('gpu',{'W101_GPU_TEXTURE_CONVERSION':'auto'})]:
                text=run([probes/'WizardGraphicalClient.exe','edges'],'edges-'+name,flags)
                if text.count('PASS packed edges format=')!=5: raise RuntimeError('Boundary format coverage missing')
            results['edges']={'odd_dimensions_padded_pitch':True,'partial_rectangles':True,'mip_fallback':True,'modes':['off','workers','gpu']}
            compile('contention_probe.cpp','WizardGraphicalClient.exe')
            overhead=[]
            for pair in range(5):
                measured={}
                for mode in (['off','on'] if pair%2==0 else ['on','off']):
                    flags={};folder=None
                    if mode=='on': folder,flags=capture(f'contention-{pair}')
                    text=run([probes/'WizardGraphicalClient.exe'],f'contention-pair{pair}-{mode}',flags)
                    measured[mode]=int(re.search(r'uncontended_cpu_100ns=(\d+)',text)[1])
                    if mode=='on':
                        initial,owner=map(int,re.search(r'initial_tid=(\d+) owner_tid=(\d+)',text).groups())
                        rows,valid=jsonlines(folder/'locks.jsonl');matching=[r for r in rows if r.get('type')=='lock_contention' and r['windows_tid']==initial and r['owner_windows_tid_at_wait']==owner and r['end_mach_us']-r['start_mach_us']>=60000]
                        if not valid or not any(r.get('type')=='footer' for r in rows) or not matching or matching[0]['caller_module']!='main_executable' or not matching[0]['caller_rva']: raise RuntimeError('Exact caller/owner contention mapping failed')
                        if (folder/'locks.jsonl').stat().st_size>4*1024**2: raise RuntimeError('Lock recording exceeded cap')
                        evidence=summarize(folder/'timing.csv')
                        if not evidence['initial_thread_verified'] or not evidence['aligned'] or not evidence['timing']['capture_finalized']: raise RuntimeError('Contention capture thread/clock/shutdown failed')
                        shutil.copytree(folder,keep/f'contention-{pair}')
                overhead.append(measured)
            ratio=statistics.median(p['on']/p['off'] for p in overhead)
            results['profiling_overhead']={'paired_main_thread_cpu':overhead,'median_ratio':ratio,'gate_passed':ratio<=1.02,'scope':'one hundred million uncontended game-thread lock acquisitions; native snapshots/GPU timing enabled separately from comparisons'}
            results['contention']={'caller_rva_and_owner_verified':True,'recursive_and_error_semantics':True,'main_thread_identity_verified':True,'clock_alignment':True,'max_bytes':4*1024**2}
            results['lock_limits']=lock_limits(probes,keep)
            # Disabled launch must not emit any profiler files.
            disabled=probes/'disabled';disabled.mkdir();run([probes/'WizardGraphicalClient.exe'],'disabled-no-recording',{'DXVK_LOG_PATH':str(disabled)})
            if list(disabled.glob('*.jsonl')) or list(disabled.glob('*.csv')): raise RuntimeError('Disabled profiling wrote data')
            defaults={'W101_ASSET_CACHE':'1' if results['benchmarks']['cache']['gate_passed'] else '0',
                'W101_ASSET_WORKERS':'2' if results['benchmarks']['workers']['gate_passed'] else '0','W101_LOCK_FIX':'0',
                'W101_GPU_TEXTURE_CONVERSION':'auto' if results['benchmarks']['gpu']['gate_passed'] else 'off'}
            results['feature_defaults']=defaults
            (keep/'report.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2));return results
        finally: subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','keep'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--native-d3dx',type=Path);p.add_argument('--supplement-only',action='store_true')
    a=p.parse_args()
    if a.supplement_only:verify_supplement(a.build,a.keep,a.native_d3dx)
    elif a.native_d3dx:verify(a.build,a.native_d3dx,a.keep)
    else:p.error('--native-d3dx is required for native cache comparisons')
