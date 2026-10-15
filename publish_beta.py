#!/usr/bin/env python3
"""Verify final beta artifacts; publish a GitHub prerelease only with live passes."""
import argparse
import json
from pathlib import Path
import subprocess
import tarfile

from build_installer import APP_NAME, inspect_pkg
from package_shipping import BETA_LIVE_GATES, components, sha, validate_beta_live
from reduce_runtime import APP_BUDGET, INSTALLER_BUDGET, installed_bytes


def verify_sources(directory, provenance):
    with tarfile.open(directory / 'Wizard101-Source.tar.gz') as archive:
        found = {}
        for entry in archive:
            if entry.isdir(): continue
            parts = Path(entry.name).parts
            if not entry.isfile() or len(parts) < 2 or parts[0] != 'Wizard101-Source' or '..' in parts:
                raise ValueError('Unexpected project source entry')
            import hashlib
            found['/'.join(parts[1:])] = hashlib.sha256(archive.extractfile(entry).read()).hexdigest()
        if found != provenance['source_files']: raise ValueError('Project source provenance mismatch')
    with tarfile.open(directory / 'Wizard101-Dependency-Sources.tar.gz') as archive:
        found = {}
        for entry in archive:
            if not entry.isfile() or not entry.name.startswith('cache/') or len(Path(entry.name).parts) != 2:
                raise ValueError('Unexpected dependency source entry')
            import hashlib
            found[Path(entry.name).name] = hashlib.sha256(archive.extractfile(entry).read()).hexdigest()
        if found != provenance['dependencies']: raise ValueError('Dependency source provenance mismatch')


def verify(directory, evidence=None, require_live=True):
    directory = Path(directory).resolve()
    report = json.loads((directory / 'RELEASE-STATUS.json').read_text())
    if report.get('channel') != 'community-beta' or report.get('public_release_ready') is not False:
        raise ValueError('Expected an explicitly unsigned community beta')
    checksums = {}
    for line in (directory / 'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if Path(name).name != name or name in checksums: raise ValueError('Unsafe checksum entry')
        checksums[name] = digest
        if sha(directory / name) != digest: raise ValueError('Changed artifact: ' + name)
    files = {p.name for p in directory.iterdir() if p.is_file() and p.name != 'SHA256SUMS.txt'}
    if set(checksums) != files: raise ValueError('Artifact checksum inventory differs')
    packages = list(directory.glob('*.pkg'))
    if len(packages) != 1: raise ValueError('Expected one installer')
    package = packages[0]
    if sha(package) != report['installer_sha256']: raise ValueError('Installer changed')
    app = directory / APP_NAME
    hashes = components(app)
    if hashes != report['components']: raise ValueError('Staged app changed')
    if installed_bytes(app) > APP_BUDGET or package.stat().st_size > INSTALLER_BUDGET:
        raise ValueError('Beta exceeds its size budget')
    inspect_pkg(package, hashes)
    provenance = json.loads((directory / 'SOURCE-PROVENANCE.json').read_text())
    if sha(directory / 'SOURCE-PROVENANCE.json') != report['source_provenance_sha256']:
        raise ValueError('Source provenance changed')
    if sha(directory / 'Wizard101-Source.tar.gz') != provenance['project_archive_sha256'] or sha(directory / 'Wizard101-Dependency-Sources.tar.gz') != provenance['dependency_archive_sha256']:
        raise ValueError('Corresponding source archive changed')
    verify_sources(directory, provenance)
    if require_live:
        validate_beta_live(evidence or {}, hashes, sha(package))
        # Observations stay local and are deliberately excluded from upload.
        if not all(isinstance(evidence.get('observations', {}).get(gate), str) and evidence['observations'][gate].strip()
                   for gate in BETA_LIVE_GATES):
            raise ValueError('Record a brief local observation for every live gate')
    return report


def release_assets(directory):
    return sorted(p for p in Path(directory).iterdir() if p.is_file())


def draft(directory, repo, tag, target):
    directory = Path(directory).resolve()
    verify(directory, require_live=False)
    subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--target', target,
                    '--draft', '--prerelease', '--title', 'Wizard101 Standalone — Community Beta (qualification pending)',
                    '--notes-file', str(directory / 'COMMUNITY-BETA.md'), *map(str, release_assets(directory))], check=True)


def publish(directory, evidence, repo, tag, target):
    directory = Path(directory).resolve()
    report = verify(directory, evidence)
    releases = json.loads(subprocess.check_output(['gh', 'release', 'list', '--repo', repo,
                          '--json', 'tagName,isDraft', '--limit', '100'], text=True))
    existing = next((release for release in releases if release['tagName'] == tag), None)
    if existing and existing['isDraft'] is not True: raise ValueError('Refusing to overwrite a public release')
    report.update(community_beta_ready=True, beta_pending_gates=[], live_evidence_verified=True, blocked_on=[])
    (directory / 'RELEASE-STATUS.json').write_text(json.dumps(report, indent=2) + '\n')
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.name != 'SHA256SUMS.txt')
    (directory / 'SHA256SUMS.txt').write_text(''.join(sha(p) + '  ' + p.name + '\n' for p in files))
    # A failed upload leaves a draft, never a partially uploaded public release.
    if not existing:
        subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--target', target,
                    '--draft', '--prerelease', '--title', 'Wizard101 Standalone — Community Beta',
                    '--notes-file', str(directory / 'COMMUNITY-BETA.md'),
                    *map(str, files), str(directory / 'SHA256SUMS.txt')], check=True)
    else:
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', repo, '--clobber',
                        *map(str, release_assets(directory))], check=True)
    subprocess.run(['gh', 'release', 'edit', tag, '--repo', repo, '--draft=false', '--prerelease',
                    '--title', 'Wizard101 Standalone — Community Beta',
                    '--notes-file', str(directory / 'COMMUNITY-BETA.md')], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--live-evidence', type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--publish', action='store_true', help='Publish after live qualification; otherwise verify only')
    actions.add_argument('--draft', action='store_true', help='Upload a private draft after artifact checks; never publish')
    parser.add_argument('--repo')
    parser.add_argument('--tag')
    parser.add_argument('--target', help='Existing GitHub commit or branch containing the corresponding sources')
    args = parser.parse_args()
    if args.publish or args.draft:
        if not all((args.repo, args.tag, args.target)): parser.error('--publish requires --repo, --tag and --target')
    if args.draft:
        draft(args.artifacts, args.repo, args.tag, args.target)
    elif args.publish:
        if not args.live_evidence: parser.error('--publish requires --live-evidence')
        evidence = json.loads(args.live_evidence.read_text())
        publish(args.artifacts, evidence, args.repo, args.tag, args.target)
    else:
        if not args.live_evidence: parser.error('Verification requires --live-evidence; use --draft to stage without live passes')
        evidence = json.loads(args.live_evidence.read_text())
        verify(args.artifacts, evidence)
        print('Beta artifacts and live qualification verified; nothing published.')
