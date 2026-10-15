#!/usr/bin/env python3
"""Install only a verified draw-layout experiment into the same app; preserve rollback."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
from build_runtime import ROOT, sha
from build_workload import clone
from install_asset_preparation import idle
from verify_draw_layout import score

def inputs(app,data):
    resources=app/'Contents/Resources'
    game=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin'
    cache=data/'Prefix/drive_c/graphics-patch-cache/Wizard101/known-assets.w101assets'
    files=[app/'Contents/MacOS/Wizard101Native',app/'Contents/Info.plist',resources/'Renderer/d3d9.dll',game/'d3d9.dll',cache]
    files += [game/n for n in ['WizardGraphicalClient.exe','zlib1v142x64.dll','d3dx9_43.dll','w101decompress.dll','config.xml','preferences.xml','WizardGraphicalClient.dxvk-cache']]
    return game,cache,{str(p):sha(p) if p.exists() else None for p in files}

def snapshot(app,data,destination):
    idle();app,data,destination=map(lambda p:Path(p).resolve(),(app,data,destination))
    game,cache,fingerprints=inputs(app,data)
    destination.mkdir(parents=True,exist_ok=False)
    clone(app,destination/'Wizard101 Optimizations.app')
    shutil.copy2(game/'d3d9.dll',destination/'game-d3d9.dll')
    if cache.exists():shutil.copy2(cache,destination/'known-assets.w101assets')
    manifest={'app':str(app),'game_renderer':str(game/'d3d9.dll'),'learned_cache':str(cache),
              'backup':str(destination),'baseline_inputs':fingerprints,'installed_renderer_sha256':None,'installed_launcher_sha256':None}
    (destination/'rollback.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

def require_verified(work,launcher,report):
    metadata=json.loads((work/'draw-layout-build.json').read_text());evidence=json.loads(report.read_text())
    dll=work/'build-renderer/src/d3d9/d3d9.dll'
    revision=metadata.get('revision',1)
    scoring=score
    if revision==2:
        from verify_draw_layout_v2 import score as scoring
    if not evidence.get('install_qualified') or not scoring(evidence['benchmark_pairs'])['gate_passed']:
        raise RuntimeError('Draw-layout performance gate failed; installed app, renderer, selections and learned cache remain unchanged.')
    required={'structural_collision_eviction_allocation_budget_shutdown','launcher_64_options_both_fps_profiling','installed_app_unchanged',
              *[prefix+mode for prefix in ('','ex-') for mode in ('baseline','off','on','collision','allocation')]}
    if revision==2:
        required|={'texture_preparation_off','texture_preparation_on','installed_game_app_learned_cache_unchanged'}
        if evidence.get('revision')!=2:raise RuntimeError('Wrong revision verification')
        if len(evidence.get('components',[]))!=5 or any(r['cpu_ms']<2000 for r in evidence['components']):
            raise RuntimeError('Component cost measurements missing')
        for mode in ('off','on'):
            asset_report=report.parent/('assets-'+mode)/'report.json'
            if not asset_report.exists() or sha(asset_report)!=evidence['checks'].get('texture_preparation_'+mode,{}).get('report_sha256'):
                raise RuntimeError('Texture compatibility evidence missing or changed')
            assets=json.loads(asset_report.read_text())
            if assets.get('renderer_sha256')!=sha(dll) or not all(bool(v) and (not isinstance(v,dict) or v.get('passed',True)) for v in assets['checks'].values()):
                raise RuntimeError('Texture compatibility failed')
    if not required.issubset(evidence['checks']):raise RuntimeError('Required verification is missing')
    if not all(bool(v) and (not isinstance(v,dict) or v.get('passed',True)) for v in evidence['checks'].values()):raise RuntimeError('Correctness verification failed')
    if metadata['renderer_sha256']!=sha(dll) or evidence['renderer_sha256']!=sha(dll):raise RuntimeError('Stale renderer verification')
    if sha(launcher/'Contents/MacOS/Wizard101Native')!=evidence['launcher_sha256']:raise RuntimeError('Stale launcher verification')
    for name,digest in (metadata['inputs']|evidence['verified_inputs']).items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Source changed after verification: '+name)
    return dll,metadata,evidence

def install(work,app,data,launcher,report):
    work,app,data,launcher,report=map(lambda p:Path(p).resolve(),(work,app,data,launcher,report))
    dll,metadata,evidence=require_verified(work,launcher,report);idle()
    resources=app/'Contents/Resources'
    if sha(resources/'Renderer/d3d9.dll')!=metadata['baseline_renderer_sha256']:raise RuntimeError('Installed baseline changed')
    for name,digest in evidence['runtime_inputs'].items():
        if sha(resources/'Runtime'/name)!=digest:raise RuntimeError('Verified runtime changed: '+name)
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!='org.wizard101native.combined':raise RuntimeError('Expected the same combined launcher')
    game,cache,before=inputs(app,data)
    if sha(game/'d3d9.dll')!=metadata['baseline_renderer_sha256']:raise RuntimeError('Game renderer differs from app baseline')
    backup=data.parent/'Rollback'/('draw-layout-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    manifest=snapshot(app,data,backup)
    stage=app.with_name('.Wizard101 Optimizations.draw-layout-stage.app');retired=app.with_name('.Wizard101 Optimizations.draw-layout-retired.app')
    if stage.exists() or retired.exists():raise RuntimeError('An earlier staged update needs attention')
    clone(app,stage)
    res=stage/'Contents/Resources';renderer=res/'Renderer'
    shutil.copy2(dll,renderer/'d3d9.dll');(renderer/'d3d9.sha256').write_text(sha(dll)+'\n')
    shutil.copy2(launcher/'Contents/MacOS/Wizard101Native',stage/'Contents/MacOS/Wizard101Native')
    info['W101ExperimentDefaults']['W101_DRAW_LAYOUT_CACHE']='0'
    (stage/'Contents/Info.plist').write_bytes(plistlib.dumps(info,sort_keys=False))
    metadata['verification_sha256']=sha(report)
    (renderer/'draw-layout-build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    for file in [renderer/'asset-preparation-build.json',renderer/'workload-performance-build.json',renderer/'combined-build.json',res/'Runtime/workload-performance-build.json']:
        meta=json.loads(file.read_text());meta['renderer_sha256']=sha(dll);meta['draw_layout_cache']=metadata
        if 'defaults' in meta:meta['defaults']['W101_DRAW_LAYOUT_CACHE']='0'
        file.write_text(json.dumps(meta,indent=2)+'\n')
    subprocess.run(['codesign','--force','--sign','-',str(stage)],check=True,capture_output=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(stage)],check=True,capture_output=True)
    preserved={p:d for p,d in before.items() if p not in {str(app/'Contents/MacOS/Wizard101Native'),str(app/'Contents/Info.plist'),str(resources/'Renderer/d3d9.dll'),str(game/'d3d9.dll')}}
    manifest.update(installed_renderer_sha256=sha(dll),installed_launcher_sha256=sha(launcher/'Contents/MacOS/Wizard101Native'),gameplay_accepted=False)
    (backup/'rollback.json').write_text(json.dumps(manifest,indent=2)+'\n')
    try:
        app.rename(retired);stage.rename(app)
        temporary=game/'d3d9.dll.draw-layout-stage';shutil.copy2(dll,temporary);temporary.replace(game/'d3d9.dll')
        if any((sha(Path(p)) if Path(p).exists() else None)!=d for p,d in preserved.items()):raise RuntimeError('Preserved game or cache input changed')
    except BaseException:
        if retired.exists():
            if app.exists():shutil.rmtree(app)
            retired.rename(app)
        shutil.copy2(backup/'game-d3d9.dll',game/'d3d9.dll');raise
    shutil.rmtree(retired)
    (work/'delivery.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2));return manifest

def restore(backup):
    idle();backup=Path(backup).resolve();manifest=json.loads((backup/'rollback.json').read_text())
    app=Path(manifest['app']);game=Path(manifest['game_renderer']);cache=Path(manifest['learned_cache'])
    if not manifest['installed_renderer_sha256']:raise RuntimeError('This snapshot has no installed update to restore')
    if sha(app/'Contents/Resources/Renderer/d3d9.dll')!=manifest['installed_renderer_sha256'] or sha(game)!=manifest['installed_renderer_sha256'] or sha(app/'Contents/MacOS/Wizard101Native')!=manifest['installed_launcher_sha256']:raise RuntimeError('A later update exists; refusing to overwrite it')
    for file in [backup/'Wizard101 Optimizations.app/Contents/Resources/Renderer/d3d9.dll',backup/'game-d3d9.dll']:
        original=manifest['baseline_inputs'][str(game) if file.name=='game-d3d9.dll' else str(app/'Contents/Resources/Renderer/d3d9.dll')]
        if sha(file)!=original:raise RuntimeError('Rollback renderer is corrupt')
    if (backup/'known-assets.w101assets').exists() and sha(backup/'known-assets.w101assets')!=manifest['baseline_inputs'][str(cache)]:raise RuntimeError('Rollback texture cache is corrupt')
    stage=app.with_name('.Wizard101 Optimizations.draw-layout-restore.app');retired=app.with_name('.Wizard101 Optimizations.draw-layout-restore-retired.app')
    if stage.exists() or retired.exists():raise RuntimeError('Existing restoration needs attention')
    clone(backup/'Wizard101 Optimizations.app',stage)
    old_renderer=game.read_bytes();old_cache=cache.read_bytes() if cache.exists() else None
    app.rename(retired)
    try:
        stage.rename(app);shutil.copy2(backup/'game-d3d9.dll',game)
        if (backup/'known-assets.w101assets').exists():shutil.copy2(backup/'known-assets.w101assets',cache)
        else:cache.unlink(missing_ok=True)
    except BaseException:
        if app.exists():shutil.rmtree(app)
        retired.rename(app);game.write_bytes(old_renderer)
        if old_cache is not None:cache.write_bytes(old_cache)
        else:cache.unlink(missing_ok=True)
        raise
    shutil.rmtree(retired);print('Restored app, renderer and learned texture cache; saved selections retained.')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,default=Path('/private/tmp/w101-draw-layout'))
    p.add_argument('--app',type=Path,default=Path.home()/'Desktop/Wizard101 Optimizations.app')
    p.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/Wizard101 Optimizations/Data')
    p.add_argument('--launcher',type=Path,default=Path('/private/tmp/w101-layout-launcher.app'))
    p.add_argument('--report',type=Path,default=ROOT/'verification-local/draw-layout/report.json')
    p.add_argument('--snapshot',type=Path)
    p.add_argument('--restore',type=Path)
    a=p.parse_args()
    if a.restore:restore(a.restore)
    elif a.snapshot:print(json.dumps(snapshot(a.app,a.data,a.snapshot),indent=2))
    else:install(a.work,a.app,a.data,a.launcher,a.report)
