# Remaining stutter investigation

Local diagnostic app: `dist/stutter-diagnostics/Wizard101 Diagnostics.app`.
It has an isolated data folder and a distinct app identifier. The working
launcher is the rollback. No rendering, shader translation, scheduling, draw
skipping, warm-up budget or pacing behavior changes in `renderer/capture.patch`.
Build it with `build_renderer.py --capture-diagnostic`, then `build_app.py` using
the generated renderer and current MoltenVK 1.4.2 runtime. The builder verifies
the original translation fingerprint before applying instrumentation and emits
`capture-build.json` with hashes of all three patches.

The previous run's 200 restored shaders / 1,968 pipelines / 1.57-second startup,
393-ms lock wait, avatar events, zone loading, texture retries and seasonal image
checks are leads supplied by the investigation plan. They do not establish a
cause. This implementation does not extend preparation.

## Capture

Schema 2 CSVs retain schema 1 column names. They add pipeline IDs derived from
shader keys, packed state bytes and explicit render-pass fields; shader IDs;
coverage labels (`restored`, `new`, `generated`, `unknown`); and foreground or
background role. IDs match request, lock, compilation and driver spans within
the same renderer build. `new` means translated during this launch, including
previously learned shaders when warm-up is off. Coverage is not a claim that all
possible pipeline combinations were prepared. Generated auxiliary shaders are
identified separately. Unknown/internal shaders remain explicitly unknown.

Repeated background request/check spans and reads below 100 microseconds become
count/total/max aggregates. Actual translation and compilation are always kept,
even below that threshold. Longer requests and waits remain timed spans. Frames,
compilation/waits and ordinary work have separate bounded queues; losses are
reported per category. Aggregates and loss counters cover the whole capture,
including when the report requests a smaller window. Time is capped at 900
seconds and the CSV at 64 MiB. Unfinalized or incomplete captures cannot support
acceptance.

Clock metadata samples Unix time, QPC ticks/frequency and a bracketing relative
steady-clock timestamp at startup and every second. Use these samples to align
Instruments and game events, checking clock drift and bracket uncertainty.
Windows thread IDs are **not** native macOS thread IDs. Confirm thread mapping
from native stacks/thread names. CPU API wall time does not measure GPU execution.

CPU and GPU captures use **separate diagnostic launches** and 30-second windows.
Launch `trace-cpu` or `trace-gpu`, sign in locally, then use:

```sh
python3 capture_trace.py cpu --pid GAME_PID --capture SESSION/timing.csv --output LOCAL/cpu.trace
python3 capture_trace.py gpu --pid GAME_PID --capture SESSION/timing.csv --output LOCAL/gpu.trace
```

