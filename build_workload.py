#!/usr/bin/env python3
"""Build an isolated workload diagnostic runtime and baseline renderer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from build_runtime import ROOT, LOCK, WORK, JOBS, download, extract, sha, run

def clone(source, target):
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cp', '-cR', str(source), str(target)], check=True)

def build(work, base=WORK):
    work, base = Path(work).resolve(), Path(base).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source, output = work/'workload-d9vk', work/'build-workload-d9vk'
    lock = json.loads(LOCK.read_text())
    pins=[('d9vk-f229921c1b7f14edeadeccff04a9e65d0a016148.tar.gz',source),
          ('SPIRV-Headers-0bcc624926a25a2a273d07877fd25a6ff5ba1cfb.tar.gz',source/'include/spirv'),
          ('Vulkan-Headers-85c2334e92e215cce34e8e0ed8b2dce4700f4a50.tar.gz',source/'include/vulkan')]
    # Use new trees for changed patches; existing baseline artifacts survive.
    stamp=source/'.workload-inputs.json'
    patches=[ROOT/'renderer/wizard101.patch', ROOT/'renderer/diagnostic.patch',ROOT/'renderer/capture.patch', ROOT/'renderer/workload.patch']
    inputs={p.name:sha(p) for p in patches}
    if source.exists() and not stamp.exists():
        raise RuntimeError('Unstamped source tree. Choose a fresh --work directory.')
    if stamp.exists() and json.loads(stamp.read_text()) != inputs:
        raise RuntimeError('Inputs changed. Choose a fresh --work directory.')
    if not stamp.exists():
        for name,target in pins: extract(download(name,lock[name]['url'],lock[name]['sha256']),target,strip=True)
        for patch in patches[:2]: run(['git','apply',str(patch)],source,log='workload-'+patch.stem)
        # Reuse schema-2 recording infrastructure, without the warm-up overlay.
        capture=patches[2].read_text().split('diff --git a/src/d3d9/d3d9_shader.cpp')[0]
        subprocess.run(['git','apply','-'],cwd=source,input=capture,text=True,check=True)
        run(['git','apply',str(patches[3])],source,log='workload-instrumentation')
        stamp.write_text(json.dumps(inputs,indent=2)+'\n')
    if not (output/'build.ninja').exists():
        run(['meson','setup',str(output),str(source),'--cross-file',str(source/'build-win64.txt'),'--buildtype','release',
             '-Denable_d3d9=true','-Denable_dxgi=false','-Denable_d3d10=false','-Denable_d3d11=false'],log='workload-configure')
    fingerprint=hashlib.sha256(); src=source/'src'
    files=list((src/'dxso').rglob('*'))+list((src/'spirv').rglob('*'))+list((src/'dxvk').glob('dxvk_shader*'))+list((src/'d3d9').glob('d3d9_shader*'))
    for f in sorted(set(files)):
        if f.is_file(): fingerprint.update(str(f.relative_to(src)).encode()); fingerprint.update(f.read_bytes())
    expected='#pragma once\n#define W101_SHADER_REVISION "'+fingerprint.hexdigest()+'"\n'
    if (src/'util/util_shader_revision.h').read_text()!=expected: raise RuntimeError('Working shader translation fingerprint changed')
    run(['ninja','-C',str(output),'-j',JOBS],log='workload-renderer')
    dll=output/'src/d3d9/d3d9.dll'
    runtime=work/'Runtime'; clone(base/'runtime',runtime)
    # Compile just ntdll's thread-start callsites using its actual configured
    # toolchain and existing objects. Source and baseline build remain untouched.
    wineSource=base/'sources/wine'; wineBuild=base/'build-wine'; native=work/'native'; native.mkdir(exist_ok=True)
    server=wineSource/'dlls/ntdll/unix/server.c'
    text=server.read_text()
    text=text.replace('static int get_unix_tid(void)', '#include "WineThreadIdentity.h"\n\nstatic int get_unix_tid(void)',1)
    text=text.replace('set_thread_id( NtCurrentTeb(), pid, tid );','set_thread_id( NtCurrentTeb(), pid, tid );\n    w101_thread_identity(tid, 1);',1)
    start=text.index('void server_init_thread(')
    end=text.index('\nNTSTATUS WINAPI NtAllocateReserveObject',start)
    block=text[start:end].replace('close( reply_pipe );','close( reply_pipe );\n    w101_thread_identity(HandleToULong(NtCurrentTeb()->ClientId.UniqueThread), 0);')
    text=text[:start]+block+text[end:]
    (native/'server.c').write_text(text); shutil.copy2(ROOT/'workload/WineThreadIdentity.h',native)
    commands=subprocess.check_output(['make','-n','-W',str(server),'dlls/ntdll/ntdll.so'],cwd=wineBuild,text=True).replace('\\\n',' ')
    compileCmd=next(shlex.split(c) for c in commands.splitlines() if c.startswith('clang ') and str(server) in c)
    compileCmd=[str(native/'server.c') if v==str(server) else str(native/'server.o') if v=='dlls/ntdll/unix/server.o' else v for v in compileCmd]
    compileCmd+=['-I'+str(server.parent)]
    run(compileCmd,wineBuild,log='workload-wine-thread-identities')
    linkCmd=next(shlex.split(c) for c in commands.splitlines() if c.startswith('clang ') and '-dynamiclib' in c)
    linkCmd=[str(native/'ntdll.so') if v=='dlls/ntdll/ntdll.so' else str(native/'server.o') if v=='dlls/ntdll/unix/server.o' else v for v in linkCmd]
    run(linkCmd,wineBuild,log='workload-wine-link')
    target=runtime/'lib/wine/x86_64-unix/ntdll.so'; shutil.copy2(native/'ntdll.so',target)
    # Match the packaged baseline's relocatable rpaths.
    subprocess.run(['install_name_tool','-delete_rpath',str(base/'runtime/lib'),str(target)],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(target)],check=True)
    metal=work/'moltenvk-1.4.2'; clone(base/'moltenvk-1.4.2',metal)
    gpu=metal/'MoltenVK/MoltenVK/GPUObjects'
    nativeHash=sha(ROOT/'workload/WorkloadNative.h'); shutil.copy2(ROOT/'workload/WorkloadNative.h',gpu)
    queue=gpu/'MVKQueue.mm'; text=queue.read_text()
    if '#include "WorkloadNative.h"' not in text:
        text=text.replace('#include "MVKGPUCapture.h"','#include "MVKGPUCapture.h"\n#include "WorkloadNative.h"')
        text=text.replace('if ( !mtlCmdBuff ) { reportError', 'if (mtlCmdBuff && w101::configured() && w101::recorder().enabled()) w101::observe(mtlCmdBuff, int(cmdUse), _queueFamily->getIndex(), _index);\n\tif ( !mtlCmdBuff ) { reportError',1)
        queue.write_text(text)
    elif 'mtlCmdBuff && w101::recorder().enabled()' in text:
        queue.write_text(text.replace('mtlCmdBuff && w101::recorder().enabled()', 'mtlCmdBuff && w101::configured() && w101::recorder().enabled()'))
    device=gpu/'MVKDevice.mm'; text=device.read_text()
    if '#include "WorkloadNative.h"' not in text:
        text='#include "WorkloadNative.h"\n'+text
        marker='MVKLogInfo("Destroyed VkDevice on GPU %s with %d Vulkan extensions enabled.",\n\t\t\t   getName(), _enabledExtensions.getEnabledCount());'
        if marker not in text: raise RuntimeError('MoltenVK destructor changed')
        text=text.replace(marker,marker+'\n    w101::deviceDestroyed();',1)
        signature='MVKDevice::MVKDevice(MVKPhysicalDevice* physicalDevice, const VkDeviceCreateInfo* pCreateInfo) : _enabledExtensions(this) {'
        if signature not in text: raise RuntimeError('MoltenVK constructor changed')
        text=text.replace(signature,signature+'\n    w101::deviceCreated();',1); device.write_text(text)
    elif 'MVKDevice::~MVKDevice() {\n    w101::deviceDestroyed();' in text:
        text=text.replace('MVKDevice::~MVKDevice() {\n    w101::deviceDestroyed();','MVKDevice::~MVKDevice() {')
        marker='MVKLogInfo("Destroyed VkDevice on GPU %s with %d Vulkan extensions enabled.",\n\t\t\t   getName(), _enabledExtensions.getEnabledCount());'
        device.write_text(text.replace(marker,marker+'\n    w101::deviceDestroyed();'))
    env=dict(os.environ,MACOSX_DEPLOYMENT_TARGET='13.0',PATH='/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
    run(['make','macos','MACOSX_DEPLOYMENT_TARGET=13.0'],metal,env,'workload-moltenvk')
    molten=metal/'Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'
    shutil.copy2(molten,runtime/'lib/libMoltenVK.dylib')
    subprocess.run(['codesign','--force','--sign','-',str(runtime/'lib/libMoltenVK.dylib')],check=True)
    metadata={'capture_schema':3,'workload_diagnostics':True,'renderer_sha256':sha(dll),'moltenvk_sha256':sha(runtime/'lib/libMoltenVK.dylib'),
        'ntdll_sha256':sha(target),'patches':inputs,'native_header_sha256':nativeHash,'thread_header_sha256':sha(ROOT/'workload/WineThreadIdentity.h'),
        'translation_source_sha256':fingerprint.hexdigest(),'base_ntdll_sha256':sha(base/'runtime/lib/wine/x86_64-unix/ntdll.so'),
        'wine_server_source_sha256':sha(native/'server.c'),
        'moltenvk':'1.4.2','optimizations':'off','warmup':False,'shader_translation':'working baseline',
        'max_seconds':900,'renderer_max_bytes':112*1024**2,'native_max_bytes':128*1024**2,'thread_map_max_bytes':1024**2,
        'synthetic_verification_required':True,'gameplay_acceptance':False}
    (dll.parent/'workload-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (runtime/'workload-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({'runtime':str(runtime),'renderer':str(dll)},indent=2)); return runtime,dll

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--work',type=Path,required=True); p.add_argument('--base',type=Path,default=WORK)
    a=p.parse_args(); build(a.work,a.base)
