#!/usr/bin/env python3
"""Compare the approved function and exercise the real detour in an own-process fixture."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import subprocess
from build_game_repair import objects
from game_context import APP, DATA, EXPECTED, GAME, ROOT, sha, wine_environment
from game.pe_identity import PEIdentity

def verify(work,keep,app=APP,data=DATA):
    work,keep,app,data=map(lambda p:Path(p).resolve(),(work,keep,app,data))
    if keep.exists():raise ValueError('Use a fresh verification directory')
    keep.mkdir(parents=True);work.mkdir(parents=True,exist_ok=True)
    pe=PEIdentity(data/GAME)
    if pe.sha256!=EXPECTED:raise ValueError('Unapproved game executable; no patch selected')
    function=pe.function(0x2239020)
    code=pe.bytes_at(function['begin_rva'],164)
    if function['code_sha256']!='5d67b2171d7d6f6f65bd27ea33557c072985a9392d3f3ce40cf8ce8fa30e8d1e':raise ValueError('Function differs')
    header=pe.bytes_at(function['unwind_rva'],4)
    if header[0]!=1:raise ValueError('Unexpected unwind flags')
    unwind=pe.bytes_at(function['unwind_rva'],4+2*((header[2]+1)&~1))
    basic=work/'lookup-original.bin';hooked=work/'lookup-hook-fixture.bin'
    basic.write_bytes(code);hooked.write_bytes(code+unwind)
    mh=objects(work,True);runtime=app/'Contents/Resources/Runtime';results={};binaries={}
    for kind,source,compiler,extra,fixture in [
        ('lookup',ROOT/'tests/game_lookup_probe.c','x86_64-w64-mingw32-gcc',[],basic),
        ('hook',ROOT/'tests/game_repair_hook_probe.cpp','x86_64-w64-mingw32-g++',['-std=c++17',*map(str,mh),'-lbcrypt'],hooked)]:
        executable=work/(kind+'_probe.exe')
        subprocess.run([compiler,'-O3','-static','-Wall','-Wextra','-fno-strict-aliasing',str(source),*extra,'-o',str(executable)],check=True)
        with (keep/(kind+'.json')).open('x') as output,(keep/(kind+'-errors.txt')).open('x') as errors:
            result=subprocess.run([str(runtime/'bin/wine'),str(executable),'Z:'+str(fixture).replace('/','\\')],env=wine_environment(runtime,data),stdout=output,stderr=errors)
        payload=json.loads((keep/(kind+'.json')).read_text())
        if result.returncode or not payload.get('passed'):raise RuntimeError(kind+' verification failed')
        results[kind]=payload;binaries[kind]=sha(executable)
    groups=defaultdict(list)
    for row in results['hook']['hook_benchmarks_ns']:groups[(row['size'],row['miss'])].append(row)
    savings=[dict(size=size,miss=miss,pairs=len(rows),median_saving=statistics.median(1-r['candidate']/r['original'] for r in rows))
             for (size,miss),rows in groups.items()]
    qualified=all(r['pairs']==5 and r['median_saving']>=.10 for r in savings) and len(savings)==8
    inputs=[ROOT/'verify_game_repair.py',ROOT/'build_game_repair.py',ROOT/'tests/game_lookup_probe.c',ROOT/'tests/game_repair_hook_probe.cpp',
            ROOT/'game/lookup.h',ROOT/'game/repair.h',*sorted((ROOT/'game/vendor/minhook').rglob('*'))]
    inputs=[p for p in inputs if p.is_file()]
    report=dict(synthetic_only=True,install_qualified=qualified,gameplay_accepted=False,rollout_allowed=False,
                function=function,executable_sha256=pe.sha256,checks=results['hook']['checks'],
                equivalence_cases=results['lookup']['equivalence_cases'],mismatches=results['lookup']['mismatches'],
                concurrent_calls=results['hook']['calls'],incorrect_concurrent_results=results['hook']['incorrect_results'],
                hooked_lookup_savings=savings,probe_sha256=binaries,
                inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs})
    (keep/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not qualified:raise RuntimeError('Lookup CPU gate failed; original retained')
    print('Qualified own-process lookup and hook checks; gameplay acceptance remains pending.')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-game-repair/verify'))
    p.add_argument('--keep',type=Path,required=True);a=p.parse_args();verify(a.work,a.keep)
