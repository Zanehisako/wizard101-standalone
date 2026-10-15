#!/usr/bin/env python3
"""Build the isolated arrival renderer over the preserved lookup candidate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone
from build_game_repair import objects

HEADERS={'ArrivalCache.h':'wizard101_asset_cache_impl.h',
         'ArrivalBudget.h':'wizard101_asset_budget.h',
         'ArrivalInputs.h':'wizard101_arrival_inputs.h',
         'SceneUploads.h':'wizard101_scene_uploads.h'}

def build(work,baseline):
    work,baseline=Path(work).resolve(),Path(baseline).resolve()
    work.mkdir(parents=True,exist_ok=True)
    source,output=work/'renderer',work/'build-renderer'
    if not source.exists():
        clone(baseline/'renderer',source)
        subprocess.run(['git','apply',str(ROOT/'renderer/arrival.patch'),str(ROOT/'renderer/arrival-v2.patch')],cwd=source,check=True)
    else:
        subprocess.run(['git','apply','--reverse','--check',str(ROOT/'renderer/arrival-v2.patch')],cwd=source,check=True)
    clone(baseline/'build-renderer',output)
    for name,target in HEADERS.items():shutil.copy2(ROOT/'performance'/name,source/'src/d3d9'/target)
    commands=subprocess.check_output(['ninja','-C',str(baseline/'build-renderer'),'-t','commands','src/d3d9/d3d9.dll'],text=True)
    commands=commands.replace('../workload-d9vk','../renderer').replace(str(baseline/'renderer'),str(source))
    # Image lifetime accounting changes a common layout. Recompile every consumer
    # so no object from the baseline assumes the old image size or member offsets.
    jobs=[shlex.split(c) for c in commands.splitlines() if ' -c ' in c]
    def compile(command):
        name=Path(command[-1]).stem
        obj=output/command[command.index('-o')+1]
        dep=output/command[command.index('-MF')+1] if '-MF' in command else None
        if obj.exists() and dep and dep.exists():
            paths=dep.read_text().replace('\\\n',' ').split(':',1)[-1].split()
            dependencies=[output/p.replace('../workload-d9vk','../renderer') for p in paths]
            if dependencies and all(p.is_file() and p.stat().st_mtime<=obj.stat().st_mtime for p in dependencies):return
        with (work/(name+'.log')).open('w') as log:
            subprocess.run(command,cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile,jobs))
    for command in commands.splitlines()[:-1]:
        if " -c " not in command:
            with (work/"archive.log").open("a") as log:
                subprocess.run(command,shell=True,cwd=output,stdout=log,stderr=log,check=True)
    link=shlex.split(commands.splitlines()[-1]);link.extend(map(str,objects(work)))
    with (work/'link.log').open('w') as log:subprocess.run(link,cwd=output,stdout=log,stderr=log,check=True)
    dll=output/'src/d3d9/d3d9.dll'
    from build_decompression import adapter
    decoder=adapter(work,native=True,libraries_work=ROOT/'work/arrival-decoders' if (ROOT/'work/arrival-decoders').exists() else Path('/private/tmp/w101-combined'))
    inputs=[ROOT/'build_arrival.py',ROOT/'renderer/arrival.patch',ROOT/'renderer/arrival-v2.patch',*[ROOT/'performance'/n for n in HEADERS],ROOT/'decompression/Adapter.c',ROOT/'decompression/Identity.h',ROOT/'build_decompression.py']
    metadata=dict(adapter_sha256=sha(decoder),renderer_sha256=sha(dll),baseline_renderer_sha256=sha(baseline/'build-renderer/src/d3d9/d3d9.dll'),
                  inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},
                  defaults={'W101_SCENE_TEXTURES':'0','W101_PREPARE_PIPELINES':'0','W101_PREPARE_APPEARANCE':'0'},
                  asset_limit=128*1024**2,startup_limit=64*1024**2,speculative_limit=32*1024**2,
                  combined_asset_records_limit=32*1024**2,scene_chain_limit=8*1024**2,
                  shader_count_limit=2048,shader_bytes_limit=32*1024**2,
                  pipeline_count_limit=8192,pipeline_bytes_limit=16*1024**2,
                  startup_cutoff=None,preparation_workers=1,gameplay_preparation=False,pipeline_learning_with_preparation_off=True,wad_caller_rva=0x150935a,wad_buffer_minimum=1024,
                  logging_added=False,gameplay_accepted=False)
    (work/'arrival-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return dll

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-arrival'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-game-repair'))
    a=p.parse_args();print(build(a.work,a.baseline))
