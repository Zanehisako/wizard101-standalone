#!/usr/bin/env python3
"""Measure v1 components separately without changing its sources or evidence."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from build_runtime import ROOT, sha

def measure(work, app, keep):
    work, app, keep = map(lambda p: Path(p).resolve(), (work, app, keep))
    keep.mkdir(parents=True, exist_ok=True)
    runtime = app/'Contents/Resources/Runtime'
    # Use the same sanitized, independent Wine prefix as the render verifier.
    import os
    with tempfile.TemporaryDirectory(prefix='w101-layout-cost-') as tmp:
        temp = Path(tmp); source=work/'renderer'; build=work/'build-renderer'
        env={k:v for k,v in os.environ.items() if not k.startswith(('CX_','CROSSOVER','DYLD_','WINE','VK_','DXVK_','D9VK_','MVK_','W101_'))}
        env.update(WINEPREFIX=str(temp/'Prefix'),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',
                   WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib',
                   WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree=d;mshtml=d')
        program=temp/'cost.exe'
        flags=['x86_64-w64-mingw32-g++','-O3','-std=c++17','-static','-DNOMINMAX','-D_WIN32_WINNT=0xa00','-DDXVK_WSI_WIN32',
               *['-I'+str(source/p) for p in ('src','include','include/vulkan/include','include/spirv/include')]]
        subprocess.run([*flags,'-ffunction-sections','-fdata-sections',str(ROOT/'tests/draw_layout_cost_probe.cpp'),
                        str(source/'src/d3d9/d3d9_util.cpp'),str(build/'src/util/libutil.a'),'-Wl,--gc-sections','-lgdi32','-luser32','-o',str(program)],check=True)
        try:
            with (keep/'components.log').open('w') as out:
                subprocess.run([str(runtime/'bin/wine'),str(program)],cwd=temp,env=env,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=180)
            rows=[json.loads(x) for x in re.findall(r'COST (\{.*\})',(keep/'components.log').read_text())]
            if len(rows)!=5 or any(r['cpu_ms']<2000 for r in rows): raise RuntimeError('Incomplete component measurements')
            report={'revision':1,'production_header_sha256':sha(source/'src/d3d9/wizard101_draw_layout_cache.h'),
                    'probe_sha256':sha(ROOT/'tests/draw_layout_cost_probe.cpp'),'components':rows,'synthetic_only':True}
            (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2),flush=True)
        finally:
            subprocess.run([str(runtime/'bin/wineserver'),'-k'],env=env,capture_output=True,timeout=15)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-draw-layout'))
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--keep',type=Path,default=ROOT/'verification-local/draw-layout-v1-components')
    a=p.parse_args();measure(a.work,a.app,a.keep)
