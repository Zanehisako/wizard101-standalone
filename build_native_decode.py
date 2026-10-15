#!/usr/bin/env python3
"""Build an ARM64 helper and isolated Wine bridge, keeping original queues."""
import argparse,json,shlex,shutil,subprocess
from pathlib import Path
from build_runtime import ROOT,WORK,run,sha
from build_decompression import libraries,adapter,renderer
from build_workload import clone

def helper(work,test=False):
    source=work/'sources/libdeflate';output=work/'build-arm64-libdeflate'
    run(['cmake','-S',str(source),'-B',str(output),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER=clang',
        '-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0','-DLIBDEFLATE_BUILD_SHARED_LIB=OFF',
        '-DLIBDEFLATE_BUILD_STATIC_LIB=ON','-DLIBDEFLATE_BUILD_GZIP=OFF'],log='native-decode-arm64-configure')
    run(['cmake','--build',str(output),'-j','4'],log='native-decode-arm64-libdeflate')
    file=work/('w101decode-helper-test' if test else 'w101decode-helper')
    cmd=['clang','-O3','-arch','arm64','-mmacosx-version-min=13.0','-I'+str(source),str(ROOT/'decompression/NativeHelper.c'),str(output/'libdeflate.a'),'-pthread','-o',str(file)]
    if test:cmd.insert(1,'-DW101_VERIFY')
    run(cmd,log='native-decode-arm64-helper');subprocess.run(['codesign','--force','--sign','-',str(file)],check=True,capture_output=True);return file

def wine_bridge(work,baseline,wine_base=WORK,test_hash=None,thread_baseline=None,wait_queues=False):
    thread_baseline=Path(thread_baseline or baseline.parent/'w101-workload-build').resolve()
    native=work/('test-native' if test_hash else 'native');native.mkdir(exist_ok=True)
    source=wine_base/'sources/wine';build=wine_base/'build-wine'
    lib=(baseline/'native/unixlib.h').read_text().replace('    unix_w101_lock_end,','    unix_w101_lock_end,\n    unix_w101_native_decode,')
    (native/'unixlib.h').write_text(lib)
    for name in ['Sha256.h','Identity.h','NtIdentity.h','NativeProtocol.h','NativePE.h','NativeClient.h']:
        shutil.copy2(ROOT/'decompression'/name,native/name)
    for name in ['WineLockPE.h','WineLockNative.h']:shutil.copy2(baseline/'native'/name,native/name)
    sync=(baseline/'native/sync.c').read_text()+'\n#include "NativePE.h"\n';(native/'sync.c').write_text(sync)
    if wait_queues:
        from build_wait_queues import queue_overlay
        sync=queue_overlay(sync,test_hash is not None)
        (native/'sync.c').write_text(sync)
        shutil.copy2(ROOT/'decompression/WaitQueues.h',native/'WaitQueues.h')
    loader=(baseline/'native/loader.c').read_text().replace('#include "WineLockNative.h"','#include "WineLockNative.h"\n#include "NativeClient.h"')
    end=loader.index('\n};',loader.index('static const unixlib_entry_t unix_call_funcs[]'))
    loader=loader[:end]+'\n    w101_native_dispatch,'+loader[end:];(native/'loader.c').write_text(loader)
    exports='\n@ stdcall W101NativeDecode(ptr)\n'
    if wait_queues and test_hash:exports+='@ stdcall W101WaitQueueInfo()\n@ stdcall W101WaitQueueDepth(ptr)\n'
    spec=native/'ntdll.spec';spec.write_text((source/'dlls/ntdll/ntdll.spec').read_text()+exports)
    def commands(file,target):
        out=subprocess.check_output(['make','-n','-W',str(source/file),target],cwd=build,text=True).replace('\\\n',' ')
        return [shlex.split(c) for c in out.splitlines() if c.startswith(('clang ','x86_64-w64-mingw32-gcc ','tools/winegcc/winegcc '))]
    pairs={str(source/'dlls/ntdll/sync.c'):str(native/'sync.c'),'dlls/ntdll/x86_64-windows/sync.o':str(native/'sync.o'),
        'dlls/ntdll/x86_64-windows/ntdll.dll':str(native/'ntdll.dll'),str(source/'dlls/ntdll/ntdll.spec'):str(spec)}
    cmds=commands('dlls/ntdll/sync.c','dlls/ntdll/x86_64-windows/ntdll.dll');cc=next(c for c in cmds if '/sync.c' in ' '.join(c));cc=[pairs.get(v,v) for v in cc]
    if test_hash:cc+=['-DW101_TEST_HASH="'+test_hash+'"']
    run(cc,build,log='native-decode-wine-pe');run([pairs.get(v,v) for v in next(c for c in cmds if c[0]=='tools/winegcc/winegcc')],build,log='native-decode-wine-pe-link')
    cmds=commands('dlls/ntdll/unix/loader.c','dlls/ntdll/ntdll.so');cc=next(c for c in cmds if '/loader.c' in ' '.join(c))
    pairs={str(source/'dlls/ntdll/unix/loader.c'):str(native/'loader.c'),'dlls/ntdll/unix/loader.o':str(native/'loader.o'),
        'dlls/ntdll/ntdll.so':str(native/'ntdll.so'),'dlls/ntdll/unix/server.o':str(thread_baseline/'native/server.o')}
    run([pairs.get(v,v) for v in cc]+['-I'+str(source/'dlls/ntdll/unix')],build,log='native-decode-wine-unix')
    run([pairs.get(v,v) for v in next(c for c in cmds if '-dynamiclib' in c)],build,log='native-decode-wine-unix-link')
    subprocess.run(['install_name_tool','-delete_rpath',str(wine_base/'runtime/lib'),str(native/'ntdll.so')],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(native/'ntdll.so')],check=True,capture_output=True)
    return native

