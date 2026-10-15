#!/usr/bin/env python3
"""Freeze APFS inputs and launch isolated alternating gameplay comparisons."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

GAME = Path('Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101')
CACHES = [Path('Prefix/drive_c/graphics-patch-cache'), GAME/'Bin/WizardGraphicalClient.dxvk-cache']
FROZEN = CACHES + [GAME/'Data', GAME/'Data:CRC', GAME/'Bin/config.xml', GAME/'Bin/preferences.xml']
ROUTE = 'Ravenwood → Commons → Pet Pavilion → Commons'
ORDERS = {1: ('baseline','candidate'), 2: ('candidate','baseline'), 3: ('baseline','candidate')}

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def require_closed():
    # Inspect executable names only, never command lines containing session keys.
    names = subprocess.check_output(['ps', '-axo', 'comm='], text=True).lower().replace('\\', '/')
    for name in ('wizardgraphicalclient.exe', 'wizardlauncher.exe', 'wizard101.exe', 'wizard101native'):
        if any(line.strip().rsplit('/', 1)[-1] == name for line in names.splitlines()):
            raise RuntimeError('Exit all Wizard101 games/launchers normally before preparing or restarting a comparison.')

def safe_work(path):
    path = Path(path).absolute()
    if path != path.resolve() or not (path/'comparison.json').is_file():
        raise RuntimeError('Use the comparison folder created by prepare.')
    meta = json.loads((path/'comparison.json').read_text())
    if meta.get('source') == str(path/'Data') or not (path/'Data'/GAME/'Bin/WizardGraphicalClient.exe').is_file():
        raise RuntimeError('Incomplete or unsafe comparison folder.')
    return path

def clone(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or destination.is_symlink(): raise RuntimeError('Frozen inputs cannot use symlinks.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cp', '-cR', str(source), str(destination)], check=True)

def contained(path, data):
    if data.resolve() not in path.resolve().parents:
        raise RuntimeError('Frozen input leaves the isolated data folder: '+str(path))

def prepare(source, work, app):
    require_closed()
    source, work, app = map(lambda p:Path(p).absolute(), (source, work, app))
    if source != source.resolve() or work != work.resolve() or work.exists():
        raise RuntimeError('Use a new comparison folder and ordinary absolute data paths.')
    if source in work.parents or work in source.parents or source == work:
        raise RuntimeError('Comparison data must be separate from the working installation.')
    if not (source/GAME/'Bin/WizardGraphicalClient.exe').is_file():
        raise RuntimeError('The source must be a complete standalone data folder.')
    renderer = app/'Contents/Resources/Renderer/d3d9.dll'
    expected = (renderer.parent/'d3d9.sha256').read_text().strip()
    if sha(renderer) != expected: raise RuntimeError('Candidate renderer integrity check failed.')
    work.mkdir(parents=True)
    clone(source, work/'Data')
    shutil.copy2(renderer, work/'Data'/GAME/'Bin/d3d9.dll')
    metadata = {'source':str(source), 'renderer_sha256':expected, 'working_installation_modified':False,
                'route':ROUTE, 'movement_window_seconds':30, 'launches':[]}
    build = renderer.parent/'capture-build.json'
    if build.exists(): metadata['capture_build'] = json.loads(build.read_text())
    performance = renderer.parent/'performance-build.json'
    if performance.exists(): metadata['performance_build'] = json.loads(performance.read_text())
    cpu = renderer.parent/'cpu-build.json'
    if cpu.exists(): metadata['cpu_build'] = json.loads(cpu.read_text())
    rendering = renderer.parent/'rendering-build.json'
    if rendering.exists(): metadata['rendering_build'] = json.loads(rendering.read_text())
    workload = renderer.parent/'workload-build.json'
    if workload.exists(): metadata['workload_build'] = json.loads(workload.read_text())
    (work/'comparison.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(work/'Data', flush=True)

def frozen_roots(data):
    roots = list(FROZEN)
    # Include tracking files located outside the archive directories too.
    for p in sorted((data/GAME).rglob('*.utd')):
        relative = p.relative_to(data)
        if not any(relative == root or root in relative.parents for root in roots): roots.append(relative)
    return roots

def inventory(data, roots):
    files = {}
    for relative in roots:
        source = data/relative
        contained(source, data)
        if source.is_symlink(): raise RuntimeError('Frozen inputs cannot use symlinks.')
        if not source.exists(): continue
        for p in ([source] if source.is_file() else sorted(source.rglob('*'))):
            if p.is_symlink(): raise RuntimeError('Frozen inputs cannot contain symlinks.')
            if p.is_file(): files[str(p.relative_to(data))] = {'sha256':sha(p), 'size':p.stat().st_size,
                                                             'mode':stat.S_IMODE(p.stat().st_mode)}
    return files

def inventory_hash(files):
    # Paths, sizes and content are included, permissions are restored separately.
    return hashlib.sha256(json.dumps({p:{k:v for k,v in item.items() if k!='mode'} for p,item in files.items()},
                                     sort_keys=True, separators=(',',':')).encode()).hexdigest()

def seed(work):
    require_closed(); work = safe_work(work)
    if (work/'Seed').exists(): raise RuntimeError('A seed already exists; use a new folder to change it.')
    data = work/'Data'; roots = frozen_roots(data)
    if not list((data/CACHES[0]).rglob('*.w101shaders')): raise RuntimeError('No learned shader catalog exists.')
    print('Hashing learned caches, archives, tracking files and settings…', flush=True)
    files = inventory(data, roots)
    with tempfile.TemporaryDirectory(prefix='seed-stage-', dir=work) as stage:
        target = Path(stage)/'Seed'; target.mkdir()
        for relative in roots:
            if (data/relative).exists(): clone(data/relative, target/relative)
        manifest = {'version':2, 'roots':list(map(str,roots)), 'files':files, 'seed_sha256':inventory_hash(files)}
        (target/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        target.replace(work/'Seed')
    for p in sorted((work/'Seed').rglob('*'), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    (work/'Seed').chmod(0o555)
    subprocess.run(['chflags','-R','uchg',str(work/'Seed')],check=True)
    print('Saved immutable APFS seed:', manifest['seed_sha256'], flush=True)
    return manifest

def validate_seed(work):
    path=work/'Seed'; manifest=json.loads((path/'manifest.json').read_text())
    if manifest.get('version') != 2: raise RuntimeError('Create a schema-2 seed including archives and tracking files.')
    if inventory_hash(manifest['files']) != manifest['seed_sha256']: raise RuntimeError('Seed manifest is damaged.')
    # Frozen flags + sizes are cheap; content is independently verified after
    # cloning at launch. No writable aliases are allowed in the seed.
    for p in [path,*path.rglob('*')]:
        if p.is_symlink() or p.stat().st_mode & 0o222 or not p.stat().st_flags & stat.UF_IMMUTABLE:
            raise RuntimeError('The seed is no longer immutable: '+str(p))
    for relative,item in manifest['files'].items():
        if (path/relative).stat().st_size != item['size']: raise RuntimeError('Seed file size changed.')
    return manifest

def restore(work):
    manifest=validate_seed(work); data=work/'Data'
    roots=[Path(p) for p in manifest['roots']]
    # Remove newly-created tracking files outside roots as well.
    extra=[p.relative_to(data) for p in (data/GAME).rglob('*.utd')
           if not any(root == p.relative_to(data) or root in p.relative_to(data).parents for root in roots)]
    for relative in roots+extra:
        dest=data/relative
        contained(dest, data)
        if dest.is_symlink(): raise RuntimeError('Refusing to reset a symlinked input.')
        if dest.is_dir(): shutil.rmtree(dest)
        elif dest.exists(): dest.unlink()
        source=work/'Seed'/relative
        if source.exists():
            clone(source,dest)
            subprocess.run(['chflags','-R','nouchg',str(dest)],check=True)
            for p in ([dest] if dest.is_file() else [dest,*dest.rglob('*')]):
                p.chmod(0o755 if p.is_dir() else manifest['files'][str(p.relative_to(data))]['mode'])
    print('Verifying restored content…', flush=True)
    files=inventory(data,roots)
    if inventory_hash(files) != manifest['seed_sha256']: raise RuntimeError('Restored archives/cache/tracking/settings differ from seed.')
    return manifest['seed_sha256']

def expected_labels():
    return [f'pair{i}-{mode}{suffix}' for i in (1,2,3) for mode in ORDERS[i] for suffix in ('','-restart')]+['persistence']

def launch(work, app, warmup, label, pipeline_opt=None, synchronous_submits='1', comparison=None, ordinary_play=False, cpu_opt='off', stutter_fix=None):
    require_closed(); work=safe_work(work)
    if ordinary_play and (comparison not in ('queue','cpu','rendering') or label != 'diagnostic'):
        raise RuntimeError('Ordinary-play trials use queue, cpu or rendering with the diagnostic label; scored labels remain controlled.')
    if stutter_fix not in (None,'0','1'):
        raise RuntimeError('Use rendering switch 0 or 1.')
    if comparison!='rendering' and stutter_fix not in (None,'0'):
        raise RuntimeError('Use a separate rendering comparison for the stutter fix.')
    if cpu_opt not in ('off','constants','locking','both'):
        raise RuntimeError('Use CPU mode off, constants, locking or both.')
    if synchronous_submits not in ('0','1'):
        raise RuntimeError('Use submission mode 0 or 1.')
    if not re.fullmatch(r'(pair[1-3]-(baseline|candidate)(-restart)?|screen-(baseline|candidate)|learning|diagnostic|trace-cpu|trace-gpu|persistence)',label):
        raise RuntimeError('Use a route-learning, diagnostic/trace, paired-run or persistence label.')
    data=work/'Data'; app=Path(app).resolve(); meta=json.loads((work/'comparison.json').read_text())
    dll=data/GAME/'Bin/d3d9.dll'; bundled=app/'Contents/Resources/Renderer/d3d9.dll'
    if sha(dll) != meta['renderer_sha256'] or sha(bundled) != meta['renderer_sha256']:
        raise RuntimeError('The app or isolated comparison renderer changed.')
    screen=label.startswith('screen-')
    performance=comparison is not None
    if performance:
        build_key={'cpu':'cpu_build','rendering':'rendering_build'}.get(comparison,'performance_build')
        if comparison not in ('pipeline','queue','cpu','rendering') or not meta.get(build_key):
            raise RuntimeError('Use a separate performance app and comparison type.')
        if warmup!='on' or pipeline_opt not in ('off','replay','lookup','both'):
            raise RuntimeError('Performance runs require equal enabled warm-up and an explicit pipeline mode.')
        candidate='candidate' in label or label=='persistence'
        if comparison=='rendering':
            if pipeline_opt!='off' or cpu_opt!='off' or synchronous_submits!='1':
                raise RuntimeError('Rendering runs keep CPU and pipeline modes off and synchronous submissions 1.')
            if stutter_fix not in ('0','1') or (not ordinary_play and stutter_fix!=('1' if candidate else '0')):
                raise RuntimeError('Rendering comparison requires switch 0 baseline and 1 candidate.')
        if comparison=='cpu':
            if pipeline_opt!='off' or synchronous_submits!='1':
                raise RuntimeError('CPU runs keep pipeline modes off and synchronous submissions 1.')
            if not ordinary_play and (cpu_opt=='off')==candidate:
                raise RuntimeError('CPU comparison requires off baseline and optimized candidate.')
        elif cpu_opt!='off':
            raise RuntimeError('Use a separate CPU comparison for CPU optimizations.')
        if comparison=='pipeline' and (synchronous_submits!='1' or (pipeline_opt=='off')==candidate):
            raise RuntimeError('Pipeline comparison requires off baseline, optimized candidate, synchronous submissions.')
        if comparison=='queue' and (pipeline_opt!='off' or (not ordinary_play and synchronous_submits!=('0' if candidate else '1'))):
            raise RuntimeError('Queue comparison requires pipeline optimizations off and submission modes 1 then 0.')
        if meta.get('performance_comparison',comparison)!=comparison:
            raise RuntimeError('Use a fresh comparison folder to change the experiment.')
        meta['performance_comparison']=comparison
    elif screen or pipeline_opt is not None or synchronous_submits!='1' or cpu_opt!='off':
        raise RuntimeError('Specify a performance comparison for screening or pipeline/submission changes.')
    scored=label.startswith('pair') or screen; persistence=label=='persistence'
    seed_hash=None
    launches=meta.get('launches',[])
    if scored or persistence:
        history=[entry['label'] for entry in launches if entry['label'].startswith(('pair','screen-')) or entry['label']=='persistence']
        labels=(['screen-baseline','screen-candidate'] if performance else [])+expected_labels()
        if history and label == history[-1]:
            # An aborted login or handoff check can be retried after normal exit.
            launches = [entry for entry in launches if entry['label'] != label]
            history = history[:-1]
        if len(history)>=len(labels) or label!=labels[len(history)]:
            raise RuntimeError('Next controlled launch must be '+(labels[len(history)] if len(history)<len(labels) else 'in a fresh comparison'))
        if performance and label.startswith('pair') and meta.get('screen_improved') is not True:
            raise RuntimeError('Evaluate and record an improved screening pair before expanding to three pairs.')
        expected_mode= 'on' if performance or 'candidate' in label or persistence else 'off'
        if warmup!=expected_mode: raise RuntimeError('Wrong warm-up mode for '+label)
        seed_hash=validate_seed(work)['seed_sha256'] if persistence else restore(work)
    if warmup=='on' and meta.get('diagnostic_only'): raise RuntimeError('This old build has no warm-up.')
    current=inventory(data, frozen_roots(data))
    launch_meta={'label':label,'seed_sha256':seed_hash,'starting_inputs_sha256':inventory_hash(current),
                 'seed_restored':scored,'heavyweight_trace':label.startswith('trace-'),'route':meta.get('route',ROUTE)}
    if ordinary_play:
        launch_meta.update(ordinary_play_trial=True, eligible_for_rollout=False, route='ordinary play',
                           pipeline_optimization=pipeline_opt, synchronous_queue_submits=synchronous_submits)
        launch_meta['cpu_optimization']=cpu_opt
        launch_meta['stutter_fix']=stutter_fix=='1'
    if persistence:
        launch_meta['persistence_restart']=True
    env=dict(os.environ,W101_DATA_ROOT=str(data),W101_CAPTURE_TIMING='1',W101_WARMUP_SELECTION='1' if warmup=='on' else '0',
             W101_COMPARISON_LABEL=label,W101_COMPARISON_METADATA=json.dumps(launch_meta,separators=(',',':')))
    env['DXVK_W101_PIPELINE_OPT']=pipeline_opt or 'off'
    env['DXVK_W101_CPU_OPT']=cpu_opt
    env['DXVK_W101_STUTTER_FIX']=stutter_fix or '0'
    env['MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS']=synchronous_submits
    subprocess.Popen([str(app/'Contents/MacOS/Wizard101Native')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    launches.append(launch_meta); meta['launches']=launches
    (work/'comparison.json').write_text(json.dumps(meta,indent=2)+'\n')
    if ordinary_play:
        print('Opened ordinary-play trial:',comparison,label,'warm-up',warmup,'CPU mode',cpu_opt,'submissions',synchronous_submits,flush=True)
    else:
        print('Opened isolated comparison:',label,'warm-up',warmup,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('prepare'); a.add_argument('source',type=Path); a.add_argument('work',type=Path); a.add_argument('app',type=Path)
    for name in ('seed','verify-seed'): a=commands.add_parser(name); a.add_argument('work',type=Path)
    a=commands.add_parser('launch'); a.add_argument('work',type=Path); a.add_argument('app',type=Path)
    a.add_argument('--warmup',choices=('off','on'),default='off'); a.add_argument('--label',required=True)
    a.add_argument('--pipeline-opt',choices=('off','replay','lookup','both'))
    a.add_argument('--synchronous-submits',choices=('0','1'),default='1')
    a.add_argument('--comparison',choices=('pipeline','queue','cpu','rendering'))
    a.add_argument('--stutter-fix',choices=('0','1'))
    a.add_argument('--cpu-opt',choices=('off','constants','locking','both'),default='off')
    a.add_argument('--ordinary-play',action='store_true',help='Unscored queue trial with the diagnostic label; preserves learned inputs.')
    a=commands.add_parser('record-screen'); a.add_argument('work',type=Path); a.add_argument('manifest',type=Path)
    args=p.parse_args()
    if args.command=='prepare': prepare(args.source,args.work,args.app)
    elif args.command=='seed': seed(args.work)
    elif args.command=='verify-seed': print(validate_seed(safe_work(args.work))['seed_sha256'])
    elif args.command=='record-screen':
        from compare_performance import compare_performance
        work=safe_work(args.work); meta=json.loads((work/'comparison.json').read_text())
        result=compare_performance(json.loads(args.manifest.read_text()),args.manifest.parent,screen=True)
        if result['comparison']!=meta.get('performance_comparison'): raise RuntimeError('Screen used a different experiment.')
        captures=[sample['capture'] for pair in json.loads(args.manifest.read_text())['pairs'] for mode in ('baseline','candidate') for sample in pair[mode].values()]
        if any((work/'Data/Prefix/drive_c/NativeLogs').resolve() not in (args.manifest.parent/path).resolve().parents for path in captures):
            raise RuntimeError('Screen captures must belong to this isolated comparison.')
        meta['screen_improved']=result['screen_improved']; meta['screen_result']={k:v for k,v in result.items() if k!='pairs'}
        (work/'comparison.json').write_text(json.dumps(meta,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    else: launch(args.work,args.app,args.warmup,args.label,args.pipeline_opt,args.synchronous_submits,args.comparison,args.ordinary_play,args.cpu_opt,args.stutter_fix)
