# First-appearance stutter candidate

For the remaining-stutter investigation, use the separate schema-2 diagnostic
build and archive/tracking-file seed described in [STUTTER-DIAGNOSTICS.md](STUTTER-DIAGNOSTICS.md).

This candidate has not passed gameplay acceptance. The working installation
remains the rollback. Warm-up is off by default. Preserve 60 FPS, legacy pacing,
2560x1600, visual settings and the larger cursor for every comparison.

The additional `renderer/warmup.patch` learns up to 2,048 programmable shaders,
64 KiB each and 32 MiB total. A private checksummed catalog stores original DXSO
bytecode. Compatibility includes translation revision, shader options, constant
layouts, GPU, driver version and Vulkan cache UUID. The catalog has one fixed
filename; incompatible revisions replace it rather than accumulate. Corrupt,
oversized, invalid or incompatible entries are ignored; restored DXSO parsing
has explicit bounds. Atomic replacement preserves the previous complete file.
The usual source allowlist exports no cached shaders.

On opt-in warm-up, the existing D3D9 shader-module set restores catalog entries
and registers them with the existing state-cache compiler. Recorded render
passes and pipeline states are prepared normally. Duplicate shader requests
share one in-flight translation. Startup waits at most 10 seconds on a condition
variable, even if a driver call takes longer. Remaining work stays at lowest
priority, with one background compilation admitted at a time. Foreground shader
and pipeline requests take priority over queued work. Already-running driver
calls cannot safely be interrupted. Required draws still wait for valid
pipelines; async draw skipping stays disabled.

A first launch with an empty catalog learns content but restores no shaders.
Its startup wait finishes immediately when there are no queued pipeline jobs.
Completion includes both queued and running work, so idle workers cannot make
startup appear finished before they pick up newly restored pipelines. Renderer
logs report the restored shader count, elapsed wait and pipelines prepared before
gameplay; the 10-second allowance is a maximum, not an unconditional delay.