def build(work,baseline,thread_baseline=None,wait_queues=False):
    work,baseline=map(lambda p:Path(p).resolve(),(work,baseline));work.mkdir(parents=True,exist_ok=True)
    libraries(work);helper(work);adapter(work,native=True);render=renderer(work,baseline)
    native=wine_bridge(work,baseline,thread_baseline=thread_baseline,wait_queues=wait_queues);clone(baseline/'Runtime',work/'Runtime')
    for name,path in [('ntdll.dll','lib/wine/x86_64-windows/ntdll.dll'),('ntdll.so','lib/wine/x86_64-unix/ntdll.so')]:
        shutil.copy2(native/name,work/name);shutil.copy2(native/name,work/'Runtime'/path)
    shutil.copy2(work/'w101decode-helper',work/'Runtime/bin/w101decode-helper')
    metadata={'renderer_sha256':sha(render),'adapter_sha256':sha(work/'w101decompress.dll'),'helper_sha256':sha(work/'w101decode-helper'),
        'baseline_renderer_sha256':json.loads((baseline/'Runtime/workload-performance-build.json').read_text())['renderer_sha256'],
        'ntdll_pe_sha256':sha(work/'ntdll.dll'),'ntdll_unix_sha256':sha(work/'ntdll.so'),'arena_bytes':32*1024**2,'workers':2,'slots':2,
        'request_timeout_ms':50,'startup_timeout_ms':2000,'default_mode':'off','gameplay_accepted':False,
        'inputs':{name:sha(ROOT/'decompression'/name) for name in ['Adapter.c','Identity.h','RendererLoader.h','NativeProtocol.h','NativeHelper.c','NativeClient.h','NativePE.h','NtIdentity.h','Sha256.h','sources.lock.json']}}
    (work/'native-decode-build.json').write_text(json.dumps(metadata,indent=2)+'\n');return work

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-native-decode'));p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'));p.add_argument('--thread-baseline',type=Path);a=p.parse_args();print(build(a.work,a.baseline,a.thread_baseline))
