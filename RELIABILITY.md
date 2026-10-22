# 3.2 local reliability candidates

## Build 14: interrupted dynamic-archive recovery

The current candidate is `dist/reliability-build14/Wizard101 Reliability Candidate.app`.
Full visual preload remains the default. After a transient download failure on
a type-5 visual archive, **Use streaming once** is offered only when its existing
installed size and header CRC match the current official manifest. Root and
_Shared-WorldData are excluded. Integrity failures cannot enable this recovery.
The explicit choice applies to one Play attempt, which still checks all ordinary
startup files before authentication; the next Play returns to full preload.
The existing optional type-3 HTTP 403/404 recovery remains unchanged.

This recovery also installs already completed visual downloads in the existing
rollback transaction, requiring their exact current-manifest full-file CRCs.
Incomplete or corrupt staging is left untouched. Readiness is recalculated and
remains incomplete while any visual archive is missing. Prepared-file checks
batch process scans and report progress instead of scanning processes for every
absent staging path. CLI preparation without sign-in is available with:

```sh
'dist/reliability-build14/Wizard101 Reliability Candidate.app/Contents/MacOS/Wizard101Native' \
  --prepare-content --install-prepared-visuals
```

Fixtures exercise an actual dropped connection, validated installed streaming
content, a manual one-attempt choice, mandatory startup files, full-CRC prepared
installation, refusal of partial/corrupt staging, retained streaming state and
incomplete readiness. No real-account or graphics acceptance is established.
Build 13 is retained as a development build; its slow prepared-file scan was
cancelled before installation. Prior candidates and installed releases remain.

Real preparation on 2026-10-21 installed the completed staged updates. Full
visual verification now passes 3,548 of 3,549 archives; only Mob2-WorldData
remains queued. Ordinary startup validation reports zero downloads. The GUI
and ClassicMode Colossus Balcony installed archives independently match their
full official CRCs. Mob2's installed header matches the current manifest, its
276,824,064-byte partial download is unchanged, and all 44 snapshotted protected
files are unchanged. Build 14 passed 51,019 launcher checks and 123 Python tests.
Evidence is in `dist/reliability-build14/content-verification.json`. The user
subsequently reported that **Use streaming once** works. This is user attestation;
sign-in, gameplay and graphics were not independently observed. Full preload
remains incomplete.

## Build 12: bounded archive downloads

The retained candidate is `dist/reliability-build12/Wizard101 Reliability Candidate.app`.
Downloads now request explicit byte ranges of at most 8 MiB, including the
initial range. Successful ranges advance through the archive and interrupted
ranges resume from accepted bytes. Each range retains bounded transient-error
retries and official-CDN routing policy; the entire download shares a one-hour
deadline. A 206 response must match the exact requested start, end and manifest
total. A server ignoring Range may return the complete file. Final manifest CRC
verification remains required before installation. Cancellation preserves staging.

This follows a GUI-WorldData connection-loss report at 35,651,584 bytes. The
same official URL served bounded ranges successfully. Explicit bounded ranges
also retrieved the earlier ClassicMode Colossus Balcony archive with its exact
manifest size and CRC. Build 11's 403 evidence described those requests; it did
not establish that the archive could never be retrieved. Full preload remains
the default, and the explicit optional-file streaming recovery remains available
for requests that still fail with 403/404.

Fixtures exercise eight separate dropped connections during one download,
multiple successful ranges, incorrect returned endpoints, cancellation/resume,
and existing full-file integrity and installation behavior. These tests do not
establish real-account or graphics acceptance. Prior candidates are retained;
runtime and renderer remain unchanged.

Real preparation on 2026-10-21 independently CRC-verified 1,065 complete staged
files (2,937,812,422 bytes), including GUI-WorldData and the ClassicMode Colossus
Balcony archive. It did not finish: Mob2-WorldData repeatedly closed the HTTP
connection at byte 276,824,064, including after a native resume and fresh official
CDN routes. Other ranges in that archive were served. Wallaru CollieRanch also
retains an interrupted partial download. The transaction has not installed the
staged update; visual readiness remains incomplete. All 44 snapshotted settings,
renderer and streaming-tracking files remain unchanged. Local evidence is in
`dist/reliability-build12/content-verification.json`. These results establish
recovery of the two reported files, not completion of the full visual preload.

