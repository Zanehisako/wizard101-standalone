#!/usr/bin/env python3
"""Stage a portable app, corresponding sources, and a macOS DMG or PKG.

Default output is explicitly a candidate. Public release requires notarization
and fresh live acceptance bound to the final signed app's component hashes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tarfile
import tempfile

from audit_bundle import audit
from build_app import APP_BUILD, APP_VERSION, build, launcher_inputs
from export_clean import export
from build_installer import APP_NAME, build_pkg, inspect_pkg
from reduce_runtime import reduce, installed_bytes, APP_BUDGET, INSTALLER_BUDGET
from account_qualification import ACCOUNT_GATES, write_account_checks
from reliability_qualification import GATES as RELIABILITY_GATES, validate as validate_reliability

ROOT = Path(__file__).resolve().parent
MAGICS = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
BETA_LIVE_GATES = ['native_login', 'character_selection', 'updates', 'audio', 'keyboard_mouse',
                   'cursor', 'fullscreen', 'graphics', 'performance_accepted', 'fresh_user_no_terminal',
                   'fresh_install_gameplay', 'session_survives_launcher_exit', 'installer_install',
                   'installer_reinstall', 'rosetta_first_run', 'multiple_installations',
                   'gui_cancel_resume', 'network_interruption', 'insufficient_storage']
BETA_LIVE_GATES = list(dict.fromkeys(BETA_LIVE_GATES + ACCOUNT_GATES + RELIABILITY_GATES))

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()

def components(app):
    app = Path(app)
    result = {}
    for p in sorted(app.rglob('*')):
        if '_CodeSignature' in p.parts: continue
        if p.is_symlink(): result[p.relative_to(app).as_posix()] = 'symlink:' + str(p.readlink())
        elif p.is_file(): result[p.relative_to(app).as_posix()] = sha(p)
    return result

def adhoc_sign(app):
    for path in sorted(app.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if not path.is_file() or path.is_symlink(): continue
        with path.open('rb') as stream: magic = stream.read(4)
        if magic in MAGICS:
            subprocess.run(['codesign', '--force', '--sign', '-', '--preserve-metadata=entitlements', str(path)],
                           check=True, capture_output=True)
    for helper in sorted((app / 'Contents/Resources').rglob('*.app'), key=lambda p: len(p.parts), reverse=True):
        subprocess.run(['codesign', '--force', '--sign', '-', str(helper)], check=True, capture_output=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True, capture_output=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)

def validate_beta_live(evidence, hashes, installer_sha256):
    if evidence.get('components') != hashes or evidence.get('installer_sha256') != installer_sha256:
        raise ValueError('Beta live evidence must match the final app and installer exactly')
    missing = [gate for gate in BETA_LIVE_GATES if evidence.get('gates', {}).get(gate) is not True]
    if missing: raise ValueError('Unverified community beta gates: ' + ', '.join(missing))
    validate_reliability(evidence, hashes)

def signing_identity(identity):
    listing = subprocess.check_output(['security', 'find-identity', '-v', '-p', 'codesigning'], text=True)
    matches = [line for line in listing.splitlines() if 'Developer ID Application:' in line and identity in line]
    if len(matches) != 1: raise ValueError('Select one available Developer ID Application certificate; development certificates cannot notarize this app')
    return matches[0].split('"')[1]

def sign(app, identity):
    identity = signing_identity(identity)
    with tempfile.TemporaryDirectory(prefix='w101-sign-') as tmp:
        entitlements = Path(tmp) / 'wine.plist'
        # The Wine process maps the Windows executable and uses its own bundled
        # dynamic-library search path. The Swift launcher needs no exceptions.
        entitlements.write_bytes(plistlib.dumps({
            'com.apple.security.cs.allow-unsigned-executable-memory': True,
            'com.apple.security.cs.allow-dyld-environment-variables': True}))
        for p in sorted(app.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if not p.is_file() or p.is_symlink(): continue
            with p.open('rb') as f: magic = f.read(4)
            if magic not in MAGICS: continue
            command = ['codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity]
            if p.relative_to(app).as_posix() == 'Contents/Resources/Runtime/bin/wine':
                command += ['--entitlements', str(entitlements)]
            subprocess.run(command + [str(p)], check=True, capture_output=True)
        for helper in sorted((app / 'Contents/Resources').rglob('*.app'), key=lambda p: len(p.parts), reverse=True):
            subprocess.run(['codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity, str(helper)], check=True, capture_output=True)
        subprocess.run(['codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity, str(app)], check=True, capture_output=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)

def validate_live(evidence, hashes):
    required = ['fresh_install_gameplay', 'native_login', 'character_selection', 'session_survives_launcher_exit',
                'audio', 'keyboard_mouse', 'cursor', 'fullscreen', 'graphics', 'updates', 'gui_cancel_resume',
                'performance_accepted', 'rosetta_first_run', 'second_apple_silicon_mac', 'oldest_supported_macos', 'clean_source_rebuild'] + ACCOUNT_GATES + RELIABILITY_GATES
    if evidence.get('components') != hashes: raise ValueError('Live evidence must match the final signed app exactly')
    missing = [name for name in required if evidence.get('gates', {}).get(name) is not True]
    if missing: raise ValueError('Unverified public release gates: ' + ', '.join(missing))
    validate_reliability(evidence, hashes)

def stage_app(base, launcher, output, wine_fix=None, standalone=False):
    base, launcher, output = map(lambda p: Path(p).resolve(), (base, launcher, output))
    if output.exists(): raise ValueError('Use a new output directory; existing builds are retained')
    stamp = launcher / 'Contents/Resources/LauncherBuild.json'
    if not stamp.is_file() or json.loads(stamp.read_text()).get('inputs') != launcher_inputs():
        raise ValueError('Launcher build does not match current sources; recompile before packaging')
    original = components(base)
    subprocess.run(['cp', '-cR', str(base), str(output)], check=True)
    resources = output / 'Contents/Resources'
    shutil.copy2(launcher / 'Contents/MacOS/Wizard101Native', output / 'Contents/MacOS/Wizard101Native')
    for name in ['Spiral.metal', 'Wizard101.icns', 'Rosetta Setup.app', 'LauncherBuild.json']:
        source = launcher / 'Contents/Resources' / name
        target = resources / name
        if target.exists():
            if target.is_dir(): shutil.rmtree(target)
            else: target.unlink()
        if source.is_dir(): shutil.copytree(source, target, symlinks=True)
        else: shutil.copy2(source, target)
    for folder in [resources / 'Renderer', resources / 'Runtime']:
        for path in folder.glob('*build.json'): path.unlink()
    if wine_fix:
        work = Path(wine_fix).resolve()
        rebuilt = work / 'build-wine/dlls/ntdll/ntdll.so'
        metadata = json.loads((work / 'shipping-wine.json').read_text())
        if metadata['library_sha256'] != sha(rebuilt): raise ValueError('Rebuilt Wine bridge changed')
        for relative, digest in metadata['inputs'].items():
            if sha(ROOT / relative) != digest: raise ValueError('Wine bridge source changed: ' + relative)
        shutil.copy2(rebuilt, resources / 'Runtime/lib/wine/x86_64-unix/ntdll.so')
        (resources / 'Runtime/ShippingWine.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (resources / 'Renderer/ARRIVAL-CANDIDATE.md').unlink(missing_ok=True)
    info = plistlib.loads((output / 'Contents/Info.plist').read_bytes())
    info.update(CFBundleName='Wizard101', CFBundleDisplayName='Wizard101',
                CFBundleIdentifier='org.wizard101native.mac', CFBundleShortVersionString=APP_VERSION,
                CFBundleVersion=APP_BUILD, CFBundleIconFile='Wizard101.icns', W101DefaultDataDirectory='Wizard101 Native',
                W101CaptureTiming=False)
    info.pop('W101DataRoot', None)
    info.pop('W101PatchRoot', None)
    info.pop('W101DiagnosticCapture', None)
    if standalone:
        info.update(CFBundleName='Wizard101 Standalone', CFBundleDisplayName='Wizard101 Standalone',
                    CFBundleVersion=APP_BUILD, W101DistributionChannel='community-beta')
    info.pop('W101AuthenticationDiagnostics', None)
    # Existing proven feature defaults are retained; experimental switches start
    # off in the new preference domain and remain available under Advanced.
    (output / 'Contents/Info.plist').write_bytes(plistlib.dumps(info, sort_keys=False))
    subprocess.run(['codesign', '--force', '--sign', '-', str(output)], check=True, capture_output=True)
    if components(base) != original: raise ValueError('Source app changed during staging')
    return output

def source_archives(destination):
    repository = export(destination / 'Wizard101-Source')
    source_files = {p.relative_to(repository).as_posix(): sha(p) for p in sorted(repository.rglob('*'))
                    if p.is_file() and '.git' not in p.relative_to(repository).parts}
    with tarfile.open(destination / 'Wizard101-Source.tar.gz', 'w:gz') as archive:
        archive.add(repository, arcname=repository.name, filter=lambda entry: None if '/.git/' in entry.name or entry.name.endswith('/.git') else entry)
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    decoder_lock = json.loads((ROOT / 'decompression/sources.lock.json').read_text())
    decoder = {('libdeflate-' + entry['revision'][:8] + '.tar.gz' if name == 'libdeflate' else
                'zlib-ng-' + entry['revision'][:8] + '.tar.gz'): entry for name, entry in decoder_lock.items()}
    # Both locks refer to archives in the same public cache. Ship every required
    # source and notice, with complete pinned inputs, independent of private git.
    sources = lock | decoder
    with tarfile.open(destination / 'Wizard101-Dependency-Sources.tar.gz', 'w:gz') as archive:
        for name, entry in sorted(sources.items()):
            source = ROOT / 'cache' / name
            if not source.is_file() or sha(source) != entry['sha256']: raise ValueError('Missing or changed corresponding source: ' + name)
            archive.add(source, arcname='cache/' + name)
    shutil.rmtree(repository)
    return dict(baseline_commit='a5d4dc1634f59d1b9e8da30a6044a6572bdd9d3c', source_files=source_files,
                project_archive_sha256=sha(destination / 'Wizard101-Source.tar.gz'),
                dependency_archive_sha256=sha(destination / 'Wizard101-Dependency-Sources.tar.gz'),
                dependencies={name: entry['sha256'] for name, entry in sources.items()})

def package(base, output, identity=None, notary_profile=None, live_evidence=None, launcher=None, verified_app=None, wine_fix=None,
            format='dmg', channel='candidate', pe_strip=None, installer_identity=None):
    output = Path(output).expanduser().resolve()
    if output.exists(): raise ValueError('Use a fresh output directory')
    if bool(identity) != bool(notary_profile): raise ValueError('Supply both a Developer ID identity and notarytool Keychain profile for signed builds')
    if live_evidence and (not identity or not verified_app): raise ValueError('Public release requires the previously notarized, live-tested --verified-app and its evidence')
    if verified_app and not live_evidence: raise ValueError('A verified app needs matching live evidence')
    if format not in ('pkg', 'dmg') or channel not in ('candidate', 'community-beta'): raise ValueError('Unsupported format or channel')
    if channel == 'community-beta' and (format != 'pkg' or identity or notary_profile or live_evidence or verified_app):
        raise ValueError('Community beta uses an unsigned PKG; qualify its final artifacts with publish_beta.py')
    if installer_identity and (format != 'pkg' or not identity): raise ValueError('Installer identity requires a signed PKG build')
    if format == 'pkg' and identity and not installer_identity: raise ValueError('Signed PKG builds also require --installer-identity')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.shipping-', dir=output.parent) as tmp:
        work = Path(tmp)
        app = work / (APP_NAME if format == 'pkg' else 'Wizard101.app')
        original_base = components(Path(base)) if not verified_app else None
        reduction = None
        if verified_app:
            # Never re-sign a tested app: timestamps would change component
            # hashes and invalidate its live evidence.
            verified_app = Path(verified_app).resolve()
            signing_identity(identity)
            signature = subprocess.check_output(['codesign', '-d', '-vv', str(verified_app)], stderr=subprocess.STDOUT, text=True)
            if 'Authority=' + signing_identity(identity) not in signature:
                raise ValueError('Verified app does not use the requested Developer ID identity')
            stamp = verified_app / 'Contents/Resources/LauncherBuild.json'
            if not stamp.is_file() or json.loads(stamp.read_text()).get('inputs') != launcher_inputs():
                raise ValueError('Verified launcher differs from current corresponding sources')
            subprocess.run(['xcrun', 'stapler', 'validate', str(verified_app)], check=True)
            subprocess.run(['spctl', '--assess', '--type', 'execute', str(verified_app)], check=True)
            shutil.copytree(verified_app, app, symlinks=True)
        else:
            launcher = Path(launcher).resolve() if launcher else build(output=work / 'Launcher.app', development=True)
            app = stage_app(base, launcher, app, wine_fix, standalone=channel == 'community-beta')
            if channel == 'community-beta':
                reduction = reduce(app, work / 'Wizard101-Debug-Originals.tar.gz', pe_strip)
                (app / 'Contents/Resources/Runtime/SizeReduction.json').write_text(json.dumps(reduction, indent=2) + '\n')
                adhoc_sign(app)
            if identity: sign(app, identity)
        app_bytes = installed_bytes(app)
        if channel == 'community-beta' and app_bytes > APP_BUDGET: raise ValueError('Installed app exceeds the 350 MiB budget')
        executable = app / 'Contents/MacOS/Wizard101Native'
        tests = json.loads(subprocess.check_output([str(executable), '--self-test'], text=True))
        audited = audit(app)
        hashes = components(app)
        if live_evidence: validate_live(json.loads(Path(live_evidence).read_text()), hashes)
        if identity and not verified_app:
            zipped = work / 'notarize.zip'
            subprocess.run(['ditto', '-c', '-k', '--keepParent', str(app), str(zipped)], check=True)
            result = json.loads(subprocess.check_output(['xcrun', 'notarytool', 'submit', str(zipped), '--keychain-profile', notary_profile, '--wait', '--output-format', 'json'], text=True))
            if result.get('status') != 'Accepted': raise ValueError('Apple notarization was not accepted: ' + str(result.get('status')))
            subprocess.run(['xcrun', 'stapler', 'staple', str(app)], check=True)
            subprocess.run(['xcrun', 'stapler', 'validate', str(app)], check=True)
            subprocess.run(['spctl', '--assess', '--type', 'execute', str(app)], check=True)
        artifacts = work / 'Artifacts'; artifacts.mkdir()
        # Retain the staged app without allocating a second full runtime copy.
        app = Path(shutil.move(app, artifacts / app.name))
        quickstart = '''Wizard101 for Apple Silicon\n\nUS / Steam community beta: Steam remains experimental.\nKeep the previous launcher for rollback.\nSee ACCOUNTS.md for account setup and remaining gameplay checks.\n\n1. Open the app and reuse the existing standalone game.\n2. Choose US or Steam, enter Wizard101 credentials locally, then Play.\n3. For Steam, use the Wizard101 account created through Steam.\n   The Mac Steam client must be installed, signed in and online.\n\nMagical effects can be switched off on the welcome screen.\nGame settings and update tools are under the gear button.\n\nRequires macOS 13+, Apple Silicon, Rosetta and internet.\nThis community launcher is not affiliated with KingsIsle.\n'''
        if not identity: quickstart += '\nTEST CANDIDATE: not notarized. Public shipping is blocked.\n'
        installer_audit = None
        if format == 'pkg':
            name = 'Wizard101-AppleSilicon-' + ('community-beta' if channel == 'community-beta' else 'candidate') + '.pkg'
            if live_evidence: name = 'Wizard101-AppleSilicon.pkg'
            dmg = artifacts / name
            installer_audit = build_pkg(app, dmg, installer_identity)
            installer_audit = inspect_pkg(dmg, hashes)
            if channel == 'community-beta' and dmg.stat().st_size > INSTALLER_BUDGET:
                raise ValueError('Installer exceeds the 150 MiB budget')
            for page in ['INSTALL.html', 'CONCLUSION.html']:
                shutil.copy2(ROOT / 'installer' / page, artifacts / page)
        else:
            payload = work / 'Payload'; payload.mkdir()
            shutil.copytree(app, payload / app.name, symlinks=True)
            (payload / 'Applications').symlink_to('/Applications', target_is_directory=True)
            (payload / 'Start Here.txt').write_text(quickstart)
            name = 'Wizard101-AppleSilicon' + ('' if live_evidence else '-candidate') + '.dmg'
            dmg = artifacts / name
            subprocess.run(['hdiutil', 'create', '-volname', 'Wizard101', '-srcfolder', str(payload), '-format', 'UDZO', '-ov', str(dmg)], check=True, capture_output=True)
        if identity:
            if format == 'dmg': subprocess.run(['codesign', '--timestamp', '--sign', signing_identity(identity), str(dmg)], check=True)
            result = json.loads(subprocess.check_output(['xcrun', 'notarytool', 'submit', str(dmg), '--keychain-profile', notary_profile, '--wait', '--output-format', 'json'], text=True))
            if result.get('status') != 'Accepted': raise ValueError('Installer notarization was not accepted')
            subprocess.run(['xcrun', 'stapler', 'staple', str(dmg)], check=True)
            subprocess.run(['xcrun', 'stapler', 'validate', str(dmg)], check=True)
        provenance = source_archives(artifacts)
        provenance['base_components'] = original_base
        (artifacts / 'SOURCE-PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n')
        shutil.copy2(ROOT / 'SHIPPING.md', artifacts / 'SHIPPING.md')
        shutil.copy2(ROOT / 'ACCOUNTS.md', artifacts / 'ACCOUNTS.md')
        write_account_checks(artifacts, hashes, sha(dmg))
        report = dict(created_at=datetime.now(timezone.utc).isoformat(), public_release_ready=bool(live_evidence and identity),
                      app_version=APP_VERSION, build_number=APP_BUILD,
                      channel=channel, format=format, installed_app_bytes=app_bytes, installer_bytes=dmg.stat().st_size,
                      size_budgets=dict(app_bytes=APP_BUDGET, installer_bytes=INSTALLER_BUDGET),
                      size_reduction=reduction, installer_audit=installer_audit, installer_sha256=sha(dmg),
                      corresponding_sources_verified=True, source_provenance_sha256=sha(artifacts / 'SOURCE-PROVENANCE.json'),
                      developer_id_signed=bool(identity), notarized=bool(identity), self_tests_passed=tests['passed'],
                      bundle_audit=audited, components=hashes, runtime=json.loads((app/'Contents/Resources/Runtime/runtime.json').read_text()),
                      launcher_effects_optional=True, game_assets_bundled=False, live_evidence_verified=bool(live_evidence),
                      account_providers=['us', 'steam'], account_qualification_pending=[] if live_evidence else ACCOUNT_GATES,
                      blocked_on=[] if live_evidence else ['live release acceptance', 'US / Steam account qualification', 'second Apple Silicon Mac', 'first Rosetta install', 'clean Arrival source rebuild'] + ([] if identity else ['Developer ID signing', 'Apple notarization']))
        if channel == 'community-beta':
            report.update(community_beta_ready=False, beta_pending_gates=BETA_LIVE_GATES,
                          blocked_on=['community beta live qualification'],
                          signed_release_pending=['Developer ID signing', 'Apple notarization',
                              'second Apple Silicon Mac', 'oldest supported macOS', 'clean Arrival source rebuild'])
            evidence = dict(components=hashes, installer_sha256=sha(dmg), gates=dict.fromkeys(BETA_LIVE_GATES, False), observations={})
            (artifacts / 'BETA-LIVE-TEMPLATE.json').write_text(json.dumps(evidence, indent=2) + '\n')
            from live_checklist import write_checklist
            write_checklist(artifacts / 'LIVE-CHECKS.html', evidence)
            shutil.copy2(ROOT / 'COMMUNITY-BETA.md', artifacts / 'COMMUNITY-BETA.md')
            shutil.copy2(ROOT / 'BETA-QUALIFICATION.md', artifacts / 'BETA-QUALIFICATION.md')
        if original_base is not None and components(Path(base)) != original_base: raise ValueError('Base app changed during packaging')
        (artifacts / 'RELEASE-STATUS.json').write_text(json.dumps(report, indent=2) + '\n')
        files = [p for p in artifacts.iterdir() if p.is_file()]
        (artifacts / 'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(files)))
        if reduction:
            # Debugging originals are local maintainer artifacts, never an extra
            # installer download and never installed in Applications.
            debug = work / 'Maintainer-Debug'; debug.mkdir()
            shutil.move(work / 'Wizard101-Debug-Originals.tar.gz', debug)
            (debug / 'README.txt').write_text('Original pre-strip PE files and DEBUG-MANIFEST.json. Restore into a separate copy only.\n')
            shutil.move(debug, artifacts / 'Maintainer-Debug')
        shutil.move(artifacts, output)
    print(json.dumps(dict(output=str(output), public_release_ready=report['public_release_ready'], self_tests_passed=tests['passed']), indent=2))
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-app', type=Path, required=True, help='Complete source-built standalone runtime app; never installed CrossOver')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, help='Previously compiled launcher (otherwise compile current source)')
    parser.add_argument('--identity', help='Developer ID Application certificate')
    parser.add_argument('--notary-profile', help='Existing notarytool Keychain profile; no credentials on the command line')
    parser.add_argument('--live-evidence', type=Path, help='Final signed component hashes and all required live gates')
    parser.add_argument('--verified-app', type=Path, help='Previously notarized app that passed the supplied live gates; packaged without re-signing')
    parser.add_argument('--wine-fix', type=Path, help='Source-verified work directory from rebuild_shipping_wine.py for a macOS 26-stamped retained runtime')
    parser.add_argument('--format', choices=['dmg', 'pkg'], default='dmg')
    parser.add_argument('--channel', choices=['candidate', 'community-beta'], default='candidate')
    parser.add_argument('--pe-strip', help='PE-compatible strip executable; community beta only')
    parser.add_argument('--installer-identity', help='Developer ID Installer certificate for signed PKG builds')
    args = parser.parse_args()
    package(args.base_app, args.output, args.identity, args.notary_profile, args.live_evidence, args.launcher, args.verified_app, args.wine_fix,
            args.format, args.channel, args.pe_strip, args.installer_identity)
