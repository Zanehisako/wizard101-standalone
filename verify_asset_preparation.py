#!/usr/bin/env python3
"""Restart the real renderer/native decoder in a disposable Wine prefix; no gameplay claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from build_runtime import ROOT, sha
from verify_workload_performance import fixture

def dds(path,compressed=False):
    w,h=32,16
    # Three explicit mip levels, without implicit generation.
    fmt=[32,4 if compressed else 0x40,0x31545844 if compressed else 0,0 if compressed else 16,
         0 if compressed else 0xf800,0 if compressed else 0x7e0,0 if compressed else 0x1f,0]
    header=[124,0x21007,h,w,0,0,3,*([0]*11),*fmt,0x401008,0,0,0,0]
    body=b''
    for mip in range(3):
        if compressed:
            body+=b''.join(struct.pack('<HHI',0xf800,0x7e0,0xe4e4e4e4^mip) for _ in range(((w+3)//4)*((h+3)//4)))
        else:
            body+=b''.join(struct.pack('<H',(x*71+y*133+mip*997)&0xffff) for y in range(h) for x in range(w))
        w,h=max(1,w//2),max(1,h//2)
    path.write_bytes(b'DDS '+struct.pack('<31I',*header)+body)

def verify(work,app,data,keep,draw_layout=False,direct_layout=False):
    work,app,data,keep=map(lambda p:Path(p).resolve(),(work,app,data,keep));keep.mkdir(parents=True,exist_ok=True)
    runtime=app/'Contents/Resources/Runtime'; dll=work/'build-renderer/src/d3d9/d3d9.dll'
    native=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin/d3dx9_43.dll'
    report={'synthetic_only':True,'gameplay_verified':False,'draw_layout_cache':draw_layout,'draw_layout_direct':direct_layout,'renderer_sha256':sha(dll),'native_decoder_sha256':sha(native),'checks':{}}
    with tempfile.TemporaryDirectory(prefix='w101-assets-verify-') as temporary:
        probes=Path(temporary);prefix=probes/'Prefix';cache=probes/'known.w101assets'
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_','W101_'))}
        env.update(WINEPREFIX=str(prefix),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   WINEDLLOVERRIDES='d3d9=n;d3dx9_43=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),
                   MVK_CONFIG_RESUME_LOST_DEVICE='1',MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_FRAME_RATE='60',DXVK_W101_LIMITER='legacy',DXVK_ASYNC='0',
                   DXVK_W101_WARMUP='0',DXVK_W101_PIPELINE_OPT='off',DXVK_W101_CPU_OPT='off',DXVK_W101_STUTTER_FIX='0',DXVK_W101_CATALOG='0',DXVK_W101_CACHE='0',
                   DXVK_LOG_PATH=str(probes),W101_PERFORMANCE_TEST='1',W101_ASSET_CACHE='1',W101_ASSET_WORKERS='2',W101_GPU_TEXTURE_CONVERSION='off',W101_LOCK_FIX='0',
                   W101_ASSET_CACHE_FILE='Z:'+str(cache).replace('/','\\'),W101_PREPARE_ASSETS='0',W101_DECOMPRESS='off',W101_WAIT_QUEUES='off',W101_NATIVE_DECODE='off',W101_DRAW_LAYOUT_CACHE='1' if draw_layout else '0',W101_DRAW_LAYOUT_DIRECT='1' if direct_layout else '0')
        def run(label,mode='verify',extra=None,boot=False):
            logfile=keep/(label+'.log')
            with logfile.open('w') as out:
                r=subprocess.run([str(runtime/'bin/wine'), 'wineboot.exe' if boot else str(probes/'WizardGraphicalClient.exe'), '-u' if boot else mode],cwd=probes,env=env | (extra or {}),stdout=out,stderr=subprocess.STDOUT,timeout=240)
            output=logfile.read_text(errors='replace')
            if r.returncode:raise RuntimeError(label+' failed: '+output[-2500:])
            rendererlog=probes/'WizardGraphicalClient_d3d9.log'
            text=rendererlog.read_text(errors='replace') if rendererlog.exists() else ''
            if not boot:
                (keep/(label+'-renderer.log')).write_text(text)
                if 'PASS fallback, reset, fullscreen, orderly teardown' not in output and 'PASS unconsumed teardown' not in output: raise RuntimeError('Probe did not complete')
            return output,text
        try:
            run('wineboot',boot=True)
            shutil.copy2(dll,probes/'d3d9.dll');shutil.copy2(native,probes/'d3dx9_43.dll')
            fixture(probes/'asset.jpg');dds(probes/'packed.dds');dds(probes/'compressed.dds',True)
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static','-std=c++17',str(ROOT/'tests/asset_preparation_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-luser32','-o',str(probes/'WizardGraphicalClient.exe')],check=True)
            output,text=run('learn')
            if not cache.exists():raise RuntimeError('Orderly teardown did not persist learned assets')
            learned=cache.read_bytes();require_size=len(learned)<=32*1024**2
            report['checks']['persistent_cap']=require_size
            if not require_size:raise RuntimeError('Persistent cache exceeded cap')
            if hashlib.sha256(learned[:-32]).digest()!=learned[-32:]:raise RuntimeError('Saved integrity digest mismatch')
            for label,mode,extra,expect in [
                ('restart-off','verify',{},False),('restart-on','verify',{'W101_PREPARE_ASSETS':'1'},True),
                ('unconsumed','idle',{'W101_PREPARE_ASSETS':'1'},True),('reset-first','reset-first',{'W101_PREPARE_ASSETS':'1'},True),
                *[(fault,'verify',{'W101_PREPARE_ASSETS':'1','W101_ASSET_PREPARE_TEST':fault},False) for fault in ('allocation','create','lock','upload')]]:
                cache.write_bytes(learned);out,text=run(label,mode,extra)
                prepared=re.search(r'W101 known assets: prepared=(\d+) upload_complete=1 cutoff=none budget_bytes=(\d+)',text)
                hit=re.search(r'prepared_hits=(\d+)',text)
                if expect and (not prepared or int(prepared[1])<5):raise RuntimeError(label+' did not prepare every loader: '+text[-1500:])
                if label=='restart-on' and (not hit or int(hit[1])<5):raise RuntimeError('Prepared one-use handoff missing')
                if prepared and int(prepared[2])>128*1024**2:raise RuntimeError('Asset budget exceeded')
                if label in ('reset-first','unconsumed') and hit and int(hit[1]):raise RuntimeError('Reset/unconsumed stale handoff')
                report['checks'][label]={'passed':True,'prepared':int(prepared[1]) if prepared else 0,'prepared_hits':int(hit[1]) if hit else 0}
            for label,modify in [
                ('corrupt',lambda b: b[:200]+bytes([b[200]^1])+b[201:]),('truncated',lambda b:b[:-17]),
                ('outdated',lambda b: b[:8]+struct.pack('<I',0)+b[12:-32]),
                ('incompatible',lambda b:b[:16]+bytes([b[16]^1])+b[17:-32]),
                ('invalid-level-count',lambda b:b[:132]+struct.pack('<I',0xffffffff)+b[136:-32]),
                ('oversized',lambda b:b+b'\0'*(32*1024**2+1-len(b)))]:
                changed=modify(learned)
                if label in ('outdated','incompatible','invalid-level-count'):changed+=hashlib.sha256(changed).digest()
                cache.write_bytes(changed);out,text=run(label,extra={'W101_PREPARE_ASSETS':'1'})
                if not re.search(r'W101 known assets: prepared=0 ',text):raise RuntimeError(label+' cache was accepted')
                report['checks'][label]=True
            cache.write_bytes(learned);before=cache.read_bytes();run('atomic-save-failure',extra={'W101_ASSET_PREPARE_TEST':'save'})
            if cache.read_bytes()!=before or list(probes.glob('known.w101assets.*.tmp')):raise RuntimeError('Failed save modified cache or left staging')
            report['checks']['atomic-save-failure']=True
            cache.write_bytes(learned);fixture(probes/'asset.jpg',83)
            out,text=run('changed-content',extra={'W101_PREPARE_ASSETS':'1'})
            hit=re.search(r'prepared_hits=(\d+)',text)
            if not hit or int(hit[1])>=5:raise RuntimeError('Changed encoded content reused old prepared pixels')
            report['checks']['changed-content']=True;fixture(probes/'asset.jpg')
            for label,module in [('decoder-identity',probes/'d3dx9_43.dll'),('renderer-identity',probes/'d3d9.dll')]:
                original=module.read_bytes();module.write_bytes(original+b'identity mismatch')
                try:
                    cache.write_bytes(learned);out,text=run(label,extra={'W101_PREPARE_ASSETS':'1'})
                    if not re.search(r'W101 known assets: prepared=0 ',text):raise RuntimeError(label+' cache was accepted')
                    report['checks'][label]=True
                finally:module.write_bytes(original)
            run('unavailable',extra={'W101_PREPARE_ASSETS':'1','W101_ASSET_CACHE_FILE':'Z:\\unavailable\\known.w101assets'})
            report['checks']['unavailable']=True
            report['checks']['exact_pixels_mips_independence_errors_fullscreen']=True
            # A full working set larger than the process and persistent budgets
            # must still finish native loads. This is correctness pressure, not a benchmark.
            subprocess.run(['x86_64-w64-mingw32-g++','-O2','-static','-std=c++17','-DNOMINMAX',str(ROOT/'tests/workload_performance_probe.cpp'),'-ld3d9','-ld3dx9_43','-lgdi32','-luser32','-o',str(probes/'WizardGraphicalClient.exe')],check=True)
            logfile=keep/'pressure.log'
            with logfile.open('w') as out:
                r=subprocess.run([str(runtime/'bin/wine'),str(probes/'WizardGraphicalClient.exe'),'cache-pressure'],cwd=probes,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=240)
            text=logfile.read_text(errors='replace')
            bound=re.search(r'retained_process_bytes=(\d+)',text)
            if r.returncode or 'PASS native cache pressure' not in text or not bound or int(bound[1])>128*1024**2 or cache.stat().st_size>32*1024**2:raise RuntimeError('Asset pressure/budget failed')
            report['checks']['pressure']={'passed':True,'retained_bytes':int(bound[1]),'saved_bytes':cache.stat().st_size}
            report['learned_bytes']=len(learned)
            (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return report
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-asset-preparation'))
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Optimizations/Data')
    p.add_argument('--keep',type=Path,required=True)
    a=p.parse_args();verify(a.work,a.app,a.data,a.keep)
