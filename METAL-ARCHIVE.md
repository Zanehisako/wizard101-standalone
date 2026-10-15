# Experimental Metal pipeline reuse

The separate **Wizard101 Metal Cache.app** keeps the existing scene lookup
improvement, saved optimization selections, graphics configuration, animations,
controls, combat, larger cursor, legacy pacing and 60 FPS selection. Its game
data lives under `~/Library/Application Support/Wizard101 Metal Cache/Data`.
Existing apps and their data remain intact.

Enable **Reuse compiled Metal pipelines** in Optimizations for the next launch.
The switch defaults off (`W101_METAL_ARCHIVE=0|1`). Visit the area, quit normally
to save the archive, restart this app and revisit. Compare first entry, immediate
revisit and restarted revisit separately. The first encounter still compiles
new pipelines and archive learning can cost extra time. Gameplay stutter and
stable 60 FPS have not been verified.

## What comes from SCSKiller

[SCSKiller at the reviewed commit](https://github.com/BlueHeisenberg/SCSKiller/tree/230f68e07b7b57d0c4b52ab43a284d0a19689a67)
targets Windows DirectX and vendor shader caches. Its useful principle is reuse
of compiled pipelines with exact state and compatible driver identity. Its
DirectX hooks, Windows vendor-cache handling and engine indexers do not apply
directly to Wizard101's D3D9-to-Metal path. No upstream source code was copied.

This implementation adds Metal's `MTLBinaryArchive` to MoltenVK 1.4.2. The
existing Vulkan cache already preserves converted shader metadata/MSL; this
experiment also saves compiled Metal pipeline functions. It uses descriptors
from the actual renderer, preserving shaders, compile options and draw state.
It learns encountered pipelines; it cannot enumerate all unseen game pipelines
or provide SCSKiller's full offline preparation.

## Implementation and fallback

- Ordinary render and descriptor-based compute pipelines can attach an archive.
  Function-only compute and mesh paths retain their original implementation.
- Cache identity includes macOS build, Metal GPU registry ID, renderer DLL and
  MoltenVK library hashes. Metal also matches the exact pipeline functions/state.
- The launcher owns the cache path and key; inherited paths/keys are discarded.
- A nonblocking file lock allows one writer per cache identity. Another device
  or process retains the original pipeline path.
- Missing/unavailable storage, corrupt archives, invalid modes/keys and archive
  preparation failure retain normal Metal compilation.
- Saves happen at Vulkan device teardown. A temporary file, size check, fsync
  and atomic rename preserve the previous file on save failure. An archive file
  is limited to 64 MiB; files from older identities can be removed while the app
  is closed. No disk writes occur in pipeline creation.
- No recorder, profiler, gameplay logger or shader capture was added. The
  candidate uses the original public MoltenVK baseline plus this overlay rather
  than the older optional GPU capture overlay.

Native hardware checks verify identical pixels, a separate-process driver cache
hit with `MTLPipelineOptionFailOnBinaryArchiveMiss`, identity rejection, corrupt
and oversized archive recovery, writer exclusion, unavailable storage, and
byte-preserving save failure. Wine/D3D9 probes check graphics with the backend
off, on, and after restart: uploads, six texture formats, synthetic HUD/sprites,
cursor transparency/hotspot and fullscreen transitions. These are correctness
checks; gameplay performance remains unmeasured.

Evidence is retained under `verification-local/metal-archive-native-20261005`
and `verification-local/metal-archive-runtime-final-20261005`. The launcher tests
cover all 1,024 switch combinations; saved selections change only the next launch.

## Source build and rollback

The independent implementation is `performance/MetalArchive.h`. The guarded
integration/build script is `build_metal_archive.py`; its generated patch and
source/library hashes are retained with the build and app provenance. The
universal library contains x86_64 for the current Wine runtime under Rosetta and
arm64 for native tools. Public MoltenVK sources/dependencies are pinned by
`build_moltenvk.py` and `sources.lock.json`.

```sh
python3 portable/build_moltenvk.py
python3 portable/build_metal_archive.py --work /private/tmp/w101-metal-rebuild
python3 portable/verify_metal_archive.py --output /private/tmp/w101-metal-native-check
```

Use a fresh build directory. `--resume` regenerates this private overlay from
its baseline and rebuilds it; it never edits the baseline. Package only after
native, launcher and installed-runtime verification succeeds, using
`package_metal_archive.py --verification ...`.

For rollback, disable the Metal option and relaunch, or use the preserved
**Wizard101 Game Repair.app** / **Wizard101 Optimizations.app**. The rejected
scene-node allocation patch is unavailable in this app.
