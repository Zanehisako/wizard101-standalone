#!/usr/bin/env python3
"""Export a new, allowlisted repository with no private history or game assets."""
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
FILES = ['LICENSE', 'README.md', 'RELEASE-GATES.md', 'sources.lock.json', 'build.py', 'build_app.py', 'build_runtime.py', 'build_renderer.py', 'build_moltenvk.py', 'export_clean.py', 'audit_bundle.py', 'verify_runtime.py', 'verify_warmup.py', 'verify_learned_warmup.py', 'verify_profile.py', 'prepare_comparison.py', 'profile_report.py', 'compare_first_use.py', 'FIRST-USE.md']
DIRECTORIES = ['launcher', 'renderer', 'tests', 'licenses']
FILES += ['capture_trace.py', 'annotate_window.py', 'diagnose_hitches.py', 'thread_map.py', 'STUTTER-DIAGNOSTICS.md']
FILES += ['compare_performance.py', 'verify_pipeline_opt.py', 'PERFORMANCE.md']
FILES += ['verify_cpu_opt.py', 'CPU-PERFORMANCE.md']
FILES += ['verify_rendering.py', 'RENDERING-PERFORMANCE.md']
FILES += ['build_workload.py', 'verify_workload.py', 'workload_report.py', 'WORKLOAD-DIAGNOSTICS.md']
DIRECTORIES += ['workload']
FILES += ['build_workload_performance.py', 'verify_workload_performance.py', 'WORKLOAD-PERFORMANCE.md']
DIRECTORIES += ['performance']
FILES += ['build_decompression.py','verify_decompression.py','build_wait_queues.py','verify_wait_queues.py',
          'build_native_decode.py','verify_native_decode.py','package_experiment.py','STUTTER-EXPERIMENTS.md','STUTTER-EXPERIMENTS-RESULTS.md']
FILES += ['build_combined.py','verify_combined.py','COMBINED-OPTIMIZATIONS.md']
FILES += ['build_asset_preparation.py','verify_asset_preparation.py','install_asset_preparation.py','ASSET-PREPARATION.md']
FILES += ['build_draw_layout.py','verify_draw_layout.py','install_draw_layout.py','DRAW-LAYOUT-CACHE.md']
FILES += ['build_draw_layout_v2.py','verify_draw_layout_v2.py','measure_draw_layout_costs.py','DRAW-LAYOUT-CACHE-V2.md']
FILES += ['build_draw_layout_direct.py','prepare_draw_layout_direct.py','verify_draw_layout_direct.py','install_draw_layout_direct.py','DRAW-LAYOUT-DIRECT.md']
DIRECTORIES += ['decompression']
FILES += ['game_context.py', 'verify_game_context.py', 'score_game_repair.py',
          'build_game_repair.py', 'verify_game_repair.py', 'package_game_repair.py',
          'GAME-SIDE-REPAIR.md']
DIRECTORIES += ['game']
FILES += ['build_metal_archive.py', 'verify_metal_archive.py', 'package_metal_archive.py', 'METAL-ARCHIVE.md',
          'build_arrival.py', 'build_arrival_metal.py', 'build_arrival_launcher.py', 'package_arrival.py',
          'verify_arrival.py', 'verify_arrival_learning.py', 'verify_arrival_decompression.py', 'verify_arrival_metal.py',
          'ARRIVAL-CANDIDATE.md', 'package_shipping.py', 'rebuild_shipping_wine.py', 'SHIPPING.md']
FILES += ['reduce_runtime.py', 'build_installer.py', 'publish_beta.py', 'live_checklist.py', 'COMMUNITY-BETA.md', 'BETA-QUALIFICATION.md']
FILES += ['ACCOUNTS.md', 'account_qualification.py', 'install_account_candidate.py', 'build_account_diagnostic.py']
DIRECTORIES += ['installer']
ALLOWED = {'.swift', '.c', '.h', '.cpp', '.mm', '.metal', '.vert', '.frag', '.comp', '.py', '.md', '.json', '.txt', '.patch', '.S'}
ALLOWED |= {'.html', '.svg'}

def export(destination):
    destination = Path(destination).resolve()
    if destination.exists(): raise RuntimeError('Use a new export directory')
    destination.mkdir(parents=True)
    for name in FILES: shutil.copy2(ROOT / name, destination / name)
    for name in DIRECTORIES:
        for source in sorted((ROOT / name).rglob('*')):
            if not source.is_file() or source.is_symlink() or '__pycache__' in source.parts: continue
            if source.suffix not in ALLOWED and source.name not in ['UPSTREAM-LICENSE', 'LICENSE', 'COPYING', 'NOTICE', 'AUTHORS']: raise RuntimeError(f'Unexpected export file: {source}')
            target = destination / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
    (destination / '.gitignore').write_text('/cache/\n/dist/\n/verification-local/\n/work/\n__pycache__/\n*.pyc\n*.w101shaders\n*.w101assets\n*.vkcache\n*.dxvk-cache\n*.dxso\n*.spv\n.DS_Store\n')
    subprocess.run(['git', 'init', '-b', 'main'], cwd=destination, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['git', 'add', '.'], cwd=destination, check=True)
    subprocess.run(['git', '-c', 'user.name=Wizard101 Native contributors', '-c', 'user.email=build@wizard101native.invalid', 'commit', '-m', 'Initial portable launcher and source-build runtime'], cwd=destination, check=True, stdout=subprocess.DEVNULL)
    return destination

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('destination'); args = p.parse_args(); print(export(args.destination))
