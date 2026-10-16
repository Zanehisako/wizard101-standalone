#!/usr/bin/env python3
"""Build a local arm64/x86_64 macOS app using Apple's installed Swift toolchain."""
from pathlib import Path
import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import tempfile
import hashlib
import json

PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT / "launcher"

def launcher_inputs():
    paths = [Path(__file__).resolve()] + sorted(p for p in ROOT.rglob('*') if p.is_file())
    return {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def build(output=None, runtime=None, renderer=None, development=False, data_root=None, capture_timing=False):
    inputs = launcher_inputs()
    output = Path(output).expanduser().resolve() if output else PROJECT / 'dist' / 'Wizard101 Native.app'
    output.parent.mkdir(parents=True, exist_ok=True)
    # Compile in a staging folder. Existing builds survive compilation failure.
    with tempfile.TemporaryDirectory(prefix='w101-native-build-', dir=output.parent) as temp:
        stage = Path(temp) / output.name
        macos = stage / 'Contents' / 'MacOS'
        resources = stage / 'Contents' / 'Resources'
        macos.mkdir(parents=True)
        resources.mkdir()
        swift = subprocess.check_output(['xcrun', '--find', 'swiftc'], text=True).strip()
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        sources = sorted((ROOT / 'Sources').glob('*.swift'))
        objects = []
        for source in [ROOT / 'Vendor/Twofish/twofish.c', ROOT / 'Vendor/CryptoBridge.c', ROOT / 'Vendor/GzipBridge.c', ROOT / 'Vendor/SteamBridge.c']:
            obj = Path(temp) / (source.stem + '.o')
            subprocess.run(['xcrun', 'clang', '-O2', '-target', f'{platform.machine()}-apple-macosx13.0', '-isysroot', sdk, '-c', str(source), '-o', str(obj)], check=True)
            objects.append(str(obj))
        command = [swift, '-sdk', sdk, '-target', f'{platform.machine()}-apple-macosx13.0',
                   '-swift-version', '5', '-O', '-module-cache-path', str(Path(temp) / 'module-cache'),
                   '-import-objc-header', str(ROOT / 'Vendor/CryptoBridge.h'), '-lz',
                   '-framework', 'Security', '-framework', 'Network', '-framework', 'AppKit', '-framework', 'SwiftUI', '-framework', 'Metal', '-framework', 'MetalKit',
                   *map(str, sources), *objects, '-o', str(macos / 'Wizard101Native')]
        env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='13.0')
        subprocess.run(command, env=env, check=True)
        shutil.copy2(ROOT / 'Resources' / 'Spiral.metal', resources)
        # LaunchServices offers Apple's Rosetta installation UI when opening
        # this Intel-only helper. No license is accepted on the user's behalf.
        helper = resources / 'Rosetta Setup.app'
        (helper / 'Contents/MacOS').mkdir(parents=True)
        helper_source = Path(temp) / 'rosetta.c'
        helper_source.write_text('int main(void) { return 0; }\n')
        subprocess.run(['xcrun', 'clang', '-target', 'x86_64-apple-macosx13.0', '-isysroot', sdk,
                        str(helper_source), '-o', str(helper / 'Contents/MacOS/RosettaSetup')], check=True)
        (helper / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'org.wizard101native.rosetta-setup', 'CFBundleName': 'Rosetta Setup',
            'CFBundleExecutable': 'RosettaSetup', 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': '1', 'LSUIElement': True, 'LSMinimumSystemVersion': '13.0'}))
        subprocess.run(['codesign', '--force', '--sign', '-', str(helper)], check=True)
        icon_builder = Path(temp) / 'MakeIcon'
        subprocess.run([swift, '-sdk', sdk, '-target', f'{platform.machine()}-apple-macosx13.0',
                        '-module-cache-path', str(Path(temp) / 'module-cache'),
                        str(ROOT / 'Resources/MakeIcon.swift'), '-o', str(icon_builder)], check=True)
        iconset = Path(temp) / 'Wizard101.iconset'
        subprocess.run([str(icon_builder), str(iconset)], check=True)
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(resources / 'Wizard101.icns')], check=True)
        info = {
            'CFBundleName': 'Wizard101 Native', 'CFBundleDisplayName': 'Wizard101 Native',
            'CFBundleIdentifier': 'org.wizard101native.portable',
            'CFBundleExecutable': 'Wizard101Native', 'CFBundlePackageType': 'APPL',
            'CFBundleIconFile': 'Wizard101.icns',
            'CFBundleShortVersionString': '3.2', 'CFBundleVersion': '8',
            'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
            'NSPrincipalClass': 'NSApplication',
            'NSAppTransportSecurity': {'NSExceptionDomains': {'versionak.us.wizard101.com': {'NSExceptionAllowsInsecureHTTPLoads': True, 'NSIncludesSubdomains': False}}},
            'NSHumanReadableCopyright': 'Unofficial local launcher. Wizard101 belongs to KingsIsle Entertainment.',
        }
        if data_root:
            info['W101DataRoot'] = str(Path(data_root).expanduser().resolve())
        if capture_timing:
            info['W101CaptureTiming'] = True
        if not development:
            if not runtime or not renderer: raise RuntimeError("A complete runtime and renderer are required for a distributable app")
            runtime = Path(runtime).resolve(); renderer = Path(renderer).resolve()
            if not (runtime / 'runtime.json').is_file(): raise RuntimeError("Runtime build metadata missing")
            shutil.copytree(runtime, resources / 'Runtime', symlinks=True, ignore=shutil.ignore_patterns('include', '*.a', '*.la', 'pkgconfig', 'man', 'doc'))
            (resources / 'Renderer').mkdir()
            shutil.copy2(renderer, resources / 'Renderer/d3d9.dll')
            provenance = renderer.parent / 'capture-build.json'
            if provenance.is_file():
                shutil.copy2(provenance, resources / 'Renderer/capture-build.json')
                info['W101DiagnosticCapture'] = True
                info['CFBundleName'] = 'Wizard101 Diagnostics'
                info['CFBundleDisplayName'] = 'Wizard101 Diagnostics'
                info['CFBundleIdentifier'] = 'org.wizard101native.diagnostics'
            performance = renderer.parent / 'performance-build.json'
            if performance.is_file():
                shutil.copy2(performance, resources / 'Renderer/performance-build.json')
                info['W101PerformanceCandidate'] = True
                info['CFBundleName'] = 'Wizard101 Performance'
                info['CFBundleDisplayName'] = 'Wizard101 Performance'
                info['CFBundleIdentifier'] = 'org.wizard101native.performance'
            cpu = renderer.parent / 'cpu-build.json'
            if cpu.is_file():
                shutil.copy2(cpu, resources / 'Renderer/cpu-build.json')
                info['W101CPUPerformanceCandidate'] = True
                info['W101DefaultDataDirectory'] = 'Wizard101 CPU Performance Comparison/Data'
                info['CFBundleName'] = 'Wizard101 CPU Performance'
                info['CFBundleDisplayName'] = 'Wizard101 CPU Performance'
                info['CFBundleIdentifier'] = 'org.wizard101native.cpu-performance'
            rendering = renderer.parent / 'rendering-build.json'
            if rendering.is_file():
                metadata = json.loads(rendering.read_text())
                if metadata['renderer_sha256'] != hashlib.sha256(renderer.read_bytes()).hexdigest():
                    raise RuntimeError('Rendering provenance does not match the renderer')
                shutil.copy2(rendering, resources / 'Renderer/rendering-build.json')
                info['W101RenderingPerformanceCandidate'] = True
                info['W101DefaultDataDirectory'] = 'Wizard101 Rendering Performance Comparison/Data'
                info['CFBundleName'] = 'Wizard101 Rendering Performance'
                info['CFBundleDisplayName'] = 'Wizard101 Rendering Performance'
                info['CFBundleIdentifier'] = 'org.wizard101native.rendering-performance'
            workload = renderer.parent / 'workload-build.json'
            if workload.is_file():
                metadata = json.loads(workload.read_text())
                if capture_timing:
                    raise RuntimeError('Workload profiling must default off')
                for key, file in [('renderer_sha256', renderer), ('moltenvk_sha256', runtime / 'lib/libMoltenVK.dylib'),
                                  ('ntdll_sha256', runtime / 'lib/wine/x86_64-unix/ntdll.so')]:
                    if metadata[key] != hashlib.sha256(file.read_bytes()).hexdigest():
                        raise RuntimeError('Workload provenance does not match ' + key)
                shutil.copy2(workload, resources / 'Renderer/workload-build.json')
                info['W101WorkloadDiagnostics'] = True
                info['W101DefaultDataDirectory'] = 'Wizard101 Workload Diagnostics/Data'
                info['CFBundleName'] = 'Wizard101 Workload Diagnostics'
                info['CFBundleDisplayName'] = 'Wizard101 Workload Diagnostics'
                info['CFBundleIdentifier'] = 'org.wizard101native.workload-diagnostics'
            workload_performance = renderer.parent / 'workload-performance-build.json'
            if workload_performance.is_file():
                metadata = json.loads(workload_performance.read_text())
                if capture_timing: raise RuntimeError('Performance candidate profiling must default off')
                for key, file in [('renderer_sha256', renderer), ('moltenvk_sha256', runtime / 'lib/libMoltenVK.dylib'),
                                  ('ntdll_sha256', runtime / 'lib/wine/x86_64-unix/ntdll.so'),
                                  ('ntdll_pe_sha256', runtime / 'lib/wine/x86_64-windows/ntdll.dll')]:
                    if metadata[key] != hashlib.sha256(file.read_bytes()).hexdigest(): raise RuntimeError('Performance provenance does not match ' + key)
                shutil.copy2(workload_performance, resources / 'Renderer/workload-performance-build.json')
                info['W101WorkloadDiagnostics'] = True
                info['W101WorkloadPerformanceCandidate'] = True
                info['W101WorkloadPerformanceDefaults'] = metadata['feature_defaults']
                info['W101DefaultDataDirectory'] = 'Wizard101 Workload Performance/Data'
                info['CFBundleName'] = info['CFBundleDisplayName'] = 'Wizard101 Workload Performance'
                info['CFBundleIdentifier'] = 'org.wizard101native.workload-performance'
            (resources / 'Renderer/d3d9.sha256').write_text(hashlib.sha256(renderer.read_bytes()).hexdigest() + '\n')
            shutil.copytree(PROJECT / 'licenses', resources / 'Licenses')
        (stage / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps(info, sort_keys=False))
        if launcher_inputs() != inputs: raise RuntimeError('Launcher inputs changed during compilation; rebuild before packaging')
        (resources / 'LauncherBuild.json').write_text(json.dumps({'inputs': inputs}, indent=2) + '\n')
        (stage / 'Contents' / 'PkgInfo').write_bytes(b'APPL????')
        subprocess.run(['codesign', '--force', '--sign', '-', str(stage)], check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(stage)], check=True)
        if output.exists():
            # This path is exclusively generated by this builder.
            if not (output / 'Contents' / 'Info.plist').exists():
                raise RuntimeError(f'Refusing to replace non-app path: {output}')
            old = plistlib.loads((output / 'Contents' / 'Info.plist').read_bytes())
            if old.get('CFBundleIdentifier') != info['CFBundleIdentifier']:
                raise RuntimeError(f'Refusing to replace another app: {output}')
            shutil.rmtree(output)
        shutil.move(str(stage), output)
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='App bundle output (default: native-launcher/dist)')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--renderer', type=Path)
    parser.add_argument('--development', action='store_true', help='Launcher only, not distributable')
    parser.add_argument('--data-root', type=Path, help='Local comparison data folder for direct opening from Finder')
    parser.add_argument('--capture-timing', action='store_true', help='Enable timing capture by default in a local comparison app')
    args = parser.parse_args()
    build(args.output, args.runtime, args.renderer, args.development, args.data_root, args.capture_timing)
