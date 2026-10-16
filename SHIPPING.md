# Shipping Wizard101 for Apple Silicon

This guide covers generated app packages and the steps a maintainer must complete
before public distribution. For player setup, source-build prerequisites, import,
backups and troubleshooting, start with [the full setup guide](README.md).
There is currently no published notarized release on this repository.

## Unsigned community beta installer

The community beta requires no paid Apple membership. It is intentionally
unsigned and unnotarized, with `public_release_ready: false`. Player instructions
and remaining qualification are in [COMMUNITY-BETA.md](COMMUNITY-BETA.md); the
installer includes [illustrated Open Anyway instructions](installer/INSTALL.html).
The signed DMG workflow below remains available separately.

Build from the isolated `a5d4dc1` Standalone Candidate baseline plus the beta
launcher/packaging changes. Do not package a stutter-overhaul app or its runtime.

```sh
python3 package_shipping.py \
  --base-app "/path/to/Wizard101 Standalone Candidate.app" \
  --format pkg --channel community-beta --output dist/community-beta
```

The packager compiles the launcher, clones the base, strips PE debug sections
and unused COFF symbols using MinGW binutils (or an explicitly selected
`--pe-strip`), and checks every retained section byte, RVA, size and protection.
It verifies loader headers and all non-debug data directories, including imports,
exports, relocations, exception/unwind records and resources. It retains all
runtime modules and Mach-O libraries. Renderer/adapter hashes are regenerated,
then nested ad-hoc signatures and the app resource seal are regenerated.

Original changed PE images and their hashes are retained under
`Maintainer-Debug/Wizard101-Debug-Originals.tar.gz`, outside the app and GitHub
upload set. `Runtime/SizeReduction.json` maps original and stripped hashes.
The app must fit 350 MiB and the PKG 150 MiB, excluding downloaded game content.

`pkgbuild` and `productbuild` create a standard offline installer for Apple
Silicon/macOS 13+. It has no installation scripts or network actions. The sole
payload is `/Applications/Wizard101 Standalone.app`. Relocation is disabled for
the main bundle and helper, preventing matching by bundle ID on the Desktop.
Reinstallation atomically replaces this named app. The official app and existing
data are preserved. The bundle identifier, Keychain service and default data
directory are unchanged. Rosetta is handled by Apple's prompt after installation.

The source archives include the exact exported source file hashes and all pinned
dependency archives, validated by `SOURCE-PROVENANCE.json`. Build machines need
the existing source cache (including the pinned CrossOver source release) plus
LLVM or MinGW binutils. `SHA256SUMS.txt` covers all public artifact files.

Before publication, copy `BETA-LIVE-TEMPLATE.json` to a private verification
directory and complete **actual** checks, recording a short observation for each.
Automated fixtures do not count as fresh-user, missing-Rosetta or gameplay passes.
Use `publish_beta.py dist/community-beta --draft --repo OWNER/REPO --tag TAG
--target BETA_SOURCE_COMMIT` to upload a private draft while live checks are
pending. This performs artifact verification and never publishes the release.
Validate without publishing:

```sh
python3 publish_beta.py dist/community-beta \
  --live-evidence verification-local/beta-live.json
```

Once every beta gate passes on the exact final app/PKG, publish one GitHub
prerelease using an existing repository commit/branch for the corresponding source:

```sh
python3 publish_beta.py dist/community-beta \
  --live-evidence verification-local/beta-live.json --publish \
  --repo OWNER/REPO --tag v3.1-community-beta.1 --target BETA_SOURCE_COMMIT
```

The publisher verifies hashes, extracted PKG payload, size, corresponding sources
and live evidence before uploading. It creates a draft first and publishes only
after all assets upload. It excludes the staged app and maintainer debug folder.
`public_release_ready` stays false even when beta qualification passes.

An explicitly requested experimental prerelease can be uploaded while gameplay
qualification is pending. It runs the same artifact, installer and source checks,
but keeps `community_beta_ready: false`, `live_evidence_verified: false` and every
pending gate. Its title and notes must clearly identify experimental support:

```sh
python3 publish_beta.py dist/community-beta --publish-experimental \
  --repo OWNER/REPO --tag v3.2-community-beta.1 --target BETA_SOURCE_COMMIT
```

This does not qualify gameplay or authorize the gated installed-app replacement.
Keep the previous release and working local app available for rollback.

For signed PKG builds, use `--format pkg --identity ... --notary-profile ...`
and a separate `--installer-identity "Developer ID Installer: ..."` certificate.
The existing signed-app live evidence and notarization gates still apply.

## Install a supplied package

1. Open `Wizard101-AppleSilicon-candidate.dmg` and drag **Wizard101** to
   **Applications**. Eject the disk image and open the app from Applications.
2. If needed, choose **Install Rosetta**, complete Apple's prompt, return to
   the launcher, and choose **Check again**.
3. Choose **Install Wizard101**, or import the game folder containing `Bin`
   and `Data`. Interrupted downloads resume when setup is retried.
