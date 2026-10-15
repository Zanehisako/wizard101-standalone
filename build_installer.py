#!/usr/bin/env python3
"""Build and inspect an offline, fixed-location macOS product installer."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

APP_NAME = 'Wizard101 Standalone.app'
PACKAGE_ID = 'org.wizard101native.mac.installer'
ROOT = Path(__file__).resolve().parent


def component_settings(records):
    for record in records:
        record.update(BundleIsRelocatable=False, BundleIsVersionChecked=False,
                      BundleHasStrictIdentifier=True, BundleOverwriteAction='upgrade')
        component_settings(record.get('ChildBundles', []))
    return records


def build_pkg(app, output, installer_identity=None):
    app, output = Path(app).resolve(), Path(output).resolve()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    with tempfile.TemporaryDirectory(prefix='.pkg-', dir=output.parent) as tmp:
        work = Path(tmp)
        root = work / 'Root'; root.mkdir()
        subprocess.run(['cp', '-cR', str(app), str(root / APP_NAME)], check=True)
        settings = work / 'Components.plist'
        subprocess.run(['pkgbuild', '--analyze', '--root', str(root), str(settings)], check=True, capture_output=True)
        records = component_settings(plistlib.loads(settings.read_bytes()))
        settings.write_bytes(plistlib.dumps(records))
        component = work / 'Standalone.pkg'
        subprocess.run(['pkgbuild', '--root', str(root), '--component-plist', str(settings),
                        '--identifier', PACKAGE_ID, '--version', info['CFBundleVersion'],
                        '--install-location', '/Applications', '--ownership', 'recommended',
                        '--min-os-version', '13.0', '--compression', 'latest', str(component)],
                       check=True, capture_output=True)
        requirements = work / 'Requirements.plist'
        requirements.write_bytes(plistlib.dumps({'arch': ['arm64'], 'os': ['13.0']}))
        distribution = work / 'Distribution'
        subprocess.run(['productbuild', '--synthesize', '--product', str(requirements),
                        '--package', str(component), str(distribution)], check=True, capture_output=True)
        document = ET.parse(distribution); product = document.getroot()
        ET.SubElement(product, 'title').text = 'Wizard101 Standalone — Community Beta'
        for tag, page in [('welcome', 'INSTALL.html'), ('conclusion', 'CONCLUSION.html')]:
            ET.SubElement(product, tag, {'file': page, 'mime-type': 'text/html'})
        options = product.find('options')
        if options is None:
            options = ET.SubElement(product, 'options')
        options.set('hostArchitectures', 'arm64')
        options.set('customize', 'never')
        options.set('require-scripts', 'false')
        ET.SubElement(product, 'domains', {'enable_anywhere': 'false',
                      'enable_currentUserHome': 'false', 'enable_localSystem': 'true'})
        document.write(distribution, encoding='utf-8', xml_declaration=True)
        command = ['productbuild', '--distribution', str(distribution),
                   '--package-path', str(work), '--resources', str(ROOT / 'installer')]
        if installer_identity:
            if not installer_identity.startswith('Developer ID Installer:'):
                raise ValueError('A signed PKG requires a Developer ID Installer certificate')
            command += ['--sign', installer_identity, '--timestamp']
        subprocess.run(command + [str(output)], check=True, capture_output=True)
    return inspect_pkg(output)


def inspect_pkg(package, expected_components=None):
    with tempfile.TemporaryDirectory(prefix='w101-pkg-audit-') as tmp:
        expanded = Path(tmp) / 'Expanded'
        subprocess.run(['pkgutil', '--expand-full', str(package), str(expanded)], check=True, capture_output=True)
        product = ET.parse(expanded / 'Distribution').getroot()
        if product.find('options').get('hostArchitectures') != 'arm64':
            raise ValueError('Installer must require Apple Silicon')
        minimum = product.find('volume-check/allowed-os-versions/os-version')
        if minimum is None or minimum.get('min') != '13.0':
            raise ValueError('Installer must require macOS 13+')
        domains = product.find('domains')
        if domains is None or domains.get('enable_anywhere') != 'false' or domains.get('enable_currentUserHome') != 'false':
            raise ValueError('Installer must target the system Applications folder')
        components = list(expanded.glob('*.pkg/PackageInfo'))
        if len(components) != 1:
            raise ValueError('Expected one offline component')
        info = ET.parse(components[0]).getroot()
        if info.get('install-location') != '/Applications' or info.get('identifier') != PACKAGE_ID:
            raise ValueError('Unexpected install destination or receipt identifier')
        relocate = info.find('relocate')
        if info.get('relocatable') != 'false' or (relocate is not None and len(relocate)):
            raise ValueError('Installer relocation must be disabled')
        if info.find('scripts') is not None or list(expanded.rglob('Scripts')):
            raise ValueError('Offline installer must not have scripts')
        payload = components[0].parent / 'Payload'
        if {p.name for p in payload.iterdir()} != {APP_NAME}:
            raise ValueError('Installer contains unexpected payloads')
        app = payload / APP_NAME
        if expected_components is not None:
            from package_shipping import components as hashes
            if hashes(app) != expected_components:
                raise ValueError('Installer payload differs from staged app')
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)
        return dict(contents_verified=True, relocation_disabled=True, scripts_present=False,
                    offline=True, minimum_macos='13.0', architectures=['arm64'],
                    install_path='/Applications/' + APP_NAME,
                    payload_components_verified=expected_components is not None)
