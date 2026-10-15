#!/usr/bin/env python3
"""Build pinned public MoltenVK 1.4.2 to match the working Metal runtime."""
import argparse
import json
import os
from pathlib import Path
from build_runtime import WORK, LOCK, download, extract, run


def prepare(record=False):
    lock = json.loads(LOCK.read_text())
    name = 'MoltenVK-v1.4.2.tar.gz'
    entry = lock[name]
    archive = download(name, entry['url'], entry['sha256'])
    source = WORK / 'moltenvk-1.4.2'
    if not (source / 'fetchDependencies').exists(): extract(archive, source, strip=True)
    repos = [('cereal', 'cereal', 'USCiLab'), ('Vulkan-Headers', 'Vulkan-Headers', 'KhronosGroup'),
             ('SPIRV-Cross', 'SPIRV-Cross', 'KhronosGroup'), ('SPIRV-Tools', 'SPIRV-Tools', 'KhronosGroup'),
             ('SPIRV-Headers', 'SPIRV-Tools/external/spirv-headers', 'KhronosGroup'),
             ('Vulkan-Tools', 'Vulkan-Tools', 'KhronosGroup'), ('Volk', 'Volk', 'zeux')]
    for repo, directory, owner in repos:
        revision = (source / 'ExternalRevisions' / (repo + '_repo_revision')).read_text().strip()
        name = repo + '-' + revision + '.tar.gz'
        archive = download(name, f'https://codeload.github.com/{owner}/{repo}/tar.gz/{revision}',
                           lock.get(name, {}).get('sha256'), record, lock)
        target = source / 'External' / directory
        if not target.exists(): extract(archive, target, strip=True)
        if record: LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    return source


def build(record=False):
    source = prepare(record)
    fetch = (source / 'fetchDependencies').read_text()
    start = fetch.index('function update_repo() {'); end = fetch.index('\n# Build a repository', start)
    fetch = fetch[:start] + 'function update_repo() { test -d "$1"; }\n' + fetch[end:]
    script = source / 'fetchPinnedDependencies'; script.write_text(fetch); script.chmod(0o755)
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='13.0',
               PATH='/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
    dylib = source / 'Package/Release/MoltenVK/dylib/macOS/libMoltenVK.dylib'
    if not dylib.exists():
        run([str(script), '--macos'], source, env, 'moltenvk-1.4.2-dependencies')
        run(['make', 'macos', 'MACOSX_DEPLOYMENT_TARGET=13.0'], source, env, 'moltenvk-1.4.2')
    return dylib


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--record-lock', action='store_true'); p.add_argument('--sources-only', action='store_true')
    args = p.parse_args()
    print(prepare(args.record_lock) if args.sources_only else build(args.record_lock))
