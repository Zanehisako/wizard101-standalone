# Crowd workload and zone loading

**Gameplay status, 3 October 2026:** the user accepts the instrumented session as
the baseline for investigating stutter, despite reporting worse performance while
logging. CPU-heavy loading and critical-section waits are observed; their exact
functions remain partly unresolved. The separate workload-performance candidate
adds code changes and reduces hot-path recorder overhead. Gameplay gains require
matched comparisons and user acceptance. Detailed evidence is in
`verification-local/workload-gameplay-2026-10-03-EF6D27F5/REPORT.md`.

The rendering candidate was unsuccessful. This separate app uses the working
D9VK renderer and MoltenVK 1.4.2, with warm-up, catalog, CPU, pipeline and stutter
optimizations disabled. It preserves 60 FPS, legacy pacing, graphics settings,
2560×1600 and the larger cursor. The working apps and their data are retained.

## Use the app

Open **Wizard101 Workload Diagnostics.app** on the Desktop. Its data folder is
`~/Library/Application Support/Wizard101 Workload Diagnostics/Data`.
Use the existing **Capture workload (15 minutes)** checkbox before launching.
It defaults off every time. The launcher still signs in, checks installed content,
starts the game directly and closes after handoff. Credentials are kept out of
the recordings. **Launch logs** opens the capture folder before launch; after
handoff, look in `Data/Prefix/drive_c/NativeLogs/native-*/`.

Each enabled capture writes `timing.csv`, `native.jsonl`, `threads.jsonl` and
`session.json`. Event recording ends after at most 900 seconds; finalization runs on the next
writer wake-up (normally 250 ms; scheduling can delay it). CSV uses at most 112 MiB, native data 128 MiB,
and thread identities 1 MiB. These reserve space within the 256 MiB recording
budget. GPU handlers never wait for disk; bounded queues explicitly count loss.
Ordinary shutdown flushes the writers. An abrupt exit leaves incomplete data,
which the report rejects as complete evidence.

## Record the two symptoms separately

Keep the same resolution, frame cap, graphics settings and camera route. Use
three repetitions, noting realm and visible player count in the window notes.
Do not run Instruments, `sample`, screen recording or other heavy traces during
performance comparison windows.

1. Visit quiet Commons; settle for **60 seconds**. Record **30 seconds stationary**,
   then **30 seconds moving** along a fixed route.
2. Repeat in crowded Commons, settling for **60 seconds** again. Keep stationary
   and moving windows separate. Alternate quiet/crowded order across repetitions.
3. In a separate recording, mark a portal/zone transition on first entry, then
   immediately revisit the same zone. Exit normally, restart the app/game, and
   mark the same entry after restart. Do not restore learned caches between these
   three phases: retained caches are part of the distinction being investigated.
4. Repeat the zone trio, noting the exact zone and whether the pause recurred.

Run the annotation command just before each 30-second window (paths are examples):

```sh
python3 portable/annotate_window.py /path/to/timing.csv --activity stationary --phase diagnostic --zone Commons --crowd quiet --settled-seconds 60
python3 portable/annotate_window.py /path/to/timing.csv --activity movement --phase diagnostic --zone Commons --crowd crowded --settled-seconds 60
python3 portable/annotate_window.py /path/to/timing.csv --activity loading --phase first_arrival --zone Ravenwood
python3 portable/annotate_window.py /path/to/timing.csv --activity loading --phase immediate_revisit --zone Ravenwood
python3 portable/annotate_window.py /path/to/timing.csv --activity loading --phase after_restart --zone Ravenwood
```

Use `--seconds` for a shorter transition window. Crowd settling metadata is an
operator statement; annotation does not detect player count or prove settling.
For fixed-input repeats, the existing `prepare_comparison.py` can APFS-clone and
freeze archives, tracking, settings and caches before the handoff. Retain seed
hashes and restart/handoff checks when comparing a future fix to the baseline.

