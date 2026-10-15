#!/usr/bin/env python3
"""Build one runtime containing all three explicitly selected experiments."""
import argparse,json
from pathlib import Path
from build_native_decode import build as native_build
from build_runtime import ROOT,sha

def build(work,baseline,thread_baseline=None):
    work=Path(work).resolve()
    native_build(work,baseline,thread_baseline,wait_queues=True)
    metadata=json.loads((work/'native-decode-build.json').read_text())
    metadata['inputs']['WaitQueues.h']=sha(ROOT/'decompression/WaitQueues.h')
    metadata['default_mode']='manual'
    metadata['defaults']={'W101_DECOMPRESS':'off','W101_WAIT_QUEUES':'off','W101_NATIVE_DECODE':'off'}
    metadata['queue_count']=4096;metadata['separation_bytes']=128
    metadata['combined_gameplay_accepted']=False
    (work/'combined-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return work

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-combined'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-workload-performance'))
    p.add_argument('--thread-baseline',type=Path)
    a=p.parse_args();print(build(a.work,a.baseline,a.thread_baseline))
