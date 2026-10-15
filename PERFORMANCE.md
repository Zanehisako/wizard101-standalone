# Renderer overhead candidate

`Wizard101 Performance.app` is a separate build. Pipeline optimizations default
to `off`; it retains MoltenVK 1.4.2, 60 FPS, legacy pacing, `DXVK_ASYNC=0`, imported
2560×1600 settings and the larger cursor. It uses an isolated APFS data copy.
The working launcher and rollback are preserved. Gameplay acceptance is pending.

Local synthetic verification passed 65 Python tests, 78 launcher checks and all
four renderer modes. A read-only copy of the current learned cache retained
5,050 states: both modes prepared 4,201 available pipelines from 476 restored
shaders. Replay checks fell from 112,931 to 4,201 (jobs: 4,201 to 540); isolated
startup preparation was 4.10 seconds with `off` and 2.46 seconds with `both`.
HUD, textures, fullscreen and cursor probes passed in both modes. These figures
describe cache preparation, not measured gameplay stutter or process CPU savings.

## Build and modes

```sh
W101_BUILD_ROOT=/private/tmp/w101-performance python3 build_renderer.py --performance-candidate
python3 build_app.py --output 'dist/performance/Wizard101 Performance.app' \
  --runtime /private/tmp/w101-runtime-26.3.0/runtime \
  --renderer /private/tmp/w101-performance/build-performance-d9vk/src/d3d9/d3d9.dll \
  --data-root "$HOME/Library/Application Support/Wizard101 Performance Comparison/Data" \
  --capture-timing
```

The renderer supports `DXVK_W101_PIPELINE_OPT=off|replay|lookup|both`:

| Mode | Change |
| --- | --- |
| off | Baseline replay and list lookup |
| replay | Admit each complete six-stage shader key once per cache lifetime |
| lookup | Atomic last-match lookup and 64 hash buckets |
| both | Both changes |

Every cached state and render-pass variant remains in the state cache. A replay
job visits all entries for its exact shader combination. Registration is serialized;
incomplete combinations are admitted when their missing shader arrives. Pending
counts include queued and running jobs; shutdown cancels queued jobs and rejects
further registrations. Worker exceptions release their pending count.

Lookup hashes every byte compared by existing state equality plus the render-pass
pointer. Collisions use exact equality. Instances and index nodes remain immutable
and alive until the owning pipeline is destroyed. Acquire/release publication
allows readers to skip the list mutex; the existing compilation mutex still
serializes driver calls and prevents duplicate instances. Null pipeline failures
retain baseline behavior. The shader translation fingerprint and cache format
are unchanged. Renderer logs report selected mode and bounded replay totals.

## Ordinary-play trial

The partial baseline used warm-up with pipeline optimizations `off`; stutters
remain unresolved. Its movement windows started after arrival and cannot measure
area-entry pauses. Try the already-built candidate during ordinary play before
requesting further matched measurements.

After exiting the game normally, run this from the graphics-patch checkout:

```sh
python3 portable/prepare_comparison.py launch \
  '/Users/mac/Library/Application Support/Wizard101 Performance Comparison' \
  '/Users/mac/Desktop/Wizard101 Performance.app' \
  --comparison pipeline --label screen-candidate --warmup on \
  --pipeline-opt both --synchronous-submits 1
```

This restores the existing isolated seed and opens the native launcher. Verify
`pipeline_optimization: "both"` in the new session metadata and `W101 pipeline
optimizations: both` in the renderer log after sign-in. Double-clicking the app
alone defaults to `off`. Keep warm-up, 60 FPS, graphics settings, cursor, legacy
pacing, `DXVK_ASYNC=0` and synchronous queue submissions unchanged.

Use normal play with the existing 900-second/64-MiB capture limit. Collect one
report about area-entry pauses, smaller ongoing stutters, movement/combat and
graphics. Treat this as exploratory: do not create invented movement windows,
record a formal screening pass or replace the working app. If unchanged or worse,
use `off` at the next launch and review the existing stall evidence. Improvement
still needs the matched timing and gameplay acceptance checks below.

The 2026-10-02 ordinary-play trial confirmed `both` in the session and renderer
log. The user reported no meaningful improvement: pauses remain on entering new
areas and when players appear. Startup preparation took 2,415 ms, but this does
not establish gameplay or process CPU savings. Retain the candidate as experimental
and use `off` at the next launch; leave the current game and working app intact.
The existing capture contains a 189.82-ms foreground pipeline wait for a new
shader, while game logs report avatar/equipment processing up to 105 ms and
equipment texture loading up to 81 ms. These are separate leads, not a proven
cause or a matched screening result. Formal screening remains unaccepted.

## Screen one pair

After normal exit, prepare a new clone from the existing learned diagnostic data:

```sh
python3 prepare_comparison.py prepare SOURCE_DATA NEW_WORK APP
python3 prepare_comparison.py seed NEW_WORK
python3 prepare_comparison.py launch NEW_WORK APP --comparison pipeline \
  --label screen-baseline --warmup on --pipeline-opt off
```

Sign in locally. Follow **Ravenwood → Commons → Pet Pavilion → Commons** and repeat
immediately. Keep movement windows separate from menus, loading and idle time;
include the first appearance being evaluated. Use `annotate_window.py` to record
30-second movement windows for `first_arrival` and `immediate_revisit`. Record
matching sections of the route in both modes. Exit normally, then launch:

```sh
python3 prepare_comparison.py launch NEW_WORK APP --comparison pipeline \
  --label screen-candidate --warmup on --pipeline-opt both
```

Both runs restore the same immutable cache/archive/tracking/settings seed and
enable the same warm-up. The launcher verifies the seed again before handoff.
Timing capture is bounded to 900 seconds and 64 MiB. No heavyweight traces or
forced game exits are used.

