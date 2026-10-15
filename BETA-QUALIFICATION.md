# Community beta qualification — 2026-10-15

The installer is built. Public binary publication is pending the live checks
below. `public_release_ready` remains false for this unsigned beta.

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
- Fixtures covered guided-step selection, multiple import detection, import
  cancellation/staged retry, independent clones and insufficient storage; existing
  fixtures covered interrupted downloads and resume.
- Checksums and the complete project/dependency source archive inventories verified.
  The retained original app and separate stutter work were not replaced.

## Still required before publishing the prerelease

- Real account login, character selection, game updates and gameplay after handoff.
- Audio, keyboard/mouse/cursor, fullscreen, existing graphics settings and user
  acceptance of frame pacing.
- Actual Installer installation and reinstall; Keychain access and data reuse.
- A fresh-user walkthrough without Terminal, including macOS Open Anyway.
- First Rosetta setup on a Mac without Rosetta.
- Visual multiple-source/manual-picker checks and real GUI import cancellation,
  retry, network interruption and low-storage recovery.

Computer Use app access was unavailable during implementation, so visual setup
and actual Installer checks are not marked passed. Copy `BETA-LIVE-TEMPLATE.json`
to a private verification directory and record actual observations bound to the
final app and installer hashes. `publish_beta.py` rejects missing passes.

Second-Mac/oldest-macOS gameplay, Developer ID/notarization and the full retained
Arrival clean rebuild remain separate signed-release qualification gates.
