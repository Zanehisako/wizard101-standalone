#!/usr/bin/env python3
"""Build an isolated direct draw-layout construction overlay over the installed renderer sources."""
import argparse
from pathlib import Path
import json
import shlex
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone

def build(work, baseline):
    work, baseline = Path(work).resolve(), Path(baseline).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source, output = work/'renderer', work/'build-renderer'
    patch = ROOT/'renderer/draw-layout-direct.patch'
    if not source.exists():
        clone(baseline/'renderer', source)
        subprocess.run(['git','apply',str(patch)],cwd=source,check=True)
        (source/'.draw-layout-direct.patch').write_bytes(patch.read_bytes())
    elif (source/'.draw-layout-direct.patch').read_bytes() != patch.read_bytes():
        subprocess.run(['git','apply','--reverse',str(source/'.draw-layout-direct.patch')],cwd=source,check=True)
        subprocess.run(['git','apply',str(patch)],cwd=source,check=True)
        (source/'.draw-layout-direct.patch').write_bytes(patch.read_bytes())
    inputs=[patch, ROOT/'performance/AssetBudget.h', ROOT/'performance/DrawLayoutDirect.h',ROOT/'performance/AssetPreparation.h',ROOT/'build_draw_layout_direct.py']
    for name in ('AssetBudget','DrawLayoutDirect','AssetPreparation'):
        target={'AssetBudget':'asset_budget','DrawLayoutDirect':'draw_layout_direct','AssetPreparation':'asset_preparation'}[name]
        shutil.copy2(ROOT/f'performance/{name}.h',source/f'src/d3d9/wizard101_{target}.h')
    if not output.exists(): clone(baseline/'build-renderer', output)
    commands=subprocess.check_output(['ninja','-C',str(baseline/'build-renderer'),'-t','commands','src/d3d9/d3d9.dll'],text=True)
    commands=commands.replace('../workload-d9vk','../renderer').replace(str(baseline/'renderer'),str(source))
    # The overlay changes D3D9DeviceEx's size: rebuild every D3D9 translation unit.
    from concurrent.futures import ThreadPoolExecutor
    jobs=[shlex.split(c) for c in commands.splitlines() if ' -c ' in c and ' -o src/d3d9/' in c]
    def compile(command):
        with (work/(Path(command[-1]).stem+'.log')).open('w') as log:
            subprocess.run(command,cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True)
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(compile,jobs))
    with (work/'link.log').open('w') as log:
        subprocess.run(shlex.split(commands.splitlines()[-1]),cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True)
    dll=output/'src/d3d9/d3d9.dll'
    metadata={'renderer_sha256':sha(dll),'baseline_renderer_sha256':sha(baseline/'build-renderer/src/d3d9/d3d9.dll'),
              'inputs':{str(p.relative_to(ROOT)):sha(p) for p in inputs},
              'revision':3,'experiment':'direct','resource_fingerprints':False,'persistent_layout_bytes':0,'semantic_stack_elements':64,'sse2_semantics_per_comparison':8,
              'default_enabled':False,'gameplay_accepted':False}
    (work/'draw-layout-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return dll
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-draw-layout-direct'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-asset-preparation'))
    a=p.parse_args();print(build(a.work,a.baseline))
