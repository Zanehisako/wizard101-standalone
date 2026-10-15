#!/usr/bin/env python3
"""Stress both real Wine wait-queue tables and benchmark five alternating pairs."""
import argparse,json,os,re,shutil,statistics,subprocess
from pathlib import Path
from build_runtime import ROOT,sha
from build_workload import clone
from build_wait_queues import build

def verify(work,baseline,data):
    work,baseline,data=map(lambda p:Path(p).resolve(),(work,baseline,data));keep=work/'verification';keep.mkdir(exist_ok=True)
    exe=work/'wait_queues_probe.exe';subprocess.run(['x86_64-w64-mingw32-gcc','-O3','-static',str(ROOT/'tests/wait_queues_probe.c'),'-o',str(exe)],check=True)
    test=build(work,baseline,test_hash=sha(exe));test_runtime=work/'TestRuntime';clone(work/'Runtime',test_runtime);shutil.copy2(test,test_runtime/'lib/wine/x86_64-windows/ntdll.dll')
    prefix=work/'ProbePrefix';clone(data/'Prefix',prefix)
    env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','W101_'))}
    env.update(WINEPREFIX=str(prefix),WINEDEBUG='-all',WINEMSYNC='1',WINEDLLPATH=str(test_runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(test_runtime/'lib')+':/usr/lib',WINEDLLOVERRIDES='winemenubuilder.exe=d')
    def run(mode,kind,program=exe,label=None):
        log=keep/((label or mode+'-'+kind)+'.log')
        with log.open('w') as f:r=subprocess.run([str(test_runtime/'bin/wine'),str(program),kind],env={**env,'W101_WAIT_QUEUES':mode},stdout=f,stderr=subprocess.STDOUT,timeout=120)
        if r.returncode:raise RuntimeError(log.read_text(errors='replace')[-2000:])
        return log.read_text(errors='replace')
    try:
        checks={}
        for mode in ['off','sharded']:checks[mode]='PASS ordering' in run(mode,'compat')
        reject=work/'unverified.exe';reject.write_bytes(exe.read_bytes()+b'X');checks['hash_gate']='PASS unverified' in run('sharded','reject',reject)
        pairs=[]
        for i in range(5):
            times={}
            for mode in (['off','sharded'] if i%2==0 else ['sharded','off']):
                t=run(mode,'bench',label=f'pair{i+1}-{mode}');times[mode]=float(re.search(r'BENCH seconds=([\d.]+)',t)[1])
            pairs.append(times)
        savings=[1-p['sharded']/p['off'] for p in pairs];median=statistics.median(savings);wins=sum(x>0 for x in savings)
        report={'synthetic_only':True,'gameplay_verified':False,'ntdll_pe_sha256':sha(work/'ntdll.dll'),'compatibility':checks,'pairs':pairs,'median_savings_fraction':median,'wins':wins,'gate_passed':all(checks.values()) and median>=.10 and wins>=4}
        (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n');meta=work/'wait-queues-build.json';m=json.loads(meta.read_text());m['verification_sha256']=sha(keep/'report.json');m['default_mode']='sharded' if report['gate_passed'] else 'off';meta.write_text(json.dumps(m,indent=2)+'\n')
        print(json.dumps(report,indent=2));return report
    finally:subprocess.run([str(test_runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-wait-queues'));p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'));p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Workload Performance/Data');a=p.parse_args();verify(a.work,a.baseline,a.data)
