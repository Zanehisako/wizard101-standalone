#!/usr/bin/env python3
"""Build an isolated performance renderer and contention-only Wine instrumentation."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from build_runtime import ROOT, WORK, JOBS, run, sha
from build_workload import clone, build as build_baseline

def verify_translation(source):
    src=source/'src'; fingerprint=hashlib.sha256()
    files=list((src/'dxso').rglob('*'))+list((src/'spirv').rglob('*'))+list((src/'dxvk').glob('dxvk_shader*'))+list((src/'d3d9').glob('d3d9_shader*'))
    for file in sorted(set(files)):
        if file.is_file():
            fingerprint.update(str(file.relative_to(src)).encode()); fingerprint.update(file.read_bytes())
    expected='#pragma once\n#define W101_SHADER_REVISION "'+fingerprint.hexdigest()+'"\n'
    if (src/'util/util_shader_revision.h').read_text()!=expected:
        raise RuntimeError('Performance overlay changed working shader translation')
    return fingerprint.hexdigest()

def apply_verification(work,report):
    """Select defaults only from a successful report for this exact renderer."""
    work,report=Path(work).resolve(),Path(report).resolve()
    evidence=json.loads(report.read_text()); dll=work/'build-workload-d9vk/src/d3d9/d3d9.dll'
    if evidence['renderer_sha256']!=sha(dll) or not evidence['profiling_overhead']['gate_passed']:
        raise RuntimeError('Verification does not match renderer or profiling overhead gate')
    defaults={'W101_ASSET_CACHE':'1' if evidence['benchmarks']['cache']['gate_passed'] else '0',
        'W101_ASSET_WORKERS':'2' if evidence['benchmarks']['workers']['gate_passed'] else '0',
        'W101_LOCK_FIX':'0','W101_GPU_TEXTURE_CONVERSION':'auto' if evidence['benchmarks']['gpu']['gate_passed'] else 'off'}
    if evidence['feature_defaults']!=defaults: raise RuntimeError('Verification defaults disagree with measured gates')
    for path in (dll.parent/'workload-performance-build.json',work/'Runtime/workload-performance-build.json'):
        metadata=json.loads(path.read_text())
        if metadata['renderer_sha256']!=sha(dll): raise RuntimeError('Build provenance is stale')
        metadata['feature_defaults']=defaults
        metadata['verification_report_sha256']=sha(report)
        metadata['native_d3dx_verified_sha256']=evidence['native_d3dx_sha256']
        path.write_text(json.dumps(metadata,indent=2)+'\n')
    return defaults

def wine_contention(work, baseline, wine_base):
    source=wine_base/'sources/wine'; build=wine_base/'build-wine'
    out=work/'native'; out.mkdir(exist_ok=True)
    for f in ('WineLockPE.h','WineLockNative.h'): shutil.copy2(ROOT/'performance'/f,out/f)
    lib=(source/'dlls/ntdll/unixlib.h').read_text()
    lib=lib.replace('    unix_pe_module_loaded,\n#endif','    unix_pe_module_loaded,\n#endif\n    unix_w101_lock_begin,\n    unix_w101_lock_end,')
    (out/'unixlib.h').write_text(lib)
    sync=(source/'dlls/ntdll/sync.c').read_text().replace('WINE_DEFAULT_DEBUG_CHANNEL(sync);','#include "WineLockPE.h"\n\nWINE_DEFAULT_DEBUG_CHANNEL(sync);')
    old='        /* Now wait for it */\n        if ((status = RtlpWaitForCriticalSection( crit ))) RtlRaiseStatus( status );'
    new='        /* Instrument only this original contention branch. */\n        struct w101_lock_params params;\n        w101_lock_begin(&params,crit,__builtin_return_address(0));\n        status = RtlpWaitForCriticalSection( crit );\n        w101_lock_end(&params);\n        if (status) RtlRaiseStatus( status );'
    if old not in sync: raise RuntimeError('Wine contention callsite changed')
    sync=sync.replace('#include \"ntdll_misc.h\"','#include \"unixlib.h\"\n#include \"ntdll_misc.h\"',1)
    (out/'sync.c').write_text(sync.replace(old,new,1))
    loader=(source/'dlls/ntdll/unix/loader.c').read_text().replace('static const unixlib_entry_t unix_call_funcs[] =','#include "WineLockNative.h"\n\nstatic const unixlib_entry_t unix_call_funcs[] =',1)
    end=loader.index('\n};',loader.index('static const unixlib_entry_t unix_call_funcs[]'))
    loader=loader[:end]+'\n    w101_lock_begin_native,\n    w101_lock_end_native,'+loader[end:]
    (out/'loader.c').write_text(loader)
    def commands(file,target):
        text=subprocess.check_output(['make','-n','-W',str(source/file),target],cwd=build,text=True).replace('\\\n',' ')
        return [shlex.split(c) for c in text.splitlines() if c.startswith(('clang ','x86_64-w64-mingw32-gcc ','tools/winegcc/winegcc '))]
    def replace(command,pairs): return [pairs.get(v,v) for v in command]
    cmds=commands('dlls/ntdll/sync.c','dlls/ntdll/x86_64-windows/ntdll.dll')
    compiler=next(c for c in cmds if '/sync.c' in ' '.join(c))
    compiler=replace(compiler,{str(source/'dlls/ntdll/sync.c'):str(out/'sync.c'),'dlls/ntdll/x86_64-windows/sync.o':str(out/'sync.o')})
    run(compiler,build,log='workload-performance-wine-pe')
    linker=next(c for c in cmds if c[0]=='tools/winegcc/winegcc')
    linker=replace(linker,{'dlls/ntdll/x86_64-windows/sync.o':str(out/'sync.o'),'dlls/ntdll/x86_64-windows/ntdll.dll':str(out/'ntdll.dll')})
    run(linker,build,log='workload-performance-wine-pe-link')
    cmds=commands('dlls/ntdll/unix/loader.c','dlls/ntdll/ntdll.so')
    compiler=next(c for c in cmds if '/loader.c' in ' '.join(c))
    compiler=replace(compiler,{str(source/'dlls/ntdll/unix/loader.c'):str(out/'loader.c'),'dlls/ntdll/unix/loader.o':str(out/'loader.o')})
    compiler+=['-I'+str(source/'dlls/ntdll/unix')]
    run(compiler,build,log='workload-performance-wine-native')
    linker=next(c for c in cmds if '-dynamiclib' in c)
    linker=replace(linker,{'dlls/ntdll/unix/loader.o':str(out/'loader.o'),'dlls/ntdll/ntdll.so':str(out/'ntdll.so'),'dlls/ntdll/unix/server.o':str(baseline/'native/server.o')})
    run(linker,build,log='workload-performance-wine-native-link')
    runtime=work/'Runtime'
    shutil.copy2(out/'ntdll.dll',runtime/'lib/wine/x86_64-windows/ntdll.dll')
    target=runtime/'lib/wine/x86_64-unix/ntdll.so'; shutil.copy2(out/'ntdll.so',target)
    subprocess.run(['install_name_tool','-delete_rpath',str(wine_base/'runtime/lib'),str(target)],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(target)],check=True)

def build(work,baseline,wine_base,defaults=None):
    work,baseline,wine_base=map(lambda p:Path(p).resolve(),(work,baseline,wine_base))
    if not (baseline/'Runtime/workload-build.json').exists(): build_baseline(baseline,wine_base)
    work.mkdir(parents=True,exist_ok=True)
    source=work/'workload-d9vk'; output=work/'build-workload-d9vk'
    clone(baseline/'workload-d9vk',source); clone(baseline/'Runtime',work/'Runtime')
    patch=ROOT/'renderer/workload-performance.patch'; stamp=source/'.performance-applied.patch'
    if stamp.exists(): run(['git','apply','--reverse',str(stamp)],source,log='workload-performance-remove')
    if subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=source,capture_output=True).returncode:
        run(['git','apply',str(patch)],source,log='workload-performance-overlay')
    stamp.write_bytes(patch.read_bytes())
    for a,b in [('AssetBudget.h','wizard101_asset_budget.h'),('AssetPreparation.h','wizard101_asset_preparation.h'),('AssetCacheImpl.h','wizard101_asset_cache_impl.h'),('NativeAssetHooks.h','wizard101_native_assets.h'),('Identity.h','wizard101_performance_identity.h')]:
        shutil.copy2(ROOT/'performance'/a,source/'src/d3d9'/b)
    shutil.copy2(ROOT/'performance/convert16.comp',source/'src/d3d9/shaders/d3d9_convert_packed16.comp')
    if not (output/'build.ninja').exists():
        run(['meson','setup',str(output),str(source),'--cross-file',str(source/'build-win64.txt'),'--buildtype','release','-Denable_d3d9=true','-Denable_dxgi=false','-Denable_d3d10=false','-Denable_d3d11=false'],log='workload-performance-configure')
    translation=verify_translation(source)
    run(['ninja','-C',str(output),'-j',JOBS],log='workload-performance-renderer')
    wine_contention(work,baseline,wine_base)
    dll=output/'src/d3d9/d3d9.dll'; runtime=work/'Runtime'
    baseline_meta=json.loads((baseline/'Runtime/workload-build.json').read_text())
    if translation!=baseline_meta['translation_source_sha256']: raise RuntimeError('Translation differs from working renderer')
    metadata={**baseline_meta,'workload_performance':True,'workload_diagnostics':False,
        'renderer_sha256':sha(dll),'ntdll_sha256':sha(runtime/'lib/wine/x86_64-unix/ntdll.so'),
        'ntdll_pe_sha256':sha(runtime/'lib/wine/x86_64-windows/ntdll.dll'),
        'performance_inputs':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'performance').glob('*')) if p.is_file()},
        'performance_patch_sha256':sha(patch),'baseline_renderer_sha256':baseline_meta['renderer_sha256'],
        'feature_defaults':defaults or {'W101_ASSET_CACHE':'0','W101_ASSET_WORKERS':'0','W101_LOCK_FIX':'0','W101_GPU_TEXTURE_CONVERSION':'off'},
        'feature_scope':{'cache':'native D3DX memory loaders, immutable managed static 2D results','workers':'independent 16-bit conversion rows','gpu':'large 2D packed-16 conversion','lock_fix':'unavailable: game lock owner/caller unresolved'},
        'asset_memory_max_bytes':128*1024**2,'worker_threads':2,'worker_queue_max_jobs':32,
        'gpu_min_input_bytes':256*1024,'draw_timing_stride':256,'lock_max_bytes':4*1024**2,
        'gameplay_acceptance':False,'optimizations':'independent workload performance switches; previous candidates off'}
    (dll.parent/'workload-performance-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (runtime/'workload-performance-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return runtime,dll

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-build'));p.add_argument('--wine-base',type=Path,default=WORK)
    p.add_argument('--verified-report',type=Path,help='Select defaults for an existing build without recompiling measured binaries')
    a=p.parse_args()
    if a.verified_report:
        verify_translation(a.work/'workload-d9vk');apply_verification(a.work,a.verified_report)
        rt,dll=a.work/'Runtime',a.work/'build-workload-d9vk/src/d3d9/d3d9.dll'
    else:rt,dll=build(a.work,a.baseline,a.wine_base)
    print(json.dumps({'runtime':str(rt),'renderer':str(dll)},indent=2))
