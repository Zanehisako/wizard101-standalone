#!/usr/bin/env python3
"""Build, check and archive the complete app and its corresponding sources."""
import argparse
import json
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

import build_runtime
import build_renderer
import build_app
from audit_bundle import audit
from export_clean import export

ROOT = Path(__file__).resolve().parent


def collect_licenses():
    target = ROOT / 'licenses'
    target.mkdir(exist_ok=True)
    sources = build_runtime.WORK / 'sources'
    groups = {'Wine': sources / 'wine', 'MoltenVK': build_runtime.WORK / 'moltenvk-1.4.2',
              'GMP': sources / 'gnutls/gmp', 'Nettle': sources / 'gnutls/nettle',
              'GnuTLS': sources / 'gnutls/gnutls', 'FreeType': sources / 'freetype',
              'D9VK': build_runtime.WORK / 'd9vk'}
    for name, folder in groups.items():
        if not folder.is_dir(): raise RuntimeError('Missing corresponding source: ' + name)
        for source in folder.rglob('*'):
            if source.is_symlink() or not source.is_file(): continue
            if not source.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')) and source.name.upper() not in ['FTL.TXT', 'GPLV2.TXT']: continue
            if any(part in ['Build', 'build', 'Package', '.git'] for part in source.relative_to(folder).parts): continue
            relative = source.relative_to(folder)
            dest = target / name / relative.parent / (relative.name + '.txt')
            dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, dest)
    with tarfile.open(build_runtime.CACHE / 'nettle-3.10.tar.gz') as tar:
        for member in tar.getmembers():
            if member.isfile() and Path(member.name).name.startswith('COPYING'):
                (target / 'Nettle' / (Path(member.name).name + '.txt')).write_bytes(tar.extractfile(member).read())
    shutil.copy2(ROOT / 'LICENSE', target / 'Project-MIT.txt')
    # This source's opening comment contains its complete permission and notice.
    twofish = (ROOT / 'launcher/Vendor/Twofish/twofish.c').read_text()
    (target / 'Twofish-notice.txt').write_text(twofish[:twofish.index('*/') + 2] + '\n')
    lock = json.loads(build_runtime.LOCK.read_text())
    for name in ['mingw-w64-COPYING-v14.0.0.txt', 'GCC-Runtime-Library-Exception-3.1.txt', 'GPL-3.0.txt']:
        entry = lock[name]
        notice = build_runtime.download(name, entry['url'], entry['sha256'])
        shutil.copy2(notice, target / name)
    (target / 'DEPENDENCIES.md').write_text('''# Included software and corresponding sources

Original launcher, build scripts and synthetic tests: MIT (Project-MIT.txt).
Twofish 0.3 by Niels Ferguson: original permissive notice (Twofish-notice.txt).
D9VK and renderer changes: upstream zlib/libpng license (D9VK/).
Wine 11.0 from CodeWeavers 26.3.0: LGPL 2.1 or later; bundled sublibraries
retain their individual notices (Wine/). This includes FAudio and vkd3d.
MoltenVK and its SPIRV-Cross: Apache 2.0 and component notices (MoltenVK/).
GMP: LGPL 3 or GPL 2 or later (GMP/). Nettle: LGPL 3 or GPL 2 or later
(Nettle/). GnuTLS: LGPL 2.1 or later for the library, with individual component
notices (GnuTLS/). FreeType: the FreeType License (FreeType/docs/FTL.TXT.txt).
Portions of this software are copyright (c) 2024 The FreeType Project
(www.freetype.org). All rights reserved.
The MinGW-w64 runtime retains its ZPL and component terms; GCC runtime
libraries use GPL 3 with the GCC Runtime Library Exception 3.1. Their notices
are included alongside the project notices.

See the original notices for exact terms and copyright holders. All runtime
and renderer source inputs, including component notices, are shipped in
Wizard101-Native-dependency-sources.tar.gz; hashes are in sources.lock.json.
Wizard101-Native-source.tar.gz contains the clean project, patches, configure
options and one-command build/relink scripts. Extract its repository and put
the dependency archives in cache/ (or allow the builder to fetch those same
checksum-pinned archives). Run python3 build.py. W101_RUNTIME_ROOT selects a
replacement runtime; alternatively replace and ad-hoc sign a modified app.

Apple system libraries, macOS, Rosetta and KingsIsle game files are supplied
by their owners and are not included in these dependency source archives.
''')


