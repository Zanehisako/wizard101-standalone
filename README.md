# Wizard101 Native: install and setup guide

This unofficial Apple Silicon app runs the Windows Wizard101 client using bundled
open-source Wine 11.0, D9VK and MoltenVK 1.4.2. CrossOver is not required. The
native launcher installs the game, checks updates and handles sign-in. Its UI
uses official Wizard101 artwork fetched and cached separately, parchment panels,
and optional animated effects.

> **[Join our Discord for feedback and help →](https://discord.gg/b2KVmJ84P)**
>
> Discord is our main contact for bug reports, questions and suggestions.
> [How to reach us](#feedback-and-support).

**Latest: [3.2 beta 2 — sign-in and content recovery](https://github.com/Zanehisako/wizard101-standalone/releases/tag/v3.2-community-beta.2).**
[Download the complete installer](https://github.com/Zanehisako/wizard101-standalone/releases/download/v3.2-community-beta.2/Wizard101-AppleSilicon-community-beta.pkg),
then choose **US / Steam**. Both providers share installed content and settings;
saved accounts and Keychain passwords are separate. The owner confirmed Steam
working locally on 2026-10-16. The complete two-provider gameplay, relaunch and
ten-minute handoff qualification remains pending. See [account setup](ACCOUNTS.md)
and [verification details](BETA-QUALIFICATION.md).

Build 15 adds bounded sign-in, resumable visual downloads and verified content
recovery. Before Play, the launcher attempts full visual preload. After an
eligible download failure, **Use streaming once** continues for that attempt;
the next Play returns to full preload. Streaming does not mark visual readiness
complete or establish that missing graphics are fixed.

This release is **unsigned and not notarized**; follow macOS **Open Anyway**
in the [installation guide](COMMUNITY-BETA.md). Keep your previous app for rollback.
The [US-only 3.1 beta](https://github.com/Zanehisako/wizard101-standalone/releases/tag/v3.1-community-beta.1)
remains available. Developer ID, notarization, additional-Mac/oldest-macOS gameplay
and a clean retained Arrival rebuild remain [signed-release gates](SHIPPING.md).

## Feedback and support

1. [Join our Discord server](https://discord.gg/b2KVmJ84P).
2. Accept the invite in your browser or Discord app, then post your feedback or question in the server.

For a bug, include the app version, your Mac/macOS, **US or Steam**, and what
happened. Reproduction steps and a screenshot help. Thank you for helping improve the project!

## Choose your setup path

The smaller unsigned installer workflow is documented in
[Community Beta](COMMUNITY-BETA.md). It installs **Wizard101 Standalone.app**,
offers detected game imports and guided setup, and requires macOS Open Anyway
approval. The app stays below 350 MiB and the installer below 150 MiB, excluding
downloaded game content. Exact sizes and hashes accompany each release. `public_release_ready` remains false for this unsigned beta.
Additional testers can open the release’s `LIVE-CHECKS.html` to record
observations without Terminal.

| What you have | What to do |
| --- | --- |
| A community beta `.pkg` | Follow [the illustrated installer guide](installer/INSTALL.html), then Prepare Mac → Install or reuse game → Sign in and Play. |
| A complete DMG or candidate app archive | Follow [install the app](#install-the-app). No development tools are needed. |
| A Wizard101 game folder you want to reuse | Follow [import an existing installation](#import-an-existing-installation). |
| Only this Git checkout | Follow [build from source](#build-from-source), then install the resulting app. |
| Project and dependency source archives | Follow [use the supplied source archives](#use-the-supplied-source-archives). |
| A standalone app you want to distribute | Follow [create a disk image](#create-a-disk-image), then [signing and release](SHIPPING.md#developer-id-signing-and-notarization). |

## Requirements

- Apple Silicon and macOS 13 or later, while Rosetta is available. The minimum
  deployment target is audited; live acceptance on macOS 13 is still pending.
- Rosetta for the bundled x64 runtime. Use the launcher's **Install Rosetta**
  button and Apple's guided prompt if it is absent.
- A US standalone Wizard101 account or US Wizard101 account created through
  Steam. Steam requires the installed Mac Steam client, signed in and online;
  see [account setup and pending qualification](ACCOUNTS.md).
  EU login, Intel Macs and macOS 28 are not qualified.
- Internet access and free storage for the app, prefix, game and resumable staging.
  The launcher calculates the current space needed for full visual preload.
  A small startup download is not the complete visual installation; allow space
  for additional game content and updates.

See [Apple's Rosetta documentation](https://support.apple.com/en-us/102527).
Full Xcode, Homebrew and compilers are needed only to build or verify source,
not to run a complete app.

## Install the app

1. Open `Wizard101-AppleSilicon-candidate.dmg`.
2. Drag **Wizard101** to **Applications**, then eject the disk image. If you have
   the base-build ZIP instead, extract it and move **Wizard101 Native.app** to
   Applications. Keep the app bundle intact; do not copy out its executable.
3. Open the app from Applications. If **Install Rosetta** appears, select it,
   complete Apple's prompt, return to the launcher, and select **Check again**.
4. Select **Install Wizard101**. Setup creates an independent Windows environment
   and downloads official game content. It suppresses optional Wine Mono/Gecko
   installer dialogs; those components are not needed by this C++ client.
5. Wait for the username/password form. Select **Cancel** if needed; partial
   downloads remain staged. Reopen the same app and select Install again to retry.
6. Choose **US** or **Steam**, enter that Wizard101 account’s username and
   password, then select **Play**.
   Command-V and Command-A work in the form. **Remember me** is optional and
   stores the password in Mac Keychain.

A complete app does not need this repository, build outputs, dependency source
archives, or an installed CrossOver. Keep your working game installation until
this candidate has passed your real gameplay checks. Current candidates use
ad-hoc signing; they are not the final trusted public distribution. For a
blocked downloaded test app, follow [Apple's app-opening guidance](https://support.apple.com/en-us/102445)
after verifying its origin. Do not disable Gatekeeper or clear quarantine using
Terminal commands.

## Import an existing installation

Use this instead of fresh installation during first-time setup:

1. Close the game and its official launcher.
2. Select **Already installed? Import game…**.
3. Choose the **Wizard101 game folder containing `Bin` and `Data`**. Inside an
   existing Wine/CrossOver prefix it is commonly
   `drive_c/ProgramData/KingsIsle Entertainment/Wizard101`.
4. Wait for the copy and update check, then sign in normally.

Do not select a macOS app bundle, `drive_c`, or the entire bottle. The import
copies game data and configuration into a separate prefix; it does not move the
source installation. APFS clones may share storage blocks but do not share
writable file identities. Prefix registry files, credentials, official launcher
executables, logs and shader captures are not imported. Interrupted imports must
resume from the same source folder. Import is not a way to overwrite an already
configured destination.

## Play, update and change settings

Open the app, sign in, and select **Play**. In the local
[build-14 reliability candidate](RELIABILITY.md), game updates and all non-audio
GameData archives are fully verified and installed before authentication. This
includes classic scenery, every world's visual assets, equipment and numbered
Mob archives. Existing verified files are reused. The first preparation can be
large; its size comes from the current official manifest. Music and dialogue remain available through
the game's streaming system. The launcher exits when it hands off to the game.

When a qualifying optional archive download fails, **Use streaming once**
selects ordinary asset streaming for one Play attempt. Required startup files
are still verified, and the next Play attempts full visual preload again.
Some visuals may still be missing until full preparation completes.

In 3.2, choose **US** or **Steam** first. Steam uses the
Wizard101 credentials created through Steam and opens the Mac Steam client when
needed. Both providers share installed content and settings. Saved usernames,
Remember me preferences and Keychain passwords are separate. See [ACCOUNTS.md](ACCOUNTS.md)
before testing or replacing the currently installed beta.

The gear opens Settings:

| Control | Behavior |
| --- | --- |
| Magical effects | Saves the launcher effects preference. Honors Reduce Motion; pauses when inactive or minimized. Does not reduce game animations. |
| 60 FPS / Uncapped | Saves the launch frame-rate choice. 60 FPS and legacy pacing are the defaults; display/VSync settings may still limit uncapped play. |
| Check game updates | Shows checking/completion feedback. Checks without applying files; pending content installs before the next Play. |
| Forget saved password | Removes the remembered Keychain password for the entered account. |
| Advanced | Holds optional performance controls, shader preparation where available, diagnostics and launch details. |

Set resolution, fullscreen, graphics and gameplay options inside Wizard101.
Experimental performance features start off in a fresh shipping preference
profile; enable one at a time only for comparisons. **Reset to baseline** clears
experimental selections. Diagnostic timing capture is off by default and can
perturb gameplay. Remaining stutter is unresolved; synthetic gains are not a
promise of smooth gameplay.

Official Ravenwood artwork and the Wizard101 logo are downloaded over HTTPS,
checked against pinned hashes, and cached for offline reuse. Artwork is not
bundled into the MIT source/app distribution. If loading it fails, the original
illustration is a fallback; installing or starting the game remains available.

## Data, backups and removal

Standard base and shipping apps use:

| Location under `~/Library/Application Support/Wizard101 Native/` | Contents |
| --- | --- |
| `Prefix/` | The independent Wine Windows environment. |
| `Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/` | Installed game, streamed content and game configuration. |
| `State/` | Setup marker, checksum metadata and resumable update staging. |
| `State/Artwork/` | Verified website artwork cache. |
| `Prefix/drive_c/NativeLogs/` | Per-launch details; opt-in timing captures when enabled. |

App preferences live in macOS user defaults and remembered passwords in Mac
Keychain. Experimental comparison apps may declare their own data directory;
`--diagnose` prints the effective prefix and game paths. `W101_DATA_ROOT` overrides
the complete data root for developer tests.

Moving or replacing the app leaves data intact. To back up, quit the launcher
and game, then copy the effective data folder. To remove the app, move it to
Trash. Keep or back up the separate data folder before deciding to remove it;
removing the app alone does not remove game content or Keychain entries. Use
**Forget saved password** before removing the app if you want that entry removed.
The standard standalone data folder is separate from the retained Arrival
candidate and existing CrossOver bottle.

## Build from source

Use a native Apple Silicon Terminal (`uname -m` should report `arm64`). Install
[full Xcode](https://developer.apple.com/xcode/), open it and complete its initial
setup. Command Line Tools alone are insufficient for the MoltenVK build.
Install [Homebrew](https://brew.sh/) at its standard Apple Silicon prefix,
`/opt/homebrew`. Your build host must support the installed Xcode/Homebrew
versions; this is separate from the app's macOS 13 target.

Select Xcode and install dependencies:

```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcrun --find swiftc
xcrun --sdk macosx --show-sdk-path
brew install python cmake ninja meson mingw-w64 autoconf automake libtool bison pkgconf
python3 --version
x86_64-w64-mingw32-g++ --version
```

Python must be 3.12 or newer. If `brew` is not found, complete Homebrew's printed
shell setup instructions and reopen Terminal. The builder explicitly uses
`/opt/homebrew`, including its Bison and GNU Libtool paths.

For a new checkout:

```sh
mkdir -p "$HOME/Developer"
git clone https://github.com/Zanehisako/wizard101-standalone.git "$HOME/Developer/wizard101-standalone"
cd "$HOME/Developer/wizard101-standalone"
python3 build.py
```

If you already have the repository, start in its `portable/` directory instead.
The builder downloads public inputs into `cache/` and verifies SHA-256 values in
`sources.lock.json`. It builds Wine, runtime libraries, MoltenVK, the patched
base D9VK renderer, the native launcher and icon; collects license notices; runs
self-tests; audits signatures/dependencies/deployment targets; and packages:

| Output relative to `portable/` | Purpose |
| --- | --- |
| `dist/Wizard101 Native.app` | Complete base standalone app with the current launcher UI. |
| `dist/Wizard101-Native-AppleSilicon-candidate.zip` | Base app, source archives and build metadata. |
| `dist/Wizard101-Native-source/` | Clean allowlisted source export. |

The base build is **not** the exact retained Arrival renderer. Arrival overlays
need prerequisite source/build trees; see [ARRIVAL-CANDIDATE.md](ARRIVAL-CANDIDATE.md)
and its linked experiment guides. The complete clean Arrival rebuild remains a
release gate, not a verified one-command path.

Build intermediates default to `/private/tmp/w101-runtime-26.3.0`. Build logs are
in that folder's `logs/`. `BUILD_JOBS` defaults to 4. Choose an absolute build
folder with **no spaces** if you want a persistent location:

```sh
W101_BUILD_ROOT=/Users/Shared/w101-build BUILD_JOBS=4 python3 build.py
```

Use the same override on later commands that reuse those outputs. A complete
existing build can be recompiled/repackaged using `python3 build.py --package-existing`.
Pinned input archives are reproducible inputs; byte-identical output across
compiler/Xcode versions is not promised. Allow substantial additional storage
for Xcode and multiple build trees, beyond the game's installation space.

## Use the supplied source archives

The shipping package contains `Wizard101-Source.tar.gz` and
`Wizard101-Dependency-Sources.tar.gz`. In a separate workspace, extract the
project, change into its root, then extract the dependency archive there:

```sh
tar -xzf Wizard101-Source.tar.gz
cd Wizard101-Source
tar -xzf ../Wizard101-Dependency-Sources.tar.gz
python3 build.py
```

This places the locked public archives in `cache/`. Install the same developer
toolchain first. Base-build ZIPs use the older archive names
`Wizard101-Native-source.tar.gz` and `Wizard101-Native-dependency-sources.tar.gz`;
extract their project and dependency cache in the same way. No local game files
or private Git history are required by the clean shipping source export.

`W101_RUNTIME_ROOT` selects an alternate runtime directory containing `bin/wine`,
`runtime.json` and its libraries. This supports local runtime replacement and
relinking. Modified local bundles need their own signatures; they are not
covered by an earlier public signature or acceptance result.

## Verify a build and use CLI setup

Run these from `portable/` after building. The graphics probe uses a disposable
prefix and requires the MinGW toolchain; close real gameplay first.

```sh
python3 -m unittest discover -s tests
"dist/Wizard101 Native.app/Contents/MacOS/Wizard101Native" --self-test
"dist/Wizard101 Native.app/Contents/MacOS/Wizard101Native" --diagnose
python3 audit_bundle.py "dist/Wizard101 Native.app"
python3 verify_runtime.py "dist/Wizard101 Native.app"
```

These are synthetic/runtime checks, not real account or gameplay acceptance.
For isolated command-line setup, choose a separate writable data directory:

```sh
W101_DATA_ROOT="$PWD/verification-local/manual-setup/Data" \
  "dist/Wizard101 Native.app/Contents/MacOS/Wizard101Native" --setup-fresh
W101_DATA_ROOT="$PWD/verification-local/manual-setup/Data" \
  "dist/Wizard101 Native.app/Contents/MacOS/Wizard101Native" --check-updates
```

`--import-game "/path/to/Wizard101"` performs first-time import.
`--list-startup` and `--check-updates` do not replace game files.
`--prepare-content` downloads content but does not complete runtime setup.
Add `--prepare-visuals` to `--prepare-content` to fully prepare every non-audio
GameData archive, or to `--check-updates` to inspect that same scope without
replacing game files. The existing `--prepare-content --prepare-appearance`
command retains its narrower equipment/mob scope, including numbered families.
The GUI always prepares all visuals independently of optimization selections.
`--protocol-probe` tests encrypted transport without sending credentials; it
does not prove real login. Omit `W101_DATA_ROOT` only when you intend to use the
app's normal data folder. Do not run GUI setup and CLI setup on the same data
folder concurrently.

## Create a disk image

From `portable/`, use a **complete source-built standalone app** as the base.
Do not use a CrossOver wrapper app or a launcher-only `--development` build.
When starting from a fresh base build, the shipping source bundle also needs
the locked decoder source archives. Fetch them using the existing checksum
verified downloader (or supply them through the dependency source archive):

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

The output folder must not already exist. The command compiles the current
launcher, stages the complete app without altering its base, audits it, runs
self-tests, creates a drag-to-Applications DMG, exports sources, and writes
`RELEASE-STATUS.json` plus `SHA256SUMS.txt`. No game files are placed in the app.
For the retained Arrival app's macOS-26-linked Wine bridge, use the source
rebuild and `--wine-fix` instructions in [SHIPPING.md](SHIPPING.md#package-a-local-candidate).
Verify delivered files with `shasum -a 256 -c SHA256SUMS.txt` from the output folder.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Install Rosetta still appears | Complete Apple's prompt, return to the app and select Check again. Check Apple's current support for your macOS. |
| Bundled runtime is missing | Obtain/build the complete app; a development launcher alone cannot run the game. |
| Download interrupted or cancelled | Retry setup/Play in the same app and data folder. Partial downloads are kept. Check internet and available storage. |
| Import rejected | Select the folder with `Bin` and `Data`, close gameplay, and resume using the same source. Do not import into an already configured destination. |
| Username/password cannot sign in | Choose the correct US / Steam provider. Steam needs Steam-created Wizard101 credentials and the signed-in Mac Steam client, and remains experimental. See [account instructions](ACCOUNTS.md). EU is unsupported. |
| Unsupported game revision | Use a candidate updated for that client revision. Authentication intentionally stops before credentials are sent; do not bypass validation. |
| Official launcher or game is already open | Close it before setup or another sign-in/update operation. |
| Build cannot find SDK or Swift | Install/select full Xcode, open it once, then rerun the `xcrun` checks above. |
| Build cannot find MinGW/Meson/Ninja | Install the listed Homebrew tools and ensure the native `/opt/homebrew` environment is available. |
| Source checksum or integration mismatch | Keep the lock and checks intact. Use the matching pinned inputs; a fresh build directory is preferable to modifying already patched sources. |
| Shipping rejects deployment target or external paths | Use a self-contained source-built runtime with macOS 13 targets. For retained Arrival Wine, follow the bridge rebuild guide. |
| Artwork fails to load | Game setup remains available with fallback art; verify connectivity and reopen to retry. |
| Game issue or remaining stutter | Advanced > Open launch details locates logs. Keep the working app; qualify controls, graphics, sound and performance with the release protocol. |

## Further guides and licenses

- [Shipping, signing, notarization and remaining public release gates](SHIPPING.md)
- [Retained Arrival candidate and prerequisite overlays](ARRIVAL-CANDIDATE.md)
- [Combined optimization controls](COMBINED-OPTIMIZATIONS.md)
- [Game-side repair](GAME-SIDE-REPAIR.md), [Metal archives](METAL-ARCHIVE.md),
  [asset preparation](ASSET-PREPARATION.md), and [direct draw layouts](DRAW-LAYOUT-DIRECT.md)
- [Workload diagnostics](WORKLOAD-DIAGNOSTICS.md) and
  [decompression/wait-queue/native-decode experiments](STUTTER-EXPERIMENTS.md)

Original launcher/build/test code and original fallback artwork use MIT.
Renderer changes retain the upstream zlib/libpng license. Wine and its libraries
retain their own licenses; notices are under `licenses/` and in the app's
`Contents/Resources/Licenses/`. Public corresponding sources accompany the app.
Official Wizard101 artwork and game assets, macOS and Rosetta belong to their
owners and are not MIT assets. This project is not affiliated with KingsIsle,
CodeWeavers or Apple.