Find the game PID with `ps -axo pid,comm` (never print session-bearing arguments).
The helper checks the session label, exports the trace table of contents and
writes clock/validity metadata before recording and after export. Metal tracing
requires 16 GiB free: a live 30-second recording generated 4.1 GiB of raw data,
plus large temporary tables and bundle storage. Saving may take several minutes. A
failed save is not a valid trace. Repeat the same movement segment in both traces.
Plain CPU captures use Time Profiler and require 256 MiB free. Optional
`--thread-states` adds Thread State Trace and requires 16 GiB; this instrument
also produced multi-gigabyte raw data and temporary tables. Running-thread
samples alone cannot identify a blocking wait. `thread_map.py`
can read Wine 11 x86-64 TEB pthread pointers and match them to native thread
identifiers before tracing. When Mach inspection is unavailable, it brackets
XNU's ordered handle/ID lists, checks they remained stable, and normalizes the
TSD offset using independent pthread APIs in an x86-64 helper. Unique native
and Wine descriptions are a fallback. The Wine main thread can have a zero
pthread pointer and an empty name; it stays explicitly unmapped. Unavailable
or ambiguous inspection supplies no identity.
Heavyweight traces never share scored sessions. Metal System Trace records CPU
and GPU behavior; see the [pinned MoltenVK guidance](https://github.com/KhronosGroup/MoltenVK/blob/v1.4.2/Docs/MoltenVK_Runtime_UserGuide.md#metal-system-trace-tool).

## Controlled launches

Default route: **Ravenwood → Commons → Pet Pavilion → Commons**. Use 30-second
movement windows at first arrival and immediate repeat. Record portals, loading
screens, menus, idle time and shutdown as separate activities. Do not include a
portal in a movement window. Start from the same character, realm, camera and
route; keep 60 FPS, 2560×1600, graphics settings, larger cursor and legacy pacing.
`annotate_window.py SESSION/timing.csv --activity movement --phase first_arrival
--zone Commons` times and saves a 30-second window with clock uncertainty and
launch hashes in `windows.json`. Begin moving when it prints “Begin now”. Change
activity/phase for the other windows; exclude portals and loading from scoring.

`prepare_comparison.py prepare SOURCE_DATA NEW_WORK APP` creates an APFS clone
and changes only its renderer. After learning and normal exit, `seed WORK`
freezes caches, entire game archive directories, `.utd` tracking files (including
those outside archives), and both settings files. The seed uses separate APFS
file identities, content hashes, read-only permissions and immutable flags.
Each scored launch restores and verifies those bytes. The native launcher checks
them again after installed-content checks and before handing off to the game.
A changed archive or tracking file blocks that run. No active game is killed.

Launch order (every session exits normally before the next):

| Pair | First mode | Second mode |
| --- | --- | --- |
| 1 | baseline, baseline-restart | candidate, candidate-restart |
| 2 | candidate, candidate-restart | baseline, baseline-restart |
| 3 | baseline, baseline-restart | candidate, candidate-restart |

Use `launch WORK APP --label LABEL --warmup off` for baseline and `--warmup on`
for candidate. Both ordinary and `-restart` scored launches restore the seed.
After all pairs, launch `persistence --warmup on`: this one preserves learned
cache changes and checks ordinary restart persistence. An aborted last launch
may be retried under the same label. An existing schema 1 seed must be recreated
in a new comparison folder. To discard a seed deliberately, remove `uchg` flags
and restore directory permissions first; never thaw a seed while using it.

## Evidence and acceptance

`profile_report.py CSV --start-us N --end-us N` reports every >50-ms hitch as
inconclusive until native blocking-thread evidence is supplied. `diagnose_hitches.py
MANIFEST` expects diagnostic trace metadata under `traces`, movement `windows`,
and per-hitch `evidence`: `hitch_start_us`, `cause`, `cpu_trace`, `gpu_trace`,
`blocking_thread`, `native_thread_mapping`, `cpu_stack`, `gpu_observation`,
`trace_time_range`, and `activity`. Compilation coverage evidence also needs
`pipeline_id` and `missing_pipeline_coverage`. Two distinct recurring hitches
must match that pipeline before expansion is supported. Separate CPU/GPU runs
corroborate repeatability; they do not sample the same frame. Retain the actual
trace artifacts and stack/timeline references for review. Lost compilation
records or clock alignment uncertainty leave the result inconclusive.

Asset loading, resource retries, game processing or GPU execution evidence
stops further warm-up work and calls for a separate targeted proposal.

`compare_first_use.py MANIFEST` keeps older reports readable but accepts only
schema 2 scored captures. Each of three distinct pairs contains `baseline` and
`candidate` samples for `first_arrival`, `immediate_revisit`, `after_restart`.
Each sample has `capture`, `start_us`, `end_us`, `activity: movement`, `route`,
`settings_sha256`, `starting_cache_sha256`, `seed_sha256`, `starting_inputs_sha256`.
Hashes must match `session.json`. Add `persistence: {capture: ...}`. Reused windows,
wrong launch order, traced sessions, lost frames/compilation evidence, changed
inputs or unverified handoff cannot pass. Require fewer first-arrival >50-ms
frames and no phase/pair p99 regression over 1 ms. User movement/combat and visual
acceptance remain separate required fields. Do not replace the working launcher
before all live gates pass.

Synthetic checks verify queue pressure, clocks, matching IDs, loss accounting,
legacy parsing, APFS restoration, pixel readbacks, read-hook errors and learned
cache replay. They cannot establish a real-game stutter reduction.
