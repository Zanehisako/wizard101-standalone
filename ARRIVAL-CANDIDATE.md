# Wizard101 Arrival Candidate

This isolated candidate implements complete-upload GPU initialization elision,
scene texture reuse, saved pipeline preparation and appearance downloads before
sign-in. The three arrival options default off. On 2026-10-06 the user selected
this app as the retained version after reporting a modest improvement with
pipeline preparation enabled. Visible stutter remains unresolved.

The retained Desktop app is `Wizard101 Arrival Candidate.app`. Its saved
**Prepare known pipelines** selection is enabled; other saved selections are
unchanged, the scene-node pool is disabled, and ordinary play has no profiling or
capture enabled. The user explicitly requested removal of older app versions and
their data copies. This selection does not change factory defaults or retroactively
pass the failed offline pipeline performance gate below.

The app uses its own data at
`~/Library/Application Support/Wizard101 Arrival Candidate/Data` and its own
preferences domain, `org.wizard101native.arrival-candidate`. Packaging clones the
Metal Cache candidate's installed content and preserves its existing selections.
The rejected scene-node pool remains disabled. The game executable, lookup hook,
animations, controls, combat, graphics settings, resolution, cursor and existing
60 FPS legacy pacing are preserved.

## Options

| Saved option | Environment | Default | Activation |
| --- | --- | --- | --- |
| Reuse scene texture uploads | `W101_SCENE_TEXTURES=0\|1` | 0 | Next launch |
| Prepare known pipelines | `W101_PREPARE_PIPELINES=0\|1` | 0 | Next launch |
| Download appearance assets before play | `W101_PREPARE_APPEARANCE=0\|1` | 0 | Before sign-in |

Metal archive reuse follows the existing **Reuse Metal pipelines** selection.
Startup has no time cutoff. The pipeline worker drains and joins before device
creation returns; template uploads finish before play. Unknown states and
unsupported texture requests follow the original paths.

## Implementation

`ArrivalCache.h` uses indexed CPU, learned-record and prepared-template lookups.
Allocation pressure retires unused prepared textures before useful CPU snapshots.
COM releases and pixel destruction occur outside cache locks. A lease attached to
each GPU image remains charged while queued commands retain that image.

The process asset budget is 128 MiB, retained startup data is at most 64 MiB, and
speculative preparation is at most 32 MiB. CPU snapshots, metadata and conservative
GPU/staging reservations share these limits. Scene and D3DX records share one
32 MiB file; their separate caches cannot each consume another 32 MiB.

The revision keeps separate pending GPU-initialization bits for managed static
2D textures. CPU initialization remains unchanged. A proven complete write of
all supported mips omits the redundant GPU clear on both cache hits and misses.
Partial, unwritten, unsupported, locked or individually preloaded requests retain
clearing before GPU access. Successfully queued mips retire independently, so
an interrupted upload leaves remaining mips guarded. Template copies restore
`UnmapTextures()` and the original weak submission hint.

Appearance preparation uses the same matching official Windows manifest and
resumable downloader as the updater. Only top-level Equipment and Mob WAD groups
are forced to full-file CRC validation and full downloads. A cached header check
cannot pass as a body check. Missing appearance archives bypass header-only
bootstrap. Staging space includes the remaining complete bodies and the existing
512 MiB reserve; full-length sparse or corrupt staged bodies cannot bypass this
check. Current downloads are about 2 GiB, so allow roughly 3 GiB free. Cancellation
retains partial downloads; the existing journal and hard-link backups restore
installed files after interrupted replacement. All work finishes before account
authentication, leaving other optional content on demand.

Full downloads of type-5 archives start from the matching, CRC-verified compressed
header when staging has not reached the body. This avoids an observed official
server disconnect within the uncompressed Equipment header. Body downloads resume
at the end of the verified prefix. Later body progress is retained; invalid
complete staging restarts from a real prefix. Header and compressed-wire staging
are included in the space check. A prefix cannot satisfy the full-file CRC or be
installed as a prepared appearance archive.

