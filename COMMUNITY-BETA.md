# Wizard101 Standalone — Community Beta

**Version 3.2: experimental Steam community beta.** Choose **US / Steam** in
the native sign-in form. The project owner confirmed Steam working locally on
2026-10-16. Full two-provider gameplay, relaunch and ten-minute launcher-handoff
qualification remains pending; see [the account checks](ACCOUNTS.md) and
[verification record](BETA-QUALIFICATION.md). EU accounts are unsupported.
This beta is unsigned and not notarized; `public_release_ready` remains false.
Game content downloads separately.

Keep your previous app for rollback before using the installer: it replaces
`/Applications/Wizard101 Standalone.app`. The
[previous US-only 3.1 beta](https://github.com/Zanehisako/wizard101-standalone/releases/tag/v3.1-community-beta.1)
remains available. Existing standalone game content and settings are reused.

1. Download [**Wizard101-AppleSilicon-community-beta.pkg**](https://github.com/Zanehisako/wizard101-standalone/releases/download/v3.2-community-beta.1/Wizard101-AppleSilicon-community-beta.pkg)
   and open it. Verify it against the accompanying `SHA256SUMS.txt` if desired.
2. If macOS blocks it, open **System Settings → Privacy & Security**, scroll to
   Security, choose **Open Anyway**, and confirm **Open**. The `INSTALL.html`
   download includes an illustration. Follow
   [Apple's guide](https://support.apple.com/en-us/102445). The app may need the
   same approval after installation. Approve only the download you trust.
3. Complete Installer, then open **Wizard101 Standalone** from Applications.
4. Follow **Prepare Mac → Install or reuse game → Sign in and Play**.
   Complete Apple's Rosetta prompt if needed. Choose a detected game, browse to
   the folder containing `Bin` and `Data`, or download a fresh copy.
5. Choose **US** for website accounts or **Steam** for Wizard101 accounts created
   through Steam. Steam needs the installed Mac Steam client, signed in and online.
   Enter the Wizard101 username and password created through Steam, not your
   Steam login. Password saving is separate for each provider.

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

The app is below its **350 MiB** budget and the installer below **150 MiB**,
excluding downloaded game assets. `RELEASE-STATUS.json` records exact sizes. Runtime modules, notices, graphics defaults and legacy
frame pacing are retained. Debugging originals are stored separately by the
maintainer and are not installed. `SHA256SUMS.txt`, `SOURCE-PROVENANCE.json` and
the two corresponding-source archives accompany the installer.

For the previous 3.1 build only, the project owner confirmed all 19 beta live checks passed on 2026-10-15,
including login/gameplay, controls/audio/fullscreen, existing graphics and pacing,
installation/reinstallation, Rosetta, imports and recovery, and a fresh-user
walkthrough without Terminal. These are user-reported results; the implementation
agent did not independently observe the live checks. `BETA-QUALIFICATION.md` and
`RELEASE-STATUS.json` separate these results from automated verification and the
remaining signed-release gates. These passes do not qualify 3.2. Additional testers can use `LIVE-CHECKS.html`
offline in Safari to save their own results; it does not publish them.

Thank you for trying the beta. Report problems or share feedback through
[GitHub Issues](https://github.com/Zanehisako/wizard101-standalone/issues).

Unofficial project, not affiliated with KingsIsle. Wine and dependencies retain
their licenses. The source archives include pinned dependencies and project
overlays; a full clean rebuild of all retained Arrival overlays remains a
qualification gate for the signed release.
