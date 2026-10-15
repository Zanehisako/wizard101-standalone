#!/usr/bin/env python3
"""Verify production compilation, shutdown maintenance and cache failure paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent

def verify(app,source,build,keep):
    app,source,build,keep=[Path(p).resolve() for p in (app,source,build,keep)]
    runtime=app/'Contents/Resources/Runtime'; keep.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='w101-rendering-isolated-') as temp:
        work=Path(temp)
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_'))}
        env.update(PATH=str(runtime/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin',WINEPREFIX=str(work/'Prefix'),WINEARCH='win64',
            WINEDEBUG='-all',WINEMSYNC='1',WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree=d;mshtml=d',
            WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
            VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'),MVK_CONFIG_RESUME_LOST_DEVICE='1',
            MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1',DXVK_ASYNC='0',DXVK_W101_CPU_OPT='off',DXVK_W101_PIPELINE_OPT='off',
            DXVK_W101_WARMUP='0',DXVK_W101_CACHE='0')
        def run(command,label,cwd=work):
            path=keep/(label+'.log')
            with path.open('w') as out:
                result=subprocess.run(command,cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=180)
            output=path.read_text(errors='replace')
            if result.returncode: raise RuntimeError(label+' failed: '+output[-4000:])
            return output
        flags=['x86_64-w64-mingw32-g++','-std=c++17','-O2','-static','-DNOMINMAX','-msse3',
            *['-I'+str(source/p) for p in ('src','include','include/vulkan/include','include/spirv/include')]]
        libraries=['-Wl,--start-group',*[str(build/p) for p in ('src/dxvk/libdxvk.a','src/spirv/libspirv.a','src/util/libutil.a','src/vulkan/libvkcommon.a')],'-Wl,--end-group','-lgdi32','-luser32','-ldxguid']
        try:
            run([str(runtime/'bin/wine'),'wineboot.exe','-u'],'wineboot')
            subprocess.run([*flags,str(ROOT/'tests/rendering_probe.cpp'),*libraries,'-o',str(work/'rendering.exe')],check=True)
            for name in ('snapshot.vert','snapshot.frag','replay.comp'):
                subprocess.run(['glslangValidator','-V','--target-env','vulkan1.1',str(ROOT/'tests'/name),'-o',str(work/(name+'.spv'))],check=True,stdout=subprocess.DEVNULL)
            runs=[]
            for mode in ('0','1'):
                target=work/('mode-'+mode); target.mkdir()
                for path in work.glob('*.spv'): shutil.copy2(path,target)
                env['DXVK_W101_STUTTER_FIX']=mode
                output=run([str(runtime/'bin/wine'),str(work/'rendering.exe')],'compilation-'+mode,target)
                if 'PASS all rendering checks' not in output: raise RuntimeError('Incomplete compilation checks')
                runs.append({'switch':mode,'checks':[s for s in output.splitlines() if s.startswith('PASS')]})
            # Both legacy and shutdown-only paths exercise the actual production
            # cache with a controlled dispatch table, including driver faults.
            for name,mode in [('cache_fault_probe','0'),('cache_shutdown_probe','1')]:
                extra=[str(source/'src/d3d9/d3d9_warmup.cpp')] if mode=='1' else []
                subprocess.run([*flags,str(ROOT/'tests'/(name+'.cpp')),str(source/'src/dxvk/dxvk_pipecache.cpp'),*extra,str(build/'src/util/libutil.a'),str(build/'src/vulkan/libvkcommon.a'),'-luser32','-lgdi32','-o',str(work/(name+'.exe'))],check=True)
                env['DXVK_W101_STUTTER_FIX']=mode; env.pop('DXVK_W101_CACHE',None)
                data=work/'Prefix/drive_c/graphics-patch-tests/cache-fault/data'
                if data.exists(): shutil.rmtree(data)
                data.mkdir(parents=True)
                output=run([str(runtime/'bin/wine'),str(work/(name+'.exe'))],name)
                if 'PASS' not in output: raise RuntimeError('Incomplete cache checks')
                runs.append({'switch':mode,'checks':[s for s in output.splitlines() if s.startswith('PASS')]})
            subprocess.run([*flags,str(ROOT/'tests/cache_file_probe.cpp'),str(build/'src/util/libutil.a'),'-luser32','-lgdi32','-o',str(work/'storage.exe')],check=True)
            output=run([str(runtime/'bin/wine'),str(work/'storage.exe')],'storage')
            if 'PASS' not in output: raise RuntimeError('Incomplete storage checks')
            result={'synthetic_only':True,'renderer_sha256':hashlib.sha256((build/'src/d3d9/d3d9.dll').read_bytes()).hexdigest(),
                'runs':runs,'storage_checks':output.strip(),'cache_formats_changed':False,'gameplay_improvement_verified':False,'working_app_replaced':False}
            (keep/'report.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2)); return result
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('app','source','build','keep'): parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); verify(args.app,args.source,args.build,args.keep)
