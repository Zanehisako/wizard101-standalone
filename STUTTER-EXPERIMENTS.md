# Separate Wizard101 stutter experiments

The delivered apps retain the current Workload Performance renderer, asset
cache and two workers, 60 FPS, legacy pacing, MoltenVK 1.4.2, installed
2560×1600 settings and larger cursor. Animation, controls, combat and game locks
are unchanged. Each app has an independent APFS-cloned installation under
`~/Library/Application Support/<app name>/Data`. Existing apps are retained.

## Decompression

`Wizard101 Decompression.app` hooks only the verified main executable's
`uncompress`, `inflateInit_`, `inflate`, `inflateReset` and `inflateEnd` imports
from the verified `zlib1v142x64.dll` (version 1.2.3). Installation occurs at the
first D3D9 initialization, outside the DLL loader lock. Streams opened earlier
or during import publication and caller-supplied allocators remain on the original
backend. Shadow streams are admitted only after every hook is installed. Both executable
and original-DLL SHA-256 gates fail closed after an update.

Source pins are libdeflate 1.26 at
`92e6a0db9fa848d742f9eb286c92afc60f2c3dda` and zlib-ng 2.3.3 at
`12731092979c6d07f42da27da673a9f6c7b13586`. Archive SHA-256 values are in
`decompression/sources.lock.json`. zlib-ng is compiled in compatibility mode
with private `w101ng_` symbols; the original DLL and all compression, gzip,
dictionary and other-module callers remain installed.

Whole-buffer acceleration accepts 32 KiB–4 MiB input and at most 8 MiB output.
It decodes into scratch storage and publishes only successful decoded bytes.
Failures, unsupported requests and exhausted budgets call the original DLL.
Additional decoder heap allocation is atomically limited to 64 MiB, including
allocation headers and conservative static-map space. Streaming operations
retain their chosen backend through reset and cleanup, with public allocator
callbacks and the original state pointer preserved by a shadow-stream adapter.

The streaming contract compares produced bytes, return codes, input/output
pointers and availability, totals, Adler checksums, message text, data type,
reserved state and callbacks at every step. Unproduced bytes inside an offered
output region are not defined decoded output; separate redzones check that
neither backend writes outside the supplied output region. Dictionary requests
return the original `Z_NEED_DICT` state; complete dictionary decoding is tested
on pre-existing and custom-allocator streams, which retain the original DLL.
The verified game has no dictionary-setter import to replace.

Switch: `W101_DECOMPRESS=off|buffer|stream|both`. The app's **Use experiment**
checkbox disables only these new paths. Existing cache and workers stay on.

## Wine address-wait queues

`Wizard101 Wait Queues.app` changes only Wine's address-to-queue selection in
its private ntdll PE module. The original 256 queues and exact original
wait/wake implementation remain available. The experimental table has 4,096
mixed-hash slots, each aligned and separated by 128 bytes. Table choice is
immutable before the first waiter is admitted. Early initialization uses NT
file I/O and an allocation-free SHA-256 gate; recursive initialization selects
the original table permanently.

Same-address FIFO order, wake-one/all batching, timeout handling and critical
section ownership/recursion use the original implementation. This changes no
work done by a game lock owner. `W101_WAIT_QUEUES=off|sharded` is restricted to
the verified game process. Disposable verifier builds contain only the exact
probe hash and test-only queue introspection exports; production builds have
neither bypass flags nor test exports.

The targeted benchmark deliberately creates addresses that collide under the
old hash. Its savings describe that collision case, not overall game CPU time.

## Native decode

`Wizard101 Native Decode.app` starts a thin ARM64 helper during graphics
initialization and uses a private ntdll Unix-call bridge. A socket pair and an
unlinked 32 MiB shared-memory arena are inherited by the helper. Two workers
use two slots, each with 4 MiB input and 8 MiB output regions. Only whole-buffer
inputs of 256 KiB–4 MiB qualify; streaming uses the original in-process DLL.
The native candidate does not enable the decompression or wait-queue
experiment alongside it. Its ordinary fallback is the original game DLL.

Busy slots fall back immediately. Startup has a separate two-second maximum
to allow first executable validation; requests have a 50 ms deadline. Failed
startup disables offloading. Timed-out slots are quarantined and helper failure
disables offloading for the launch. Data never goes directly from the helper
into a caller's buffers. Completion uses acquire/release shared state;
notification sends never block worker completion. The helper exits if its
parent disappears. Normal shutdown kills/reaps it and releases mappings/fds.

The adapter reserves 34 MiB of its 64 MiB budget for shared storage and helper
decoder/thread overhead. Remaining scratch and decoder allocations use the
same atomic budget. `W101_NATIVE_DECODE=off|auto` controls offloading; helper
paths and test-fault flags cannot be inherited through the production launcher.

## Build and verify

Install the toolchain in README.md and build the pinned runtime first. All
commands below are run from this source directory; they never require an
installed CrossOver. The baseline source build is a prerequisite, and its
runtime/renderer must match the current performance baseline app.

```sh
python3 build_runtime.py
python3 build_workload.py --work /private/tmp/w101-workload-build
python3 build_workload_performance.py --work /private/tmp/w101-workload-performance
python3 build_decompression.py
python3 verify_decompression.py --game-bin "/path/to/installed/Wizard101/Bin" --baseline-data "/path/to/baseline/Data"
python3 build_wait_queues.py
python3 verify_wait_queues.py --data "/path/to/baseline/Data"
python3 build_native_decode.py --thread-baseline /private/tmp/w101-workload-build
python3 verify_native_decode.py --data "/path/to/baseline/Data" --thread-baseline /private/tmp/w101-workload-build
python3 package_experiment.py decompression --work /private/tmp/w101-decompression --baseline-app "/path/to/Wizard101 Workload Performance.app" --baseline-data "/path/to/baseline/Data"
python3 package_experiment.py wait-queues --work /private/tmp/w101-wait-queues --baseline-app "/path/to/Wizard101 Workload Performance.app" --baseline-data "/path/to/baseline/Data"
python3 package_experiment.py native-decode --work /private/tmp/w101-native-decode --baseline-app "/path/to/Wizard101 Workload Performance.app" --baseline-data "/path/to/baseline/Data"
```

Verification uses your installed proprietary DLL only as a local reference;
the game and DLL are excluded from source exports and app bundles. Apps include
upstream licenses. Packaging requires a new app/data destination and verifies
the measured binaries, source inputs, report hash and current baseline renderer.
The launcher reinstalls and integrity-checks its adapter during fresh setup.

Each path needs passing compatibility checks and at least 10% median targeted
savings across five alternating pairs, winning four pairs. Otherwise it stays
off. Native scores include startup, copying, IPC and completion; the first
observed startup is charged to the first scored pair if slower. An additional
comparison with in-process libdeflate is reported separately. Machine-readable
results are supplied alongside the source archive; they are synthetic evidence.

## Gameplay acceptance

Open each app separately, with capture off. Use short matched Commons routes,
new arrivals, zone entry, immediate revisit and the same route after restarting.
Compare **Use experiment** on/off from the same starting cache and installation
snapshot. `prepare_comparison.py` provides frozen APFS seeds for scored trials.
Confirm HUD/text/icons, cursor, fullscreen, movement, controls and combat.
Heavy CPU/GPU profiling stays outside comparisons. Frame-only measurement
requires its own overhead gate before scoring. Combine features only after
each has independent gameplay acceptance. No gameplay stutter improvement is
claimed by these builds or synthetic checks.
