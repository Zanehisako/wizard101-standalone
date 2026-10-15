# Wizard101 Standalone — Community Beta

One offline installer for Apple Silicon, macOS 13 or later, and US standalone
accounts. Game content downloads separately. Steam and EU accounts are unsupported.
This is an unsigned, unnotarized community beta; `public_release_ready` remains false.

1. Download [**Wizard101-AppleSilicon-community-beta.pkg**](https://github.com/Zanehisako/wizard101-standalone/releases/download/v3.1-community-beta.1/Wizard101-AppleSilicon-community-beta.pkg)
   (**36.3 MiB**) and open it.
2. If macOS blocks it, open **System Settings → Privacy & Security**, scroll to
   Security, choose **Open Anyway**, and confirm **Open**. The `INSTALL.html`
   download includes an illustration. Follow
   [Apple's guide](https://support.apple.com/en-us/102445). The app may need the
   same approval after installation. Approve only the download you trust.
3. Complete Installer, then open **Wizard101 Standalone** from Applications.
4. Follow **Prepare Mac → Install or reuse game → Sign in and Play**.
   Complete Apple's Rosetta prompt if needed. Choose a detected game, browse to
   the folder containing `Bin` and `Data`, or download a fresh copy.

Imports preserve original files and settings. Cancelled imports and interrupted
downloads stay staged; choose **Continue setup** to retry. Free storage if asked.
The launcher checks game updates before play. Password saving is optional and
uses Mac Keychain. App updates use a new installer for this beta.

The installer uses `/Applications/Wizard101 Standalone.app`. It preserves the
official Wizard101 app, Desktop candidate and separate stutter experiments.
The bundle identifier stays `org.wizard101native.mac`, and game data stays in
`~/Library/Application Support/Wizard101 Native`. Existing standalone data is
reused automatically. Keep your previous app and data for rollback; replacing
an app does not reverse changes made by a subsequent game-content update.

The app is **205.9 MiB**, below its **350 MiB** budget; the installer is below
its **150 MiB** budget, excluding
downloaded game assets. Runtime modules, notices, graphics defaults and legacy
frame pacing are retained. Debugging originals are stored separately by the
maintainer and are not installed. `SHA256SUMS.txt`, `SOURCE-PROVENANCE.json` and
the two corresponding-source archives accompany the installer.

The project owner confirmed all 19 beta live checks passed on 2026-10-15,
including login/gameplay, controls/audio/fullscreen, existing graphics and pacing,
installation/reinstallation, Rosetta, imports and recovery, and a fresh-user
walkthrough without Terminal. These are user-reported results; the implementation
agent did not independently observe the live checks. `BETA-QUALIFICATION.md` and
`RELEASE-STATUS.json` separate these results from automated verification and the
remaining signed-release gates. Additional testers can use `LIVE-CHECKS.html`
offline in Safari to save their own results; it does not publish them.

Thank you for trying the beta. Report problems or share feedback through
[GitHub Issues](https://github.com/Zanehisako/wizard101-standalone/issues).

Unofficial project, not affiliated with KingsIsle. Wine and dependencies retain
their licenses. The source archives include pinned dependencies and project
overlays; a full clean rebuild of all retained Arrival overlays remains a
qualification gate for the signed release.