## Build 11: unavailable optional archives

The retained candidate is `dist/reliability-build11/Wizard101 Reliability Candidate.app`.
Builds 8, 9 and 10 remain retained. On 2026-10-21 the current official manifest
listed `ClassicMode-WC_Streets-Interiors-WC_Colossus_Balcony.wad`, but the
official URL returned Apache HTTP 403 on the normal CDN route and two fresh
official DNS answers. Its compressed header was also unavailable. Other
archives at the same revision were served successfully. This is not a storage
failure; the file has not been downloaded or verified.

Play still attempts complete visual preparation by default. After an optional
type-3 visual archive returns HTTP 403 or 404, the error offers **Retry full
preload** or **Use streaming once**. The latter selects **Play with streaming**
for one play attempt; sign-in still follows the normal required startup update
and session checks. It neither retries credentials automatically nor marks
visual readiness complete. Required/shared archives, other HTTP errors,
network failures and integrity errors do not offer this recovery. CLI full
preparation remains strict. Some visuals may still be missing when streaming
is selected, and the next ordinary Play attempts the full preload again.

Partial downloads, existing installed files, settings and rollback copies are
preserved. Automated fixtures cover actual 403/404 responses, unchanged partial
bytes, strict full preparation, required-file validation during streaming,
incomplete readiness, resumption after service recovery and the one-attempt
selection. No real sign-in, gameplay or graphics fix is established by these
checks. Runtime and renderer remain unchanged.

## Build 10: complete visual preparation

The retained candidate is `dist/reliability-build10/Wizard101 Reliability Candidate.app`.
Build 9 and the public build 8 remain available. This candidate retains build 9's
encrypted authentication and recovery corrections and adds full visual preparation
before sign-in, independently of experimental performance selections.

Preparation selects every top-level, non-audio WAD in the official manifest's
`Data/GameData` directory. This includes classic assets, every world, numbered
Mob/Equipment families, shared assets, mounts and effects. Music, Sound and
Sound_* archive families keep their ordinary streaming behavior. The cached
manifest contained about 12.2 GB of selected archives; actual download and
staging requirements are calculated from the current manifest and installed files.

Header-valid streamed archives remain valid streamed content, but require a
complete body checksum for visual readiness. Verified complete files are reused.
Cancellation, failed verification or insufficient staging space stops the launch
before authentication. Partial downloads remain resumable, and installed files
use the existing rollback transaction. Settings, caches and streaming tracking
files remain in place.

The previous appearance toggle is replaced with content-readiness information.
Its saved preference is retained for compatibility. Resetting optimizations
does not disable visual preparation. CLI preparation is available without sign-in:

```sh
'dist/reliability-build10/Wizard101 Reliability Candidate.app/Contents/MacOS/Wizard101Native' \
  --prepare-content --prepare-visuals
```

Use a separate `W101_DATA_ROOT` for isolated verification.
`--check-updates --prepare-visuals` checks the same scope without replacing game files. The
existing `--prepare-content --prepare-appearance` command retains its narrower
scope with numbered families included.

Diagnostic schema 2 reads renderer logs from the recorded launch's NativeLogs
directory and captures that launch's effective renderer/frame/graphics settings.
Older runs use the newest recognized log directory with historical settings
marked unavailable. Missing logs are explicitly unavailable rather than zero
errors. Reports include a dated content-readiness observation and the candidate
version/build; raw logs, accounts, credentials and network contents are excluded.

Automated fixtures exercise sparse bodies, numbered/classic/world coverage,
audio exclusion, full CRC verification, cancellation/resume, insufficient space,
unchanged originals on failure, reuse, log selection and report privacy. These
are not evidence that the tester's missing models or red scenery are fixed.
Live release gates additionally cover both classic modes, clothing/mounts,
Bartleby/floors, visible Arcanum Paradox combatants and preload/restart behavior.
The tester cannot retest; their reported hardware/macOS combination remains
unverified. Publish no replacement until the relevant live gates pass.

## Retained build 9

