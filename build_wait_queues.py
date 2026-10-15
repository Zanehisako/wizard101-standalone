#!/usr/bin/env python3
"""Build only the experimental ntdll PE; original wait/wake code is retained."""
import argparse,json,shlex,shutil,subprocess
from pathlib import Path
from build_runtime import ROOT,WORK,sha,run
from build_workload import clone

def queue_overlay(text,test=False):
    marker='static struct futex_queue futex_queues[256];'
    if text.count(marker)!=1:raise RuntimeError('Wine queue definition changed')
    text=text.replace(marker,marker+'\n#include "WaitQueues.h"')
    marker='    return &futex_queues[(val >> 4) % ARRAY_SIZE(futex_queues)];'
    if text.count(marker)!=1:raise RuntimeError('Wine queue mapping changed')
    text=text.replace(marker,'    if (w101_sharded_enabled()) return &w101_sharded_queues[w101_queue_hash(val)].value;\n'+marker)
    if test:
        text+='\nLONG WINAPI W101WaitQueueDepth(const void *addr) { struct futex_queue *q=get_futex_queue(addr); struct futex_entry *e; LONG n=0; spin_lock(&q->lock); if(q->queue.next) LIST_FOR_EACH_ENTRY(e,&q->queue,struct futex_entry,entry) if(e->addr==addr) ++n; spin_unlock(&q->lock); return n; }\n'
    return text

def build(work,baseline,wine_base=WORK,test_hash=None):
    work,baseline,wine_base=map(lambda p:Path(p).resolve(),(work,baseline,wine_base));work.mkdir(parents=True,exist_ok=True)
    native=work/('test-native' if test_hash else 'native');native.mkdir(exist_ok=True)
    source=wine_base/'sources/wine';wine_build=wine_base/'build-wine'
    original=baseline/'native/sync.c';text=queue_overlay(original.read_text(),test_hash is not None)
    (native/'sync.c').write_text(text)
    for file in ['WaitQueues.h','Sha256.h','Identity.h','NtIdentity.h']:shutil.copy2(ROOT/'decompression'/file,native/file)
    for file in ['WineLockPE.h','unixlib.h']:shutil.copy2(baseline/'native'/file,native/file)
    commands=subprocess.check_output(['make','-n','-W',str(source/'dlls/ntdll/sync.c'),'dlls/ntdll/x86_64-windows/ntdll.dll'],cwd=wine_build,text=True).replace('\\\n',' ')
    cmds=[shlex.split(c) for c in commands.splitlines() if c.startswith(('clang ','x86_64-w64-mingw32-gcc ','tools/winegcc/winegcc '))]
    cc=next(c for c in cmds if '/sync.c' in ' '.join(c))
    mapping={str(source/'dlls/ntdll/sync.c'):str(native/'sync.c'),'dlls/ntdll/x86_64-windows/sync.o':str(native/'sync.o')}
    cc=[mapping.get(v,v) for v in cc]
    if test_hash:cc+=['-DW101_TEST_HASH="'+test_hash+'"']
    run(cc,wine_build,log='wait-queues-compile')
    link=next(c for c in cmds if c[0]=='tools/winegcc/winegcc')
    mapping['dlls/ntdll/x86_64-windows/ntdll.dll']=str(native/'ntdll.dll')
    if test_hash:
        spec=native/'ntdll.spec';spec.write_text((source/'dlls/ntdll/ntdll.spec').read_text()+'\n@ stdcall W101WaitQueueInfo()\n@ stdcall W101WaitQueueDepth(ptr)\n')
        mapping[str(source/'dlls/ntdll/ntdll.spec')]=str(spec)
    link=[mapping.get(v,v) for v in link];run(link,wine_build,log='wait-queues-link')
    if not test_hash:
        shutil.copy2(native/'ntdll.dll',work/'ntdll.dll');clone(baseline/'Runtime',work/'Runtime')
        shutil.copy2(work/'ntdll.dll',work/'Runtime/lib/wine/x86_64-windows/ntdll.dll')
        metadata={'ntdll_pe_sha256':sha(work/'ntdll.dll'),'original_sync_sha256':sha(original),
            'baseline_renderer_sha256':json.loads((baseline/'Runtime/workload-performance-build.json').read_text())['renderer_sha256'],
            'wine_sync_sha256':sha(source/'dlls/ntdll/sync.c'),'wine_runtime':json.loads((baseline/'Runtime/runtime.json').read_text()),
            'inputs':{name:sha(ROOT/'decompression'/name) for name in ['WaitQueues.h','NtIdentity.h','Sha256.h','Identity.h']},'queue_count':4096,'separation_bytes':128,'default_mode':'off','gameplay_accepted':False}
        (work/'wait-queues-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return native/'ntdll.dll'

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-wait-queues'));p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'));a=p.parse_args();print(build(a.work,a.baseline))
