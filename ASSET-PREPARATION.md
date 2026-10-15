# Prepare known assets

**Wizard101 Optimizations.app → Optimizations… → Prepare known assets** is an
independent, saved experimental option, off by default. Existing decompression,
wait-queue and native-helper selections persist. Reset to baseline disables all
five experiments and keeps the existing cache, workers and gameplay settings.

The first run learns decoded static managed 2D textures. Quit the game normally
to save them. On a later launch, preparation creates separate texture objects,
copies every saved mip, uploads them, flushes the command thread and waits for
the GPU before CreateDevice returns. There is no startup time cutoff. Each
prepared object is handed out once after checking current encoded content and
decode parameters. Later loads create independent objects from immutable pixels.
Mutating one texture never changes another or the saved snapshot.

The disk cache is at most 32 MiB, under the combined app's existing data folder:
`Data/Prefix/drive_c/graphics-patch-cache/Wizard101/known-assets.w101assets`.
It saves by writing and flushing a temporary file, then atomically replacing
the old file during orderly device teardown. Forced termination may lose that
session's learning. It never saves or releases prepared COM objects under the
Windows loader lock. Raw snapshots, preparation storage and workers share the
existing 128 MiB asset budget; preparation reserves conservative managed,
staging, converted GPU and alignment costs. Admission failure keeps native loads.

Cache integrity, version, renderer binary, native decoder binary, adapter and
device capabilities must match. Unsupported layouts, palette outputs, dynamic
resources, malformed files, changed encoded content, unavailable storage and
failed allocations use the original loader. Resets and managed-resource
eviction discard prepared objects while retaining bounded immutable learning.
Private texture references prevent device lifetime cycles.

The verified main-executable imports include both existing memory loaders and
`D3DXCreateTextureFromFileExA`. Memory requests retain native codec initialization
until an unchanged-LastError success has been observed for that codec in the
current process. PNG, JPEG, DDS and BMP have known signatures; unclassified
codecs retain native decoding. The filename decoder clears LastError on success,
so filename cache hits require incoming LastError zero. Other calls retain the
native path. File hashing holds a read guard that denies writes and renames;
native sharing conflicts retry without the guard, with no cache admission.

## Verification and acceptance

Automated verification uses the installed Wine/MoltenVK runtime and native D3DX
in a disposable prefix, with heavy profiling off. It checks exact native CPU
pixels and GPU readbacks for every mip, packed and compressed textures, all
three loaders, independent mutations, source/error/output behavior, first codec
initialization, unconsumed device teardown, reset/fullscreen, allocation/upload
failure, checksum/version/decoder/renderer mismatch, truncation, oversized and
invalid records, unavailable storage, failed atomic saves and budget pressure.
Launcher checks cover all 32 saved switch combinations with both frame modes
and profiling selections. Existing combined runtime decoder/wait-queue tests
remain separate evidence for the unchanged runtime binaries.

Visible gameplay improvement is **unverified**. Previously encountered textures
are the target; unseen content still requires work. Preparation also does not
precompile shaders or change game animation, controls, combat or graphics.

For live acceptance, leave Capture workload off and hold the other optimization
selections, resolution and graphics settings fixed. First play the route once
to learn its textures, then quit normally. Restart the game before every trial.
Run three pairs in order **off/on, on/off, off/on**. In each trial observe new
player arrivals in the same crowded area, the first entry into the same zone,
then an immediate revisit. Record visible pause count and longest perceived
pause for each scenario, plus any graphics/control problems and startup delay.
Keep the same realm and route where possible. No real gameplay comparison has
been performed automatically; persistent arrival or zone-entry pauses mean
stutter removal remains unverified.

## Build and rollback

Reuse the combined sources and installed runtime; no runtime rebuild or new
Desktop app is required:

```sh
python3 build_asset_preparation.py --baseline /private/tmp/w101-combined
python3 build_app.py --development --output /private/tmp/w101-assets-launcher.app
python3 verify_asset_preparation.py --keep verification-local/asset-preparation
/private/tmp/w101-assets-launcher.app/Contents/MacOS/Wizard101Native --self-test
python3 install_asset_preparation.py
```

The installer verifies inputs and measured binary hashes, checks the game is
closed, backs up the current app and renderer under
`~/Library/Application Support/Wizard101 Optimizations/Rollback/`, then updates
the same app. It preserves game content, settings, saved selections and all
runtime executable bytes. The exact backup path is in `delivery.json` in the
build work directory. To restore it, close the launcher/game and run:

```sh
python3 install_asset_preparation.py --restore "/path/to/Rollback/asset-preparation-TIMESTAMP"
```

Unchecking the new option disables startup preparation immediately on the next
launch. Deleting the `.w101assets` file forgets learned pixels and is safe while
the game is closed. Source exports exclude local caches and game content.
