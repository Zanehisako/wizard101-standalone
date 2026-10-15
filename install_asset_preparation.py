#!/usr/bin/env python3
"""Update the same combined launcher transactionally, retaining a local rollback."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone

def idle():
    result=subprocess.run(['pgrep','-fl','WizardGraphicalClient.exe|Wizard101Native'],capture_output=True,text=True)
    if result.returncode==0:raise RuntimeError('Close the game and launcher before installing or restoring: '+result.stdout.strip())

def install(work, app, data, launcher, report):
    work,app,data,launcher,report=map(lambda p:Path(p).resolve(),(work,app,data,launcher,report))
    idle()
    metadata=json.loads((work/'asset-preparation-build.json').read_text())
    evidence=json.loads(report.read_text())
    render=work/'build-renderer/src/d3d9/d3d9.dll'
    if metadata['renderer_sha256']!=sha(render) or evidence['renderer_sha256']!=sha(render):raise RuntimeError('Stale renderer verification')
    for name,digest in metadata['inputs'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Build input changed: '+name)
    if not all(bool(v) and (not isinstance(v,dict) or v.get('passed',True)) for v in evidence['checks'].values()):raise RuntimeError('Verification failed')
    original=app/'Contents/Resources'
    if sha(original/'Renderer/d3d9.dll')!=metadata['baseline_renderer_sha256']:raise RuntimeError('Installed combined renderer differs from build baseline')
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!='org.wizard101native.combined':raise RuntimeError('Expected the combined launcher')
    game=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin'
    if sha(game/'d3dx9_43.dll')!=evidence['native_decoder_sha256']:raise RuntimeError('Native decoder differs from verification')
    preserved={name:sha(game/name) for name in ['WizardGraphicalClient.exe','zlib1v142x64.dll','d3dx9_43.dll','w101decompress.dll','config.xml','preferences.xml','WizardGraphicalClient.dxvk-cache'] if (game/name).exists()}
    runtime={str(p.relative_to(original/'Runtime')):sha(p) for p in sorted((original/'Runtime').rglob('*')) if p.is_file() and not p.is_symlink()}
    backup=data.parent/'Rollback'/('asset-preparation-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));backup.mkdir(parents=True)
    clone(app,backup/'Wizard101 Optimizations.app');shutil.copy2(game/'d3d9.dll',backup/'game-d3d9.dll')
    stage=work/'Wizard101 Optimizations.app'
    if stage.exists():shutil.rmtree(stage)
    clone(app,stage)
    resources=stage/'Contents/Resources';renderer=resources/'Renderer'
    shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',stage/'Contents/MacOS/Wizard101Native')
    shutil.copy2(render,renderer/'d3d9.dll');(renderer/'d3d9.sha256').write_text(sha(render)+'\n')
    info['W101ExperimentDefaults']['W101_PREPARE_ASSETS']='0'
    plistlib.dump(info,(stage/'Contents/Info.plist').open('wb'),sort_keys=False)
    metadata['verification_sha256']=sha(report)
    (renderer/'asset-preparation-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    for file in [renderer/'workload-performance-build.json',resources/'Runtime/workload-performance-build.json']:
        meta=json.loads(file.read_text());meta['renderer_sha256']=sha(render)
        meta['asset_preparation']=metadata
        meta['feature_scope']['cache']='Native D3DX memory loaders and FileExA; immutable managed static 2D pixels and one-use prepared textures'
        file.write_text(json.dumps(meta,indent=2)+'\n')
    combined=renderer/'combined-build.json'
    meta=json.loads(combined.read_text());meta['renderer_sha256']=sha(render);meta['asset_preparation']=metadata;meta['defaults']['W101_PREPARE_ASSETS']='0'
    combined.write_text(json.dumps(meta,indent=2)+'\n')
    subprocess.run(['codesign','--force','--sign','-',str(stage)],check=True,capture_output=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(stage)],check=True,capture_output=True)
    # Runtime metadata names the new renderer; all executable runtime bytes stay identical.
    changed=[name for name,digest in runtime.items() if name!='workload-performance-build.json' and sha(resources/'Runtime'/name)!=digest]
    if changed:raise RuntimeError('Runtime unexpectedly changed: '+str(changed))
    manifest={'app':str(app),'game_renderer':str(game/'d3d9.dll'),'backup':str(backup),'preserved_game_inputs':preserved,'installed_renderer_sha256':sha(render),'runtime_executables_unchanged':True,'gameplay_verified':False}
    (backup/'rollback.json').write_text(json.dumps(manifest,indent=2)+'\n')
    # Copy staging beside the destination, then swap directories on the same volume.
    next_app=app.with_name('.Wizard101 Optimizations.asset-stage.app')
    if next_app.exists():raise RuntimeError('Previous installation staging needs attention: '+str(next_app))
    clone(stage,next_app)
    retired=app.with_name('.Wizard101 Optimizations.asset-retired.app')
    if retired.exists():raise RuntimeError('Previous installation retirement needs attention: '+str(retired))
    try:
        app.rename(retired);next_app.rename(app)
        temporary=game/'d3d9.dll.asset-stage';shutil.copy2(render,temporary);temporary.replace(game/'d3d9.dll')
        if any(sha(game/name)!=digest for name,digest in preserved.items()):raise RuntimeError('Game input changed')
    except BaseException:
        if retired.exists():
            if app.exists():shutil.rmtree(app)
            retired.rename(app)
        shutil.copy2(backup/'game-d3d9.dll',game/'d3d9.dll')
        raise
    shutil.rmtree(retired)
    (work/'delivery.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2));return manifest

def restore(backup):
    idle();backup=Path(backup).resolve();manifest=json.loads((backup/'rollback.json').read_text())
    app=Path(manifest['app']);game=Path(manifest['game_renderer'])
    if sha(app/'Contents/Resources/Renderer/d3d9.dll')!=manifest['installed_renderer_sha256']:raise RuntimeError('A later app update exists; refusing to overwrite it')
    stage=app.with_name('.Wizard101 Optimizations.restore.app');clone(backup/'Wizard101 Optimizations.app',stage)
    retired=app.with_name('.Wizard101 Optimizations.restore-retired.app')
    if retired.exists():raise RuntimeError('Restore retirement already exists')
    app.rename(retired)
    try:stage.rename(app);shutil.copy2(backup/'game-d3d9.dll',game)
    except BaseException:
        if app.exists():shutil.rmtree(app)
        retired.rename(app);raise
    shutil.rmtree(retired);print('Restored previous launcher and renderer; saved selections and game settings retained.')

def refresh_launcher(work,app,launcher):
    """Replace a launcher via a bundle swap; a running launcher keeps its old image."""
    work,app,launcher=map(lambda p:Path(p).resolve(),(work,app,launcher))
    metadata=json.loads((work/'asset-preparation-build.json').read_text())
    if sha(app/'Contents/Resources/Renderer/d3d9.dll')!=metadata['renderer_sha256']:raise RuntimeError('Unexpected installed renderer')
    next_app=app.with_name('.Wizard101 Optimizations.layout-stage.app')
    retired=app.with_name('.Wizard101 Optimizations.layout-retired.app')
    if next_app.exists() or retired.exists():raise RuntimeError('Launcher update staging already exists')
    clone(app,next_app)
    shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',next_app/'Contents/MacOS/Wizard101Native')
    subprocess.run(['codesign','--force','--sign','-',str(next_app)],check=True,capture_output=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(next_app)],check=True,capture_output=True)
    app.rename(retired)
    try:next_app.rename(app)
    except BaseException:retired.rename(app);raise
    shutil.rmtree(retired)
    print('Launcher updated for its next opening. Running launcher/game, saved selections and runtime retained.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-asset-preparation'))
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Optimizations/Data')
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-assets-launcher.app'))
    p.add_argument('--report',type=Path,default=ROOT/'verification-local/asset-preparation/report.json')
    p.add_argument('--restore',type=Path)
    p.add_argument('--launcher-only',action='store_true')
    a=p.parse_args()
    if a.restore:restore(a.restore)
    elif a.launcher_only:refresh_launcher(a.work,a.app,a.launcher)
    else:install(a.work,a.app,a.data,a.launcher,a.report)
