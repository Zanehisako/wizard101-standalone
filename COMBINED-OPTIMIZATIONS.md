# Wizard101 Optimizations

One app includes buffer decompression, streaming decompression, sharded Wine
wait queues and native Apple Silicon whole-buffer decoding. Open
**Optimizations…** in the launcher to choose each option independently. Choices
are saved for the next launch. **Prepare known assets** additionally uploads
previously learned textures before gameplay, without a startup cutoff; see
[ASSET-PREPARATION.md](ASSET-PREPARATION.md). **Reset to baseline** turns all five experiments
off; the existing asset cache, two workers, 60 FPS, legacy pacing, resolution,
graphics settings and larger cursor retain the performance baseline.

The combined app has its own APFS-cloned installation under
`~/Library/Application Support/Wizard101 Optimizations/Data`. It contains one
bundled runtime and renderer. Original apps and installations remain available.
It does not package proprietary game content or credentials.

Native decoding runs first for qualifying large whole buffers. When unavailable
or unsuccessful, an enabled buffer decoder is the next fallback, followed by
the original game DLL. Streaming retains one backend per operation. The same
64 MiB additional decoding budget includes native reservations. Wait queues
only change address sharding; game lock ownership and work remain unchanged.

The original four-feature combined runtime passes all 16 switch combinations, original import/backend
checks with decoding off, compatibility with malformed/fragmented data, public
stream state/reset/cleanup, memory exhaustion, concurrency, native startup/crash/
timeout fallbacks and wait-queue ordering/wakeup/timeout/ownership stress.
Individual synthetic benchmark results are in STUTTER-EXPERIMENTS-RESULTS.md;
those timings were measured in the separate candidates. Combined gameplay and
performance have not been accepted. Compare one feature at a time before
combining settings.

The launcher no longer requires a 512 MiB update staging reserve when there are
no updates to stage. Real updates still require room for missing content and
the reserve. Duplicate release ZIPs and disposable test prefixes were removed
to recover storage; app bundles, game data and reproducible source are retained.

## Rebuild

Build the pinned runtime and Workload Performance baseline described in
STUTTER-EXPERIMENTS.md first. From this source directory:

```sh
python3 build_combined.py --thread-baseline /private/tmp/w101-workload-build
python3 verify_combined.py --thread-baseline /private/tmp/w101-workload-build --data "/path/to/baseline/Data"
python3 package_experiment.py combined --work /private/tmp/w101-combined --baseline-app "/path/to/Wizard101 Workload Performance.app" --baseline-data "/path/to/baseline/Data"
```

Packaging requires fresh app/data destinations and checks the measured binary,
input and report hashes. `--launcher` optionally reuses a launcher freshly built
from this source. The original executable/DLL SHA-256 gates, source revisions,
fallback rules and helper protocol are detailed in STUTTER-EXPERIMENTS.md.
