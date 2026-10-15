# Reuse character draw layouts

Implemented as an isolated renderer experiment and a sixth independent saved
launcher switch: `W101_DRAW_LAYOUT_CACHE=0|1`, off by default. The installed
**Wizard101 Optimizations.app is unchanged** because the cold-path gate failed.
The launcher source contains the option; it has not been deployed into the
installed app. Existing selections, learned textures, gameplay settings and
runtime binaries retain their current values.

## Results

The final local report is `verification-local/draw-layout/report.json`.
Production-header CPU measurements on the installed Wine runtime used five
alternating off/on, on/off pairs, one million operations per mode and pair:

- Repeated layouts: **43.75% median preparation CPU savings**, five of five wins.
- Unique layouts: **120% median and worst-pair CPU regression**, above the 2% cap.
- Decision: **not qualified for installation**. These are preparation CPU results,
  not frame-time or gameplay improvements. No live Commons trial was performed.

Exact full render-target pixels matched the installed baseline for both D3D9
and D3D9Ex, across candidate off/on, forced hash collisions and failed admission.
Each run covered 346 readbacks, shader and declaration switches, missing
attributes, state blocks, vertex-buffer and shader/declaration destruction,
280 unique declarations and eviction/revisit, indexed instancing with multiple
instance divisors, fixed-function draws, Reset/ResetEx, fullscreen/windowed and
orderly teardown. All 64 launcher selections passed both FPS modes and both
profiling selections (499 self-tests). Four gate tests include rejection before
any installation mutation, even with an erroneous qualification flag.

The existing texture preparation verification also passed against this DLL:
exact texture pixels/mips, native fallbacks, immutable results, six prepared
handoffs, allocation/upload failures, reset/fullscreen, 128 MiB pressure,
32 MiB persistence, renderer/decoder mismatch and failed atomic saves.

## Implementation

`renderer/draw-layout.patch` changes `D3D9DeviceEx::BindInputLayout`; the
production cache and original construction helper are in
`performance/DrawLayoutCache.h`. Lookup, publication, LRU eviction and cache
reset/destruction occur in command-stream order. Current resource references
remain captured by the existing queued layout command. Cache nodes retain only
values, never COM/resource pointers. Hits restore both arrays/counts and used
and instanced stream masks, then call the same context layout setter. Vertex
buffer binding, shader binding and draw order stay intact.

Keys retain all six fields of every ordered declaration element, the ordered
shader semantic usage/index pairs, every stream frequency and the instancing
mask. Structural hashing selects a bucket; full equality resolves collisions.
Programmable versus fixed-function input is also distinguished. PositionT
normalization and missing-attribute/null-stream frequency behavior follow the
original construction path. Unsupported keys and allocation/budget failures
use that construction path.

Each device admits at most **256 entries and 1 MiB**, including bucket storage
and conservatively charged allocator overhead. `performance/AssetBudget.h`
contains the existing atomic 128 MiB lease shared with decoded textures,
preparation and workers. Cache nodes reserve bytes before allocating. Failed
publication releases its reservation. Heavy profiling stays opt-in; test
controls are stripped by the launcher, and normal gameplay emits no per-layout
logging. The test-only CPU probe uses the production key/cache/construction
code and thread CPU time; its all-unique workload exposes admission overhead.

## Reproduce and installation gate

From `graphics-patch`:

```sh
python3 portable/build_draw_layout.py --baseline /private/tmp/w101-asset-preparation
python3 portable/build_app.py --development --output /private/tmp/w101-layout-launcher.app
python3 portable/verify_draw_layout.py --keep portable/verification-local/draw-layout
python3 -m unittest discover -s portable/tests -p test_draw_layout.py
python3 portable/verify_asset_preparation.py --work /private/tmp/w101-draw-layout --keep portable/verification-local/draw-layout-assets
python3 portable/install_draw_layout.py
```

The last command currently refuses installation. It requires exact input,
renderer, launcher and runtime hashes, every correctness check, >=10% median
reuse CPU savings, four of five wins and <=2% cold regression in every pair.
A failed gate performs no app, game, preferences or learned-cache writes.

The local baseline snapshot is at
`/private/tmp/w101-draw-layout/baseline-backup/`; it holds an APFS clone of the
current app, the game renderer and a byte-identical learned texture cache.
If a future candidate qualifies, the installer additionally creates a durable
backup under the existing data parent's `Rollback/draw-layout-TIMESTAMP`,
replaces the same launcher transactionally and leaves the option off. It
retains the existing bundle ID/data root so selections persist independently.
The learned texture cache retains its binary-identity checks: the new DLL
invalidates old preparation records, so play and quit normally to relearn.
Rollback restores the previous app, renderer and original learned textures:

```sh
python3 portable/install_draw_layout.py --restore "/path/to/Rollback/draw-layout-TIMESTAMP"
```

Only gate rejection and snapshots were exercised locally. The successful
installation/rollback path remains unexercised because this candidate failed.

## Gameplay acceptance after a qualifying build

Keep Capture workload off and every other selection fixed. Restart the game
before each trial; compare three pairs **off/on, on/off, off/on** in the same
realm. Observe Commons after 60 seconds settling, stationary and moving play,
and new-player arrivals. Record visible pause count and longest pause separately
for settled crowds and arrivals, plus visual, combat and control behavior.
Keep the option experimental until both scenarios show repeatable visible
improvement without regressions. Preserve all animations, draws, controls,
60 FPS, 2560x1600, graphics settings, larger cursor and legacy pacing.

Stream-frequency tests follow Microsoft's
[SetStreamSourceFreq documentation](https://learn.microsoft.com/en-us/windows/win32/api/d3d9/nf-d3d9-idirect3ddevice9-setstreamsourcefreq).
