#!/usr/bin/env python3
"""Run synthetic GPU and cursor probes in a disposable, bundle-only prefix."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def cursor_file(path):
    # Synthetic 32x32 BGRA cursor: green/red opaque top, transparent bottom.
    pixels = b''.join(struct.pack('<I', 0 if y < 16 else (0xff00ff00 if x < 16 else 0xffff0000))
                      for y in range(32) for x in range(32))
    mask = b''.join(b'\xff' * 4 if y < 16 else b'\0' * 4 for y in range(32))
    bitmap = struct.pack('<IiiHHIIiiII', 40, 32, 64, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0) + pixels + mask
    path.write_bytes(struct.pack('<HHH', 0, 2, 1) + struct.pack('<BBBBHHII', 32, 32, 0, 0, 7, 11, len(bitmap), 22) + bitmap)


def verify(app, keep=None, pipeline_opt='off', synchronous_submits='1', cpu_opt='off', stutter_fix='0', prefix_seed=None):
    app = Path(app).resolve(); resources = app / 'Contents/Resources'
    runtime = resources / 'Runtime'; wine = runtime / 'bin/wine'
    if not wine.is_file(): raise RuntimeError('Complete runtime required')
    if not shutil.which('x86_64-w64-mingw32-g++'): raise RuntimeError('Install mingw-w64 to compile synthetic verification probes')
    with tempfile.TemporaryDirectory(prefix='w101-isolated-runtime-') as temp:
        work = Path(temp); prefix = work / 'Prefix'; probes = work / 'probes'; probes.mkdir()
        if prefix_seed:
            # APFS clone keeps the probe prefix independent without duplicating
            # hundreds of MiB of identical Wine system DLLs on a nearly full disk.
            from build_workload import clone
            seed = Path(prefix_seed).resolve()
            if not (seed / 'system.reg').is_file(): raise ValueError('Invalid prefix seed')
            clone(seed, prefix)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CX_', 'CROSSOVER', 'DYLD_', 'WINE', 'VK_', 'DXVK_', 'D9VK_'))}
        env.update(PATH=str(runtime / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin', WINEPREFIX=str(prefix),
                   WINEARCH='win64', WINEDEBUG='-all', WINEMSYNC='1', WINEDLLOVERRIDES='d3d9=n;winemenubuilder.exe=d;mscoree=d;mshtml=d',
                   WINEDLLPATH=str(runtime / 'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=str(runtime / 'lib') + ':/usr/lib',
                   VK_ICD_FILENAMES=str(runtime / 'share/vulkan/icd.d/MoltenVK_icd.json'),
                   MVK_CONFIG_RESUME_LOST_DEVICE='1', DXVK_FRAME_RATE='60', DXVK_W101_LIMITER='legacy',
                   DXVK_W101_SHADER_CACHE='0', DXVK_W101_PIPELINE_CACHE='0', DXVK_LOG_LEVEL='info', DXVK_LOG_PATH=str(probes))
        env['DXVK_W101_PIPELINE_OPT'] = pipeline_opt
        env['DXVK_W101_CPU_OPT'] = cpu_opt
        env['DXVK_W101_STUTTER_FIX'] = stutter_fix
        env['DXVK_ASYNC'] = '0'
        env['MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS'] = synchronous_submits
        def run(command, name, timeout=180, cwd=None):
            log = work / (name + '.log')
            with log.open('w') as output:
                result = subprocess.run(command, env=env, cwd=cwd or work, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            text = log.read_text(errors='replace')
            if result.returncode: raise RuntimeError(f'{name} failed: ' + text[-4000:])
            return text
        try:
            version = run([str(wine), '--version'], 'wine-version').strip()
            if not prefix_seed:
                run([str(wine), 'wineboot.exe', '-u'], 'wineboot')
            run([str(wine), 'cmd.exe', '/c', 'ver'], 'cmd')
            for source, name in [('d3d9_probe.cpp', 'render.exe'), ('sprite_probe.cpp', 'sprites.exe'), ('cursor_probe.cpp', 'WizardGraphicalClient.exe')]:
                subprocess.run(['x86_64-w64-mingw32-g++', '-O2', '-static', str(ROOT / 'tests' / source),
                                '-ld3d9', '-lgdi32', '-o', str(probes / name)], check=True)
            shutil.copy2(resources / 'Renderer/d3d9.dll', probes)
            cursor_file(probes / 'test.cur')
            render = run([str(wine), str(probes / 'render.exe'), '--uploads'], 'render', cwd=probes)
            fullscreen = run([str(wine), str(probes / 'render.exe'), '--fullscreen'], 'fullscreen', cwd=probes)
            sprites = run([str(wine), str(probes / 'sprites.exe')], 'sprites', cwd=probes)
            cursor = run([str(wine), str(probes / 'WizardGraphicalClient.exe'), '64'], 'cursor', cwd=probes)
            if 'PASS all checks' not in render or 'PASS synthetic HUD' not in sprites or 'PASS cursor hook' not in cursor: raise RuntimeError('Synthetic probes did not finish')
            if 'PASS fullscreen/windowed transition' not in fullscreen: raise RuntimeError('Fullscreen transition probe did not finish')
            report = {'runtime_verified': True, 'wine_version': version, 'isolated_prefix': True,
                      'pipeline_optimization': pipeline_opt,
                      'cpu_optimization': cpu_opt,
                      'stutter_fix': stutter_fix,
                      'synchronous_queue_submits': synchronous_submits,
                      'gpu_render_readback': True, 'six_texture_formats': True, 'upload_rewrite_readbacks': 192,
                      'cursor_size': 64, 'cursor_hotspot_transparency': True, 'synthetic_only': True,
                      'fullscreen_windowed_transitions': True,
                      'synthetic_hud_readbacks': 1536,
                      'real_login_verified': False, 'gameplay_performance_verified': False}
            (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2)); return report
        finally:
            # This server belongs to our temporary prefix, never the user's game.
            subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=15)
            if keep:
                keep = Path(keep); keep.mkdir(parents=True, exist_ok=True)
                for log in work.glob('*.log'): shutil.copy2(log, keep)
                for log in probes.glob('*.log'): shutil.copy2(log, keep)
                if (work / 'report.json').exists(): shutil.copy2(work / 'report.json', keep)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('app', type=Path); p.add_argument('--keep-logs', type=Path)
    p.add_argument('--pipeline-opt', choices=('off','replay','lookup','both'), default='off')
    p.add_argument('--synchronous-submits', choices=('0','1'), default='1')
    p.add_argument('--cpu-opt', choices=('off','constants','locking','both'), default='off')
    p.add_argument('--stutter-fix', choices=('0','1'), default='0')
    p.add_argument('--prefix-seed', type=Path, help='Clone this quiescent prefix into the disposable probe directory')
    args = p.parse_args(); verify(args.app, args.keep_logs, args.pipeline_opt, args.synchronous_submits, args.cpu_opt, args.stutter_fix, args.prefix_seed)
