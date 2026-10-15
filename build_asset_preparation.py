#!/usr/bin/env python3
"""Add persistent texture preparation to the existing combined renderer sources."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone

def build(work, baseline):
    work, baseline = Path(work).resolve(), Path(baseline).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source, output = work/'renderer', work/'build-renderer'
    if not source.exists():
        clone(baseline/'renderer', source)
        subprocess.run(['git', 'apply', str(ROOT/'renderer/asset-preparation.patch')], cwd=source, check=True)
    for a,b in [('AssetBudget.h','wizard101_asset_budget.h'),('AssetPreparation.h','wizard101_asset_preparation.h'),
                ('AssetCacheImpl.h','wizard101_asset_cache_impl.h'),
                ('NativeAssetHooks.h','wizard101_native_assets.h')]:
        shutil.copy2(ROOT/'performance'/a, source/'src/d3d9'/b)
    if not output.exists():
        clone(baseline/'build-renderer', output)
    commands = subprocess.check_output(['ninja','-C',str(baseline/'build-renderer'),'-t','commands','src/d3d9/d3d9.dll'],text=True)
    commands = commands.replace('../workload-d9vk','../renderer').replace(str(baseline/'renderer'),str(source))
    jobs = [shlex.split(c) for c in commands.splitlines() if ' -c ' in c and ' -o src/d3d9/' in c]
    def compile(command):
        name = Path(command[-1]).stem
        with (work/(name+'.log')).open('w') as log:
            subprocess.run(command,cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(compile,jobs))
    with (work/'link.log').open('w') as log:
        subprocess.run(shlex.split(commands.splitlines()[-1]),cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True)
    dll=output/'src/d3d9/d3d9.dll'
    metadata={'renderer_sha256':sha(dll),'baseline_renderer_sha256':sha(baseline/'build-renderer/src/d3d9/d3d9.dll'),
              'inputs':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'renderer/asset-preparation.patch',ROOT/'performance/AssetPreparation.h',ROOT/'performance/AssetBudget.h',ROOT/'performance/AssetCacheImpl.h',ROOT/'performance/NativeAssetHooks.h',ROOT/'build_asset_preparation.py']},
              'persistent_cache_max_bytes':32*1024**2,'asset_memory_max_bytes':128*1024**2,
              'startup_cutoff_seconds':None,'default_enabled':False,'gameplay_accepted':False}
    (work/'asset-preparation-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return dll

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-asset-preparation'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-combined'))
    a=p.parse_args(); print(build(a.work,a.baseline))
