# Community beta qualification

## 3.2 build 8 — experimental Steam beta, 2026-10-16

The project owner reported “nice it's working” after the local Steam retry and
requested commit, push and release publication. This records a successful local
report; it does not establish individual passes for every account/gameplay gate.
The release is explicitly experimental. `community_beta_ready`,
`live_evidence_verified` and `public_release_ready` remain false, and the
unrecorded live checks stay pending in `RELEASE-STATUS.json`.

- Remembered US / Steam selector, provider-isolated credentials and one shared
  game installation and settings.
- Steam ticket startup/callback handling and scoped cancellation/cleanup.
- Typed authentication failures retain only provider, numeric code, response
  stage and an allowlisted reason category. Arbitrary server text and secrets
  are excluded from displayed errors and diagnostic output.
- The local diagnostic candidate passed 50,879 launcher self-checks; 50,882 with
  the isolated Keychain checks enabled. Normal release apps disable the optional
  local authentication diagnostic file.
- All 121 Python tests passed in the release checkout, including Steam bridge,
  provider isolation and experimental-publication checks.
- The release build repeats launcher self-checks, bundle/signature audits,
  extracted installer payload checks, complete source inventory and checksum
  verification. The accompanying status file contains the final artifact hashes.
- Existing runtime/renderer bytes and game defaults are retained. The installed
  working launcher and external game data were not replaced during packaging.

The complete US/Steam character selection, gameplay, relaunch, ten-minute
continued play after launcher exit, switching and settings/pacing checks remain
pending as recorded in [ACCOUNTS.md](ACCOUNTS.md). The 3.1 record below is historical
and does not transfer qualification to changed binaries. Downloaded apps remain
unsigned and unnotarized; additional-Mac/oldest-macOS and clean Arrival rebuild
checks are also pending.

---

## 3.1 historical qualification — 2026-10-15

The project owner confirmed **all beta live checks passed** and authorized
publication on 2026-10-15. `community_beta_ready` is true;
`public_release_ready` remains false for this unsigned, unnotarized beta.

This qualification applies to the 36.3 MiB installer with SHA-256
`db67615288addb46d924167075742f0d10f7a1bc5ca4654df9c8593da887eb19`.
The final installer and its app payload are unchanged by this status update.

## Verified on the development Mac

- 205.9 MiB installed app and 36.3 MiB PKG, excluding game downloads.
- 773 PE images inspected; 746 stripped; zero runtime modules removed. DOS/Wine
  markers, retained section bytes, virtual addresses/protection and non-debug
  loader directories preserved, including imports/exports, relocation and unwind data.
- Renderer integrity hashes regenerated; nested ad-hoc signatures and 47 native
  components audited. Declared minimum macOS 13 verified; this does not prove
  gameplay compatibility on macOS 13.
- PKG expanded: one Applications payload, Apple Silicon/macOS 13 requirements,
  relocation disabled, no scripts/network setup, exact app component hashes.
- 49,369 launcher self-checks; 99 Python tests in the checkout and again from
  the exported corresponding-source archive.
- The final reduced app's isolated Wine prefix passed rendering/upload readbacks,
  six texture formats, synthetic HUD, 64-pixel cursor/hotspot/transparency, and
  fullscreen/windowed transition probes. These are synthetic checks.
- Fresh setup with the final reduced app downloaded and verified 871.6 MB from
  the official game service, installed revision `r806919.Wizard_1_610`, and reached
  Setup complete in a disposable data folder. This automated run did not test
  real account login or gameplay.
- Fixtures covered guided-step selection, multiple import detection, import
  cancellation/staged retry, independent clones and insufficient storage; existing
  fixtures covered interrupted downloads and resume.
- Checksums and the complete project/dependency source archive inventories verified.
  The retained original app and separate stutter work were not replaced.

## Live checks reported passed by the project owner

- Real account login, character selection, game updates and gameplay after handoff.
- Audio, keyboard/mouse/cursor, fullscreen, existing graphics settings and user
  acceptance of frame pacing.
- Actual Installer installation and reinstall; Keychain access and data reuse.
- A fresh-user walkthrough without Terminal, including macOS Open Anyway.
- First Rosetta setup on a Mac without Rosetta.
- Visual multiple-source/manual-picker checks and real GUI import cancellation,
  retry, network interruption and low-storage recovery.

The owner's confirmation was: “all live checks pass ,upload it”. All 19 beta
gates are recorded as user-reported passes, bound to the final app component
hashes and installer above. Device details and individual step observations
were not supplied. The implementation agent did not independently observe these
live checks; the automated report retains that distinction.

Additional testers can open `LIVE-CHECKS.html` in Safari to save their own results
without Terminal. The sheet and `BETA-LIVE-TEMPLATE.json` remain blank templates,
bound to this installer. Private qualification records are not release assets.
`publish_beta.py` checks every gate and the matching artifact hashes.

Second-Mac/oldest-macOS gameplay, Developer ID/notarization and the full retained
Arrival clean rebuild remain separate signed-release qualification gates.
