#!/usr/bin/env python3
"""Check a qualified account candidate, or replace the app while retaining rollback.

No installation occurs without --install. Game data and preferences are external
to the app and are never touched by this helper.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import uuid

from account_qualification import validate_accounts
from build_installer import inspect_pkg
from package_shipping import components, sha

BUNDLE_ID = 'org.wizard101native.mac'


def require_launcher(app):
    app = Path(app)
    if app.is_symlink() or not app.is_dir():
        raise ValueError('Use a real standalone app bundle')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != BUNDLE_ID:
        raise ValueError('Expected the Wizard101 Standalone launcher')


def require_idle():
    processes = subprocess.check_output(['ps', '-axo', 'comm='], text=True)
    if any('Wizard101Native' in line or 'WizardGraphicalClient' in line for line in processes.splitlines()):
        raise ValueError('Close Wizard101 and both launchers before replacing the app')


def verify_signature(app):
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)],
                   check=True, capture_output=True)


def replace_app(app, target, expected):
    """Stage and verify first; rename the old bundle and retain it as rollback."""
    app, target = Path(app).resolve(), Path(target).absolute()
    require_launcher(app); require_launcher(target)
    if app == target or app.is_relative_to(target) or target.is_relative_to(app):
        raise ValueError('Candidate and installed app must be separate bundles')
    require_idle(); verify_signature(app)
    if components(app) != expected:
        raise ValueError('Candidate changed after qualification')
    previous = components(target)
    stage = target.with_name('.Wizard101-account-stage-' + uuid.uuid4().hex + '.app')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = target.with_name(target.stem + ' previous-' + stamp + '.app')
    try:
        subprocess.run(['cp', '-cR', str(app), str(stage)], check=True)
        verify_signature(stage)
        if components(stage) != expected or components(app) != expected or components(target) != previous:
            raise ValueError('App changed during staging; nothing was installed')
        require_idle()
        target.rename(backup)
        try:
            stage.rename(target)
        except BaseException:
            backup.rename(target)
            raise
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return backup


def qualify(app, installer, evidence):
    require_launcher(app)
    hashes = components(app)
    validate_accounts(evidence, hashes, sha(installer))
    verify_signature(app)
    inspect_pkg(installer, hashes)
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--target', type=Path, default=Path('/Applications/Wizard101 Standalone.app'))
    parser.add_argument('--install', action='store_true', help='Replace only after every live check passes')
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text())
    hashes = qualify(args.app, args.installer, evidence)
    result = dict(qualified=True, installed=False)
    if args.install:
        backup = replace_app(args.app, args.target, hashes)
        result.update(installed=True, backup=str(backup),
                      rollback='Close the game and launcher, move the new app aside, and rename this backup to the original app name in Finder.')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
