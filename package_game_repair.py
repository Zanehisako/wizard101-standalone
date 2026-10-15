#!/usr/bin/env python3
"""Create a separate candidate app and optionally seed its data after normal game exit."""
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

NAME='Wizard101 Game Repair'
IDENTIFIER='org.wizard101native.game-repair'

def unsigned_sha(binary):
    # Signing with the candidate's new bundle identifier changes the signature
    # blob in Mach-O. Compare identical executable content independently of it.
    with tempfile.TemporaryDirectory(prefix='w101-game-code-') as folder:
        copy=Path(folder)/'launcher';shutil.copy2(binary,copy)
        subprocess.run(['codesign','--remove-signature',str(copy)],check=True,capture_output=True)
        return sha(copy)

def package(work,launcher,report,output,seed=False):
    work,launcher,report,output=map(lambda p:Path(p).resolve(),(work,launcher,report,output))
    evidence=json.loads(report.read_text());metadata=json.loads((work/'game-repair-build.json').read_text())
    if not evidence.get('install_qualified') or not all(evidence['checks'].values()):raise ValueError('Hook verification is incomplete')
    for name,digest in (metadata['inputs']|evidence['inputs']).items():
        if sha(ROOT/name)!=digest:raise ValueError('Unverified source change: '+name)
    renderer=work/'build-renderer/src/d3d9/d3d9.dll'
    if sha(renderer)!=metadata['renderer_sha256'] or sha(APP/'Contents/Resources/Renderer/d3d9.dll')!=metadata['baseline_renderer_sha256']:raise ValueError('Renderer identity differs')
    tests=json.loads((work/'launcher-delivery-tests.json').read_text())
    if not tests.get('passed'):raise ValueError('Launcher checks failed')
    watched=[APP/'Contents/MacOS/Wizard101Native',APP/'Contents/Info.plist',APP/'Contents/Resources/Renderer/d3d9.dll',
             APP/'Contents/Resources/Runtime/bin/wine',APP/'Contents/Resources/Runtime/lib/libMoltenVK.dylib']
    before={str(p):sha(p) for p in watched}
    if not output.exists():
        clone(APP,output)
        resources=output/'Contents/Resources';folder=resources/'Renderer'
        shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',output/'Contents/MacOS/Wizard101Native')
        shutil.copy2(renderer,folder/'d3d9.dll');(folder/'d3d9.sha256').write_text(sha(renderer)+'\n')
        shutil.copy2(ROOT/'licenses/minhook-1.3.4.txt',resources/'Licenses/minhook-1.3.4.txt')
        info=plistlib.loads((output/'Contents/Info.plist').read_bytes())
        info.update(CFBundleName=NAME,CFBundleDisplayName=NAME,CFBundleIdentifier=IDENTIFIER,W101DefaultDataDirectory=NAME+'/Data')
        info.pop('W101DataRoot',None)
        info['W101ExperimentDefaults']['W101_GAME_REPAIR']='0'
        # Prior layout candidates failed gameplay. Keep their saved values, but
        # both sides of this comparison use the original draw implementation.
        info['W101ExperimentDefaults'].pop('W101_DRAW_LAYOUT_DIRECT',None)
        info['W101ExperimentDefaults'].pop('W101_DRAW_LAYOUT_CACHE',None)
        (output/'Contents/Info.plist').write_bytes(plistlib.dumps(info,sort_keys=False))
        metadata['verification_sha256']=sha(report)
        (folder/'game-repair-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
        for file in [folder/'asset-preparation-build.json',folder/'workload-performance-build.json',folder/'combined-build.json',resources/'Runtime/workload-performance-build.json']:
            item=json.loads(file.read_text());item['renderer_sha256']=sha(renderer);item['game_repair']=metadata
            if 'defaults' in item:
                item['defaults']['W101_GAME_REPAIR']='0';item['defaults'].pop('W101_DRAW_LAYOUT_DIRECT',None);item['defaults'].pop('W101_DRAW_LAYOUT_CACHE',None)
            file.write_text(json.dumps(item,indent=2)+'\n')
        subprocess.run(['codesign','--force','--sign','-',str(output)],check=True,capture_output=True)
    if sha(output/'Contents/Resources/Renderer/d3d9.dll')!=sha(renderer) or unsigned_sha(output/'Contents/MacOS/Wizard101Native')!=unsigned_sha(launcher/'Contents/MacOS/Wizard101Native'):raise ValueError('Existing candidate differs; use a fresh app path')
    subprocess.run(['codesign','--verify','--deep','--strict',str(output)],check=True,capture_output=True)
    candidate_data=Path.home()/'Library/Application Support'/NAME/'Data'
    preserved={}
    if seed:
        names=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
        if any(n.replace('\\','/').rsplit('/',1)[-1].lower()=='wizardgraphicalclient.exe' for n in names):raise ValueError('Quit normally before cloning game settings')
        if candidate_data.exists():raise ValueError('Candidate data exists; retain it rather than replacing it')
        game=DATA/GAME.parent
        files=[game/n for n in ('WizardGraphicalClient.exe','zlib1v142x64.dll','d3dx9_43.dll','w101decompress.dll','config.xml','preferences.xml','WizardGraphicalClient.dxvk-cache')]
        files+=[DATA/'Prefix/drive_c/graphics-patch-cache/Wizard101/known-assets.w101assets']
        original={str(p.relative_to(DATA)):sha(p) for p in files if p.is_file()}
        clone(DATA,candidate_data)
        for relative,digest in original.items():preserved[relative]=sha(candidate_data/relative)==digest
        if not all(preserved.values()):raise ValueError('Cloned settings or cache differs')
        target=candidate_data/GAME.parent/'d3d9.dll';shutil.copy2(renderer,target)
        source_preferences=Path.home()/'Library/Preferences/org.wizard101native.combined.plist'
        prefs=plistlib.loads(source_preferences.read_bytes()) if source_preferences.exists() else {}
        prefs['optimization.gameRepair']=False
        with tempfile.NamedTemporaryFile(suffix='.plist') as f:
            os.chmod(f.name,0o600);f.write(plistlib.dumps(prefs));f.flush()
            subprocess.run(['defaults','import',IDENTIFIER,f.name],check=True,capture_output=True)
    if before!={str(p):sha(p) for p in watched}:raise ValueError('Working app changed unexpectedly')
    result=dict(app=str(output),data=str(candidate_data),seeded=seed,renderer_sha256=sha(renderer),launcher_sha256=sha(output/'Contents/MacOS/Wizard101Native'),
                launcher_unsigned_sha256=unsigned_sha(output/'Contents/MacOS/Wizard101Native'),baseline_app_preserved=True,baseline_inputs=before,cloned_inputs_preserved=preserved,new_switch_default_off=True,
                rejected_layout_paths_disabled=True,saved_layout_selections_retained=True,gameplay_accepted=False,rollout_allowed=False,verification_sha256=sha(report))
    (work/'delivery.json').write_text(json.dumps(result,indent=2)+'\n');print('Candidate app packaged; data seeded:',seed);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-game-repair'))
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-game-repair-launcher-delivery.app'))
    p.add_argument('--report',type=Path,default=ROOT/'verification-local/game-repair-qualified-final-20261005/report.json')
    p.add_argument('--output',type=Path,default=Path.home()/'Desktop'/(NAME+'.app'));p.add_argument('--seed',action='store_true')
    a=p.parse_args();package(a.work,a.launcher,a.report,a.output,a.seed)
