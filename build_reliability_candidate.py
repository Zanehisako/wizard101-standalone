#!/usr/bin/env python3
"""Build a separate diagnostic candidate from retained 3.2 build 8 or build 15."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

from build_app import build, launcher_inputs
from package_shipping import components, stage_app

from reliability_qualification import GATES


def candidate(base, output, launcher=None, build_number='14'):
    base, output = Path(base).resolve(), Path(output).resolve()
    info = plistlib.loads((base / 'Contents/Info.plist').read_bytes())
    base_build = info.get('CFBundleVersion')
    if info.get('CFBundleShortVersionString') != '3.2' or base_build not in ('8', '15'):
        raise ValueError('The diagnostic candidate requires retained 3.2 build 8 or build 15')
    if not str(build_number).isdigit() or int(build_number) < max(10, int(base_build) + 1):
        raise ValueError('A diagnostic candidate must have a newer build number than its retained base')
    if output.exists() or output == base or base in output.parents or output.parent == Path('/Applications'):
        raise ValueError('Use a fresh local candidate path; installed apps and prior candidates are retained')
    before = components(base)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.reliability-', dir=output.parent) as folder:
        work = Path(folder)
        launcher = Path(launcher).resolve() if launcher else build(output=work / 'Launcher.app', development=True)
        app = stage_app(base, launcher, work / output.name, standalone=True)
        plist = app / 'Contents/Info.plist'
        updated = plistlib.loads(plist.read_bytes())
        updated.update(CFBundleName='Wizard101 Reliability Candidate',
                       CFBundleDisplayName='Wizard101 Reliability Candidate', CFBundleVersion=str(build_number),
                       W101ReliabilityCandidate=True, W101DistributionChannel='local-diagnostic-candidate')
        if base_build == '15':
            updated.update(CFBundleName=f'Wizard101 Diagnostics Build {build_number}',
                           CFBundleDisplayName=f'Wizard101 Diagnostics Build {build_number}')
        # Share the existing preference domain and prefix without migrating data.
        updated.pop('W101AuthenticationDiagnostics', None)
        plist.write_bytes(plistlib.dumps(updated, sort_keys=False))
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True, capture_output=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)
        result = json.loads(subprocess.check_output([str(app / 'Contents/MacOS/Wizard101Native'), '--self-test'], text=True))
        after = components(app)
        for relative, digest in before.items():
            if relative.startswith(('Contents/Resources/Runtime/', 'Contents/Resources/Renderer/')) and after.get(relative) != digest:
                raise ValueError('Candidate changed a runtime or renderer component: ' + relative)
        if components(base) != before:
            raise ValueError('Retained base app changed during candidate build')
        report = dict(candidate=True, base_version='3.2', base_build=base_build, build=str(build_number), visual_preload_default=True,
                      diagnostic_report_schema=3, transfer_observation_limit=20,
                      optional_archive_streaming_recovery='explicit_single_attempt_after_optional_http_403_404_or_interrupted_verified_dynamic_archive',
                      self_tests_passed=result['passed'], public_release_ready=False,
                      installed_launcher_replaced=False, graphics_fix_verified=False, alt_tab_fix_verified=False,
                      live_evidence_verified=False, runtime_renderer_unchanged=True,
                      components=after, base_components=before, launcher_inputs=launcher_inputs(),
                      gates={gate: False for gate in GATES}, observations={})
        shutil.move(str(app), output)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, help='Reuse a launcher compiled from these exact sources')
    parser.add_argument('--build-number', default='14')
    args = parser.parse_args()
    candidate(args.base_app, args.output, args.launcher, args.build_number)