MoltenVK's Vulkan cache preserves conversion work, while pipeline preparation
still needs to run. See the pinned [MoltenVK guide](https://github.com/KhronosGroup/MoltenVK/blob/v1.4.2/Docs/MoltenVK_Runtime_UserGuide.md#shader-loading-time).
New shaders, fixed-function variants and streamed assets can still need first-use
work. This catalog targets programmable shaders previously encountered by this
candidate, not arbitrary unseen content.

## Diagnose first

For a profiling-only build, run `build_renderer.py --diagnostic-only`. This
applies `diagnostic.patch` to the working renderer and preserves its shader
translation fingerprint and cache compatibility. It does not include catalog
restoration, shader-module deduplication or scheduling changes. Leave warm-up
off while using this build. The first live control circuit restored the HUD but
still stuttered; its older recorder dropped 2,694 events without separately
counting dropped presentation events, so its p99 cannot pass the live gate.

The updated recorder gives presentations a separate bounded queue and counts
any lost frame events. Background lock checks and queue admissions below
100 microseconds are filtered and counted in `filtered_short_events`; real
waits and presentation timestamps remain recorded.
File reads below 100 microseconds are also filtered and counted separately;
`DXVK_W101_PROFILE_ALL_READS=1` enables those spans for synthetic hook probes.
`build_app.py --data-root WORK/Data --capture-timing` embeds local comparison
defaults, allowing the app to open directly from Finder. Explicit environment
overrides still take priority. Leave warm-up off for the initial learning
circuit, then restart with the toggle on to test previously learned content.

`verify_profile.py` checks frame retention under queue pressure, disabled recording, time/size bounds,
orderly shutdown, read-hook errors, rendering and compatible cache reload in
an isolated prefix. These synthetic checks do not establish gameplay results.

After normal game exit, create a separate APFS clone using
`prepare_comparison.py prepare SOURCE_DATA NEW_WORK APP`. This replaces only the
clone's renderer. The working app, prefix, settings and renderer remain intact.
The script refuses to run while any Wizard101 game/launcher is active. It never
terminates a game. No credentials are copied into comparison metadata.

Run `prepare_comparison.py launch WORK APP --label diagnostic --warmup off`.
Sign in locally. Capture a repeatable route's first arrival and immediate
revisit; exit normally and capture the same route after restarting. The capture
lasts at most 900 seconds and 64 MiB. Annotate activity boundaries in microseconds
relative to the timing CSV; omit menus, loading screens and idle periods from
movement windows, but include the first appearance that is being evaluated.

The profile distinguishes foreground pipeline requests/locks, background work,
driver compilation, texture creation/uploads and game `ReadFile` /
`InternetReadFile` calls. Read hooks are scoped to the game's own imports and
installed only when profiling is enabled. They preserve results and last-error
semantics, and record no paths or payloads. Mapped-file faults, decompression and
other game work are not measured. Overlap alone does not establish causation.
Use `profile_report.py CAPTURE --start-us N --end-us N` to inspect each phase.
Reports retain dropped event and dropped presentation counts. Unfinished
captures or dropped presentation events cannot pass the comparison gate.

If fresh evidence points to asset loading, leave warm-up off and stop this
candidate. Record the evidence before designing a separate asset-loading change.

## Compare after compilation evidence

Play the selected route with warm-up off to learn its shaders, then exit and run
`prepare_comparison.py seed WORK`. This freezes learned caches, game archives,
tracking files and settings. Each numbered launch restores the clone from this
immutable APFS seed.

Use labels `pair1-baseline`, `pair1-candidate`, and the same labels with
`-restart` for their restarted sessions. Baseline uses `--warmup off`; candidate
uses `--warmup on`. Repeat pairs 2 and 3, alternating mode order. Every pair
needs first-arrival, immediate-revisit and after-restart activity windows.
Avoid other simultaneous games and preserve settings and route. The native
launcher records the renderer, settings and starting cache hashes per session.

`compare_first_use.py MANIFEST.json` expects `diagnosis: "compilation"`, three
`pairs` (each with `id`, `baseline` and `candidate`), and each mode containing
`first_arrival`, `immediate_revisit`, `after_restart` samples. Each sample contains
`capture` (relative CSV path), `start_us`, `end_us`, `route`, `settings_sha256`,
`starting_cache_sha256`. The hashes must match that capture's `session.json`.
Top-level `movement_and_combat_accepted` and `graphics_accepted` are boolean user
acceptance fields, initially false. Set them true only after actual confirmation.

Require fewer first-arrival intervals above 50 ms, no phase/pair p99 regression
over 1 ms, correct HUD/effects/transparency/cursor and user acceptance during
ordinary movement and combat. A separate build or synthetic probe cannot pass
these live gates. Do not replace the working installation before they pass.

## Verify the implementation

`verify_warmup.py --app APP --source PATCHED_D9VK --build BUILD_DIR --baseline
BASELINE_DLL --keep LOCAL_LOG_DIR` builds synthetic catalog/scheduling/concurrency
probes and uses a temporary Wine prefix. Optional `--compatible-cache DIRECTORY`
copies the current cache read-only and verifies it loads with the baseline DLL.
It checks candidate restart reload, exact pixels, uploads, catalog corruption,
bounded startup and game-read hook error semantics. `verify_runtime.py` checks
the synthetic HUD, texture formats, fullscreen transitions and larger cursor.
Local evidence belongs under `verification-local/`; it is excluded from exports.

`verify_learned_warmup.py --app APP --learned-data DATA_ROOT --keep LOCAL_LOG_DIR`
copies an existing private catalog and pipeline caches into a temporary prefix,
then creates a device with warm-up off and on from identical starting contents.
It reports restored shaders, pipelines created before gameplay, startup time and
dropped profiling events. Original cache hashes must stay unchanged. It signs
into no account and loads no game assets. This verifies actual preparation from
learned content, without establishing a gameplay performance improvement.
