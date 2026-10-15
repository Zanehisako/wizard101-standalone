#!/usr/bin/env python3
"""Build the isolated, default-off resource lookup repair overlay."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone

def objects(work, verify=False):
    vendor=ROOT/'game/vendor/minhook'
    result=[]
    for name in ('buffer.c','hook.c','trampoline.c','hde/hde64.c'):
        output=work/('mh-'+Path(name).stem+('-verify' if verify else '')+'.o')
        args=['x86_64-w64-mingw32-gcc','-O2','-c',str(vendor/'src'/name),'-o',str(output)]
        if verify:args.insert(1,'-DW101_MINHOOK_VERIFY')
        subprocess.run(args,check=True);result.append(output)
    return result

def build(work, baseline):
    work,baseline=Path(work).resolve(),Path(baseline).resolve();work.mkdir(parents=True,exist_ok=True)
    source,output=work/'renderer',work/'build-renderer'
    clone(baseline/'renderer',source);clone(baseline/'build-renderer',output)
    destination=source/'src/d3d9/w101_game'
    if destination.exists():shutil.rmtree(destination)
    shutil.copytree(ROOT/'game',destination,ignore=shutil.ignore_patterns('__pycache__'))
    main=source/'src/d3d9/d3d9_main.cpp'
    text=main.read_text()
    if '#include "w101_game/repair.h"' not in text:
        text=text.replace('#include "wizard101_decompression_loader.h"','#include "wizard101_decompression_loader.h"\n#include "w101_game/repair.h"')
        text=text.replace('    wizard101::InstallDecompressionHooks();','    wizard101::InstallDecompressionHooks();\n    static std::once_flag gameRepairOnce;\n    std::call_once(gameRepairOnce,[] {\n      w101repair::install();\n      Logger::info(str::format("W101 game repair: ",w101repair::status,"; lookup RVA 0x2239020 SHA256 ",w101repair::LookupSHA));\n    });')
        main.write_text(text)
    commands=subprocess.check_output(['ninja','-C',str(baseline/'build-renderer'),'-t','commands','src/d3d9/d3d9.dll'],text=True)
    commands=commands.replace('../workload-d9vk','../renderer').replace(str(baseline/'renderer'),str(source))
    command=next(shlex.split(c) for c in commands.splitlines() if ' -c ' in c and 'd3d9_main.cpp' in c)
    with (work/'compile.log').open('w') as log:subprocess.run(command,cwd=output,stdout=log,stderr=log,check=True)
    mh=objects(work)
    command=shlex.split(commands.splitlines()[-1]);command.extend(map(str,mh))
    with (work/'link.log').open('w') as log:subprocess.run(command,cwd=output,stdout=log,stderr=log,check=True)
    dll=output/'src/d3d9/d3d9.dll'
    inputs=[ROOT/'build_game_repair.py',*sorted((ROOT/'game').rglob('*'))]
    inputs=[p for p in inputs if p.is_file() and '__pycache__' not in p.parts]
    metadata=dict(renderer_sha256=sha(dll),baseline_renderer_sha256=sha(baseline/'build-renderer/src/d3d9/d3d9.dll'),
                  inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},default_enabled=False,gameplay_accepted=False,
                  executable_sha256='544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e',
                  hooks=[dict(rva=0x2239020,bytes=164,sha256='5d67b2171d7d6f6f65bd27ea33557c072985a9392d3f3ce40cf8ce8fa30e8d1e',getter_rva=0x224ed40,getter_signature='488d4110c3')])
    (work/'game-repair-build.json').write_text(json.dumps(metadata,indent=2)+'\n');return dll

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-game-repair'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-draw-layout-direct'))
    a=p.parse_args();print(build(a.work,a.baseline))
