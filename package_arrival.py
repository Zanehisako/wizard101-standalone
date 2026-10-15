#!/usr/bin/env python3
"""Transactionally stage/deliver the isolated Arrival Candidate and rollback."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
from build_runtime import ROOT,sha
from build_workload import clone
from game_context import GAME,EXPECTED,PEIdentity
from package_game_repair import unsigned_sha

NAME='Wizard101 Arrival Candidate'
IDENTIFIER='org.wizard101native.arrival-candidate'
BASE_APP=Path.home()/'Desktop/Wizard101 Metal Cache.app'
BASE_DATA=Path.home()/'Library/Application Support/Wizard101 Metal Cache/Data'

def package(work,launcher,output,verification=None,seed=False,learning_verification=None,metal_verification=None,decompression_verification=None,replace=False):
    work,launcher,output=map(lambda p:Path(p).resolve(),(work,launcher,output))
    renderer=work/'build-renderer/src/d3d9/d3d9.dll'
    adapter=work/'w101decompress.dll'
    library=work/'moltenvk/Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'
    metadata=json.loads((work/'arrival-build.json').read_text())
    metal=json.loads((work/'arrival-metal-build.json').read_text())
    for name,digest in (metadata['inputs']|metal['inputs']).items():
        if sha(ROOT/name)!=digest:raise ValueError('Build input changed: '+name)
    if sha(adapter)!=metadata['adapter_sha256']:raise ValueError('Decoder artifact changed')
    if sha(renderer)!=metadata['renderer_sha256'] or sha(library)!=metal['library_sha256']:raise ValueError('Build artifact changed')
    if sha(BASE_APP/'Contents/Resources/Renderer/d3d9.dll')!=metadata['baseline_renderer_sha256']:raise ValueError('Lookup baseline changed')
    if sha(BASE_DATA/GAME)!=EXPECTED:raise ValueError('Game executable changed')
    inherited=json.loads((BASE_APP/'Contents/Resources/Renderer/game-repair-build.json').read_text())
    for name,digest in inherited['inputs'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Inherited lookup/hook source changed: '+name)
    pe=PEIdentity(BASE_DATA/GAME)
    for hook in inherited['hooks']:
        if hashlib.sha256(pe.bytes_at(hook['rva'],hook['bytes'])).hexdigest()!=hook['sha256']:
            raise ValueError('Inherited lookup signature changed')
        signature=bytes.fromhex(hook['getter_signature'])
        if pe.bytes_at(hook['getter_rva'],len(signature))!=signature:raise ValueError('Inherited getter signature changed')
    if sha(work/'moltenvk/MoltenVK/MoltenVK/GPUObjects/MVKPipeline.mm')!=metal['source_integration_sha256']:
        raise ValueError('Metal completion integration changed')
    tests=json.loads((work/'launcher-tests.json').read_text())
    for name,digest in tests['inputs'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Launcher source changed: '+name)
    if tests.get('passed',0)<24000:raise ValueError('Launcher verification incomplete')
    if tests.get('launcher_unsigned_sha256')!=unsigned_sha(launcher/'Contents/MacOS/Wizard101Native'):
        raise ValueError('Launcher differs from the tested executable')
    if output.exists() and not replace:raise ValueError('Use a fresh app output or explicit replacement; existing candidates survive failures')
    if replace and not verification:raise ValueError('Replacement requires verified artifacts')
    evidence=json.loads(Path(verification).read_text()) if verification else None
    if output.parent==Path.home()/'Desktop' and not evidence:raise ValueError('Verify a staged app before Desktop delivery')
    if evidence and (not evidence.get('correctness_qualified') or evidence['renderer_sha256']!=sha(renderer)
                     or evidence['metal_build_sha256']!=sha(library)
                     or evidence['adapter_sha256']!=sha(adapter)):
        raise ValueError('Verification does not bind the delivered artifacts')
    if evidence:
        for name,digest in evidence['inputs'].items():
            if sha(ROOT/name)!=digest:raise ValueError('Verified source changed: '+name)
    if output.parent==Path.home()/'Desktop' and not evidence.get('performance_qualified'):raise ValueError('Upload performance gate failed; retain the staged experiment')
    extra_evidence={}
    for label,file in [('pipeline_learning',learning_verification),('metal_archive',metal_verification),('decompression',decompression_verification)]:
        if file:
            item=json.loads(Path(file).read_text())
            if not item.get('passed'):raise ValueError('Supplementary verification failed: '+label)
            if label=='pipeline_learning' and item['renderer_sha256']!=sha(renderer):raise ValueError('Pipeline replay uses a different renderer')
            if label=='decompression' and item['adapter_sha256']!=sha(adapter):raise ValueError('Decoder verification uses a different adapter')
            for name,digest in item['inputs'].items():
                if sha(ROOT/name)!=digest:raise ValueError('Supplementary source changed: '+name)
            extra_evidence[label]=sha(file)
        elif output.parent==Path.home()/'Desktop':raise ValueError('Missing supplementary verification: '+label)
    data=Path.home()/'Library/Application Support'/NAME/'Data'
    seed_preferences=None
    if seed:
        names=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
        if any(n.replace('\\','/').rsplit('/',1)[-1].lower()=='wizardgraphicalclient.exe' for n in names):raise ValueError('Game must exit normally before cloning its data')
        if data.exists():raise ValueError('Existing candidate data will not be replaced')
        source=subprocess.run(['defaults','export','org.wizard101native.metal-cache','-'],capture_output=True)
        if source.returncode and (Path.home()/'Library/Preferences/org.wizard101native.metal-cache.plist').exists():
            raise ValueError('Cannot read current saved selections')
        seed_preferences=plistlib.loads(source.stdout) if source.returncode==0 else {}
    watched=[]
    for app in (BASE_APP,Path.home()/'Desktop/Wizard101 Game Repair.app',Path.home()/'Desktop/Wizard101 Optimizations.app'):
        watched += [app/'Contents'/n for n in ('MacOS/Wizard101Native','Info.plist','Resources/Renderer/d3d9.dll','Resources/Runtime/lib/libMoltenVK.dylib')]
    watched += [BASE_DATA/GAME,BASE_DATA/GAME.parent/'config.xml',BASE_DATA/GAME.parent/'preferences.xml']
    watched += [data/GAME.parent/n for n in ('WizardGraphicalClient.exe','config.xml','preferences.xml','d3d9.dll','w101decompress.dll')]
    before={str(p):sha(p) for p in watched if p.is_file()}
    previous_app=None
    previous_hashes={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()} if output.exists() else {}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.arrival-stage-',dir=output.parent) as folder:
        stage=Path(folder)/output.name;clone(BASE_APP,stage)
        resources=stage/'Contents/Resources'
        shutil.copy2(renderer,resources/'Renderer/d3d9.dll');(resources/'Renderer/d3d9.sha256').write_text(sha(renderer)+'\n')
        shutil.copy2(adapter,resources/'Renderer/w101decompress.dll')
        (resources/'Renderer/w101decompress.sha256').write_text(sha(adapter)+'\n')
        shutil.copy2(library,resources/'Runtime/lib/libMoltenVK.dylib')
        subprocess.run(['codesign','--force','--sign','-',str(resources/'Runtime/lib/libMoltenVK.dylib')],check=True,capture_output=True)
        shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',stage/'Contents/MacOS/Wizard101Native')
        info=plistlib.loads((stage/'Contents/Info.plist').read_bytes())
        info.update(CFBundleName=NAME,CFBundleDisplayName=NAME,CFBundleIdentifier=IDENTIFIER,W101DefaultDataDirectory=NAME+'/Data')
        info.pop('W101DataRoot',None)
        info['W101ExperimentDefaults'].update(W101_SCENE_TEXTURES='0',W101_PREPARE_PIPELINES='0',W101_PREPARE_APPEARANCE='0')
        info['W101ExperimentDefaults'].pop('W101_SCENE_NODES',None)
        (stage/'Contents/Info.plist').write_bytes(plistlib.dumps(info,sort_keys=False))
        provenance=metadata|dict(metal=metal,installed_metal_sha256=sha(resources/'Runtime/lib/libMoltenVK.dylib'),
                                  verification_sha256=sha(verification) if verification else None,
                                  supplementary_verification=extra_evidence,
                                  performance_qualified=bool(evidence and evidence.get('performance_qualified')))
        if evidence and provenance['installed_metal_sha256']!=evidence['installed_metal_sha256']:
            raise ValueError('Signed Metal backend differs from the tested runtime')
        (resources/'Renderer/arrival-build.json').write_text(json.dumps(provenance,indent=2)+'\n')
        shutil.copy2(ROOT/'ARRIVAL-CANDIDATE.md',resources/'Renderer/ARRIVAL-CANDIDATE.md')
        # Keep provenance of inherited components, but update every artifact hash
        # consumed by validation to refer to the actual packaged renderer/backend.
        for file in list((resources/'Renderer').glob('*build.json'))+list((resources/'Runtime').glob('*build.json')):
            if file.name=='arrival-build.json':continue
            item=json.loads(file.read_text())
            if 'adapter_sha256' in item:item['adapter_sha256']=sha(adapter)
            if 'renderer_sha256' in item:item['renderer_sha256']=sha(renderer)
            if 'moltenvk_sha256' in item:item['moltenvk_sha256']=sha(resources/'Runtime/lib/libMoltenVK.dylib')
            item['arrival_candidate']=provenance;file.write_text(json.dumps(item,indent=2)+'\n')
        subprocess.run(['codesign','--force','--sign','-',str(stage)],check=True,capture_output=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(stage)],check=True,capture_output=True)
        if output.exists():
            previous_app=output.with_name(output.stem+' Previous '+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.app')
            if previous_app.exists():raise ValueError('Rollback app already exists')
            os.rename(output,previous_app)
        try:os.rename(stage,output)
        except BaseException:
            if previous_app:os.rename(previous_app,output)
            raise
    if previous_app and previous_hashes!={str(p.relative_to(previous_app)):sha(p) for p in previous_app.rglob('*') if p.is_file()}:
        raise ValueError('Rollback app changed during replacement')
    preserved={}
    if seed:
        names=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
        if any(n.replace('\\','/').rsplit('/',1)[-1].lower()=='wizardgraphicalclient.exe' for n in names):raise ValueError('Game must exit normally before cloning its data')
        if data.exists():raise ValueError('Existing candidate data will not be replaced')
        files=[BASE_DATA/GAME.parent/n for n in ('WizardGraphicalClient.exe','config.xml','preferences.xml','d3dx9_43.dll','zlib1v142x64.dll','w101decompress.dll','WizardGraphicalClient.dxvk-cache')]
        original={str(p.relative_to(BASE_DATA)):sha(p) for p in files if p.is_file()}
        data.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.arrival-data-',dir=data.parent) as folder:
            stage=Path(folder)/'Data';clone(BASE_DATA,stage)
            preserved={n:sha(stage/n)==digest for n,digest in original.items()}
            if not all(preserved.values()):raise ValueError('Game settings or identity changed during data cloning')
            shutil.copy2(renderer,stage/GAME.parent/'d3d9.dll');shutil.copy2(adapter,stage/GAME.parent/'w101decompress.dll');os.rename(stage,data)
        prefs=seed_preferences
        prefs['optimization.sceneTextures']=False;prefs['optimization.preparePipelines']=False;prefs['optimization.prepareAppearance']=False
        with tempfile.NamedTemporaryFile(suffix='.plist') as f:
            os.chmod(f.name,0o600);f.write(plistlib.dumps(prefs));f.flush()
            subprocess.run(['defaults','import',IDENTIFIER,f.name],check=True,capture_output=True)
    if before!={str(p):sha(p) for p in watched if p.is_file()}:raise ValueError('Preserved working app/data changed')
    result=dict(app=str(output),previous_app=str(previous_app) if previous_app else None,previous_app_preserved=bool(previous_app),data=str(data),seeded=seed,baseline_preserved=True,baseline_hashes=before,
                cloned_inputs_preserved=preserved,renderer_sha256=sha(renderer),metal_build_sha256=sha(library),
                installed_metal_sha256=sha(output/'Contents/Resources/Runtime/lib/libMoltenVK.dylib'),
                launcher_unsigned_sha256=unsigned_sha(output/'Contents/MacOS/Wizard101Native'),
                defaults=metadata['defaults'],signatures_verified=True,correctness_qualified=bool(evidence),
                performance_qualified=bool(evidence and evidence.get('performance_qualified')),
                gameplay_accepted=False,rollback='Disable the arrival options and relaunch, or open the preserved Metal Cache/working app.')
    (work/('delivery.json' if verification else 'staging.json')).write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-arrival'))
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-arrival-launcher-final.app'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--verification',type=Path);p.add_argument('--seed',action='store_true')
    p.add_argument('--learning-verification',type=Path);p.add_argument('--metal-verification',type=Path)
    p.add_argument('--decompression-verification',type=Path);p.add_argument('--replace',action='store_true')
    a=p.parse_args();print(json.dumps(package(a.work,a.launcher,a.output,a.verification,a.seed,a.learning_verification,a.metal_verification,a.decompression_verification,a.replace),indent=2))
