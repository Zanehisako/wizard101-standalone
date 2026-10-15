#!/usr/bin/env python3
"""Build the existing game-scoped D9VK patch using only pinned public inputs."""
import json
from pathlib import Path
import subprocess
from build_runtime import ROOT, WORK, LOCK, download, extract, sha, run, JOBS

def build(diagnostic_only=False, capture_diagnostic=False, performance_candidate=False, cpu_candidate=False, rendering_candidate=False):
    lock = json.loads(LOCK.read_text())
    capture_diagnostic = capture_diagnostic or performance_candidate or cpu_candidate or rendering_candidate
    name = 'rendering-d9vk' if rendering_candidate else ('cpu-d9vk' if cpu_candidate else ('performance-d9vk' if performance_candidate else ('capture-d9vk' if capture_diagnostic else ('diagnostic-d9vk' if diagnostic_only else 'd9vk'))))
    source = WORK / name
    output = WORK / ('build-' + name)
    pins = [('d9vk-f229921c1b7f14edeadeccff04a9e65d0a016148.tar.gz', source),
            ('SPIRV-Headers-0bcc624926a25a2a273d07877fd25a6ff5ba1cfb.tar.gz', source / 'include/spirv'),
            ('Vulkan-Headers-85c2334e92e215cce34e8e0ed8b2dce4700f4a50.tar.gz', source / 'include/vulkan')]
    for name, destination in pins:
        entry = lock[name]; archive = download(name, entry['url'], entry['sha256'])
        if not destination.exists() or not any(destination.iterdir()): extract(archive, destination, strip=True)
    patch = ROOT / 'renderer/wizard101.patch'
    rendering_stamp = source / '.rendering-applied.patch'
    if rendering_candidate and rendering_stamp.exists():
        run(['git', 'apply', '--reverse', str(rendering_stamp)], source, log='rendering-remove')
        rendering_stamp.unlink()
    cpu_stamp = source / '.cpu-applied.patch'
    if cpu_candidate and cpu_stamp.exists():
        run(['git', 'apply', '--reverse', str(cpu_stamp)], source, log='cpu-remove')
        cpu_stamp.unlink()
    performance_stamp = source / '.performance-applied.patch'
    if performance_candidate and performance_stamp.exists():
        run(['git', 'apply', '--reverse', str(performance_stamp)], source, log='performance-remove')
        performance_stamp.unlink()
    # This separate tree preserves the current warm-up implementation. Remove
    # its last instrumentation overlay before verifying translation inputs.
    capture_stamp = source / '.capture-applied.patch'
    if capture_diagnostic and capture_stamp.exists():
        run(['git', 'apply', '--reverse', str(capture_stamp)], source, log='capture-remove')
        capture_stamp.unlink()
    overlay = ROOT / 'renderer' / ('diagnostic.patch' if diagnostic_only else 'warmup.patch')
    overlay_applied = overlay.is_file() and subprocess.run(
        ['git', 'apply', '--reverse', '--check', str(overlay)], cwd=source, capture_output=True).returncode == 0
    # The overlay changes base-patch contexts; detect the complete overlay first
    # so a second build never attempts to apply the base patch over itself.
    if not overlay_applied:
        if subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=source, capture_output=True).returncode:
            run(['git', 'apply', str(patch)], source, log='d9vk-patch')
        if overlay.is_file(): run(['git', 'apply', str(overlay)], source, log='d9vk-overlay-patch')
    # The patch includes its translation-source fingerprint; verify it before compiling.
    import hashlib
    src = source / 'src'
    files = list((src/'dxso').rglob('*')) + list((src/'spirv').rglob('*')) + list((src/'dxvk').glob('dxvk_shader*')) + list((src/'d3d9').glob('d3d9_shader*'))
    fingerprint = hashlib.sha256()
    for f in sorted(set(files)):
        if f.is_file(): fingerprint.update(str(f.relative_to(src)).encode()); fingerprint.update(f.read_bytes())
    expected = '#pragma once\n#define W101_SHADER_REVISION "'+fingerprint.hexdigest()+'"\n'
    if (src/'util/util_shader_revision.h').read_text() != expected: raise RuntimeError('Renderer translation source fingerprint changed')
    if capture_diagnostic:
        capture = ROOT / 'renderer/capture.patch'
        run(['git', 'apply', str(capture)], source, log='capture-overlay')
        capture_stamp.write_bytes(capture.read_bytes())
    capture_fingerprint = hashlib.sha256()
    for f in sorted(set(files)):
        if f.is_file(): capture_fingerprint.update(str(f.relative_to(src)).encode()); capture_fingerprint.update(f.read_bytes())
    if performance_candidate:
        performance = ROOT / 'renderer/performance.patch'
        run(['git', 'apply', str(performance)], source, log='performance-overlay')
        performance_stamp.write_bytes(performance.read_bytes())
    if cpu_candidate:
        cpu = ROOT / 'renderer/cpu.patch'
        run(['git', 'apply', str(cpu)], source, log='cpu-overlay')
        cpu_stamp.write_bytes(cpu.read_bytes())
    if rendering_candidate:
        rendering = ROOT / 'renderer/stutter.patch'
        run(['git', 'apply', str(rendering)], source, log='rendering-overlay')
        rendering_stamp.write_bytes(rendering.read_bytes())
    # Overlays must not change shader translation or cache compatibility.
    after = hashlib.sha256()
    for f in sorted(set(files)):
        if f.is_file(): after.update(str(f.relative_to(src)).encode()); after.update(f.read_bytes())
    if after.hexdigest() != capture_fingerprint.hexdigest(): raise RuntimeError('Optimization overlay changed shader translation')
    if not (output / 'build.ninja').exists():
        run(['meson', 'setup', str(output), str(source), '--cross-file', str(source / 'build-win64.txt'), '--buildtype', 'release', '-Denable_d3d9=true', '-Denable_dxgi=false', '-Denable_d3d10=false', '-Denable_d3d11=false'], log='d9vk-configure')
    run(['ninja', '-C', str(output), '-j', JOBS], log='d9vk')
    dll = output / 'src/d3d9/d3d9.dll'
    print('Renderer SHA256:', sha(dll))
    if capture_diagnostic:
        (dll.parent/'capture-build.json').write_text(json.dumps({
            'capture_schema': 2, 'renderer_sha256': sha(dll),
            'translation_source_sha256': fingerprint.hexdigest(),
            'base_patch_sha256': sha(patch), 'warmup_patch_sha256': sha(overlay),
            'capture_patch_sha256': sha(capture),
            'rendering_and_warmup_changes': performance_candidate or cpu_candidate or rendering_candidate,
        }, indent=2)+'\n')
    if performance_candidate:
        (dll.parent/'performance-build.json').write_text(json.dumps({
            'renderer_sha256': sha(dll), 'translation_source_sha256': fingerprint.hexdigest(),
            'base_patch_sha256': sha(patch), 'warmup_patch_sha256': sha(overlay),
            'capture_patch_sha256': sha(capture), 'performance_patch_sha256': sha(performance),
            'modes': ['off', 'replay', 'lookup', 'both'], 'default_mode': 'off',
        }, indent=2)+'\n')
    if cpu_candidate:
        (dll.parent/'cpu-build.json').write_text(json.dumps({
            'renderer_sha256': sha(dll), 'translation_source_sha256': fingerprint.hexdigest(),
            'base_patch_sha256': sha(patch), 'warmup_patch_sha256': sha(overlay),
            'capture_patch_sha256': sha(capture), 'cpu_patch_sha256': sha(cpu),
            'modes': ['off', 'constants', 'locking', 'both'], 'default_mode': 'off',
            'cache_formats_changed': False, 'driver_compilation_lock_retained': True,
        }, indent=2)+'\n')
    if rendering_candidate:
        (dll.parent/'rendering-build.json').write_text(json.dumps({
            'renderer_sha256': sha(dll), 'translation_source_sha256': fingerprint.hexdigest(),
            'base_patch_sha256': sha(patch), 'warmup_patch_sha256': sha(overlay),
            'capture_patch_sha256': sha(capture), 'stutter_patch_sha256': sha(rendering),
            'switch': 'DXVK_W101_STUTTER_FIX', 'modes': ['0', '1'], 'default_mode': '0',
            'cache_formats_changed': False, 'driver_locks_retained': True,
            'cpu_optimizations': 'off', 'pipeline_optimizations': 'off',
            'maintenance': 'normal shutdown when enabled',
        }, indent=2)+'\n')
    return dll

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--diagnostic-only', action='store_true', help='Keep working rendering and shader translation; add profiling only')
    mode.add_argument('--capture-diagnostic', action='store_true', help='Separate schema-2 capture build retaining current warm-up and rendering')
    mode.add_argument('--performance-candidate', action='store_true', help='Separate renderer with opt-in replay and lookup optimizations')
    mode.add_argument('--cpu-candidate', action='store_true', help='Separate renderer with opt-in constant and recursive-lock optimizations')
    mode.add_argument('--rendering-candidate', action='store_true', help='Separate renderer with opt-in per-state compilation and shutdown-only cache maintenance')
    args = parser.parse_args()
    build(args.diagnostic_only, args.capture_diagnostic, args.performance_candidate, args.cpu_candidate, args.rendering_candidate)
