# Rendering performance candidate

Open **Wizard101 Rendering Performance.app** for the new experiment. The app
uses `DXVK_W101_STUTTER_FIX=1`, CPU and earlier pipeline optimizations `off`,
60 FPS, legacy pacing, synchronous submissions `1`, `DXVK_ASYNC=0`, the larger
cursor and MoltenVK 1.4.2. Timing capture and learned-shader warm-up remain
opt-in. Its independent data directory is
`~/Library/Application Support/Wizard101 Rendering Performance Comparison/Data`.
Imported graphics settings and 2560×1600 resolution are preserved.

The renderer defaults to `DXVK_W101_STUTTER_FIX=0`. Only the exact value `1`
enables the changes; `0`, missing and invalid values use the baseline path.
The separate app supplies the enabled default. An explicit environment value
can select `0` for a comparison, while CPU and other pipeline experiments remain
disabled in this app.

## Implementation

Each graphics state plus render-pass identity, or compute state, has one
compilation record. A brief table lock publishes or locates the record; driver
compilation happens outside that lock. Duplicate foreground/background requests
share a completed instance, null pipeline or exception. Complete packed-state
equality checks hash collisions. Existing instance storage and handle lifetimes
are preserved. Required draws still wait for their actual pipeline and retain
command ordering.

The foreground gate is active even with shader warm-up disabled. Queued
background variants acquire permission before claiming a state, so a required
request can claim that state first. Foreground requests never acquire the
background permission. A driver call already running cannot be preempted; its
own Vulkan-cache and Metal locks remain intact. Other states can prepare
concurrently without the old shader-set compilation mutex.

When enabled, the Vulkan cache writer sleeps until shutdown. The shader catalog
still loads/restores as requested, then sleeps until shutdown. Neither performs
periodic snapshots, hashing or persistence during gameplay. Normal shutdown
joins replay, snapshots the dirty driver cache and saves learned catalog records.
Existing atomic file formats, compatibility keys, size limits, corruption
rejection and uncached compilation fallback remain unchanged. Unexpected process
termination can discard entries learned since the last normal exit. Existing
valid files remain protected by atomic replacement. The small DXVK state cache
continues using its existing writer and format.

Shutdown also clears cancelled replay accounting, rejects post-shutdown
registration and completes replay accounting after compilation exceptions.
Pipeline-manager destruction stops workers before destroying instance storage
on the normal teardown path.

## Build and verify

Run from this directory:

```sh
W101_BUILD_ROOT=/private/tmp/w101-rendering python3 build_renderer.py --rendering-candidate
python3 build_app.py --output 'dist/rendering/Wizard101 Rendering Performance.app' \
  --runtime /private/tmp/w101-runtime-26.3.0/runtime \
  --renderer /private/tmp/w101-rendering/build-rendering-d9vk/src/d3d9/d3d9.dll
python3 verify_rendering.py --app 'dist/rendering/Wizard101 Rendering Performance.app' \
  --source /private/tmp/w101-rendering/rendering-d9vk \
  --build /private/tmp/w101-rendering/build-rendering-d9vk \
  --keep verification-local/rendering/unit
python3 verify_runtime.py 'dist/rendering/Wizard101 Rendering Performance.app' \
  --stutter-fix 1 --keep-logs verification-local/rendering/runtime-on
python3 verify_runtime.py 'dist/rendering/Wizard101 Rendering Performance.app' \
  --stutter-fix 0 --keep-logs verification-local/rendering/runtime-off
'dist/rendering/Wizard101 Rendering Performance.app/Contents/MacOS/Wizard101Native' --self-test
python3 audit_bundle.py 'dist/rendering/Wizard101 Rendering Performance.app'
python3 -m unittest discover -s tests -p 'test_*.py'
```

Build the pinned runtime first with `build_runtime.py` if needed. The renderer
uses `wizard101.patch`, `warmup.patch`, `capture.patch` and `stutter.patch` in a
separate tree; the CPU and earlier pipeline optimization patches are omitted.
`rendering-build.json` records source/patch fingerprints and the exact DLL hash.
The translation fingerprint is checked before building and remains compatible
with the existing warm-up/capture renderer. Session metadata records the switch.

Verification uses disposable prefixes. It checks exact state/pass keys, shared
null/exception failures, foreground takeover, queued cancellation, 48 actual
Vulkan graphics/compute states with 16 mixed requests each, and independent
foreground progress while a different background driver request is held. Cache
fault probes check both legacy scheduling and shutdown-only persistence, more
than six seconds without a gameplay write, cache/catalog reload, failed snapshots,
storage failure, driver creation/retry/fallback, repeated stop and cancelled-job
accounting. Rendering checks cover six texture formats, 192 upload/readbacks,
1,536 synthetic HUD readbacks, cursor size/hotspot/transparency and fullscreen.

These synthetic checks do not establish a gameplay improvement or substitute
for visual and control confirmation.

## Comparison and rollback

Keep the working app until this exact candidate passes the gameplay gate. For
an isolated copy, exit all games normally and use:

```sh
python3 prepare_comparison.py prepare SOURCE_DATA COMPARISON_DIRECTORY APP
```

Ordinary opening leaves profiling disabled. Enable **Capture timing** only when
collecting a comparison. A controlled rendering comparison uses
`prepare_comparison.py launch` with `--comparison rendering --pipeline-opt off
--cpu-opt off --synchronous-submits 1 --warmup on --stutter-fix 0` for baseline
and `--stutter-fix 1` for candidate. Both retain the same learned warm-up,
settings, frozen caches, route and movement windows. Existing seed, screen,
alternating-pair and restart controls apply.

Set `comparison` to `rendering` and `candidate_mode` to `1` in the comparison
manifest. `compare_performance.py` requires fewer movement intervals above
50 ms, fewer first-arrival long intervals, no p99 increase above 1 ms in matched
movement phases/areas, finalized captures without lost presentation or
compilation evidence, three alternating pairs, cache persistence, and the user's
graphics and movement/combat confirmation before rollout. A screening result
cannot authorize replacement.

The working app and its data are untouched. To roll back, close this candidate
normally and open the working app. To compare the new DLL's disabled path:

```sh
DXVK_W101_STUTTER_FIX=0 '/Users/mac/Desktop/Wizard101 Rendering Performance.app/Contents/MacOS/Wizard101Native'
```

Completely new shaders and game-side loading can still pause. Improvement
remains unproven until matched gameplay measurements and confirmation.
