#!/usr/bin/env python3
"""Verify workload instrumentation in disposable prefixes; never gameplay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from profile_report import report
from workload_report import summarize,jsonlines

ROOT=Path(__file__).resolve().parent

def verify(app,build,keep):
    app,build,keep=map(lambda p:Path(p).resolve(),(app,build,keep));keep.mkdir(parents=True,exist_ok=True)
    resources=app/'Contents/Resources'; runtime=resources/'Runtime'
    with tempfile.TemporaryDirectory(prefix='w101-workload-check-') as temp:
        work=Path(temp); probes=work/'probes';probes.mkdir()
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','W101_WORKLOAD_'))}
        env.update(WINEPREFIX=str(work/'Prefix'),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',
            WINEDLLPATH=str(runtime/'lib/wine'),WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
            DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),
            MVK_CONFIG_RESUME_LOST_DEVICE='1',MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_FRAME_RATE='60',
            DXVK_W101_LIMITER='legacy',DXVK_W101_WARMUP='0',DXVK_ASYNC='0',DXVK_LOG_PATH=str(probes))
        def run(args,name,wine=True):
            with (keep/(name+'.log')).open('w') as log:
                r=subprocess.run(([str(runtime/'bin/wine')] if wine else [])+list(map(str,args)),cwd=probes,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            if r.returncode: raise RuntimeError(name+' failed: '+(keep/(name+'.log')).read_text(errors='replace')[-2000:])
            return (keep/(name+'.log')).read_text(errors='replace')
        def profile(mode):
            folder=probes/mode; folder.mkdir();
            env['DXVK_W101_PROFILE']=str(folder/'timing.csv'); env['DXVK_W101_PROFILE_SECONDS']='900'
            env['W101_WORKLOAD_NATIVE']=str(folder/'native.jsonl'); env['W101_WORKLOAD_THREADS']=str(folder/'threads.jsonl')
            import time
            env['W101_WORKLOAD_DEADLINE_UNIX_US']=str(time.time_ns()//1000+900000000)
            return folder
        results={}
        try:
            run(['wineboot.exe','-u'],'wineboot')
            shutil.copy2(resources/'Renderer/d3d9.dll',probes)
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static',str(ROOT/'tests/workload_hooks_probe.cpp'),'-ld3d9','-lgdi32','-o',str(probes/'WizardGraphicalClient.exe')],check=True)
            run([probes/'WizardGraphicalClient.exe'],'hooks-disabled')
            if list(probes.rglob('*.csv')) or list(probes.rglob('*.jsonl')): raise RuntimeError('Disabled instrumentation wrote recordings')
            folder=profile('hooks')
            env['DXVK_W101_PROFILE_ALL_READS']='1'
            output=run([probes/'WizardGraphicalClient.exe'],'hooks-enabled')
            initial,worker=map(int,re.search(r'initial_tid=(\d+) worker_tid=(\d+)',output).groups())
            evidence=summarize(folder/'timing.csv'); shutil.copytree(folder,keep/'hooks',dirs_exist_ok=True)
            if not evidence['initial_thread_verified'] or evidence['initial_thread'][0]!=initial: raise RuntimeError('Wine initial-thread callsite mapping failed')
            if worker not in evidence['verified_thread_mapping']: raise RuntimeError('Created Windows thread has no native ID')
            if not evidence['aligned'] or not evidence['evidence_complete']: raise RuntimeError('Clock, recording loss or orderly shutdown failed')
            counters=evidence['timing']['cpu_event_summary']
            covered=set(counters)|set(evidence['timing']['aggregated_events'])
            if not {'game_read_file','game_read_file_async_admission','game_resource_wait','game_critical_section'}<=covered: raise RuntimeError('Read/wait scope missing')
            (keep/'hooks-summary.json').write_text(json.dumps(evidence,indent=2)+'\n')
            results['hooks']={'read_results_and_error_semantics':True,'wait_results_and_error_semantics':True,
                'initial_thread_verified':True,'created_thread_verified':True,'clock_uncertainty_us':evidence['clock_uncertainty_us'],
                'recording_loss':False,'orderly_shutdown':True,'disabled_no_recordings':True}
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static',str(ROOT/'tests/d3d9_probe.cpp'),'-ld3d9','-lgdi32','-o',str(probes/'WizardGraphicalClient.exe')],check=True)
            folder=profile('render-uploads')
            output=run([probes/'WizardGraphicalClient.exe','--uploads'],'render-uploads-profiled')
            if 'PASS all checks' not in output: raise RuntimeError('Profiled rendering did not finish')
            evidence=summarize(folder/'timing.csv'); counters=evidence['workload_counters']['deltas']
            shutil.copytree(folder,keep/'render-uploads',dirs_exist_ok=True)
            (keep/'render-uploads-summary.json').write_text(json.dumps(evidence,indent=2)+'\n')
            if not evidence['aligned'] or not evidence['initial_thread_verified'] or not evidence['native_capture_finalized'] or not evidence['timing']['capture_finalized'] or not evidence['gpu_buffers'] or not evidence['timing']['presentations']:
                raise RuntimeError('Profiled rendering coverage/clock/finalization missing')
            if sum(evidence['timing']['dropped_by_category'].values())!=evidence['timing']['dropped_events']:
                raise RuntimeError('CPU event loss is not accounted by category')
            if evidence['timing']['dropped_events'] and evidence['evidence_complete']:
                raise RuntimeError('Lossy capture was incorrectly marked complete evidence')
            if not all(counters.get(k,0)>0 for k in ('draw_calls','primitive_count','texture_creates','texture_upload_bytes')): raise RuntimeError('Draw/texture workload counters have no interval coverage')
            import csv
            rows=csv.DictReader(line for line in (folder/'timing.csv').read_text().splitlines() if not line.startswith('#'))
            if not any(r['event']=='graphics_pipeline_driver_compile' and r['pipeline_id'] for r in rows): raise RuntimeError('Pipeline identity missing')
            shutil.copytree(folder,keep/'render-uploads',dirs_exist_ok=True)
            (keep/'render-uploads-summary.json').write_text(json.dumps(evidence,indent=2)+'\n')
            results['profiled_rendering']={'readbacks':True,'draw_texture_counters':True,'pipeline_identity':True,'gpu_buffers':evidence['gpu_buffers'],'clock_uncertainty_us':evidence['clock_uncertainty_us'],
                'dropped_cpu_events':evidence['timing']['dropped_events'],'loss_accounted':True,'complete_recording_evidence':evidence['evidence_complete']}
            # Exercise renderer queue contention, size/time caps and shutdown.
            flags=['x86_64-w64-mingw32-g++','-std=c++17','-O2','-static','-DNOMINMAX','-msse3','-I'+str(build/'workload-d9vk/src')]
            text=(ROOT/'tests/profile_probe.cpp').read_text().replace('std::chrono::seconds(181)','std::chrono::seconds(901)')
            (probes/'profile.cpp').write_text(text)
            subprocess.run([*flags,str(probes/'profile.cpp'),str(build/'build-workload-d9vk/src/util/libutil.a'),'-luser32','-lgdi32','-o',str(probes/'profile.exe')],check=True)
            for mode in ('devices','time','contention','size'):
                folder=profile('renderer-'+mode);env['DXVK_W101_PROFILE_MAX_BYTES']='1048576'
                run([probes/'profile.exe',mode],'renderer-'+mode)
                r=report(folder/'timing.csv')
                if not r['capture_finalized'] or (folder/'timing.csv').stat().st_size>1048576: raise RuntimeError('Renderer cap/finalization failed')
                if mode=='contention' and (r['presentations']!=128 or r['dropped_presentations']!=0): raise RuntimeError('Frame timestamps lost under pressure')
                results['renderer_'+mode]={'finalized':True,'bytes':(folder/'timing.csv').stat().st_size,'dropped_events':r['dropped_events']}
                shutil.copy2(folder/'timing.csv',keep/('renderer-'+mode+'.csv'))
            for k in list(env):
                if k.startswith(('W101_WORKLOAD_','DXVK_W101_PROFILE')): env.pop(k)
            subprocess.run(['clang++','-arch','x86_64','-std=c++17','-O2','-fblocks','-I'+str(ROOT/'workload'),str(ROOT/'tests/workload_native_probe.mm'),'-framework','Metal','-framework','Foundation','-o',str(probes/'native-probe')],check=True)
            for mode in ('disabled','gpu','time','size','outstanding','invalid_path'):
                folder=probes/('native-'+mode);folder.mkdir();env.pop('W101_WORKLOAD_NATIVE',None)
                env['W101_WORKLOAD_SECONDS']='1' if mode=='time' else '900';env['W101_WORKLOAD_NATIVE_MAX_BYTES']='32768' if mode=='size' else str(128*1024**2)
                if mode!='disabled': env['W101_WORKLOAD_NATIVE']=str(folder if mode=='invalid_path' else folder/'native.jsonl')
                run([probes/'native-probe',mode],'native-'+mode,wine=False)
                rows,valid=jsonlines(folder/'native.jsonl')
                if mode in ('disabled','invalid_path'):
                    if rows: raise RuntimeError('Disabled/failed-open recording wrote data')
                    continue
                footer=next((r for r in rows if r['type']=='footer'),None)
                if not valid or not footer: raise RuntimeError('Native writer did not finalize')
                if mode=='gpu':
                    gpu=[r for r in rows if r['type']=='gpu'];
                    if len(gpu)!=16 or footer['dropped_gpu'] or footer['invalid_timestamps'] or footer['outstanding_gpu']: raise RuntimeError('Real Metal completion timing failed')
                if mode=='size' and (folder/'native.jsonl').stat().st_size>32768: raise RuntimeError('Native size bound exceeded')
                if mode=='time':
                    header=next(r for r in rows if r['type']=='header')
                    if header['deadline_mach_us']-header['origin_mach_us']>1000000 or any(r.get('mach_us',0)>=header['deadline_mach_us'] for r in rows): raise RuntimeError('Native recording deadline exceeded')
                results['native_'+mode]=footer;shutil.copy2(folder/'native.jsonl',keep/('native-'+mode+'.jsonl'))
            for k in list(env):
                if k.startswith('W101_WORKLOAD_'): env.pop(k)
            subprocess.run(['clang','-arch','x86_64','-O2','-I'+str(ROOT/'workload'),str(ROOT/'tests/workload_thread_probe.c'),'-o',str(probes/'thread-probe')],check=True)
            for mode in ('disabled','size','expired'):
                folder=probes/('thread-'+mode);folder.mkdir();env.pop('W101_WORKLOAD_THREADS',None)
                env['W101_WORKLOAD_DEADLINE_UNIX_US']='1' if mode=='expired' else str(__import__('time').time_ns()//1000+900000000)
                if mode!='disabled': env['W101_WORKLOAD_THREADS']=str(folder/'threads.jsonl')
                run([probes/'thread-probe'],'thread-'+mode,wine=False)
                rows,valid=jsonlines(folder/'threads.jsonl')
                if mode=='size':
                    if not valid or not rows or (folder/'threads.jsonl').stat().st_size>1024**2: raise RuntimeError('Thread identity size bound/transparency failed')
                    results['thread_size']={'bytes':(folder/'threads.jsonl').stat().st_size,'records':len(rows),'errno_preserved':True}
                elif rows: raise RuntimeError('Disabled/expired thread recorder wrote data')
            results.update(synthetic_only=True,gameplay_verified=False,renderer_sha256=hashlib.sha256((resources/'Renderer/d3d9.dll').read_bytes()).hexdigest())
            (keep/'report.json').write_text(json.dumps(results,indent=2)+'\n'); print(json.dumps(results,indent=2)); return results
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('app','build','keep'): p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();verify(a.app,a.build,a.keep)
