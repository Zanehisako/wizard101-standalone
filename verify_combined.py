#!/usr/bin/env python3
"""Verify all 16 switch combinations in one Wine runtime, without gameplay."""
import argparse,json,os,shutil,subprocess
from pathlib import Path
from build_runtime import ROOT,sha
from build_workload import clone
from build_decompression import adapter
from build_native_decode import helper,wine_bridge

def verify(work,baseline,data,thread_baseline=None):
    work,baseline,data=map(lambda p:Path(p).resolve(),(work,baseline,data))
    keep=work/'verification';keep.mkdir(exist_ok=True)
    probes=work/'probes';probes.mkdir(exist_ok=True)
    original=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin/zlib1v142x64.dll'
    shutil.copy2(original,probes/original.name)
    definition=probes/'zlib.def';definition.write_text('LIBRARY zlib1v142x64.dll\nEXPORTS\nuncompress\ninflateInit_\ninflate\ninflateReset\ninflateEnd\n')
    library=probes/'zlib.a';subprocess.run(['x86_64-w64-mingw32-dlltool','-d',str(definition),'-l',str(library)],check=True)
    exe=probes/'decompression_probe.exe'
    subprocess.run(['x86_64-w64-mingw32-gcc','-O3','-static',str(ROOT/'tests/decompression_probe.c'),str(library),'-o',str(exe)],check=True)
    test_adapter=adapter(work,sha(exe),native=True);shutil.copy2(test_adapter,probes/test_adapter.name)
    shutil.copy2(work/'w101decompress.dll',probes/'w101decompress.dll')
    runtime=work/'TestRuntime';clone(work/'Runtime',runtime)
    native=wine_bridge(work,baseline,test_hash=sha(exe),thread_baseline=thread_baseline,wait_queues=True)
    for name,target in [('ntdll.dll','lib/wine/x86_64-windows/ntdll.dll'),('ntdll.so','lib/wine/x86_64-unix/ntdll.so')]:shutil.copy2(native/name,runtime/target)
    prefix=work/'ProbePrefix';clone(data/'Prefix',prefix)
    env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','W101_'))}
    env.update(WINEPREFIX=str(prefix),WINEDEBUG='-all',WINEMSYNC='1',WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',WINEDLLOVERRIDES='zlib1v142x64=n;winemenubuilder.exe=d')
    def run(program,args,label,extra):
        log=keep/(label+'.log')
        with log.open('w') as out:r=subprocess.run([str(runtime/'bin/wine'),str(program),*args],cwd=probes,env={**env,**extra},stdout=out,stderr=subprocess.STDOUT,timeout=180)
        if r.returncode:raise RuntimeError(log.read_text(errors='replace')[-2500:])
        return log.read_text(errors='replace')
    report={'synthetic_only':True,'gameplay_verified':False,'switch_combinations':{},'failure_fallback':{},'wait_queues':{},'production_artifacts':{}}
    try:
        for mask in range(16):
            mode='both' if mask&1 and mask&2 else 'buffer' if mask&1 else 'stream' if mask&2 else 'off'
            native_on=bool(mask&8);flags={'W101_DECOMPRESS':mode,'W101_WAIT_QUEUES':'sharded' if mask&4 else 'off','W101_NATIVE_DECODE':'auto' if native_on else 'off','W101_DECODE_HELPER':str(work/'w101decode-helper')}
            kind='disabled' if mode=='off' and not native_on else 'compat'
            text=run(exe,[test_adapter.name,kind],'combination-'+str(mask),flags)
            passed=('PASS disabled original' if kind=='disabled' else 'PASS compatibility') in text
            report['switch_combinations'][str(mask)]={'features':flags | {'W101_DECODE_HELPER':'bundled ARM64 helper'},'passed':passed}
            print('Combination',mask,'pass' if passed else 'FAIL',flush=True)
        test_helper=helper(work,test=True)
        flags={'W101_DECOMPRESS':'both','W101_WAIT_QUEUES':'sharded','W101_NATIVE_DECODE':'auto','W101_DECODE_HELPER':str(test_helper)}
        for fault in ['startup','crash','late']:
            report['failure_fallback'][fault]='PASS compatibility' in run(exe,[test_adapter.name,'compat'],'combined-'+fault,{**flags,'W101_NATIVE_TEST':fault})
        reject=probes/'unverified.exe';reject.write_bytes(exe.read_bytes()+b'X')
        report['adapter_hash_gate']='PASS unverified' in run(reject,['w101decompress.dll','reject'],'production-adapter-reject',flags)
        report['native_hash_gate']='PASS unverified' in run(reject,[test_adapter.name,'reject'],'native-reject',flags)
        subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)
        waiting=probes/'wait_queues_probe.exe';subprocess.run(['x86_64-w64-mingw32-gcc','-O3','-static',str(ROOT/'tests/wait_queues_probe.c'),'-o',str(waiting)],check=True)
        native=wine_bridge(work,baseline,test_hash=sha(waiting),thread_baseline=thread_baseline,wait_queues=True)
        shutil.copy2(native/'ntdll.dll',runtime/'lib/wine/x86_64-windows/ntdll.dll')
        for mode in ['off','sharded']:
            report['wait_queues'][mode]='PASS ordering' in run(waiting,['compat'],'queues-'+mode,{'W101_WAIT_QUEUES':mode,'W101_DECOMPRESS':'both','W101_NATIVE_DECODE':'auto'})
        bad=probes/'unverified-wait.exe';bad.write_bytes(waiting.read_bytes()+b'X')
        report['wait_hash_gate']='PASS unverified' in run(bad,['reject'],'queue-reject',{'W101_WAIT_QUEUES':'sharded'})
        for key,path in [('adapter_sha256',work/'w101decompress.dll'),('ntdll_pe_sha256',work/'ntdll.dll'),('ntdll_unix_sha256',work/'ntdll.so'),('helper_sha256',work/'w101decode-helper')]:report[key]=sha(path)
        report['compatibility_passed']=all(r['passed'] for r in report['switch_combinations'].values()) and all(report['failure_fallback'].values()) and all(report['wait_queues'].values()) and report['adapter_hash_gate'] and report['native_hash_gate'] and report['wait_hash_gate']
        report['verification_source_sha256']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'verify_combined.py',ROOT/'tests/decompression_probe.c',ROOT/'tests/wait_queues_probe.c']}
        (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        meta=work/'combined-build.json';m=json.loads(meta.read_text());m['verification_sha256']=sha(keep/'report.json');meta.write_text(json.dumps(m,indent=2)+'\n')
        if not report['compatibility_passed']:raise RuntimeError('Combined checks failed')
        return report
    finally:
        subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)
        # Installed APFS clones are retained. Only this disposable test copy goes.
        shutil.rmtree(prefix,ignore_errors=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-combined'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'))
    p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Workload Performance/Data');p.add_argument('--thread-baseline',type=Path)
    a=p.parse_args();print(json.dumps(verify(a.work,a.baseline,a.data,a.thread_baseline),indent=2))
