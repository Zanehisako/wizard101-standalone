# Candidate acceptance gates

Never replace the user's working app based only on a build, synthetic tests,
process detection, or an inventory scan. Preserve the installed app and its
rollback copy until the user accepts this exact candidate after live play.

Record the archive and executable SHA-256, macOS version, candidate runtime,
renderer SHA-256, settings, resolution, areas, and observations for each run.
Do not record usernames, passwords, login command lines, session keys, or
captured game shaders in public evidence.

Required gates:

1. Extract the app to a new location, with the original repository and installed
   CrossOver unavailable to the candidate. Synthetic tests and bundle audit
   must still pass; all runtime loads must stay inside the app or system libs.
2. Create a new Wine prefix and perform fresh setup from KingsIsle. Check login
   definitions and startup resources, configuration generation, gzip and
   manifest CRC validation, verified sparse type-5 bootstrap archives, and
   full-file CRC on replacements. Complete a second scan with zero downloads.
3. Import an existing installation into a separate prefix. Verify settings,
   archive sizes/header CRCs, no needless WAD downloads, and unchanged originals.
4. Test in-flight cancellation/resume and interrupted transaction recovery.
   Synthetic URLProtocol tests supplement, but do not replace, the GUI check.
5. The user enters real credentials locally. Verify native sign-in, correct
   character selection, game session survival after launcher exit, and no
   official launcher process. Nonexistent-account or transport probes do not
   count as real login.
6. Verify audio, keyboard/mouse, larger cursor/hotspot, fullscreen/windowed
   transitions, 2560x1600, 60 FPS and Uncapped, correct effects and transparency.
7. Compare demanding areas against the working CrossOver installation using
   identical graphics, resolution, route, cap, foreground coverage, and
   comparable cold/warm cache conditions. Report manual impressions when valid
   frame-time instrumentation is unavailable. Obtain user acceptance of
   performance and visual behavior before replacement.

This repository intentionally contains no pre-filled live passes. The build
archive is named `candidate` until all gates pass. Local evidence belongs in
`verification-local/` and must be excluded from the clean public history.

## Community beta qualification

An explicitly labelled unsigned **community beta** is a separate prerelease
channel; it never sets `public_release_ready` true and requires the user's macOS
Open Anyway approval. `package_shipping.py --format pkg --channel community-beta`
retains all modules and rejects PE load-bearing changes or size-budget failures.
`publish_beta.py` blocks publication until every entry in `BETA-LIVE-TEMPLATE.json`
has an actual pass and private observation bound to the final app and PKG hashes.

In addition to real login, character selection, updates, audio, keyboard/mouse,
cursor, fullscreen, unchanged graphics and accepted frame pacing, verify:

- Install and reinstall in Applications; the Desktop candidate, official app,
  Keychain access and existing game data must remain usable and unchanged.
- A fresh user's complete walkthrough without Terminal, including approval of
  the downloaded installer and app in Privacy & Security.
- A Mac without Rosetta: installer runs natively; launcher offers Apple's prompt,
  handles cancellation and advances only after Check again succeeds.
- Multiple detected sources have friendly distinct names and a manual folder
  picker; existing standalone data advances straight to sign-in.
- Cancel an in-flight import, relaunch, retry, and verify staged reuse and original
  settings/files. Interrupt downloads and verify resume after the network returns.
- Insufficient storage leaves the original and staged files safe and offers retry.

Record fixture checks separately from human or live-machine checks. Keep previous
apps and data for rollback. Second-Mac/oldest-macOS gameplay, all retained-overlay
clean rebuilds and Developer ID/notarization remain signed-release gates even
when an unsigned prerelease is qualified.

## Public distribution gates

Verify declared macOS 13 deployment targets for every native component, Apple
Silicon launcher and x64 Wine architectures, source/relink availability, nested
signatures, Developer ID notarization/stapling, and Gatekeeper acceptance. Run
fresh setup and live gameplay on a second Apple Silicon Mac and the oldest
supported macOS. Test Apple's first Rosetta installation prompt on a Mac without
Rosetta. No public-ready label follows from ad-hoc signing or synthetic probes.

`package_shipping.py` only emits a public release when the final notarized
`--verified-app` has matching component hashes and all required live gates.
It copies that tested app without re-signing. Rebuilding or signing again
invalidates existing exact-artifact evidence. `LauncherBuild.json` binds the
compiled launcher to its source inputs; stale builds cannot be packaged.
