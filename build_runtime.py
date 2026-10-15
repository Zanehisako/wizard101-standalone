#!/usr/bin/env python3
"""Build the x64 runtime from pinned public sources, never installed CrossOver."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get('W101_BUILD_ROOT', '/private/tmp/w101-runtime-26.3.0'))
CACHE = ROOT / 'cache'
LOCK = ROOT / 'sources.lock.json'
CX_URL = 'https://media.codeweavers.com/pub/crossover/source/crossover-sources-26.3.0.tar.gz'
CX_SHA = 'ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872'
JOBS = os.environ.get('BUILD_JOBS', '4')

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def run(args, cwd=None, env=None, log=None):
    # Rebuilt overlays must retain the target at link time too. Otherwise a
    # newer Xcode stamps the host macOS version on the rebuilt Wine dylib.
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='13.0') | (env or {})
    print('Building:', log or args[0], flush=True)
    logs = WORK / 'logs'; logs.mkdir(parents=True, exist_ok=True)
    with (logs / ((log or Path(args[0]).name) + '.log')).open('a') as output:
        result = subprocess.run(args, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed. See {logs} for details.')

def download(name, url, expected=None, record=False, lock=None):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        partial = path.with_suffix(path.suffix + '.partial')
        subprocess.run(['curl', '-fL', '--retry', '3', '-o', str(partial), url], check=True)
        partial.rename(path)
    digest = sha(path)
    if expected and digest != expected: raise RuntimeError(f'Checksum mismatch: {name}')
    if not expected and not record: raise RuntimeError(f'Unpinned dependency: {name}')
    if lock is not None: lock[name] = {'url': url, 'sha256': digest}
    return path

def extract(archive, destination, strip=False):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if strip:
            for item in members: item.name = '/'.join(item.name.split('/')[1:])
            members = [m for m in members if m.name]
        tar.extractall(destination, members=members, filter='data')

def prepare(record=False):
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    archive = download('crossover-sources-26.3.0.tar.gz', CX_URL, CX_SHA, lock=lock)
    if not (WORK / 'sources/wine/configure').exists(): extract(archive, WORK)
    mvk = WORK / 'sources/moltenvk'
    repos = {'cereal': 'USCiLab', 'Vulkan-Headers': 'KhronosGroup', 'glslang': 'KhronosGroup', 'Vulkan-Tools': 'KhronosGroup', 'Volk': 'zeux'}
    for name, owner in repos.items():
        revision = (mvk / 'ExternalRevisions' / f'{name}_repo_revision').read_text().strip()
        repo = 'volk' if name == 'Volk' else name
        key = f'{repo}-{revision}.tar.gz'
        a = download(key, f'https://codeload.github.com/{owner}/{repo}/tar.gz/{revision}', lock.get(key, {}).get('sha256'), record, lock)
        target = mvk / 'External' / repo
        if not target.exists(): extract(a, target, strip=True)
    good = json.loads((mvk / 'External/glslang/known_good.json').read_text())
    for dep in good['commits']:
        if dep['name'] not in ['spirv-tools', 'spirv-tools/external/spirv-headers']: continue
        key = dep['name'].split('/')[-1] + '-' + dep['commit'] + '.tar.gz'
        url = 'https://codeload.github.com/' + dep['subrepo'] + '/tar.gz/' + dep['commit']
        a = download(key, url, lock.get(key, {}).get('sha256'), record, lock)
        target = mvk / 'External/glslang/External' / dep['name']
        if not target.exists(): extract(a, target, strip=True)
    if record: LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    # CodeWeavers' Nettle directory omits its top-level build template.
    # Restore only that template from the matching upstream release.
    key = 'nettle-3.10.tar.gz'
    upstream = download(key, 'https://ftp.gnu.org/gnu/nettle/nettle-3.10.tar.gz', lock.get(key, {}).get('sha256'), record, lock)
    with tarfile.open(upstream) as tar:
        template = tar.extractfile('nettle-3.10/Makefile.in').read()
    (WORK / 'sources/gnutls/nettle/Makefile.in').write_bytes(template)
    if record: LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    return mvk

def build(record=False):
    mvk = prepare(record)
    from build_moltenvk import build as build_metal
    metal = build_metal(record)
    env = dict(os.environ)
    env['PATH'] = '/opt/homebrew/opt/bison/bin:/opt/homebrew/opt/libtool/libexec/gnubin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    env['MACOSX_DEPLOYMENT_TARGET'] = '13.0'
    prefix = WORK / 'runtime'
    (prefix / 'lib').mkdir(parents=True, exist_ok=True)
    shutil.copy2(metal, prefix / 'lib')
    env.update(CC='clang -arch x86_64', CXX='clang++ -arch x86_64', CFLAGS='-O2 -std=gnu11 -mmacosx-version-min=13.0', CXXFLAGS='-O2 -mmacosx-version-min=13.0',
               CPPFLAGS=f'-I{prefix}/include', LDFLAGS=f'-L{prefix}/lib -Wl,-rpath,{prefix}/lib', PKG_CONFIG_LIBDIR=f'{prefix}/lib/pkgconfig', PKG_CONFIG_PATH='',
               DYLD_FALLBACK_LIBRARY_PATH=f'{prefix}/lib:/usr/lib')
    env.update(NETTLE_LIBS='-lnettle', HOGWEED_LIBS='-lhogweed', GMP_LIBS='-lgmp')
    packages = [
        ('gmp', 'gnutls/gmp', ['--host=x86_64-apple-darwin', '--disable-static', '--enable-shared', '--disable-assembly']),
        ('nettle', 'gnutls/nettle', ['--host=x86_64-apple-darwin', '--disable-static', '--enable-shared', '--disable-assembler', '--disable-documentation']),
        ('gnutls', 'gnutls/gnutls', ['--host=x86_64-apple-darwin', '--disable-static', '--enable-shared', '--disable-doc', '--disable-tools', '--disable-tests', '--without-p11-kit', '--with-included-libtasn1', '--with-included-unistring', '--disable-nls', '--disable-cxx', '--without-unbound'])]
    for name, directory, options in packages:
        src = WORK / 'sources' / directory
        if not (src / 'configure').exists(): run(['autoreconf', '-fi'], src, env, name + '-autoreconf')
        folder = WORK / ('build-' + name); folder.mkdir(exist_ok=True)
        marker = folder / '.installed'
        if not marker.exists():
            run([str(src / 'configure'), '--prefix=' + str(prefix), *options], folder, env, name + '-configure')
            targets = ['libnettle.dylib', 'libhogweed.dylib'] if name == 'nettle' else []
            run(['make', '-j' + JOBS, *targets], folder, env, name)
            run(['make', 'install-here' if name == 'nettle' else 'install'], folder, env, name + '-install'); marker.touch()
    freetype = WORK / 'build-freetype-cmake'
    if not (freetype / '.installed').exists():
        run(['cmake', '-S', str(WORK / 'sources/freetype'), '-B', str(freetype), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=ON', '-DCMAKE_OSX_ARCHITECTURES=x86_64', '-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0', '-DCMAKE_INSTALL_PREFIX=' + str(prefix), '-DCMAKE_C_COMPILER=/usr/bin/clang', '-DFT_DISABLE_BZIP2=ON', '-DFT_DISABLE_PNG=ON', '-DFT_DISABLE_HARFBUZZ=ON', '-DFT_DISABLE_BROTLI=ON'], env=env, log='freetype-configure')
        run(['cmake', '--build', str(freetype), '-j', JOBS], env=env, log='freetype')
        run(['cmake', '--install', str(freetype)], env=env, log='freetype-install')
        (freetype / '.installed').touch()
    wine = WORK / 'build-wine'; wine.mkdir(exist_ok=True)
    env.update(FREETYPE_CFLAGS='-I' + str(prefix / 'include/freetype2'), FREETYPE_LIBS='-lfreetype')
    env['CPPFLAGS'] += f' -I{mvk}/External/Vulkan-Headers/include'
    options = ['--prefix=/usr/local/w101', '--host=x86_64-apple-darwin', '--build=x86_64-apple-darwin', '--enable-win64', '--disable-tests', '--without-x', '--without-cups', '--without-dbus', '--without-gstreamer', '--without-oss', '--without-pulse', '--without-alsa', '--without-sane', '--without-usb', '--without-v4l2', '--without-pcap', '--without-krb5']
    if not (wine / 'Makefile').exists(): run([str(WORK / 'sources/wine/configure'), *options], wine, env, 'wine-configure')
    run(['make', '-j' + JOBS], wine, env, 'wine')
    dest = WORK / 'wine-install'
    run(['make', 'install', 'DESTDIR=' + str(dest)], wine, env, 'wine-install')
    installed = dest / 'usr/local/w101'
    for link in installed.rglob('*'):
        if not link.is_symlink(): continue
        target = prefix / link.relative_to(installed)
        if target.is_symlink(): target.unlink()
        elif target.exists(): raise RuntimeError(f'Unexpected regular file at generated symlink: {target}')
    shutil.copytree(installed, prefix, dirs_exist_ok=True, symlinks=True)
    # Wine's compiled optional-library names must be basenames after relocation.
    # install_name_tool repairs all Mach-O dependency paths and IDs.
    relocate(prefix)
    (prefix / 'runtime.json').write_text(json.dumps({'source_release': 'CodeWeavers 26.3.0', 'wine': '11.0', 'moltenvk': '1.4.2', 'architecture': 'x86_64', 'source_sha256': CX_SHA}, indent=2) + '\n')
    icd = prefix / 'share/vulkan/icd.d'; icd.mkdir(parents=True, exist_ok=True)
    (icd / 'MoltenVK_icd.json').write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {'library_path': '../../../lib/libMoltenVK.dylib', 'api_version': '1.2.0'}}, indent=2))
    print(prefix)
    return prefix

def relocate(prefix):
    for path in prefix.rglob('*'):
        if not path.is_file() or path.is_symlink(): continue
        kind = subprocess.check_output(['file', '-b', str(path)], text=True)
        if 'Mach-O' not in kind: continue
        listing = subprocess.check_output(['otool', '-L', str(path)], text=True)
        for line in listing.splitlines()[1:]:
            dep = line.strip().split(' (')[0]
            if dep.startswith(str(prefix)):
                relative = os.path.relpath(prefix / 'lib' / Path(dep).name, path.parent)
                subprocess.run(['install_name_tool', '-change', dep, '@loader_path/' + relative, str(path)], check=True)
            elif dep.startswith('/opt/') or 'CrossOver.app' in dep: raise RuntimeError(f'External runtime dependency: {path}: {dep}')
        commands = subprocess.check_output(['otool', '-l', str(path)], text=True)
        import re
        for rpath in set(re.findall(r'cmd LC_RPATH\n.*?path (.*?) \(offset', commands, re.S)):
            if rpath.startswith(str(prefix)):
                relative = '@loader_path/' + os.path.relpath(prefix / 'lib', path.parent)
                subprocess.run(['install_name_tool', '-rpath', rpath, relative, str(path)], check=True)
        if '.dylib' in path.name: subprocess.run(['install_name_tool', '-id', '@rpath/' + path.name, str(path)], check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--record-lock', action='store_true'); p.add_argument('--sources-only', action='store_true')
    args = p.parse_args()
    if args.sources_only: prepare(args.record_lock)
    else: build(args.record_lock)