Create a JSON manifest with `comparison: "pipeline"`, `candidate_mode: "both"`,
and one `pairs` entry (`id: "1"`) containing `baseline` and `candidate` samples
for `first_arrival` and `immediate_revisit`. Each sample contains `capture`,
`start_us`, `end_us`, `activity: "movement"`, `route`, `settings_sha256`,
`starting_cache_sha256`, `seed_sha256`, and `starting_inputs_sha256`, copied from
that run's `session.json` and activity annotation. Do not invent activity windows.

```sh
python3 compare_performance.py SCREEN.json --screen
python3 prepare_comparison.py record-screen NEW_WORK SCREEN.json
```

A screen requires fewer first-arrival and total movement intervals above 50 ms,
no phase p99 regression over 1 ms, equal inputs/settings, finalized schema-2
captures, retained frames and compilation evidence. A screening pass never
authorizes replacement. Report independently measured CPU savings separately;
they cannot pass a stutter failure. New shader/pipeline scope totals are API spans,
not whole-process CPU measurements.

## Expand only after improvement

Scored pair launches are blocked until the screen is recorded as improved. Use
the existing alternating order: pair 1 baseline then candidate, pair 2 candidate
then baseline, pair 3 baseline then candidate. Include each mode's `-restart`
launch. Keep `--comparison pipeline --warmup on` in every launch, baseline
`--pipeline-opt off` and candidate `--pipeline-opt both`. Finish with `persistence`
using candidate settings and no cache reset.

The final manifest has three pairs with `first_arrival`, `immediate_revisit` and
`after_restart`, plus `persistence: {"capture": ...}`. Only actual user confirmation
sets `movement_and_combat_accepted` and `graphics_accepted` to true. All frame,
p99, matched-input, restart and visual gates must pass before replacement. The
original `compare_first_use.py` warm-up gates remain unchanged.

If the pipeline screen shows no improvement, prepare a separate fresh experiment
and compare `--comparison queue --pipeline-opt off --warmup on`, baseline
`--synchronous-submits 1` versus candidate `--synchronous-submits 0`.
MoltenVK 1.4.2 defaults to `1`; `0` dispatches submission processing to a GCD queue.
This remains experimental; see the [pinned configuration reference](https://github.com/KhronosGroup/MoltenVK/blob/v1.4.2/Docs/MoltenVK_Configuration_Parameters.md#mvk_config_synchronous_queue_submits).
Keep queue submission at `1` throughout the initial pipeline experiment.

## Ordinary-play queue trial

After normal exit, make a fresh comparison copy from the current performance
data. Retain its newly learned shaders and settings. From the graphics-patch
checkout, prepare the separate data folder once:

```sh
python3 portable/prepare_comparison.py prepare \
  '/Users/mac/Library/Application Support/Wizard101 Performance Comparison/Data' \
  '/Users/mac/Library/Application Support/Wizard101 Queue Comparison' \
  '/Users/mac/Desktop/Wizard101 Performance.app'
python3 portable/prepare_comparison.py launch \
  '/Users/mac/Library/Application Support/Wizard101 Queue Comparison' \
  '/Users/mac/Desktop/Wizard101 Performance.app' \
  --comparison queue --label diagnostic --ordinary-play --warmup on \
  --pipeline-opt off --synchronous-submits 0
```

The ordinary-play option permits only the `diagnostic` label in a queue
experiment. It preserves learned inputs, records the selected mode and marks
the launch as unscored. It cannot bypass the controlled screen/pair order or
qualify for rollout. Both submission values are available for ordinary trials;
use `--synchronous-submits 1` to return to baseline after normal exit.

Verify the new session uses pipeline optimizations `off`, queue submissions `0`,
warm-up on, 60 FPS, legacy pacing and `DXVK_ASYNC=0`. The app's normal defaults
remain queue submissions `1` and pipeline optimizations `off`; use the controlled
command to enable this trial. Capture remains bounded to 900 seconds and 64 MiB.
Compare the perceived zone-entry and new-player pauses during normal play, and
check graphics and controls. An unmatched ordinary-play result is exploratory;
any replacement still needs the matched timing and acceptance gates above.

The runtime and warm-up verifiers accept `--synchronous-submits 0|1`, defaulting
to `1`, and record the selected value in their reports. Verify mode `0` before
the gameplay trial; passing synthetic checks does not establish stutter relief.

The ordinary-play queue trial also received "nope same issue" from the user.
Its session confirmed submission mode `0`, pipeline optimizations `off` and
warm-up enabled. Record it as unsuccessful, retain normal submission mode `1`
for the next launch, and leave the active game and working app intact. The
finalized capture retained every presentation, shader and pipeline event but
lost 148 ordinary work events, including 103 texture events. It contains a
169.096-ms foreground wait on the same newly encountered pipeline being
compiled in the background. This is a remaining compilation stall, not a
complete explanation of the zone-entry and player-appearance pauses. Texture
and player-processing leads still require separate investigation. No matched
comparison or rollout acceptance follows from this ordinary-play trial.

## Verify

`verify_pipeline_opt.py` tests mode fallback, shader arrival order, concurrent
duplicate registration, complete state coverage, collision/failure handling,
publication, driver compilation concurrency and shutdown in an isolated prefix.
`verify_runtime.py --pipeline-opt both` exercises rendering, six texture formats,
HUD readbacks, fullscreen transitions and the cursor. `verify_warmup.py
--pipeline-opt both` retains all catalog, scheduling, restart and startup-budget
checks. `verify_learned_warmup.py --pipeline-opt both` replays a read-only copy of
the private learned cache without sign-in. Launcher self-tests and the bundle
audit are also required. Synthetic passes cannot establish gameplay improvement.
