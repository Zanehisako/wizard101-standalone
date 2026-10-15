# Verification results, 2026-10-04

These are targeted synthetic results on Apple M1. Gameplay acceptance is pending.
Five alternating pairs are scored independently, without overlapping candidate
benchmarks or heavy profiling. Each path needs 10% median savings, four wins
and passing compatibility checks.

| Path | Median less time | Wins | Gate |
| --- | ---: | ---: | --- |
| buffer decompression | 37.3% | 5/5 | pass |
| stream decompression | 27.6% | 5/5 | pass |
| Wait-queue collisions | 98.1% | 5/5 | pass |
| Native whole-buffer decode vs original DLL | 40.1% | 4/5 | pass |

Defaults: decompression `both`, wait queues `sharded`, native decode `auto`.
These remain three independent apps. The native app compares with the original
game DLL and keeps the decompression and wait-queue experiments off. Its extra
median savings over in-process libdeflate were
6.1%; that separate comparison is below 10%.
The first observed native startup was 361.8 ms and
is charged to the first scored pair, which lost. Later startups and all copying,
communication and completion costs are included in their respective pairs.

Compatibility checks cover decoded bytes, checksums, public streaming state
after initialization/inflate/reset, return codes, fragmented input/output,
normal, sync, finish, block and later/unknown flush values, dictionaries on
original-backed streams, invalid/truncated data, 64 damaged-input mutations,
window headers, input/output caps, allocation failure, memory exhaustion and
48 concurrent callers. A deterministic stream opened during hook publication
stays original-backed through decode, reset and cleanup. Output redzones and
aggregate memory limits pass.

Wait-queue verification covers FIFO order, wake-one, wake-all with 280 waiters,
colliding addresses, timeout/wakeup races, invalid sizes, recursive critical
sections, ownership, thread joins and modified-executable rejection.
Native IPC verification covers byte equality, unsupported and short requests,
malformed inputs, concurrency, startup failure, helper crashes, 50 ms timeout,
late replies, slot saturation, quarantine, shutdown and parent-death cleanup.
Both production and disposable executable gates are checked.

Each app passes the bundle/dependency/signature audit, synthetic graphics and
texture readbacks, HUD readbacks, larger-cursor hotspot/transparency and
fullscreen/windowed transition checks. All three launchers passed 109 self-tests
again after the original game closed. All three full update checks queue zero
downloads; the native app's corrected data-folder metadata also passes its
read-only inventory probe. No installed game files changed. The existing
Python regression suite passes all 56 tests. Existing apps, executable, original
zlib DLL, resolution/graphics settings and starting caches are preserved.

Real sign-in, gameplay visuals, controls/combat and reduction of Commons/arrival/
zone-entry stutter still need the matched gameplay trials described in
STUTTER-EXPERIMENTS.md. No gameplay performance improvement is claimed.

JSON reports accompanying the source contain individual timings and binary
SHA-256 values. Production bundles contain no game assets, proprietary DLLs,
credentials, disposable probe identities or fault-injection flags.
