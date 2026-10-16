#!/usr/bin/env python3
"""Build a separate local Steam diagnostic app, preserving the installed app."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

from build_app import build
from package_shipping import components, stage_app


def diagnostic(base, output):
    base, output = Path(base).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Use a fresh diagnostic app path; previous candidates are retained')
    if output == Path('/Applications/Wizard101 Standalone.app'):
        raise ValueError('The diagnostic candidate must not replace the installed launcher')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.steam-diagnosis-', dir=output.parent) as temp:
        work = Path(temp)
        launcher = build(output=work / 'Launcher.app', development=True)
        candidate = stage_app(base, launcher, work / output.name, standalone=True)
        plist = candidate / 'Contents/Info.plist'
        info = plistlib.loads(plist.read_bytes())
        info.update(CFBundleName='Wizard101 Steam Diagnosis', CFBundleDisplayName='Wizard101 Steam Diagnosis',
                    W101AuthenticationDiagnostics=True)
        plist.write_bytes(plistlib.dumps(info, sort_keys=False))
        subprocess.run(['codesign', '--force', '--sign', '-', str(candidate)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(candidate)], check=True)
        result = json.loads(subprocess.check_output([str(candidate / 'Contents/MacOS/Wizard101Native'), '--self-test'], text=True))
        report = dict(diagnostic_candidate=True, self_tests_passed=result['passed'],
                      steam_gameplay_verified=False, installed_launcher_replaced=False,
                      components=components(candidate))
        shutil.move(str(candidate), output)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    diagnostic(args.base_app, args.output)
