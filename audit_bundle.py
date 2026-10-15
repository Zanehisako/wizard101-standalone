#!/usr/bin/env python3
"""Reject bundles that depend on a developer checkout or installed CrossOver."""
import argparse
import json
from pathlib import Path
import plistlib
import re
import subprocess

def audit(app):
    app = Path(app).resolve(); resources = app / 'Contents/Resources'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if 'W101PatchRoot' in info or 'W101DataRoot' in info: raise RuntimeError('Developer root in app metadata')
    for required in ['Runtime/bin/wine', 'Runtime/runtime.json', 'Runtime/lib/libMoltenVK.dylib', 'Renderer/d3d9.dll', 'Licenses/DEPENDENCIES.md']:
        if not (resources / required).is_file(): raise RuntimeError(f'Missing bundle component: {required}')
    macho = 0
    minimums = set()
    for path in app.rglob('*'):
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(app): raise RuntimeError(f'External bundle link: {path}')
            if not target.exists(): raise RuntimeError(f'Broken bundle link: {path}')
            continue
        if not path.is_file(): continue
        relative = path.relative_to(app).as_posix().lower()
        if any(name in relative for name in ['verification', 'fixtures', 'research', 'wizardgraphicalclient.exe', '.wad', '.dxso', '.dxvk-cache']): raise RuntimeError(f'Local-only artifact in bundle: {path}')
        with path.open('rb') as f: magic = f.read(4)
        if magic not in [b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca']: continue
        macho += 1
        listing = subprocess.check_output(['otool', '-L', str(path)], text=True)
        commands = subprocess.check_output(['otool', '-l', str(path)], text=True)
        versions = re.findall(r'cmd LC_BUILD_VERSION\n(?:(?!Load command).)*?\bminos (\d+(?:\.\d+){0,2})', commands, re.S)
        versions += re.findall(r'cmd LC_VERSION_MIN_MACOSX\n(?:(?!Load command).)*?\bversion (\d+(?:\.\d+){0,2})', commands, re.S)
        for version in versions:
            minimums.add(version)
            if tuple(map(int, version.split('.'))) > (13, 0, 0):
                raise RuntimeError(f'Component requires macOS newer than the declared minimum: {path}: {version}')
        rpaths = set(re.findall(r'cmd LC_RPATH\n.*?path (.*?) \(offset', commands, re.S))
        def expand(name):
            return Path(name.replace('@loader_path', str(path.parent)).replace('@executable_path', str(app / 'Contents/MacOS')))
        for line in listing.splitlines()[1:]:
            if ' (compatibility version ' not in line: continue
            dep = line.strip().split(' (')[0]
            if dep.startswith('/') and not dep.startswith(('/usr/lib/', '/System/Library/')): raise RuntimeError(f'External library: {path}: {dep}')
            if dep.startswith('@loader_path/') and not (path.parent / dep.removeprefix('@loader_path/')).resolve().is_file(): raise RuntimeError(f'Unresolved library: {path}: {dep}')
            if dep.startswith('@rpath/'):
                leaf = dep.removeprefix('@rpath/')
                # dylib IDs identify the current image, rather than a load.
                if leaf != path.name and not any((expand(rpath) / leaf).is_file() for rpath in rpaths) and not leaf.startswith(('libswift', 'Swift')):
                    raise RuntimeError(f'Unresolved rpath library: {path}: {dep}')
        for rpath in rpaths:
            if rpath.startswith('/') and not rpath.startswith(('/usr/lib', '/System/Library')): raise RuntimeError(f'External rpath: {path}: {rpath}')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)
    architectures = {}
    for relative, required in [('Contents/MacOS/Wizard101Native', 'arm64'), ('Contents/Resources/Runtime/bin/wine', 'x86_64'),
                               ('Contents/Resources/Runtime/lib/libMoltenVK.dylib', 'x86_64')]:
        found = subprocess.check_output(['lipo', '-archs', str(app / relative)], text=True).strip().split()
        if required not in found: raise RuntimeError('Unsupported component architecture: ' + relative)
        architectures[relative] = found
    result = {'bundle_audit_passed': True, 'macho_files_checked': macho, 'game_assets_bundled': False,
              'developer_files_required': False, 'minimum_macos_verified': True, 'component_minimums': sorted(minimums), 'architectures': architectures}
    print(json.dumps(result, indent=2)); return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('app', type=Path); audit(p.parse_args().app)
