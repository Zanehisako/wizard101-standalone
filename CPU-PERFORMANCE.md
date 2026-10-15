# CPU performance candidate

`Wizard101 CPU Performance.app` is an experimental, separate app. Its renderer
supports `DXVK_W101_CPU_OPT=off|constants|locking|both`, defaulting to `off`.
Unrecognized values also select `off`. It preserves 60 FPS, 2560×1600 and imported
visual settings, the larger cursor, MoltenVK 1.4.2, legacy pacing, `DXVK_ASYNC=0`,
synchronous queue submissions `1`, and pipeline optimizations `off`. Warm-up
remains opt-in; CPU comparisons enable the same warm-up in both modes, with the
existing maximum 10-second startup wait.

The [upstream constant optimization](https://github.com/doitsujin/dxvk/commit/7d9ce6bfcab8702523b9d555349cac44e1bab61c)
and [recursive-lock optimization](https://github.com/doitsujin/dxvk/commit/9d0f0023aa04eb9475ca93c5a15ed34ce0e60f1f)
informed these backports. This older renderer retains its own float emulation
and recursion accounting. Neither upstream change establishes a Wizard101 fix.

## What changes

Constant comparison runs after validation, register clamping, state-block
recording, and high-water register accounting. Raw float/integer comparisons use
bit equality. Emulated floats compare against the existing NaN-to-zero result;
signed zero remains distinct. Booleans compare normalized truth values. An equal
set preserves any dirty flag already raised by shader switches, reset, or other
work. Recording unchanged constants still captures them. Changed sets retain
the existing update and upload path.

The device lock checks ownership before attempting a recursive CAS. The owner
increments the existing recursion count; every guard still releases exactly one
acquisition. Guard moves, including a nested guard outliving the original outer
guard, preserve exclusion. Self-move is harmless. Other threads use the existing
acquire/CAS and release ordering. Driver compilation locks are unchanged. Shader
translation fingerprints and all cache formats are unchanged.

Timing capture adds `GetProcessTimes` samples once per second within the existing
900-second/64-MiB capture limits. Fixed, per-thread slots aggregate constant-set,
unchanged-set, actual-upload, acquired-lock, and fast-recursion counts. Counter
slot overflow is reported; snapshots use relaxed atomics and are approximate.
Counters stop when capture stops. Capture includes the recorder's own CPU work.
Wine's process CPU readings have coarse resolution, so short segments are not
suitable gameplay CPU measurements.

Eight main-executable D3DX9 texture imports receive timing-only wrappers,
including ordinal imports matched to the loaded library's named exports. Every
argument, output, HRESULT and incoming/outgoing Win32 error is preserved. Labels
contain only the function name; no filenames, asset bytes, addresses, handles,
credentials or session keys are recorded. These timings cover synchronous D3DX
calls, not every game-side loading path. The renderer retains existing read and
pipeline timings, synchronized frame intervals and event-loss accounting.

## Build and verify

```sh
W101_BUILD_ROOT=/private/tmp/w101-cpu python3 build_renderer.py --cpu-candidate
python3 build_app.py --output 'dist/cpu/Wizard101 CPU Performance.app' \
  --runtime /private/tmp/w101-runtime-26.3.0/runtime \
  --renderer /private/tmp/w101-cpu/build-cpu-d9vk/src/d3d9/d3d9.dll \
  --capture-timing
python3 verify_cpu_opt.py --app 'dist/cpu/Wizard101 CPU Performance.app' \
  --source /private/tmp/w101-cpu/cpu-d9vk \
  --build /private/tmp/w101-cpu/build-cpu-d9vk \
  --keep verification-local/cpu-opt
```

Build the pinned runtime with `build_runtime.py` first if it is missing. Inputs
and checksums are in `sources.lock.json`; the CPU overlay is `renderer/cpu.patch`.
The separate source tree and build stamps support repeat builds. The app's
`cpu-build.json` records its renderer hash, source fingerprint, patch hashes and
mode defaults. The launcher records the selected CPU mode in each `session.json`.

Verification exercises float/int/bool values and normalization, raw NaN payloads,
emulated NaNs, signed zero, register boundaries, state blocks, shader switches,
resets, recursion, contention, moved guards, self-moves, exceptions, eight texture
hooks, CPU sample cadence and aggregate counts. GPU tests use the actual candidate
DLL. Benchmarks run four modes in five alternating rounds with profiling disabled.
The repeated/changing-constant workloads submit actual programmable-shader draws;
lock workloads use the production device-lock class. Compilation/setup are outside
the measured intervals. Reports retain raw runs and process CPU medians.

Each optimization must improve its target median CPU time at least 10%, with no
median regression above 5% in changing-data or contended workloads. The combined
mode must pass both targets. A synthetic pass permits an experimental trial; it
does not establish gameplay CPU savings or numerical stutter reduction.

The first local benchmark of renderer `d2869ad4` passed these gates. Combined mode
measured 40 vs 240 ms for 100,000 repeated-constant draws (83.3% lower CPU time),
60 vs 160 ms for 12 million nested locks (62.5% lower), 230 vs 240 ms for changing
constants, and 450 vs 460 ms for contended locks. These are synthetic workloads,
not normal gameplay. Each individual mode also passed its targeted gate. Full
raw measurements remain private under `verification-local/cpu-opt/report.json`.

## Ordinary-play trial and rollback

Exit existing games/launchers normally. Create an independent APFS copy of the
latest standalone data, retaining settings and newly learned caches:

```sh
python3 prepare_comparison.py prepare SOURCE_DATA \
  "$HOME/Library/Application Support/Wizard101 CPU Performance Comparison" \
  '/Users/mac/Desktop/Wizard101 CPU Performance.app'
python3 prepare_comparison.py launch \
  "$HOME/Library/Application Support/Wizard101 CPU Performance Comparison" \
  '/Users/mac/Desktop/Wizard101 CPU Performance.app' \
  --comparison cpu --ordinary-play --label diagnostic --warmup on \
  --pipeline-opt off --cpu-opt both --synchronous-submits 1
```

This trial preserves the copied inputs and is explicitly unscored. Sign in
locally and play normally, checking movement/combat, HUD/text/icons, transparency,
effects, cursor and controls. Session metadata must report `cpu_optimization:
"both"`, pipeline `off`, submissions `1`, capped frame rate, legacy pacing,
async false and warm-up true. The renderer log must agree on the CPU mode.

The working app and its data are untouched. To disable the optimization, exit
normally and rerun the launch command with `--cpu-opt off`; opening the app
normally also defaults to `off`. To return to the accepted installation, exit
normally and use your existing working launcher. Never force-close gameplay or replace
the working app based on synthetic results.

## Matched gameplay acceptance

Only after the ordinary trial, create an immutable input seed with
`prepare_comparison.py seed WORK`. Use the existing controlled screen/pair labels,
`--comparison cpu --warmup on --pipeline-opt off --synchronous-submits 1`, baseline
`--cpu-opt off`, and candidate `--cpu-opt both` (or another qualifying CPU mode).
Use the existing Ravenwood → Commons → Pet Pavilion → Commons route, mark actual
30-second movement segments with `annotate_window.py`, and include first arrival,
immediate revisit, and post-restart. Never fabricate windows or confirmations.

A comparison manifest selects `comparison: "cpu"` and `candidate_mode: "both"`.
`compare_performance.py` verifies matched archives, caches, tracking, settings,
renderer, warm-up, cap, pacing, submission mode, event coverage and CPU samples.
CPU changes come from complete sample intervals inside marked windows. At least
four intervals and 80% CPU coverage per movement segment are required. Partial
intervals and gaps between movement segments are excluded. CPU results are
reported separately, so experimental CPU savings can coexist with unresolved
large pauses.

Screening never permits replacement. Expansion to three alternating pairs still
requires improved screening; persistence uses an ordinary restart without a seed
reset. Replacement requires fewer movement frames above 50 ms, no p99 regression
over 1 ms, and the user's graphics/control/gameplay confirmation. First-use shader
compilation pauses remain unresolved until separately measured and improved.
