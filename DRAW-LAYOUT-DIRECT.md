# Direct draw-layout construction

This is an isolated construction experiment built from the installed asset
preparation renderer, with `W101_DRAW_LAYOUT_DIRECT=0|1`, default `0`.
The user rejected this candidate's gameplay result: stutter remained. CPU savings
do not establish crowd or arrival improvement. It has failed gameplay acceptance
for the current game-side repair; the historical qualification remains below.

`performance/DrawLayoutDirect.h` prepares declaration semantics in a 64-element
stack array during construction. It normalizes declaration PositionT to
Position, as the original does. SSE2 compares eight 16-bit semantics per group
and chooses the first matching declaration; remaining elements use scalar
comparisons. These intrinsics are documented in the
[Microsoft x86 intrinsic reference](https://learn.microsoft.com/en-us/cpp/intrinsics/x86-intrinsics-list).

The vector path requires 8–64 declaration elements and 4–32 shader inputs.
Unsupported declarations/signatures, small inputs and non-SSE2/non-x86 builds
return to the unchanged original builder. Attribute order, formats, offsets,
missing-input bindings, frequencies, instancing masks and the existing context
setter are retained. There is no layout cache, publication, resource fingerprint,
pool or persistent layout storage. No resource creation code changes.

The launcher keeps the six saved selections and adds **Faster draw layouts**,
stored as `optimization.directLayouts`. The rejected cache option remains visible
but unavailable in this candidate; its saved value is retained. Inherited test
controls are stripped. Session metadata records `faster_draw_layouts` and the
effective experiment environment.

## Current result

Automated qualification passed and the same Desktop **Wizard101 Optimizations**
app was updated with the new switch off. Prior selections, learned textures,
settings and v1/v2 evidence were retained. The verified backup and installation
checks are in `verification-local/draw-layout-direct/delivery.json` and
`installation-verification.json`. Gameplay acceptance failed by user feedback.

| Measurement | Paired median | Other evidence |
| --- | --- | --- |
| Reuse | 54.92% CPU savings | Five of five wins |
| Cold | 54.92% CPU savings | Every pair improved; worst savings 54.53% |
| Fresh resources | 44.89% CPU savings | Every pair improved; worst savings 41.24% |
| Small fallback | 1.50% CPU increase | Five pairs; original builder used |
| Disabled versus baseline | 0.38% CPU increase | Five pairs |

Complete output comparison passed 12,861 cases, including 10,397 vector cases;
scalar-only compilation passed the same cases. All six real-render modes
matched exactly, with 368 readbacks each and verified vector/fallback execution.
The 128 launcher combinations passed 885 checks. Both texture compatibility
runs passed, and 22 Python tests passed.

Signing changed the installed launcher's signature bytes. Removing signatures
from disposable copies proved the executable code identical to the verified
build. The installer now records the staged post-signing hash for rollback; a
transactional test verifies full restoration when signing changes that hash.
The measured report remains `report.json`; `report-qualified.json` records this
installer-only amendment and its passing test evidence.

## Verification

Evidence is in `verification-local/draw-layout-direct/report.json`. The original
oracle in `tests/draw_layout_original.cpp` is independently copied from the
installed baseline. Complete structural output comparison covers declaration
sizes 0–65, shader counts 0–32, every vector lane and tail, duplicates, missing
semantics, PositionT, every format, offsets, frequencies, instancing and invalid
inputs. Forced scalar-only compilation verifies the portable fallback. Direct
construction is checked for zero allocations and untouched output on rejection.

Real-driver fixtures compare complete baseline/off/on pixel artifacts for both
D3D9 and D3D9Ex. They exercise the vector path alongside state blocks, instancing,
queued resource destruction, fixed-function rendering, reset and fullscreen.
Texture preparation is verified with direct layouts both off and on. All 128
launcher selections run both FPS and profiling choices.

CPU scoring uses five alternating pairs per reuse, cold and fresh-resource
workload, at least two seconds of thread CPU per sample, fixed operation counts
within each pair, and stack preparation inside the timed interval. Fresh samples
also include declaration/signature copies and resource destruction. Required:
at least 10% median reuse savings, four wins and no cold/fresh pair over 2%
regression. Five small-fallback pairs and five baseline/candidate-disabled pairs
are also recorded. Reports from v1/v2 and installed files are hashed before and
after verification.

## Reproduce

From `graphics-patch`, use a fresh evidence directory:

These commands qualify against the original installed asset-preparation baseline.
After this update, use the rollback copy of `Wizard101 Optimizations.app` as
`--app` for preparation and verification to reproduce that original baseline
without changing the active app. Installation requires that original baseline
to be active; it refuses to overwrite a later renderer.

```sh
python3 portable/build_draw_layout_direct.py --baseline /private/tmp/w101-asset-preparation
python3 portable/prepare_draw_layout_direct.py --keep portable/verification-local/direct-new-run
python3 portable/verify_draw_layout_direct.py --keep portable/verification-local/direct-new-run
python3 -m unittest discover -s portable/tests -p 'test_draw_layout*.py'
python3 portable/install_draw_layout_direct.py --report portable/verification-local/direct-new-run/report.json
```

The installer rejects missing/stale correctness evidence or a failed CPU gate
before writes. A qualifying update backs up the same app, game renderer and
learned textures, leaves the new switch off, and retains the existing selections.
The resulting `delivery.json` records the rollback path:

```sh
python3 portable/install_draw_layout_direct.py --restore /path/from/delivery/backup
```

## Gameplay acceptance

After automated qualification and a backed-up update, restart for all six runs:
off/on, on/off, off/on. Preserve the other saved selections, 60 FPS, 2560×1600,
graphics, all animation, controls, combat, larger cursor, legacy pacing and
MoltenVK 1.4.2. Leave heavy profiling off. Match realm, route and crowd conditions.
Allow Commons 60 seconds to settle; compare stationary crowds, movement, and
new-player arrivals separately. Confirm normal combat and controls in both modes.

Accept gameplay only with visible improvement in both crowds and arrivals and
no visual, combat or control regression. Until these observations are recorded,
`gameplay_accepted` remains false.