Built separately from the retained 3.2 build 8 app. This is an ad hoc signed local diagnostic candidate, not a replacement release. The installed app and downloaded game, graphics settings, resolution, animations, cursor, caches, 60 FPS option and legacy pacing remain in place. Runtime and renderer binaries are unchanged.

Open `dist/reliability-build9/Wizard101 Reliability Candidate.app` directly. It uses the existing standalone prefix and account preferences. Keep the previous launcher available for rollback. Choose US or Steam yourself; sign-in and credential retries are manual.

Sign-in uses a 30-second monotonic deadline for each connection, including handshake and encrypted reply reads. Small heartbeat batches alternate with reads. Outgoing encrypted traffic is capped at 4 MiB and incoming traffic at 8 MiB. Plaintext is released only after a complete GCM tag verifies. Cancelling discards the exchange; an explicit retry creates a fresh connection, keys, buffers and deadline.

Reopening the app while this installation's game is running keeps the launcher visible and offers **Force Quit Game**. This closes the selected Wine prefix through its bundled wineserver. Each shutdown helper has a six-second limit plus a short termination grace period. Setup and updates hold the same operation lock, preventing recovery while files are being changed. Successful handoff from a newly launched game still closes the launcher normally.

Under Settings, choose **Save Diagnostic Report**. The JSON contains Mac/GPU/macOS details, component hashes, allowlisted graphics/audio settings, recent authentication durations, typed failure categories and allowlisted counters. Available game logs contribute counts of exact known tokens from their last 2 MiB. Reports contain no credentials, usernames, tickets, session keys, argv, environment, raw network data or raw log lines. Token counts do not provide a complete focus/GPU trace and zero counts do not prove absence of failures.

## Local evidence

- Encrypted replays exercise replies after more than four blocks, frames crossing chunks, split tags, corrupt ciphertext/tags, silent and control-only peers, cancellation and immediate explicit retry. A loopback TCP test checks pending reads across polling timeouts.
- The read-only content audit rechecks cached official full-file or archive-header CRCs. Header-valid sparse streamed WADs are accepted. It does not force a full redownload or call sparse bodies corrupt.
- Real Wine recovery is tested with two disposable prefixes and sleeping fixture executables. This establishes prefix isolation and update locking, without claiming real account or gameplay acceptance.

## Required live checks

The reporting tester cannot retest. All live gates in the adjacent candidate JSON begin false. Another tester must record observations against this exact app's hashes.

1. Complete ten consecutive manual sign-ins per provider. Include relaunches and sign-in after Force Quit Game. Keep the real Mac Steam client signed in for Steam tests.
2. Check character selection, objects/textures, movement, combat, audio and cursor, then play for ten minutes at the saved resolution/settings, 60 FPS and legacy pacing.
3. Compare fresh streamed content with an existing installation using the same character, area and settings. Capture a diagnostic report immediately after a failure. Shader compilation, texture upload and streaming failures still need live reproduction.
4. Complete ten switches away and back in fullscreen, then ten in windowed mode. Check for corruption and hangs. Focus/presentation/device recovery still need live reproduction.
5. With another Wine installation running, recover only this installation. Confirm updates prevent recovery, and normal handoff still exits the launcher while the game continues.

Graphics and Alt-Tab causes have not been reproduced; no speculative renderer or focus change is included. Package or publish a replacement only after the relevant live checks pass. Shipping validators require these additional gates and observations.

## Rebuild and local checks

```sh
python3 portable/build_reliability_candidate.py \
  --base-app 'portable/dist/us-steam-release-build8/Wizard101 Standalone.app' \
  --output 'portable/dist/reliability-next/Wizard101 Reliability Candidate.app'

python3 portable/verify_reliability_runtime.py \
  --app 'portable/dist/reliability-build9/Wizard101 Reliability Candidate.app' \
  --seed-data-root /private/tmp/w101-community-beta-fresh \
  --output portable/dist/reliability-build9/recovery-verification.json
```

The app also supports `--game-status`, `--force-quit-game`, and `--save-diagnostic-report <file>`. These address the same data root as the GUI. The recovery verifier uses isolated temporary prefixes and cleans them up; it does not launch a real account.