4. Enter a **US standalone** account and choose **Play**. Password saving is
   optional and uses Mac Keychain. The launcher checks updates before play and
   exits after handing off to the game.

The app targets Apple Silicon, macOS 13+, and Rosetta while Apple supports it.
Apple documents general Rosetta availability through macOS 27; macOS 28 is not
qualified. The 3.2 beta supports US / Steam selection with
[experimental Steam integration](ACCOUNTS.md) and pending account qualification.
The previous US-only 3.1 release remains available for rollback. EU accounts
are unsupported. Game content is downloaded
from KingsIsle. A complete app needs neither CrossOver nor build tools.

The gear opens Settings. **Magical effects** is saved, honors Reduce Motion,
and pauses while the launcher is inactive or minimized. **60 FPS** is the
default; uncapped play and advanced controls are optional. Game graphics and
resolution are configured inside Wizard101.

## Current release status

The supplied artifact is a **test candidate**, not a public-ready release.
`RELEASE-STATUS.json` records its component hashes, audit, self-tests and blockers.
Fresh setup and graphics probes are separate from real sign-in/gameplay
acceptance. Unsupported future game executable revisions require a compatibility
update; authentication stops before sending credentials when validation fails.

The fully qualified signed release requires a **Developer ID Application** certificate, hardened
runtime, Apple notarization and stapling. An Apple Development certificate is
insufficient. Ad-hoc candidates do not provide the normal trusted double-click
experience on other Macs. For a trusted test copy blocked by macOS, follow
[Apple's app-opening guidance](https://support.apple.com/en-us/102445).
Do not disable Gatekeeper or clear quarantine with shell commands.

The current development checks do not qualify native login, character selection,
real gameplay, accepted performance, another Apple Silicon Mac, first-time
Rosetta installation, or macOS 13 gameplay. A complete clean rebuild of the
retained Arrival overlays also remains pending. The base standalone source build
and the retained Arrival renderer are different build paths.

## Package a local candidate

Run commands from this source directory: `portable/` in a Git checkout, or the
root of an extracted shipping source archive. Install the developer tools and
build a complete base app using [the source-build instructions](README.md#build-from-source).
A CrossOver wrapper or a launcher-only `--development` app is not a complete base.

The shipping source bundle also includes the pinned decoder inputs. If they were
not supplied through the dependency archive, fetch them using the verified
project downloader:

```sh
python3 - <<'PY'
import json
from build_runtime import ROOT, download
entries = json.loads((ROOT / 'decompression/sources.lock.json').read_text())
for name, entry in entries.items():
    archive = name + '-' + entry['revision'][:8] + '.tar.gz'
    download(archive, entry['url'], entry['sha256'])
PY
python3 package_shipping.py --base-app "dist/Wizard101 Native.app" \
  --output dist/shipping-candidate
```

Use an output directory that does **not** already exist. The packager compiles
the current launcher, stages a separate app, audits dependencies/signatures and
macOS targets, runs launcher self-tests, creates a drag-to-Applications DMG,
exports corresponding sources and writes checksums. It does not change the base
app or game data. Runtime and renderer components are copied from the selected
base, except for an explicitly supplied source-verified Wine bridge replacement.
Experimental controls start off in the new shipping preference domain;
diagnostic capture defaults off.

| Output | Contents |
| --- | --- |
| `Wizard101.app` | Complete standalone app; game content is installed separately. |
| `Wizard101-AppleSilicon-candidate.dmg` | App, Applications shortcut and short installation instructions. |
| `Wizard101-Source.tar.gz` | Clean project sources, overlays, build scripts, tests and notices. |
| `Wizard101-Dependency-Sources.tar.gz` | Checksum-pinned public dependency source archives under `cache/`. |
| `SHIPPING.md` | This guide. |
| `RELEASE-STATUS.json` | Exact component hashes, automated checks and release status. |
| `SHA256SUMS.txt` | Checksums for the delivered files. |

Verify the files from the output directory:

```sh
cd dist/shipping-candidate
shasum -a 256 -c SHA256SUMS.txt
```

### Retained Arrival Wine bridge

The retained Arrival app had a Wine Unix bridge linked for macOS 26. The bundle
audit rejects that mismatch with the declared macOS 13 target. A new base source
build already sets the deployment target; it does not need this repair.

For that retained Arrival base, rebuild the bridge from pinned Wine sources and
the identical dispatch, diagnostic and native-decode overlays. This compiles
source for macOS 13; it does not rewrite a binary's deployment label:

```sh
python3 rebuild_shipping_wine.py --work /private/tmp/w101-shipping-wine
python3 package_shipping.py --base-app "/path/to/Wizard101 Arrival Candidate.app" \
  --wine-fix /private/tmp/w101-shipping-wine \
  --output dist/arrival-shipping-candidate
```

The pinned dependency cache and listed developer tools are required. The repair
records its inputs and rebuilt library hash; packaging rejects changed sources
or a changed replacement library. This bridge rebuild alone does not prove a
clean rebuild of every retained Arrival overlay. Follow
[ARRIVAL-CANDIDATE.md](ARRIVAL-CANDIDATE.md) and its prerequisite guides for those.

## Developer ID signing and notarization

Maintainers need an Apple Developer account with an available **Developer ID
Application** certificate and private key. Check installed signing identities:

```sh
security find-identity -v -p codesigning
```

Configure a notarytool Keychain profile interactively. Enter the requested Apple
credentials in its prompts; do not put passwords in scripts or repository files:

```sh
xcrun notarytool store-credentials "w101-notary"
```

Then package a signed candidate, replacing the identity with your actual
certificate name:

```sh
python3 package_shipping.py --base-app "dist/Wizard101 Native.app" \
  --output dist/signed-shipping-candidate \
  --identity "Developer ID Application: Your Name (TEAMID)" \
  --notary-profile "w101-notary"
```

For the retained Arrival base, also pass its validated `--wine-fix` directory.
Both `--identity` and `--notary-profile` are required together. The workflow signs
nested native code from the inside out with hardened runtime, notarizes and
staples the app and DMG, validates tickets, and assesses the app with Gatekeeper.
Only public app artifacts are submitted to Apple. Wine receives its executable
memory and library-search entitlements; the native launcher needs neither.
The workflow must be verified using an actual Developer ID certificate before
release. A successful notarization still produces a **candidate** until live
acceptance is complete.

## Qualify the exact signed app

Test the final signed, notarized candidate using [RELEASE-GATES.md](RELEASE-GATES.md).
Keep the working installation until the user accepts real gameplay. Include a
second Apple Silicon Mac, the oldest supported macOS, and a Mac without Rosetta
for the first-install prompt. Record observations without credentials, session
keys, private login command lines or captured game shaders.

Create a local evidence template bound to the final app. Every gate starts false:

```sh
python3 - <<'PY'
import json
from pathlib import Path
from package_shipping import components
app = Path('dist/signed-shipping-candidate/Wizard101.app')
gates = [
    'fresh_install_gameplay', 'native_login', 'character_selection',
    'session_survives_launcher_exit', 'audio', 'keyboard_mouse', 'cursor',
    'fullscreen', 'graphics', 'updates', 'gui_cancel_resume',
    'performance_accepted', 'rosetta_first_run', 'second_apple_silicon_mac',
    'oldest_supported_macos', 'clean_source_rebuild',
]
evidence = {'components': components(app), 'gates': dict.fromkeys(gates, False)}
output = Path('verification-local/shipping-live.json')
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(evidence, indent=2) + '\n')
PY
```

Set a gate true only after its actual check passes, with supporting observations
kept locally. A synthetic check cannot pass a gameplay gate. Do not rebuild or
re-sign this app after testing: changed components invalidate the evidence.

Once **all** gates pass, create a public package from that exact tested app:

```sh
python3 package_shipping.py --base-app "dist/Wizard101 Native.app" \
  --verified-app "dist/signed-shipping-candidate/Wizard101.app" \
  --live-evidence verification-local/shipping-live.json \
  --output dist/public-release \
  --identity "Developer ID Application: Your Name (TEAMID)" \
  --notary-profile "w101-notary"
```

`--base-app` remains a required argument, but the `--verified-app` path supplies
the final payload. The tested app is copied without re-signing. The packager
checks its identity, notarization ticket, Gatekeeper assessment, current launcher
source stamp, exact component hashes and all live gates. A successful public
package uses `Wizard101-AppleSilicon.dmg` and sets `public_release_ready` true.
Distribute its source archives and notices alongside the app. Packaging does not
publish a GitHub Release automatically.

## Source and licensing

To rebuild from shipping sources, extract the project, change into its root,
then extract the dependency cache there:

```sh
tar -xzf Wizard101-Source.tar.gz
cd Wizard101-Source
tar -xzf ../Wizard101-Dependency-Sources.tar.gz
python3 build.py
```

Install the [developer toolchain](README.md#build-from-source) first. This builds
the base standalone app. The retained Arrival overlays still require their
prerequisite trees and are not a single verified clean rebuild command.
`W101_RUNTIME_ROOT` supports local runtime replacement/relinking. Modified
bundles require their own signatures and acceptance checks.

The source archive contains launcher code, original fallback illustration/icon
source, runtime/renderer/Wine overlays, tests and notices. Official Ravenwood
artwork and the Wizard101 logo are fetched separately over HTTPS, verified
against pinned hashes and cached for offline use. Those KingsIsle assets are
not bundled into the app or source archive and are not MIT artwork. An artwork
failure does not block setup or gameplay.

Wine and libraries retain their licenses; original launcher/build/test code and
original artwork use MIT. Wizard101 and its game assets, macOS and Rosetta belong
to their owners. This is an unofficial community project.

Apple references: [Rosetta](https://support.apple.com/en-us/102527),
[notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
