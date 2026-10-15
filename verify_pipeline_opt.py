#!/usr/bin/env python3
"""Exercise real replay queues and atomic lookups in a disposable Wine prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def verify(app, source, build, keep):
    app, source, build, keep = [Path(p).resolve() for p in (app, source, build, keep)]
    runtime = app/'Contents/Resources/Runtime'
    keep.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='w101-pipeline-isolated-') as temp:
        work = Path(temp); prefix = work/'Prefix'
        env = {k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_'))}
        env.update(PATH=str(runtime/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin', WINEPREFIX=str(prefix), WINEARCH='win64',
                   WINEDEBUG='-all', WINEMSYNC='1', WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   WINEDLLPATH=str(runtime/'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   VK_ICD_FILENAMES=str(runtime/'share/vulkan/icd.d/MoltenVK_icd.json'), MVK_CONFIG_RESUME_LOST_DEVICE='1',
                   MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS='1', DXVK_ASYNC='0', DXVK_W101_CACHE='0')
        def run(command, label, cwd=work):
            with (keep/(label+'.log')).open('w') as output:
                result = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=180)
            output = (keep/(label+'.log')).read_text(errors='replace')
            if result.returncode: raise RuntimeError(label+' failed: '+output[-3000:])
            return output
        flags = ['x86_64-w64-mingw32-g++','-std=c++17','-O2','-static','-DNOMINMAX','-msse3',
                 *['-I'+str(source/p) for p in ('src','include','include/vulkan/include','include/spirv/include')]]
        libraries = ['-Wl,--start-group', *[str(build/p) for p in ('src/dxvk/libdxvk.a','src/spirv/libspirv.a','src/util/libutil.a','src/vulkan/libvkcommon.a')],
                     '-Wl,--end-group','-lgdi32','-luser32','-ldxguid']
        try:
            run([str(runtime/'bin/wine'),'wineboot.exe','-u'],'wineboot')
            executable=work/'pipeline-opt.exe'
            subprocess.run([*flags,str(ROOT/'tests/pipeline_opt_probe.cpp'),*libraries,'-o',str(executable)],check=True)
            for name in ('snapshot.vert','snapshot.frag','replay.comp'):
                subprocess.run(['glslangValidator','-V','--target-env','vulkan1.1',str(ROOT/'tests'/name),'-o',str(work/(name+'.spv'))],check=True,stdout=subprocess.DEVNULL)
            runs=[]
            for mode in ('off','replay','lookup','both'):
                target=work/mode; target.mkdir()
                for shader in work.glob('*.spv'): shutil.copy2(shader,target)
                env['DXVK_W101_PIPELINE_OPT']=mode
                output=run([str(runtime/'bin/wine'),str(executable)],mode,target)
                if 'PASS all pipeline optimization checks' not in output: raise RuntimeError(mode+' checks incomplete')
                runs.append({'mode':mode,'checks':[line for line in output.splitlines() if line.startswith('PASS')]})
            result={'synthetic_only':True,'renderer_sha256':hashlib.sha256((build/'src/d3d9/d3d9.dll').read_bytes()).hexdigest(),
                    'runs':runs,'gameplay_improvement_verified':False,'installed':False}
            (keep/'report.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2)); return result
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('app','source','build','keep'): p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args(); verify(args.app,args.source,args.build,args.keep)