Buffer decompression admits 1 KiB inputs only when buffer acceleration is enabled
and the verified caller returns to RVA `0x150935a`. Installation verifies the game
and zlib hashes, exact call bytes, and the jump through the uncompress IAT slot.
Other callers retain the 32 KiB floor. Size limits, scratch-buffer commit, original
errors, original fallback and the 64 MiB budget are unchanged.

`SceneUploads.h` covers the renderer's managed upload path, including textures
populated by Gamebryo/NiPixelData without D3DX. Admission requires static, fully
written, supported 2D mip chains, at most 8 MiB, with no partial writes or live
locks. A bounded second-occurrence filter avoids full snapshot allocations for
one-off textures. Learning therefore requires two matching initialized occurrences
followed by an orderly exit and restart before template reuse.

A sampled fingerprint selects a candidate through the index. Every canonical
pixel byte in every mip must then compare equal; row padding is excluded. SSE2
comparisons use unaligned loads and a bounded scalar tail. Fingerprint collisions
retain the original upload. Templates stay immutable and ready for copying. One
multi-region copy populates each independent destination mip chain. CPU pixels,
subsequent mutations, reference counts, errors and resource retirement retain
their original behavior.

`ArrivalInputs.h` retains successful raw DXSO and fixed-function keys, bounded to
2,048 records / 32 MiB. Restoration validates complete bounded bytecode and stage;
fixed-function light counts are checked against current caps. Exact saved DXVK
pipeline descriptions are bounded to 8,192 records / 16 MiB. One worker prepares
states whose complete shader keys are present. Learning continues during ordinary play even when pipeline preparation is off;
no preparation worker starts in that mode. Shader and state input files save
atomically at orderly shutdown.

On the first launch, intact retained raw shader inputs and exact DXVK descriptions
can seed the new files. Existing corrupt or incompatible new files fall back
without replay. Compiled artifacts retain their separate translation, renderer,
backend, OS and driver compatibility checks. The new shader revision rejects
previous incompatible compiled inputs.

`ArrivalMetalArchive.h` asks Metal for an exact binary archive hit with
`MTLPipelineOptionFailOnBinaryArchiveMiss` before adding compilation work. A miss
uses the existing synchronous compilation and completion/error handling. Archive
saves remain at device shutdown, with failure preserving the last good file.

