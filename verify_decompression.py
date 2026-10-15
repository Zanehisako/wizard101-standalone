#!/usr/bin/env python3
"""Compare the adapter to the installed 1.2.3 DLL in a disposable Wine prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
from build_decompression import adapter
from build_runtime import ROOT,sha
from build_workload import clone

def verify(work,game_bin,baseline_data):
    work,game_bin,baseline_data=map(lambda p:Path(p).resolve(),(work,game_bin,baseline_data))
    probes=work/'probes';probes.mkdir(exist_ok=True);keep=work/'verification';keep.mkdir(exist_ok=True)
    original=game_bin/'zlib1v142x64.dll';shutil.copy2(original,probes/original.name)
    definition=probes/'zlib.def';definition.write_text('LIBRARY zlib1v142x64.dll\nEXPORTS\nuncompress\ninflateInit_\ninflate\ninflateReset\ninflateEnd\n')
    library=probes/'zlib.a'
    subprocess.run(['x86_64-w64-mingw32-dlltool','-d',str(definition),'-l',str(library)],check=True)
    exe=probes/'decompression_probe.exe'
    subprocess.run(['x86_64-w64-mingw32-gcc','-std=c11','-O3','-static',str(ROOT/'tests/decompression_probe.c'),str(library),'-o',str(exe)],check=True)
    test_dll=adapter(work,sha(exe));shutil.copy2(test_dll,probes/test_dll.name)
    shutil.copy2(work/'w101decompress.dll',probes/'w101decompress.dll')
    prefix=work/'ProbePrefix';clone(baseline_data/'Prefix',prefix)
    runtime=work/'Runtime';env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','W101_'))}
    env.update(WINEPREFIX=str(prefix),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',
        WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
        WINEDLLOVERRIDES='zlib1v142x64=n;winemenubuilder.exe=d')
    def run(mode,kind,dll='test-w101decompress.dll'):
        log=keep/(mode+'-'+kind+'.log')
        with log.open('w') as f:
            result=subprocess.run([str(runtime/'bin/wine'),str(exe),dll,kind],cwd=probes,env={**env,'W101_DECOMPRESS':mode},stdout=f,stderr=subprocess.STDOUT,timeout=180)
        return result.returncode,log.read_text(errors='replace')
    report={'synthetic_only':True,'gameplay_verified':False,'adapter_sha256':sha(work/'w101decompress.dll'),
        'original_dll_sha256':sha(original),'test_executable_sha256':sha(exe),'tests':{},'benchmarks':{}}
    try:
        code,text=run('both','reject','w101decompress.dll');report['unverified_game_rejected']=code==0 and 'PASS unverified' in text
        if not report['unverified_game_rejected']:raise RuntimeError('Production hash gate failed')
        for mode in ['buffer','stream','both']:
            code,text=run(mode,'compat');report['tests'][mode]={'passed':code==0 and 'PASS compatibility' in text,'result':text[-1800:]}
            print(mode,report['tests'][mode],flush=True)
        code,text=run('both','bench')
        if code:raise RuntimeError('Benchmark failed: '+text[-2000:])
        for path in ['buffer','stream']:
            pairs=[{'original_seconds':float(a),'candidate_seconds':float(b)} for a,b in re.findall(r'PAIR path='+path+r' pair=\d+ original=([\d.]+) candidate=([\d.]+)',text)]
            if len(pairs)!=5:raise RuntimeError('Five complete pairs required')
            savings=[1-p['candidate_seconds']/p['original_seconds'] for p in pairs]
            median=statistics.median(savings);wins=sum(x>0 for x in savings)
            report['benchmarks'][path]={'pairs':pairs,'median_savings_fraction':median,'wins':wins,
                'gate_passed':median>=.10 and wins>=4 and report['tests'][path]['passed']}
        buffer=report['benchmarks']['buffer']['gate_passed'];stream=report['benchmarks']['stream']['gate_passed']
        report['default_mode']='both' if buffer and stream and report['tests']['both']['passed'] else 'buffer' if buffer else 'stream' if stream else 'off'
        report['verification_source_sha256']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'verify_decompression.py',ROOT/'tests/decompression_probe.c']}
        (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        metadata=json.loads((work/'decompression-build.json').read_text());metadata['default_mode']=report['default_mode'];metadata['verification_sha256']=sha(keep/'report.json')
        (work/'decompression-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
        print(json.dumps(report,indent=2));return report
    finally:
        subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-decompression'))
    p.add_argument('--game-bin',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Workload Performance/Data/Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin')
    p.add_argument('--baseline-data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Workload Performance/Data')
    a=p.parse_args();verify(a.work,a.game_bin,a.baseline_data)
