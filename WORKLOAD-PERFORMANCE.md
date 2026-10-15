# Wizard101 Workload Performance candidate

This separate app implements bounded asset reuse and texture preparation with
two CPU workers. It preserves the working renderer's shader translation,
MoltenVK 1.4.2, 60 FPS, legacy pacing, imported 2560×1600 settings and larger
cursor. Previous CPU, pipeline, warm-up and rendering candidates are disabled.
The working app is retained. Gameplay acceptance is pending.

The user's instrumented 15-minute session is the assumed baseline. It contains
repeatable zone-entry stalls and CPU-heavy windows with relatively little GPU
execution. It does not identify the game's avatar-update functions or the
owner/caller responsible for its long lock waits. Those game-owned paths are
unchanged; `W101_LOCK_FIX` is forced to `0`.

## Implemented paths and defaults

| Path | Default | Scope and limits |
| --- | --- | --- |
| Asset cache | On | Native D3DX43 in-memory loaders; static managed 2D textures. SHA-256 content and decode-parameter keys; immutable pixels; fresh texture objects on every hit. Original native decoder handles misses and unsupported cases. |
| CPU workers | Two | Independent packed-16 conversion rows, with the caller processing another stripe. Below-normal priority, 32-job queue; allocation, queue or memory pressure falls back to serial conversion. |
| GPU conversion | Off | Optional compute conversion of large supported 2D packed-16 textures on the existing ordered command stream. No CPU completion wait. Small, dynamic, cube and volume textures retain the CPU path. |
| Game lock/avatars | Unchanged | Exact game functions remain unidentified. Contention records improve attribution without bypassing synchronization. |

Cache contents and in-flight preparation share a conservative 128 MiB process
budget. The cache also evicts at 4,096 entries. Eviction, native decoding,
allocation and D3D calls occur outside cache locks. Device reset and managed
resource eviction clear cached entries. Worker jobs retain their synchronization
objects through completion and drain during ordinary shutdown.

The native-loader adapter is gated to the verified game executable's SHA-256.
An updated executable leaves that adapter inactive until reviewed. Verification
has a disposable probe override; the launcher removes it from game launches.
Original D3DX libraries remain installed and are not shipped in source exports.

## Verification results

Five paired synthetic comparisons on the delivered renderer measured:

- Repeated native texture decoding: median **63.1% less time** with the cache.
- Packed-16 row conversion: median **40.0% less time** with two workers.
- GPU conversion/upload: median **17.8% more time**, so it remains off.
- Profiling around 100 million uncontended lock acquisitions: median CPU-time
  increase **0.7%**. This narrow test does not establish overall profiling cost.

These are targeted checks, not measured reductions in gameplay stutter. GPU
conversion accounted for little time in the baseline capture; enabling compute
cannot be justified as a remedy for the observed game-thread stalls.

Pixel checks cover all 65,536 packed values in five formats, repeated source
rewrites, reset, odd dimensions, padded pitches, partial rectangles and mip
fallback. Native-loader checks compare every mip, independent texture objects,
decode parameters, image information, changed content and failure semantics.
Worker tests exercise 24 simultaneous callers, queue pressure, memory limits,
shutdown and serial fallback. Standard graphics, HUD, cursor and fullscreen
checks are separate from manual gameplay acceptance.

## Use and compare

Open **Wizard101 Workload Performance.app**. Its data directory is separate:
`~/Library/Application Support/Wizard101 Workload Performance/Data`.
**Use performance fixes** starts enabled; unchecking it disables both accepted
candidate paths for comparison. **Capture workload (15 min)** starts off.
Avoid profiling during scored performance comparisons.

Advanced per-process overrides are `W101_ASSET_CACHE=0|1`,
`W101_ASSET_WORKERS=0|2` and `W101_GPU_TEXTURE_CONVERSION=off|auto`.
Only the performance candidate accepts these overrides. The app forces the
unimplemented lock switch off and preserves legacy pacing.

Capture now samples draw timing before clock reads (one in 256 calls), while
retaining workload counters. Successful uncontended and recursive critical
section acquisitions use Wine's original fast path. Actual contention records
include verified Windows/native thread identities, owner-at-wait and a caller
RVA in the main executable; other callers remain unidentified. LastError,
errno, wait results and recursive-lock semantics are preserved.

Recording stops after 900 seconds. Renderer, native, thread-map and contention
streams have respective limits of 112 MiB, 128 MiB, 1 MiB and 4 MiB, leaving
space below the combined 256 MiB budget for metadata. Contention records are
restricted to waits of at least 1 ms. Writers finalize on ordinary shutdown;
loss and incomplete captures remain explicit. Clock alignment uses local
anchors and excludes discontinuous intervals. The report aligns verified
initial-thread contention with presentation gaps but keeps causation unknown.
Short CPU traces remain separate from performance comparisons.

For gameplay acceptance, run at least three matched pairs with recording off:
quiet and crowded Commons after 60 seconds of settling, stationary and movement
windows separately, then zone entry, immediate revisit and entry after restart.
Keep resolution, graphics, cursor, frame cap, route and crowd conditions matched.
Compare median frame intervals, p95/p99 and counts/durations of pauses over
50/100 ms. Require repeatable improvement without new visual, input, shutdown
or sustained-frame-rate regressions before replacing the working app.

## Reproduce

Run these commands from the source export root, after building the pinned
runtime as described in [README.md](README.md). Paths below refer to new build
directories; neither command modifies an installed working app.

```sh
python3 build_workload_performance.py --work /private/tmp/w101-workload-performance
python3 verify_workload_performance.py \
  --build /private/tmp/w101-workload-performance \
  --native-d3dx "/path/to/your/installed/game/Bin/d3dx9_43.dll" \
  --keep verification-local/workload-performance
python3 build_workload_performance.py \
  --work /private/tmp/w101-workload-performance \
  --verified-report verification-local/workload-performance/report.json
python3 build_app.py \
  --output "dist/Wizard101 Workload Performance.app" \
  --runtime /private/tmp/w101-workload-performance/Runtime \
  --renderer /private/tmp/w101-workload-performance/build-workload-d9vk/src/d3d9/d3d9.dll
"dist/Wizard101 Workload Performance.app/Contents/MacOS/Wizard101Native" --self-test
python3 audit_bundle.py "dist/Wizard101 Workload Performance.app"
python3 verify_runtime.py "dist/Wizard101 Workload Performance.app"
python3 verify_workload.py \
  --app "dist/Wizard101 Workload Performance.app" \
  --build /private/tmp/w101-workload-performance \
  --keep verification-local/workload-instrumentation
```

Feature defaults are selected only from a matching renderer report that passes
the profiling gate. Each optimization needs at least 10% median targeted savings
and wins in at least four of five comparisons. The verification report is
hashed into build metadata. Builds also check the original shader-translation
fingerprint and record renderer, runtime, MoltenVK and overlay hashes.

For an already scored build, `verify_workload_performance.py --supplement-only`
runs boundary and recording-limit checks without repeating benchmarks. The
report tool accepts `timing.csv`, with optional `--start-us`/`--end-us` windows:

```sh
python3 workload_report.py "/path/to/capture/timing.csv" --output workload.json
```
