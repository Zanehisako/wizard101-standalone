# Draw-layout cache revision 2

V2 is a separate, rejected experiment. The installed Wizard101 Optimizations
app, game renderer, learned textures, selections and gameplay settings are
unchanged. `W101_DRAW_LAYOUT_CACHE=0|1` remains experimental and off by default.
No Commons or arrival trial was performed; gameplay improvement is unverified.

## Implementation

`performance/DrawLayoutCacheV2.h` and `renderer/draw-layout-v2.patch` retain the
original layout construction on misses, unsupported resources and failed
reservations. Declarations prepare complete ordered element fingerprints at
creation and refresh them when SetFVF replaces elements. Vertex shader resources
prepare ordered usage/index fingerprints at creation; each device separately
prepares its fixed-function signature. Shared shader modules do not charge their
first device for another device's resources.

Command-stream lookup borrows metadata while the existing queued COM references
keep its resources alive. Slots own complete value keys and compare every field
after hashing, including semantic order, frequencies and instancing masks.
The 256-slot pool is reserved at device creation. Publication and LRU eviction
reuse slots without allocating, freeing or changing budget reservations. Reset
clears entries in command-stream order and retains the reserved pool; teardown
releases it after earlier layout commands.

Pool, cache, fingerprint allocations, control blocks and conservative allocation
overhead share the 1 MiB device cap and existing atomic 128 MiB process budget.
Metadata holds only detached budget state and values, with no device/resource
reference. Failed resource metadata uses the original construction path.

## Measurements and gates

The evidence is `verification-local/draw-layout-v2/report.json`. CPU probes use
production code and thread CPU time. Every reported sample lasts at least two
seconds, with five alternating off/on, on/off pairs per workload. Reuse uses
60,000,000 operations per sample; cold uses 15,000,000; fresh resource samples use
11,428,571 and include source-data copies, fingerprint preparation and metadata
destruction inside the timed interval.

| Workload | Median result | Other evidence |
| --- | --- | --- |
| Reuse | 70.39% CPU savings | Five of five wins |
| Cold | 47.79% CPU regression | Worst pair 57.43% |
| Fresh resources | 98.90% CPU regression | Worst pair 102.40% |

Required gates are at least 10% median paired reuse savings, four wins and no
cold pair above 2% regression. Fresh-resource pairs also enforce the 2% cap so
moving work into resource creation cannot hide a regression. V2 fails both
regression checks and must not be installed.

Components were measured before implementation in v1 and separately in v2;
these include probe loop/sink overhead and are not frame-time measurements.

| Component | V1 ns/operation | V2 ns/operation |
| --- | --- | --- |
| Hash/key preparation during lookup | 30.87 | 6.61 |
| Hit lookup | 33.38 | 28.43 |
| Miss lookup | 2.36 | 1.65 |
| Publication with eviction | 112.43 | 44.69 |
| Fresh declaration plus shader fingerprints | — | 143.05 |

V1's original report remains `verification-local/draw-layout/report.json`;
its source and document snapshot is in `revisions/draw-layout-v1`. Component
evidence is in `verification-local/draw-layout-v1-components`.

Exact pixels matched the installed renderer in all ten D3D9/D3D9Ex baseline,
off, on, forced-collision and failed-allocation modes, with 346 readbacks per
run. Coverage includes instancing, missing attributes, state blocks, destroyed
resources, eviction, alternating FVF inputs, reset and fullscreen. Structural
tests passed for complete equality, allocation-free pool reuse, both budgets,
metadata lifetime and allocator failures. All 64 launcher selections passed
both FPS and profiling modes (500 checks); eleven Python gate tests passed.
Texture compatibility passed with layout caching both off and on, including
pixel/mip equality, prepared handoffs, error fallbacks, reset, fullscreen,
budget pressure, identity mismatches and failed atomic saves.

The first launcher test encountered the user's running game during its fixture
import. Fixture setup now injects its own guarded activity check; normal setup
retains the live-game guard. Launcher and texture checks then completed in
separate phases without repeating successful CPU or pixel measurements.
The real installer refused the failed gate before writes, and installed app,
renderer, configuration, preferences and learned-texture hashes still match
the initial snapshot. Rejected v1's report and archived files also match.

## Reproduce

From `graphics-patch`:

```sh
python3 portable/measure_draw_layout_costs.py
python3 portable/build_draw_layout_v2.py --baseline /private/tmp/w101-asset-preparation
python3 portable/build_app.py --development --output /private/tmp/w101-layout-v2-launcher.app
python3 portable/verify_draw_layout_v2.py --keep portable/verification-local/draw-layout-v2
python3 -m unittest discover -s portable/tests -p 'test_draw_layout*.py'
python3 portable/install_draw_layout.py --work /private/tmp/w101-draw-layout-v2 --launcher /private/tmp/w101-layout-v2-launcher.app --report portable/verification-local/draw-layout-v2/report.json
```

The installation command refuses this revision before any writes. A qualifying
revision would use the existing transactional app/renderer/learned-texture
backup and rollback. Preserve all other switches, 60 FPS, 2560x1600, graphics,
all animation, controls, combat, larger cursor, legacy pacing and MoltenVK 1.4.2.
Only after qualification and a backed-up update should restarted off/on, on/off,
off/on trials compare Commons after 60 seconds settling, stationary and moving
play, and new-player arrivals with heavy profiling off. Both crowd and arrival
scenarios must visibly improve without regressions before gameplay acceptance.
