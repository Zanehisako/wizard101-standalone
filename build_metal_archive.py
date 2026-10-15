#!/usr/bin/env python3
"""Build a separate MoltenVK 1.4.2 with default-off exact Metal binary archives."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone

def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('MoltenVK integration signature differs: '+before[:70])
    return text.replace(before, after, 1)

def build(work, baseline, compile=True, resume=False):
    work, baseline=Path(work).resolve(),Path(baseline).resolve()
    work.mkdir(parents=True,exist_ok=True);source=work/'moltenvk'
    if source.exists() and not resume:raise ValueError('Use a fresh Metal archive build directory, or --resume for this private overlay')
    if not source.exists():clone(baseline,source)
    folder=source/'MoltenVK/MoltenVK/GPUObjects'
    before={name:(baseline/'MoltenVK/MoltenVK/GPUObjects'/name).read_text() for name in ('MVKDevice.h','MVKDevice.mm','MVKPipeline.mm')}
    text=before['MVKDevice.h']
    text=replace(text,'class MVKDevice :', 'class W101MetalArchive;\n\nclass MVKDevice :')
    text=replace(text,'\tMTLCompileOptions* getMTLCompileOptions(', '\tW101MetalArchive* getW101MetalArchive();\n\n\tMTLCompileOptions* getMTLCompileOptions(')
    text=replace(text,'\tMVKPhysicalDevice* _physicalDevice = nullptr;', '\tstd::once_flag _w101ArchiveOnce;\n\tW101MetalArchive* _w101Archive = nullptr;\n\tMVKPhysicalDevice* _physicalDevice = nullptr;')
    (folder/'MVKDevice.h').write_text(text)
    text=replace(before['MVKDevice.mm'],'#include "MVKDevice.h"','#include "MVKDevice.h"\n#include "W101MetalArchive.h"')
    text=replace(text,'MVKDevice::~MVKDevice() {','W101MetalArchive* MVKDevice::getW101MetalArchive() {\n\tstd::call_once(_w101ArchiveOnce, [this] {\n\t\ttry { _w101Archive = new W101MetalArchive(_physicalDevice->getMTLDevice()); } catch (...) {}\n\t});\n\treturn _w101Archive;\n}\n\nMVKDevice::~MVKDevice() {')
    text=replace(text,'\tif (_commandResourceFactory) { _commandResourceFactory->destroy(); }','\tif (_commandResourceFactory) { _commandResourceFactory->destroy(); }\n\tif (_w101Archive) { _w101Archive->save(); delete _w101Archive; }')
    (folder/'MVKDevice.mm').write_text(text)
    text=replace(before['MVKPipeline.mm'],'#include "MVKPipeline.h"','#include "MVKPipeline.h"\n#include "W101MetalArchive.h"')
    needle='id<MTLRenderPipelineState> MVKRenderPipelineCompiler::newMTLRenderPipelineState(MTLRenderPipelineDescriptor* mtlRPLDesc) {'
    text=replace(text,needle,needle+'\n\tif (auto archive = _device->getW101MetalArchive()) archive->prepare(mtlRPLDesc);')
    needle='id<MTLComputePipelineState> MVKComputePipelineCompiler::newMTLComputePipelineState(MTLComputePipelineDescriptor* plDesc) {'
    text=replace(text,needle,needle+'\n\tif (auto archive = _device->getW101MetalArchive()) archive->prepare(plDesc);')
    # Function-only and mesh pipelines retain their original path. D3D9 uses
    # ordinary render descriptors; no pipeline state or compile options change.
    (folder/'MVKPipeline.mm').write_text(text)
    shutil.copy2(ROOT/'performance/MetalArchive.h',folder/'W101MetalArchive.h')
    diff=''.join(''.join(difflib.unified_diff(before[n].splitlines(True),(folder/n).read_text().splitlines(True),fromfile='a/MoltenVK/MoltenVK/GPUObjects/'+n,tofile='b/MoltenVK/MoltenVK/GPUObjects/'+n)) for n in before)
    (work/'metal-archive.patch').write_text(diff)
    if compile:
        subprocess.run(['xcodebuild','-quiet','build','-project','MoltenVKPackaging.xcodeproj','-scheme','MoltenVK Package (macOS only)',
                        '-configuration','Release','-destination','generic/platform=macOS','-derivedDataPath',str(work/'DerivedData'),
                        'ARCHS=arm64 x86_64','ONLY_ACTIVE_ARCH=NO','MACOSX_DEPLOYMENT_TARGET=13.0','CODE_SIGNING_ALLOWED=NO'],cwd=source,check=True)
    library=source/'Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'
    metadata=dict(default_enabled=False,gameplay_accepted=False,source=str(source),baseline_inputs={n:sha(baseline/'MoltenVK/MoltenVK/GPUObjects'/n) for n in before},
                  inputs={'performance/MetalArchive.h':sha(ROOT/'performance/MetalArchive.h'),'build_metal_archive.py':sha(ROOT/'build_metal_archive.py')},
                  upstream_reference='https://github.com/BlueHeisenberg/SCSKiller/tree/230f68e07b7b57d0c4b52ab43a284d0a19689a67',upstream_code_copied=False,
                  patch_sha256=sha(work/'metal-archive.patch'),library_sha256=sha(library) if compile else None,max_file_bytes=64*1024*1024,
                  architectures=['arm64','x86_64'],disk_writes_at_device_teardown_only=True,logging_added=False)
    (work/'metal-archive-build.json').write_text(json.dumps(metadata,indent=2)+'\n');return library

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-metal-archive'))
    p.add_argument('--baseline',type=Path,default=Path('/private/tmp/w101-runtime-26.3.0/moltenvk-1.4.2'));p.add_argument('--sources-only',action='store_true')
    p.add_argument('--resume',action='store_true');a=p.parse_args();print(build(a.work,a.baseline,not a.sources_only,a.resume))
