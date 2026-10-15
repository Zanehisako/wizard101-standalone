#!/usr/bin/env python3
"""Package isolated experiment apps using APFS clones of the current baseline."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
from build_app import build as build_launcher
from build_runtime import ROOT,sha
from build_workload import clone

def package(work,kind,baseline_app,baseline_data,output=None,launcher=None):
    work,baseline_app,baseline_data=map(lambda p:Path(p).resolve(),(work,baseline_app,baseline_data))
    name={'decompression':'Wizard101 Decompression','wait-queues':'Wizard101 Wait Queues','native-decode':'Wizard101 Native Decode','combined':'Wizard101 Optimizations'}[kind]
    output=Path(output).resolve() if output else Path.home()/'Desktop'/(name+'.app')
    if output.exists():raise RuntimeError('Use a fresh output app; existing apps are preserved')
    data=Path.home()/'Library/Application Support'/name/'Data'
    if data.exists():raise RuntimeError('Use a fresh experiment data directory')
    report=work/'verification/report.json';evidence=json.loads(report.read_text())
    metadata=work/(kind+'-build.json');provenance=json.loads(metadata.read_text())
    for input_name,digest in provenance['inputs'].items():
        if sha(ROOT/'decompression'/input_name)!=digest:raise RuntimeError('Build input changed: '+input_name)
    if provenance['verification_sha256']!=sha(report):raise RuntimeError('Stale verification report')
    for key,file in [('adapter_sha256',work/'w101decompress.dll'),('ntdll_pe_sha256',work/'ntdll.dll'),('ntdll_unix_sha256',work/'ntdll.so'),('helper_sha256',work/'w101decode-helper')]:
        if key in evidence and sha(file)!=evidence[key]:raise RuntimeError('Verification binary changed: '+key)
    if kind=='decompression':
        if evidence['adapter_sha256']!=sha(work/'w101decompress.dll') or provenance['verification_sha256']!=sha(report):raise RuntimeError('Stale decoder verification')
        defaults={'W101_DECOMPRESS':evidence['default_mode']}
    elif kind=='wait-queues':defaults={'W101_WAIT_QUEUES':'sharded' if evidence['gate_passed'] else 'off'}
    elif kind=='native-decode':defaults={'W101_NATIVE_DECODE':'auto' if evidence['gate_passed'] else 'off'}
    else:
        if not evidence['compatibility_passed']:raise RuntimeError('Combined compatibility checks failed')
        defaults={'W101_DECOMPRESS':'off','W101_WAIT_QUEUES':'off','W101_NATIVE_DECODE':'off'}
    original=baseline_app/'Contents/Resources'
    if sha(original/'Renderer/d3d9.dll')!=provenance['baseline_renderer_sha256']:raise RuntimeError('Current performance app differs from the tested build baseline')
    before={str(f.relative_to(baseline_app)):sha(f) for f in [baseline_app/'Contents/MacOS/Wizard101Native',original/'Renderer/d3d9.dll',original/'Runtime/lib/libMoltenVK.dylib']}
    with tempfile.TemporaryDirectory(prefix='w101-experiment-package-') as temp:
        temp=Path(temp);launcher=Path(launcher).resolve() if launcher else build_launcher(temp/'Launcher.app',development=True)
        if not (launcher/'Contents/MacOS/Wizard101Native').is_file():raise RuntimeError('Missing launcher executable')
        stage=temp/(name+'.app');clone(baseline_app,stage)
        macos=stage/'Contents/MacOS';resources=stage/'Contents/Resources';renderer=resources/'Renderer'
        shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',macos/'Wizard101Native')
        info_path=stage/'Contents/Info.plist';info=plistlib.loads(info_path.read_bytes())
        info['CFBundleName']=info['CFBundleDisplayName']=name;info['CFBundleIdentifier']='org.wizard101native.'+kind
        info['W101DefaultDataDirectory']=name+'/Data';info.pop('W101DataRoot',None);info.pop('W101CaptureTiming',None)
        info['W101ExperimentDefaults']=defaults
        if kind=='combined':info['W101CombinedOptimizations']=True
        for license_name in ['libdeflate-1.26.txt','zlib-ng-2.3.3.txt']:
            shutil.copy2(ROOT/'licenses'/license_name,resources/'Licenses'/license_name)
        if kind in ['decompression','native-decode','combined']:
            render=work/'build-renderer/src/d3d9/d3d9.dll'
            shutil.copy2(render,renderer/'d3d9.dll');(renderer/'d3d9.sha256').write_text(sha(render)+'\n')
            adapter=work/'w101decompress.dll';shutil.copy2(adapter,renderer/adapter.name);(renderer/'w101decompress.sha256').write_text(sha(adapter)+'\n')
            inherited=renderer/'workload-performance-build.json';base_meta=json.loads(inherited.read_text());base_meta['renderer_sha256']=sha(render)
            base_meta['experiment_overlay']=kind;inherited.write_text(json.dumps(base_meta,indent=2)+'\n')
        if kind=='wait-queues':shutil.copy2(work/'ntdll.dll',resources/'Runtime/lib/wine/x86_64-windows/ntdll.dll')
        if kind in ['native-decode','combined']:
            shutil.copy2(work/'ntdll.dll',resources/'Runtime/lib/wine/x86_64-windows/ntdll.dll')
            shutil.copy2(work/'ntdll.so',resources/'Runtime/lib/wine/x86_64-unix/ntdll.so')
            shutil.copy2(work/'w101decode-helper',resources/'Runtime/bin/w101decode-helper')
            info['W101NativeDecodeHelper']=True
        inherited=renderer/'workload-performance-build.json'
        base_meta=json.loads(inherited.read_text())
        for key,file in [('renderer_sha256',renderer/'d3d9.dll'),('ntdll_pe_sha256',resources/'Runtime/lib/wine/x86_64-windows/ntdll.dll'),('ntdll_sha256',resources/'Runtime/lib/wine/x86_64-unix/ntdll.so')]:
            base_meta.setdefault('experiment_baseline_'+key,base_meta[key]);base_meta[key]=sha(file)
        base_meta['experiment_overlay']=kind
        for file in [inherited,resources/'Runtime/workload-performance-build.json']:file.write_text(json.dumps(base_meta,indent=2)+'\n')
        plistlib.dump(info,info_path.open('wb'),sort_keys=False)
        shutil.copy2(metadata,renderer/metadata.name)
        subprocess.run(['codesign','--force','--deep','--sign','-',str(stage)],check=True,capture_output=True)
        clone(baseline_data,data)
        game=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin'
        shutil.copy2(renderer/'d3d9.dll',game/'d3d9.dll')
        if kind in ['decompression','native-decode','combined']:shutil.copy2(renderer/'w101decompress.dll',game/'w101decompress.dll')
        clone(stage,output)
    after={key:sha(baseline_app/key) for key in before}
    if before!=after:raise RuntimeError('Baseline app changed')
    preservation={name:sha(baseline_data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin'/name)==sha(game/name) for name in ['WizardGraphicalClient.exe','zlib1v142x64.dll','config.xml','preferences.xml','WizardGraphicalClient.dxvk-cache'] if (game/name).exists()}
    if not all(preservation.values()):raise RuntimeError('Cloned game settings, content or caches changed')
    result={'app':str(output),'data':str(data),'defaults':defaults,'baseline_preserved':before==after,'game_inputs_preserved':preservation,'cache_workers_unchanged':info['W101WorkloadPerformanceDefaults'],'report_sha256':sha(report)}
    (work/'delivery.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kind',choices=['decompression','wait-queues','native-decode','combined']);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--baseline-app',type=Path,default=Path.home()/'Desktop/Wizard101 Workload Performance.app')
    p.add_argument('--baseline-data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Workload Performance/Data');p.add_argument('--output',type=Path)
    p.add_argument('--launcher',type=Path,help='Optional launcher already built from these sources')
    a=p.parse_args();package(a.work,a.kind,a.baseline_app,a.baseline_data,a.output,a.launcher)