def package(app, metadata):
    dist = ROOT / 'dist'; dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='w101-public-', dir=dist) as temp:
        stage = Path(temp)
        repository = export(stage / 'Wizard101-Native-source')
        with tarfile.open(stage / 'Wizard101-Native-source.tar.gz', 'w:gz') as tar:
            tar.add(repository, arcname=repository.name)
        lock = json.loads(build_runtime.LOCK.read_text())
        with tarfile.open(stage / 'Wizard101-Native-dependency-sources.tar.gz', 'w:gz') as tar:
            for name, entry in sorted(lock.items()):
                source = build_runtime.CACHE / name
                if build_runtime.sha(source) != entry['sha256']: raise RuntimeError('Invalid source input: ' + name)
                tar.add(source, arcname='cache/' + name)
        payload = stage / 'Wizard101-Native-AppleSilicon'
        payload.mkdir()
        shutil.copytree(app, payload / app.name, symlinks=True)
        for name in ['Wizard101-Native-source.tar.gz', 'Wizard101-Native-dependency-sources.tar.gz']:
            shutil.move(stage / name, payload / name)
        shutil.copy2(ROOT / 'README.md', payload / 'README.md')
        shutil.copy2(ROOT / 'RELEASE-GATES.md', payload / 'RELEASE-GATES.md')
        (payload / 'BUILD-METADATA.json').write_text(json.dumps(metadata, indent=2) + '\n')
        archive = dist / 'Wizard101-Native-AppleSilicon-candidate.zip'
        partial = dist / (archive.name + '.partial')
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(payload), str(partial)], check=True)
        partial.replace(archive)
        # A separate repository is convenient for reviewing the one clean commit.
        clean = dist / 'Wizard101-Native-source'
        if clean.exists(): shutil.rmtree(clean)
        shutil.move(repository, clean)
        print('Candidate archive:', archive)
        print('Archive SHA256:', build_runtime.sha(archive))
        return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-existing', action='store_true', help='Package previously built and checked source outputs')
    args = parser.parse_args()
    if platform.machine() != 'arm64': raise RuntimeError('The first release targets Apple Silicon')
    if not build_runtime.WORK.is_absolute() or any(c.isspace() for c in str(build_runtime.WORK)):
        raise RuntimeError('W101_BUILD_ROOT must be an absolute path without spaces')
    if args.package_existing:
        runtime = build_runtime.WORK / 'runtime'
        renderer = build_runtime.WORK / 'build-d9vk/src/d3d9/d3d9.dll'
    else:
        runtime = build_runtime.build(); renderer = build_renderer.build()
    collect_licenses()
    app = build_app.build(runtime=runtime, renderer=renderer)
    executable = app / 'Contents/MacOS/Wizard101Native'
    result = subprocess.run([str(executable), '--self-test'], check=True, capture_output=True, text=True)
    checks = json.loads(result.stdout)
    print('Synthetic checks passed:', checks['passed'])
    audited = audit(app)
    metadata = {'candidate': True, 'source_release': 'CodeWeavers 26.3.0',
                'renderer_sha256': build_runtime.sha(renderer), 'sources': json.loads(build_runtime.LOCK.read_text()),
                'macos_build_host': platform.mac_ver()[0], 'architecture': platform.machine(),
                'clang': subprocess.check_output(['xcrun', 'clang', '--version'], text=True).splitlines()[0],
                'mingw': subprocess.check_output(['x86_64-w64-mingw32-g++', '--version'], text=True).splitlines()[0],
                'swift': subprocess.check_output(['xcrun', 'swiftc', '--version'], text=True).splitlines()[0],
                'synthetic_checks': checks['passed'], 'bundle_audit': audited,
                'real_login_verified': False, 'gameplay_performance_accepted': False}
    package(app, metadata)


if __name__ == '__main__': main()