## Interpret the evidence

```sh
python3 portable/workload_report.py /path/to/timing.csv --start-us 60000000 --end-us 90000000 --output /path/to/window-report.json
```

- Draw requests and primitive counts, texture creation and queued upload bytes,
  file-read bytes/results and resource waits come from the renderer/game import
  hooks. Short events are aggregated; longer spans retain thread and duration.
- Read hooks cover the main executable's static imports. Overlapped calls are
  labeled **async admission**, not completed disk work. Dynamic imports, other
  modules, mapped file faults, decompression and avatar logic need CPU stacks.
- Native CPU snapshots give each thread's CPU time every 250 ms. Wine's
  `init_first_thread` and subsequent thread-start callsites record exact Windows
  and native kernel IDs, including the initial game thread. Thread names do not
  establish identity; unresolved stacks and unmapped threads stay unidentified.
- Metal execution timestamps are recorded in command-buffer completion handlers.
  Their system Mach clock is bracketed against Unix time and the renderer's
  synchronized clock. Missing/zero timestamps, drift, unfinished recordings and
  loss are explicit. GPU occupancy uses a union of concurrent intervals; adding
  durations would double-count overlapping work. Buffer creation is not submission.
- Process page-ins, disk read bytes, resident size and physical footprint are
  sampled alongside host page-ins/compressions and memory pressure notifications.
  Unavailable counters are flagged. Host counters also include other processes.

The report provides **correlations**, and keeps the cause `unidentified`. A
responsible path requires repeated, aligned observations and CPU stacks on a
verified thread. Avatar-update warnings and failed texture loads are leads.
They do not establish the cause of either symptom.

For a short CPU trace, launch a separate session with `W101_COMPARISON_LABEL=trace-cpu`
and comparison metadata `{"heavyweight_trace":true}`. Enable capture manually,
then use the existing `capture_trace.py cpu --pid PID --capture PATH --output NEW.trace`.
Its 30-second trace is separate from scored windows. Thread-state or full Metal
traces remain optional and require the existing disk-space gate.

Synthetic graphics, texture/upload, HUD, cursor, fullscreen, launcher and capture
checks cannot establish gameplay correctness or performance. Confirm those in
the real game before accepting any future fix or replacing the working app.

## Reproduce the build

Prepare the pinned Wine 11.0 and MoltenVK 1.4.2 baseline with the existing build
scripts, then use a fresh build directory:

```sh
python3 portable/build_workload.py --work /private/tmp/w101-workload-build
python3 portable/build_app.py --output 'portable/dist/Wizard101 Workload Diagnostics.app' --runtime /private/tmp/w101-workload-build/Runtime --renderer /private/tmp/w101-workload-build/build-workload-d9vk/src/d3d9/d3d9.dll
python3 portable/verify_workload.py --app 'portable/dist/Wizard101 Workload Diagnostics.app' --build /private/tmp/w101-workload-build --keep portable/verification-local/workload
python3 portable/verify_runtime.py 'portable/dist/Wizard101 Workload Diagnostics.app' --keep-logs portable/verification-local/workload-graphics
```

The workload builder uses separate source/output trees and an APFS runtime clone.
It compiles patched Wine thread callsites using the configured baseline's actual
compile/link commands and objects, without modifying the baseline source or
binary. It separately builds patched MoltenVK 1.4.2. Build metadata records
renderer, native-library and instrumentation input hashes. Existing renderer
translation and cache compatibility stay unchanged. The source archive contains
the build scripts, patches, probes and licenses, without accounts or game assets.

Return to the working app for rollback. This app has an independent bundle ID and
data directory and does not replace the working installation.

Timestamp reference: [Apple gpuStartTime](https://developer.apple.com/documentation/metal/mtlcommandbuffer/gpustarttime)
and [gpuEndTime](https://developer.apple.com/documentation/metal/mtlcommandbuffer/gpuendtime).
