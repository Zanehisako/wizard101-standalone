#!/usr/bin/env python3
"""Build the arrival launcher and bind its self-tests to the executable."""
import argparse
import json
from pathlib import Path
import subprocess
from build_app import build
from build_runtime import ROOT,sha
from package_game_repair import unsigned_sha

def compile_and_verify(output,work):
    output=Path(output).resolve();work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True)
    build(output=output,development=True)
    executable=output/'Contents/MacOS/Wizard101Native'
    result=subprocess.run([str(executable),'--self-test'],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr+result.stdout)
    tests=json.loads(result.stdout)
    if tests.get('passed',0)<24000:raise ValueError('Arrival launcher tests incomplete')
    tests['inputs']={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'launcher/Sources').glob('*')) if p.is_file()}
    tests['launcher_unsigned_sha256']=unsigned_sha(executable)
    (work/'launcher-tests.json').write_text(json.dumps(tests,indent=2)+'\n')
    return dict(launcher=str(output),checks_passed=tests['passed'],unsigned_sha256=tests['launcher_unsigned_sha256'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('/private/tmp/w101-arrival-launcher-final.app'))
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-arrival'))
    a=p.parse_args();print(json.dumps(compile_and_verify(a.output,a.work),indent=2))
