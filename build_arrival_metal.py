#!/usr/bin/env python3
"""Add archive-hit-first reuse to the isolated MoltenVK archive backend."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from build_runtime import ROOT,sha
from build_workload import clone

def build(work,baseline):
    work,baseline=Path(work).resolve(),Path(baseline).resolve()
    source=work/'moltenvk';clone(baseline,source)
    folder=source/'MoltenVK/MoltenVK/GPUObjects'
    shutil.copy2(ROOT/'performance/ArrivalMetalArchive.h',folder/'W101MetalArchive.h')
    pipeline=folder/'MVKPipeline.mm';text=pipeline.read_text()
    for kind,desc in [('Render','mtlRPLDesc'),('Compute','plDesc')]:
        original='\tif (auto archive = _device->getW101MetalArchive()) archive->prepare('+desc+');'
        signature='id<MTL'+kind+'PipelineState> MVK'+kind+'PipelineCompiler::newMTL'+kind+'PipelineState('
        begin=text.index(signature);end=text.index('\n}',begin)+2
        block=text[begin:end]
        if original in block:
            block=block.replace(original,'')
            point='\t\tauto mtlDev = getMTLDevice();'
            replacement=point+'''
        if(auto archive=_device->getW101MetalArchive()) {
            if(auto hit=archive->hit(mtlDev,'''+desc+''')) {
                bool isLate=compileComplete(hit,nil);[hit release];
                if(isLate) destroy();return;
            }
            archive->prepare('''+desc+''');
        }'''
            if block.count(point)!=1:raise ValueError('Metal completion signature changed')
            block=block.replace(point,replacement)
            text=text[:begin]+block+text[end:]
        elif 'archive->hit(mtlDev,' not in block:raise ValueError('Archive integration differs')
    pipeline.write_text(text)
    # Reuse Apple's compiled dependencies. This cache is disposable; baseline
    # source trees, packaged libraries and working apps are never changed.
    subprocess.run(['xcodebuild','-quiet','build','-project','MoltenVKPackaging.xcodeproj',
                    '-scheme','MoltenVK Package (macOS only)','-configuration','Release',
                    '-destination','generic/platform=macOS','ARCHS=arm64 x86_64',
                    'ONLY_ACTIVE_ARCH=NO','MACOSX_DEPLOYMENT_TARGET=13.0','CODE_SIGNING_ALLOWED=NO'],cwd=source,check=True)
    library=source/'Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'
    inputs=[ROOT/'build_arrival_metal.py',ROOT/'performance/ArrivalMetalArchive.h']
    metadata=dict(library_sha256=sha(library),baseline_library_sha256=sha(baseline/'Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'),
                  inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},
                  source_integration_sha256=sha(pipeline),moltenvk='1.4.2',archive_hit_first=True,
                  normal_completion_handling=True,default_enabled=False,logging_added=False,gameplay_accepted=False)
    (work/'arrival-metal-build.json').write_text(json.dumps(metadata,indent=2)+'\n');return library

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-arrival'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-metal-archive/moltenvk'))
    a=p.parse_args();print(build(a.work,a.baseline))
