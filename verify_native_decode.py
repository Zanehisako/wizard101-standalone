#!/usr/bin/env python3
"""Verify IPC failure isolation and legacy-DLL compatibility before scoring."""
import argparse,json,os,re,shutil,statistics,subprocess,time
from pathlib import Path
from build_runtime import ROOT,sha,run
from build_workload import clone
from build_decompression import adapter
from build_native_decode import helper,wine_bridge

def verify(work,baseline,data,thread_baseline=None):
    work,baseline,data=map(lambda p:Path(p).resolve(),(work,baseline,data));keep=work/'verification';keep.mkdir(exist_ok=True)
    test_helper=helper(work,test=True);source=work/'sources/libdeflate';x64=work/'build-x64-libdeflate'
    run(['cmake','-S',str(source),'-B',str(x64),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER=clang','-DCMAKE_OSX_ARCHITECTURES=x86_64',
        '-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0','-DLIBDEFLATE_BUILD_SHARED_LIB=OFF','-DLIBDEFLATE_BUILD_STATIC_LIB=ON','-DLIBDEFLATE_BUILD_GZIP=OFF'],log='native-decode-probe-libdeflate-configure')
    run(['cmake','--build',str(x64),'-j','4'],log='native-decode-probe-libdeflate')
    native_probe=work/'native_decode_probe'
    subprocess.run(['clang','-DW101_VERIFY','-O3','-arch','x86_64','-mmacosx-version-min=13.0','-I'+str(source),str(ROOT/'tests/native_decode_probe.c'),str(x64/'libdeflate.a'),'-pthread','-o',str(native_probe)],check=True)
    faults={};native_env={**os.environ,'W101_DECODE_HELPER':str(test_helper)}
    for case in ['compat','startup','crash','late','busy']:
        log=keep/('ipc-'+case+'.log')
        with log.open('w') as f:r=subprocess.run([str(native_probe),case],env={**native_env,'W101_NATIVE_TEST':case},stdout=f,stderr=subprocess.STDOUT,timeout=20)
        faults[case]=r.returncode==0
        if r.returncode:raise RuntimeError(log.read_text()[-2000:])
    orphan=subprocess.Popen([str(native_probe),'orphan'],env=native_env,stdout=subprocess.PIPE,text=True)
    row=orphan.stdout.readline();child=int(re.search(r'ORPHAN pid=(\d+)',row)[1]);orphan.kill();orphan.wait(timeout=5)
    time.sleep(.7);state=subprocess.run(['ps','-o','stat=','-p',str(child)],capture_output=True,text=True).stdout.strip();faults['orphan_cleanup']=not state or state.startswith('Z')
    probes=work/'probes';probes.mkdir(exist_ok=True);original=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin/zlib1v142x64.dll';shutil.copy2(original,probes/original.name)
    definition=probes/'zlib.def';definition.write_text('LIBRARY zlib1v142x64.dll\nEXPORTS\nuncompress\ninflateInit_\ninflate\ninflateReset\ninflateEnd\n');library=probes/'zlib.a'
    subprocess.run(['x86_64-w64-mingw32-dlltool','-d',str(definition),'-l',str(library)],check=True)
    exe=probes/'decompression_probe.exe';subprocess.run(['x86_64-w64-mingw32-gcc','-O3','-static',str(ROOT/'tests/decompression_probe.c'),str(library),'-o',str(exe)],check=True)
    test_adapter=adapter(work,sha(exe),native=True);shutil.copy2(test_adapter,probes/test_adapter.name);shutil.copy2(work/'w101decompress.dll',probes/'w101decompress.dll')
    test_native=wine_bridge(work,baseline,test_hash=sha(exe),thread_baseline=thread_baseline);runtime=work/'TestRuntime';clone(work/'Runtime',runtime)
    for name,target in [('ntdll.dll','lib/wine/x86_64-windows/ntdll.dll'),('ntdll.so','lib/wine/x86_64-unix/ntdll.so')]:shutil.copy2(test_native/name,runtime/target)
    prefix=work/'ProbePrefix';clone(data/'Prefix',prefix)
    env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','W101_'))}
    env.update(WINEPREFIX=str(prefix),WINEDEBUG='-all',WINEMSYNC='1',WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
        WINEDLLOVERRIDES='zlib1v142x64=n;winemenubuilder.exe=d',W101_DECODE_HELPER=str(work/'w101decode-helper'),W101_NATIVE_DECODE='auto',W101_DECOMPRESS='off')
    def wine(kind,dll='test-w101decompress.dll',program=exe,label=None,extra=None):
        log=keep/((label or kind)+'.log')
        with log.open('w') as f:r=subprocess.run([str(runtime/'bin/wine'),str(program),dll,kind],cwd=probes,env={**env,**(extra or {})},stdout=f,stderr=subprocess.STDOUT,timeout=180)
        if r.returncode:raise RuntimeError(log.read_text(errors='replace')[-2000:])
        return log.read_text(errors='replace')
    try:
        reject=probes/'unverified.exe';reject.write_bytes(exe.read_bytes()+b'X');faults['pe_hash_gate']='PASS unverified' in wine('reject',program=reject)
        # Production adapter has no disposable test identity.
        faults['adapter_hash_gate']='PASS unverified' in wine('reject',dll='w101decompress.dll',program=reject,label='production-reject')
        compatibility=wine('compat');faults['legacy_compatibility']='PASS compatibility' in compatibility and int(re.search(r'buffer_hits=(\d+)',compatibility)[1])>=2
        first_startup=float(re.search(r'STARTUP seconds=([\d.]+)',compatibility)[1])
        # Retain a previously observed cold startup for this exact helper.
        # A verifier rerun with a warm executable cache must still charge it.
        previous=keep/'report.json'
        if previous.exists():
            prior=json.loads(previous.read_text())
            if prior.get('helper_sha256')==sha(work/'w101decode-helper'):
                first_startup=max(first_startup,prior.get('first_observed_startup_seconds',0))
        for fault in ['startup','crash','late']:
            text=wine('compat',label='wine-'+fault,extra={'W101_DECODE_HELPER':str(test_helper),'W101_NATIVE_TEST':fault});faults['wine_'+fault]='PASS compatibility' in text
        pairs=[];inprocess_pairs=[]
        for i in range(5):
            modes=['original','native'] if i%2==0 else ['native','original'];times={}
            for mode in modes:
                text=wine('bench-one',label=f'pair{i+1}-{mode}',extra={'W101_NATIVE_DECODE':'auto' if mode=='native' else 'off','W101_DECOMPRESS':'off' if mode=='native' else 'buffer'})
                rows=re.findall(r'PAIR path=buffer pair=\d+ original=([\d.]+) candidate=([\d.]+)',text);startup=float(re.search(r'STARTUP seconds=([\d.]+)',text)[1])
                # Charge all helper startup cost to each 80-decode batch.
                times[mode]={'original':statistics.median(float(a) for a,b in rows),'candidate':statistics.median(float(b) for a,b in rows)+startup,'startup':startup}
            # Include the first observed helper startup in the first scored
            # pair when it was slower than that pair's subsequent startup.
            extra_startup=max(0,first_startup-times['native']['startup']) if i==0 else 0
            times['native']['candidate']+=extra_startup
            pairs.append({'original_seconds':times['original']['original'],'candidate_seconds':times['native']['candidate'],'startup_seconds':times['native']['startup']+extra_startup})
            inprocess_pairs.append({'inprocess_seconds':times['original']['candidate'],'native_seconds':times['native']['candidate']})
        savings=[1-p['candidate_seconds']/p['original_seconds'] for p in pairs];median=statistics.median(savings);wins=sum(x>0 for x in savings)
        vs_inprocess=statistics.median(1-p['native_seconds']/p['inprocess_seconds'] for p in inprocess_pairs)
        report={'synthetic_only':True,'gameplay_verified':False,'compatibility':faults,'pairs':pairs,'median_savings_fraction':median,'wins':wins,
            'versus_inprocess_libdeflate':{'pairs':inprocess_pairs,'median_savings_fraction':vs_inprocess},
            'gate_passed':all(faults.values()) and median>=.10 and wins>=4,'helper_architecture':'arm64','client_architecture':'x86_64',
            'startup_copy_communication_completion_included':True,'adapter_sha256':sha(work/'w101decompress.dll'),'ntdll_pe_sha256':sha(work/'ntdll.dll'),
            'first_observed_startup_seconds':first_startup,'comparison_reference':'original game DLL 1.2.3; separate from in-process libdeflate comparison',
            'ntdll_unix_sha256':sha(work/'ntdll.so'),'helper_sha256':sha(work/'w101decode-helper')}
        (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n');meta=work/'native-decode-build.json';m=json.loads(meta.read_text());m['verification_sha256']=sha(keep/'report.json');m['default_mode']='auto' if report['gate_passed'] else 'off';meta.write_text(json.dumps(m,indent=2)+'\n');print(json.dumps(report,indent=2));return report
    finally:subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-native-decode'));p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'));p.add_argument('--thread-baseline',type=Path);p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Workload Performance/Data');a=p.parse_args();verify(a.work,a.baseline,a.data,a.thread_baseline)
