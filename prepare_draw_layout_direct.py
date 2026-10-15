#!/usr/bin/env python3
"""Build the isolated launcher and record read-only inputs before verification."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
from build_runtime import ROOT, sha
from build_app import build
from install_draw_layout import inputs

def prepare(app,output,keep):
    app,output,keep=map(lambda p:Path(p).resolve(),(app,output,keep))
    keep.mkdir(parents=True,exist_ok=True)
    if (keep/'report.json').exists() or (keep/'installed-before.json').exists():
        raise RuntimeError('Use a fresh evidence directory; earlier results are retained.')
    data=Path.home()/'Library/Application Support/Wizard101 Optimizations/Data'
    _,_,before=inputs(app,data)
    preferences=Path.home()/'Library/Preferences/org.wizard101native.combined.plist'
    before[str(preferences)]=sha(preferences) if preferences.exists() else None
    (keep/'installed-before.json').write_text(json.dumps(before,indent=2)+'\n')
    old={str(p):sha(p) for d in ('verification-local/draw-layout','verification-local/draw-layout-v2','revisions/draw-layout-v1')
         for p in (ROOT/d).rglob('*') if p.is_file()}
    (keep/'previous-evidence-before.json').write_text(json.dumps(old,indent=2)+'\n')
    build(output=output,development=True)
    path=output/'Contents/Info.plist';info=plistlib.loads(path.read_bytes())
    baseline=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    for key in ('W101CombinedOptimizations','W101ExperimentDefaults','W101WorkloadPerformanceDefaults','W101WorkloadPerformanceCandidate','W101WorkloadDiagnostics'):
        if key in baseline:info[key]=baseline[key]
    info.setdefault('W101ExperimentDefaults',{}).pop('W101_DRAW_LAYOUT_CACHE',None)
    info['W101ExperimentDefaults']['W101_DRAW_LAYOUT_DIRECT']='0'
    path.write_bytes(plistlib.dumps(info,sort_keys=False))
    subprocess.run(['codesign','--force','--sign','-',str(output)],check=True,capture_output=True)
    print(output)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--output',type=Path,default=Path('/private/tmp/w101-layout-direct-launcher.app'))
    p.add_argument('--keep',type=Path,default=ROOT/'verification-local/draw-layout-direct')
    a=p.parse_args();prepare(a.app,a.output,a.keep)
