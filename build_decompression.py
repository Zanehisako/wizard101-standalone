#!/usr/bin/env python3
"""Build pinned decoders and a separate renderer; baseline is never modified."""
import argparse
import json
import subprocess
import shutil
from pathlib import Path
from build_runtime import ROOT, WORK, sha, download, extract, run
from build_workload import clone

def libraries(work):
    pins=json.loads((ROOT/'decompression/sources.lock.json').read_text())
    for name,pin in pins.items():
        source=work/'sources'/name
        if not source.exists():
            archive=download(name+'-'+pin['revision'][:8]+'.tar.gz',pin['url'],pin['sha256'])
            extract(archive,source,strip=True)
        output=work/('build-'+name)
        flags=['-DCMAKE_BUILD_TYPE=Release','-DCMAKE_SYSTEM_NAME=Windows','-DCMAKE_SYSTEM_PROCESSOR=x86_64',
            '-DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc','-DCMAKE_C_COMPILER_TARGET=x86_64','-DCMAKE_C_FLAGS=-O3',
            '-DBUILD_SHARED_LIBS=OFF','-DBUILD_TESTING=OFF']
        if name=='libdeflate':flags+=['-DLIBDEFLATE_BUILD_SHARED_LIB=OFF','-DLIBDEFLATE_BUILD_STATIC_LIB=ON','-DLIBDEFLATE_BUILD_GZIP=OFF']
        else:flags+=['-DZLIB_COMPAT=ON','-DZLIB_SYMBOL_PREFIX=w101ng_','-DWITH_GTEST=OFF']
        run(['cmake','-S',str(source),'-B',str(output),'-G','Ninja',*flags],log='decompression-'+name+'-configure')
        run(['cmake','--build',str(output),'-j','4'],log='decompression-'+name)
    return pins

def adapter(work,test_hash=None,native=False,libraries_work=None):
    libraries_work=Path(libraries_work or work)
    target=work/('test-w101decompress.dll' if test_hash else 'w101decompress.dll')
    command=['x86_64-w64-mingw32-gcc','-std=c11','-O3','-shared','-static-libgcc',
        '-I'+str(libraries_work/'build-zlib-ng'),'-I'+str(libraries_work/'sources/zlib-ng'),
        '-I'+str(libraries_work/'sources/libdeflate'),'-Wl,--no-insert-timestamp',str(ROOT/'decompression/Adapter.c'),
        str(libraries_work/'build-libdeflate/libdeflate.a'),str(libraries_work/'build-zlib-ng/libz.a'),'-lbcrypt','-o',str(target)]
    if test_hash:command.insert(1,'-DW101_TEST_HASH="'+test_hash+'"')
    if native:command.insert(1,'-DW101_NATIVE')
    run(command,log='decompression-adapter');return target

def renderer(work,baseline):
    evidence=json.loads((baseline/'Runtime/workload-performance-build.json').read_text())
    if evidence['renderer_sha256']!=sha(baseline/'build-workload-d9vk/src/d3d9/d3d9.dll'):
        raise RuntimeError('Baseline renderer provenance changed')
    source=work/'renderer';clone(baseline/'workload-d9vk',source)
    main=source/'src/d3d9/d3d9_main.cpp';text=main.read_text()
    if 'wizard101_decompression_loader.h' not in text:
        marker='#include "wizard101_native_assets.h"'
        if marker not in text:raise RuntimeError('Baseline renderer entrypoint changed')
        text=text.replace(marker,marker+'\n#include "wizard101_decompression_loader.h"')
        text=text.replace('    wizard101::InstallAssetHooks();','    wizard101::InstallAssetHooks();\n    wizard101::InstallDecompressionHooks();',1)
        main.write_text(text)
    shutil.copy2(ROOT/'decompression/RendererLoader.h',source/'src/d3d9/wizard101_decompression_loader.h')
    # Reuse compiled baseline objects through a clone, rewriting build paths.
    output=work/'build-renderer'
    if not output.exists():
        clone(baseline/'build-workload-d9vk',output)
        for name in ['build.ninja','compile_commands.json']:
            file=output/name
            file.write_text(file.read_text().replace(str(baseline/'workload-d9vk'),str(source)).replace(str(baseline/'build-workload-d9vk'),str(output)))
    # Meson regeneration would use baseline paths in private pickles; compile and
    # link the one changed entrypoint using the clone's exact existing commands.
    obj='src/d3d9/d3d9.dll.p/d3d9_main.cpp.obj'
    import shlex
    commands=subprocess.check_output(['ninja','-C',str(output),'-t','commands','src/d3d9/d3d9.dll'],text=True)
    commands=commands.replace('../workload-d9vk','../renderer')
    compile_command=next(shlex.split(c) for c in commands.splitlines() if ' -c ' in c and 'd3d9_main.cpp' in c)
    run(compile_command,output,log='decompression-renderer-entrypoint')
    link_command=shlex.split(commands.splitlines()[-1]);run(link_command,output,log='decompression-renderer-link')
    return output/'src/d3d9/d3d9.dll'

def build(work,baseline):
    work=Path(work).resolve();baseline=Path(baseline).resolve();work.mkdir(parents=True,exist_ok=True)
    pins=libraries(work);dll=adapter(work);render=renderer(work,baseline)
    clone(baseline/'Runtime',work/'Runtime')
    metadata={'sources':pins,'adapter_sha256':sha(dll),'renderer_sha256':sha(render),
        'baseline_renderer_sha256':sha(baseline/'build-workload-d9vk/src/d3d9/d3d9.dll'),
        'inputs':{name:sha(ROOT/'decompression'/name) for name in ['Adapter.c','Identity.h','RendererLoader.h','sources.lock.json']},
        'default_mode':'off','memory_limit_bytes':64*1024**2,'gameplay_accepted':False}
    (work/'decompression-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return work

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-decompression'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'))
    a=p.parse_args();print(build(a.work,a.baseline))
