#!/usr/bin/env python3
"""Stage or deliver the isolated, default-off Metal cache candidate."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
from build_runtime import ROOT, sha
from build_workload import clone
from game_context import APP, DATA, GAME
from package_game_repair import unsigned_sha

NAME='Wizard101 Metal Cache'
IDENTIFIER='org.wizard101native.metal-cache'
BASE_APP=Path.home()/'Desktop/Wizard101 Game Repair.app'
BASE_DATA=Path.home()/'Library/Application Support/Wizard101 Game Repair/Data'


def package(work,launcher,output,seed=False,verification=None):
    work,launcher,output=map(lambda p:Path(p).resolve(),(work,launcher,output))
    metadata=json.loads((work/'metal-archive-build.json').read_text())
    for name,digest in metadata['inputs'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Metal source changed after build: '+name)
    library=work/'moltenvk/Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'
    if sha(library)!=metadata['library_sha256']:raise ValueError('Metal library identity changed')
    tests=json.loads((work/'launcher-tests.json').read_text())
    if tests.get('passed',0)<6000:raise ValueError('Launcher tests are incomplete')
    if verification:
        verified=json.loads(Path(verification).read_text())
        if not verified.get('install_qualified') or verified['library_build_sha256']!=sha(library):raise ValueError('Metal runtime is unverified')
        if verified['launcher_unsigned_sha256']!=unsigned_sha(launcher/'Contents/MacOS/Wizard101Native'):raise ValueError('Unverified launcher')
        for name,digest in verified['inputs'].items():
            if sha(ROOT/name)!=digest:raise ValueError('Verified source changed: '+name)
    elif output.parent==Path.home()/'Desktop':raise ValueError('Verify the staged app before Desktop delivery')
    watched=[]
    for app in (BASE_APP,APP):
        watched.extend(app/'Contents'/name for name in ['MacOS/Wizard101Native','Info.plist','Resources/Renderer/d3d9.dll',
                                                       'Resources/Runtime/bin/wine','Resources/Runtime/lib/libMoltenVK.dylib'])
    for data in (BASE_DATA,DATA):
        watched.extend(data/GAME.parent/name for name in ['WizardGraphicalClient.exe','config.xml','preferences.xml','d3d9.dll'])
    before={str(p):sha(p) for p in watched if p.is_file()}
    if output.exists():raise ValueError('Use a fresh candidate app path')
    clone(BASE_APP,output)
    resources=output/'Contents/Resources';target=resources/'Runtime/lib/libMoltenVK.dylib'
    shutil.copy2(library,target)
    subprocess.run(['codesign','--force','--sign','-',str(target)],check=True,capture_output=True)
    shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',output/'Contents/MacOS/Wizard101Native')
    info=plistlib.loads((output/'Contents/Info.plist').read_bytes())
    info.update(CFBundleName=NAME,CFBundleDisplayName=NAME,CFBundleIdentifier=IDENTIFIER,W101DefaultDataDirectory=NAME+'/Data')
    info.pop('W101DataRoot',None)
    info['W101ExperimentDefaults']['W101_METAL_ARCHIVE']='0'
    info['W101ExperimentDefaults'].pop('W101_SCENE_NODES',None)
    (output/'Contents/Info.plist').write_bytes(plistlib.dumps(info,sort_keys=False))
    metadata=metadata|dict(installed_library_sha256=sha(target),verification_sha256=sha(verification) if verification else None,
                           baseline_moltenvk_sha256=sha(BASE_APP/'Contents/Resources/Runtime/lib/libMoltenVK.dylib'),
                           inherited_gpu_capture_overlay=False)
    (resources/'Runtime/metal-archive-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    shutil.copy2(work/'metal-archive.patch',resources/'Runtime/metal-archive.patch')
    for relative in ['Runtime/workload-build.json','Runtime/workload-performance-build.json','Renderer/workload-performance-build.json']:
        file=resources/relative
        if file.exists():
            item=json.loads(file.read_text());item['moltenvk_sha256']=sha(target);item['metal_archive']=metadata
            file.write_text(json.dumps(item,indent=2)+'\n')
    subprocess.run(['codesign','--force','--sign','-',str(output)],check=True,capture_output=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(output)],check=True,capture_output=True)
    candidate_data=Path.home()/'Library/Application Support'/NAME/'Data'
    preserved={}
    if seed:
        names=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
        if any(n.replace('\\','/').rsplit('/',1)[-1].lower()=='wizardgraphicalclient.exe' for n in names):raise ValueError('Quit normally before cloning settings')
        if candidate_data.exists():raise ValueError('Candidate data exists; retain it rather than replacing it')
        files=[BASE_DATA/GAME.parent/n for n in ['WizardGraphicalClient.exe','config.xml','preferences.xml','zlib1v142x64.dll','d3dx9_43.dll','w101decompress.dll','d3d9.dll','WizardGraphicalClient.dxvk-cache']]
        files.append(BASE_DATA/'Prefix/drive_c/graphics-patch-cache/Wizard101/known-assets.w101assets')
        original={str(p.relative_to(BASE_DATA)):sha(p) for p in files if p.is_file()}
        clone(BASE_DATA,candidate_data)
        preserved={relative:sha(candidate_data/relative)==digest for relative,digest in original.items()}
        if not all(preserved.values()):raise ValueError('Cloned gameplay configuration changed')
        if sha(candidate_data/GAME.parent/'d3d9.dll')!=sha(resources/'Renderer/d3d9.dll'):raise ValueError('Installed lookup renderer differs')
        source_preferences=Path.home()/'Library/Preferences/org.wizard101native.game-repair.plist'
        prefs=plistlib.loads(source_preferences.read_bytes()) if source_preferences.exists() else {}
        prefs['optimization.metalArchive']=False;prefs['optimization.sceneNodes']=False
        with tempfile.NamedTemporaryFile(suffix='.plist') as f:
            os.chmod(f.name,0o600);f.write(plistlib.dumps(prefs));f.flush()
            subprocess.run(['defaults','import',IDENTIFIER,f.name],check=True,capture_output=True)
    if before!={str(p):sha(p) for p in watched if p.is_file()}:raise ValueError('Existing app or gameplay data changed unexpectedly')
    result=dict(app=str(output),data=str(candidate_data),seeded=seed or candidate_data.exists(),default_enabled=False,
                library_build_sha256=sha(library),installed_library_sha256=sha(target),
                renderer_sha256=sha(resources/'Renderer/d3d9.dll'),launcher_unsigned_sha256=unsigned_sha(output/'Contents/MacOS/Wizard101Native'),
                baseline_inputs=before,baseline_preserved=True,cloned_inputs_preserved=preserved,scene_patch_available=False,
                code_signature_verified=True,gameplay_accepted=False,verification_sha256=sha(verification) if verification else None)
    (work/('delivery.json' if verification else 'staging.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-metal-archive'))
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-metal-archive-launcher-delivery.app'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',action='store_true');p.add_argument('--verification',type=Path)
    a=p.parse_args();print(json.dumps(package(a.work,a.launcher,a.output,a.seed,a.verification),indent=2))