This independently applies the preparation-and-reuse principle described in
[SCSKiller's architecture](https://github.com/BlueHeisenberg/SCSKiller/blob/main/ARCHITECTURE.md).
The implementation uses the current DXVK/MoltenVK paths and copies no SCSKiller
implementation code. Multi-region copying follows
[Vulkan's image copy rules](https://docs.vulkan.org/refpages/latest/refpages/source/vkCmdCopyImage.html).

## Verification and qualification

Reports are local under `verification-local/arrival-*`. Verification uses disposable
APFS clones and the app's actual renderer, bundled Wine, MoltenVK and installed
native D3DX. It does not start the account's game or enable gameplay timing,
profiling or captures. Test harness wall-clock measurements are synthetic workloads.

The initial arrival launcher passed 49,289 checks, including all 8,192 switch combinations and
default-off preference migration. Native Metal tests confirmed exact archive hits
in a separate process, identical output, identity misses, corrupt/oversize recovery,
writer exclusion and byte-preserving failed saves. Retained input replay restored
652 shaders and prepared 5,828 pipelines before device creation returned, with no
jobs running afterward. Corrupt records fell back without replay.

Runtime checks cover exact CPU and GPU pixels across every mip; independent
mutations; partial/uninitialized requests; deliberate fingerprint collisions;
odd dimensions, padded rows and vector tails; concurrency; invalid requests;
allocation/create/lock/copy/upload failures; memory exhaustion; reset; eviction;
in-flight GPU accounting; orderly shutdown; corrupt/truncated/oversize input files;
compatibility mismatch; failed atomic asset saves; and native D3DX/fullscreen
behavior. Installed Metal archive cold and restart runs verify the same pixels.

The performance requirement is at least 10% median improvement across five
alternating pairs and at most 2% median fallback regression. Failed experiments
are retained in their own reports. Their results do not qualify the final build.
The final measured status and artifact hashes are in the delivery report.

The learned-pipeline follow-up on 2026-10-06 uses the latest Arrival inputs and
the launcher's actual renderer/backend/game/D3DX/OS compatibility key. Its
verification-only helper is built in a disposable source/object clone and is
absent from the delivered renderer. Before any draw, it observes each existing
non-null pipeline handle and compares it with two normal synchronous lookups.
It also checks pending work, queue contents, busy workers and joinable threads.

The follow-up restored **663 shader inputs** and reused **5,865 handles** from
6,621 saved states; states without complete shader coverage remain normal misses.
All preparation workers had joined before device creation returned. Compatible
restart repeated these results. Corrupt and incompatible inputs were rejected,
and exact CPU/GPU mip output, mutations, concurrency, reset and shutdown matched
the preparation-off oracle and the unmodified delivered renderer.

Five alternating pipeline-only upload/first-draw pairs improved **3.91%** at the
median, below the required 10%. Five fallback pairs regressed **1.38%**, within
the 2% limit. Startup was excluded and texture reuse was disabled in both arms.
These timings use the delivered renderer, not the verification helper.
Evidence is in `verification-local/arrival-pipeline-preparation-20261005-3/`.
The pipeline performance gate failed, so **Prepare known pipelines remains off**;
other saved selections and factory defaults remain unchanged. No relaunch or live
arrival/crowd/combat trial follows this failed gate. Visible-stutter acceptance
remains unverified.

The revised runtime passed every exact CPU/GPU mip check, including DXT1/3/5,
partial and unwritten textures, independent mutations and all existing fault,
concurrency, reset, pressure, eviction and shutdown checks. A cold launch with
pipeline preparation off persisted all three bounded input files without replay
or workers. Replaying retained inputs restored 652 shaders and prepared 5,828
pipelines before device creation returned, with zero workers afterward. Corrupt
and incompatible inputs retained normal fallback.

Across five alternating workload pairs with gameplay closed, the repeated upload
batch improved **20.56%** at the median, with **120 actual template hits** in every
enabled run. Cache-miss uploads improved **19.16%** at the median. Both pass the
10% improvement / 2% maximum fallback regression gate. These are synthetic upload
results, not a visible-stutter result. Earlier failed experiments remain recorded
separately and do not qualify this build.

The installed-zlib harness reproduces the production WAD return RVA and call
signature. It checks 1,023/1,024/32,767/32,768-byte boundaries, ordinary caller
scope, buffer-only/stream-only/combined modes, hash/signature rejection, identical
errors and output, scratch allocation failure, and the existing concurrent and
stream compatibility suite. Download tests cover resumed/interrupted transfers,
header-valid incomplete bodies, corrupt staged/installed bodies, full-length sparse
staging, insufficient space, cancellation and transaction rollback.

The streamed-header follow-up also tests repeated server disconnects inside the
header, verified-prefix resume, corrupt prefix rejection, cancellation, complete
invalid staging, retained body progress, symbolic links and completed-download
space accounting. Its launcher and delivery evidence is retained separately in
`verification-local/arrival-v2-header-20261005/`. Renderer performance evidence is
carried forward only while the renderer, Wine and Metal artifacts remain identical.

The first live appearance-preparation attempt passed the original header interruption
but remained blocked by repeated official-server disconnects at byte 92,274,688
of Equipment-WorldData. Bounded requests reproduce the missing response. Partial
downloads remain staged for retry; no incomplete archive was installed and no
appearance preparation is claimed. The attempt is recorded in the follow-up
directory's `live-appearance.json`.

The CDN follow-up uses the existing native HTTP transfer with a fresh,
request-specific route to the same official hostname after repeated transport
failures. A bounded HTTPS DNS lookup supplies at most two public IPv4 routes.
Each alternate attempt resolves again, rejects redirects and proxy authentication,
and retains the original range, size, cancellation and full-file CRC checks.
Configured system, scoped, automatic and environment proxy routing is preserved.
No system DNS setting or TLS exception is changed. The launcher passed 49,348
checks; separate evidence is retained in `verification-local/arrival-v2-cdn-20261005/`.

The recovery route completed all three official appearance archives. Each installed
body independently matches the manifest's full KingsIsle CRC. A verification
follow-up drains Foundation's autoreleased file buffers after every 1 MiB chunk.
Across six repeated 128 MiB checks, resident memory stayed below 12 MiB instead of
growing to 818 MiB, with identical CRCs. This prevents archive verification from
retaining gigabytes of read buffers during one launcher operation. Evidence is in
`verification-local/arrival-v2-integrity-20261005/`.

To prepare and independently verify the appearance archives before authentication:

```sh
"Wizard101 Arrival Candidate.app/Contents/MacOS/Wizard101Native" --prepare-content --prepare-appearance
```

Live acceptance requires comparisons of baseline, texture-only, pipeline-only,
appearance-only, buffer-decompression-only and combined modes with unchanged
settings: Commons player arrivals, first zone
entry, immediate revisit, restarted revisit, settled crowded movement and combat.
No live acceptance has been run.
Visible pauses mean the stutter objective remains unmet. No stable 60 FPS or
zero-stutter claim follows from these synthetic checks.

## Build and verify locally

These scripts extend the existing locally built Game Repair renderer and Metal
Archive source tree. Keep those baseline builds, or reproduce them with their
respective build scripts before building this overlay. They remain unchanged.
The baseline renderer must match the preserved Metal Cache app.

From this directory:

```sh
python3 build_arrival.py --work /private/tmp/w101-arrival-v2 --baseline /private/tmp/w101-game-repair
python3 build_arrival_metal.py --work /private/tmp/w101-arrival-v2 --baseline /private/tmp/w101-metal-archive/moltenvk
python3 build_arrival_launcher.py --work /private/tmp/w101-arrival-v2 \
  --output /private/tmp/w101-arrival-v2-launcher.app
python3 package_arrival.py --work /private/tmp/w101-arrival-v2 \
  --launcher /private/tmp/w101-arrival-v2-launcher.app \
  --output /private/tmp/Wizard101-Arrival-Test.app
python3 verify_arrival.py --work /private/tmp/w101-arrival-v2 --app /private/tmp/Wizard101-Arrival-Test.app \
  --output verification-local/arrival-runtime-new
python3 verify_arrival_learning.py --app /private/tmp/Wizard101-Arrival-Test.app \
  --work /private/tmp/w101-arrival-v2 \
  --data "$HOME/Library/Application Support/Wizard101 Arrival Candidate/Data" \
  --output verification-local/arrival-learning-new
python3 verify_arrival_decompression.py --app /private/tmp/Wizard101-Arrival-Test.app \
  --output verification-local/arrival-decompression-new
python3 verify_arrival_metal.py --output verification-local/arrival-metal-new
python3 audit_bundle.py /private/tmp/Wizard101-Arrival-Test.app
```

Builds require Xcode, MinGW, Ninja, the baseline dependencies and the pinned
decoder libraries produced by `build_combined.py` at `/private/tmp/w101-combined`.
Renderer objects are rebuilt when shared image layout or dependent inputs change. Metadata binds
the exact source inputs, renderer, Metal backend and tested launcher. Packaging
checks game identity, inherited lookup signatures, preserved hook inputs, signed
artifacts and test bindings before atomically installing the app. Data cloning
also uses a temporary directory and atomic rename. Existing data is never replaced.
A verified `--replace` delivery first renames
the previous app to a dated rollback app and verifies every previous app file
remained identical. Saved selections remain intact. On sign-in the launcher
installs its own hash-verified renderer and decoder before authentication, so
an existing candidate data directory uses the delivered executable code.

## Rollback

Disable the arrival options and relaunch, or open the preserved working app.
Older app versions and their data copies were removed at the user's explicit
request on 2026-10-06. Disable **Prepare known pipelines** and relaunch to roll
back that option while keeping the retained app and its current data.
