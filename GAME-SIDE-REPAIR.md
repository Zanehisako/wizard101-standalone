# Game-side stutter repair

`Wizard101 Game Repair.app` is a separate, default-off experiment. Its scene
property lookup replacement passes exact-output, failure, synchronization and
rollback checks. It saves 24–64% of **that function's CPU time** through the
installed hook in isolated tests. Total FPS improvement and relief of the
zone-entry pause are unverified. Stable 60 FPS and zero stutter remain targets.

The working `Wizard101 Optimizations.app` and its data remain available. After
normal game exit, its data and saved selections were cloned into
`~/Library/Application Support/Wizard101 Game Repair/Data`. The candidate
retains all seven existing saved choices and adds **Faster scene property
lookups**, initially off. Both previously rejected draw-layout paths are
unavailable here; their stored selections are retained. Both sides of an off/on
comparison use the original draw implementations.

## Attribution and rejected experiments

The user confirmed entering/changing zones and experiencing the usual pause
in `verification-local/game-zone-entry-20261005-01`. The bounded diagnostic
recorded 187 main-thread contexts with an exact Wine/native CPU identity join.
Maximum context suspension was 1845 us; there were zero code signature
mismatches. Ten samples entered leaf functions without PE runtime-function
entries and remain unresolved.

Scene and animation traversal dominated the identified stack frames. Transform
composition at RVA `0x2253510` and sphere merging at `0x2258440` were the largest
identified calculation leads. They were tested independently first. Preserving
exact SSE behavior removed the transform experiment's worthwhile CPU gain;
the bounds replacement was slower. Neither is installed. Their source and
rejected results remain available for review.

Scene-property search at RVA `0x2239020` recurred in the active captures, with
one self sample during the confirmed transition capture. Its complete function
and direct getter were disassembled and verified before selecting the equivalent
lookup experiment. This supports a recurring contributor, **not proof of the
largest pause's cause or duration**. The capture has only a capture-wide user
annotation, not an exact pause timestamp. No AvatarUpdate behavior, resource
lifetime or owning-lock semantics were changed.

## Installed replacement

`game/lookup.h` preserves the original signed 16-bit binary search and wrapping
64-bit key comparison. It removes calls to a verified getter whose complete
implementation is `LEA RAX,[RCX+0x10]; RET`. It preserves the original volatile
read order and rereads the result array on a match. There is no memoization,
allocation, reference ownership change, reordered update or skipped animation.

| Input | Required identity |
| --- | --- |
| Game executable SHA-256 | `544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e` |
| Lookup | RVA `0x2239020`, all 164 bytes SHA-256 `5d67b2171d7d6f6f65bd27ea33557c072985a9392d3f3ce40cf8ce8fa30e8d1e` |
| Getter | RVA `0x224ed40`, complete bytes `488d4110c3` |

`W101_GAME_REPAIR=1` requests installation once at D3D9 creation. Off, identity
mismatch or failed activation retains the original function. The launcher
records selection and expected identities; the D3D9 startup log records actual
hook status. Requested installation alone does not establish activation.

The detour uses pinned [MinHook v1.3.4](https://github.com/TsudaKageyu/minhook),
commit `c3fcafdc10146beb5919319d0683e44e3c30d537`, with its BSD license included.
Local changes retain exact suspension handles, resume only owned increments and
abort on context/suspension failure or an elapsed 50-ms freeze budget. Blocked
OS APIs can exceed that requested budget. Verification-only fault injection is
absent from production. The relocated prologue has registered
[x64 unwind metadata](https://learn.microsoft.com/en-us/windows/win32/api/winnt/nf-winnt-rtladdfunctiontable).
The renderer is pinned, and the trampoline remains valid until process exit,
including after rollback. There is no loader-lock teardown or mid-game GUI
activation; selection changes take effect next launch.

## Verification and delivery

`verification-local/game-repair-qualified-final-20261005/report.json` binds
source hashes and records 389,375 original-versus-replacement pointer comparisons
with zero mismatches, including duplicates, unsorted arrays and wrapping keys.
All 14 real-detour checks pass: identity rejection, default off, activation,
LastError preservation, unwind registration, context/timeout/suspension failures,
concurrent activation/rollback, retained external suspension, exact byte
restoration and joined-worker shutdown. More than 36 million concurrent calls
returned no incorrect results. Five alternating benchmark pairs in each of
eight hit/miss and size groups include detour overhead; median savings span
24.25–63.61%.

The packaged launcher passes 1,654 checks, including all 256 switch combinations,
upgraded preferences, disabled capabilities and reset. Eight Python tests pass
for context identities, thread joins and scoring. The isolated preview's sheet
fits, the new checkbox toggles, and reset returns it to off. Signature checks
and cloned executable/settings/cache hashes pass; the working app's watched
hashes are unchanged. Delivery records are retained under
`verification-local/game-repair-delivery-20261005`.

The new renderer has a different compatibility identity. The copied known-asset
preparation cache may be rejected and relearned safely. Visit the comparison
route once and quit normally before measuring subsequent startup preparation.
Record first entry, immediate revisit and revisit after restart separately.
Both off/on runs must use this same candidate renderer and cache seed.

Local reproduction requires the existing approved runtime/game installation,
MinGW, Swift and the earlier renderer build at `/private/tmp/w101-draw-layout-direct`.
The overlay does not rebuild a clean Wine runtime or prove a fresh installation:

```sh
python3 portable/build_game_repair.py
python3 portable/verify_game_repair.py --keep portable/verification-local/game-repair-new-check
python3 portable/build_app.py --development --output /private/tmp/w101-game-repair-launcher-delivery.app
/private/tmp/w101-game-repair-launcher-delivery.app/Contents/MacOS/Wizard101Native --self-test > /private/tmp/w101-game-repair/launcher-delivery-tests.json
python3 portable/package_game_repair.py --report portable/verification-local/game-repair-new-check/report.json
```

Use a fresh app output for a changed build. `package_game_repair.py --seed` copies
settings only after normal game exit and refuses to overwrite existing candidate
data. To roll back, uncheck the new switch and restart, or use the working app.

## Bounded diagnostics

`game_context.py` admits only the approved executable and captures external
Windows contexts for 1–10 seconds. It never writes game memory. No password,
session arguments, raw stack bytes, data pointers or general registers are
recorded. It suspends one thread, copies a bounded stack, and resumes its single
owned increment before unwinding or output. A watchdog attempts resumption after
100 ms and cancels that capture. Existing suspension counts are retained and
excluded from attribution. Measured durations are recorded.

This follows Microsoft's
[GetThreadContext](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getthreadcontext)
and [SuspendThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-suspendthread)
contracts. StackWalk64 accesses only the copied stack and nonwritable PE sections.
There is no speculative return-address search. Missing identities stay unresolved;
admitted function bounds and code signatures must match. The diagnostic fixture's
16 recovery/identity checks pass.

Remote GetThreadTimes counters did not advance under Wine 11.0 on this Mac and
are recorded as unavailable. `game/native_thread_cpu.c` uses native counters.
`thread_map.py` joins exact Wine pthread/TSD handles, including the initial
thread's recorded handle at TEB+0x320. Conflicting, zero, duplicated or reused
identities remain unknown. Recreate the map after each game restart.

```sh
python3 portable/game_context.py --seconds 5 --tid WINDOWS_THREAD_ID --output portable/verification-local/game-context-new
python3 -m unittest discover -s portable/tests -p test_game_repair.py
```

Captures are diagnostic evidence and excluded from gameplay scoring.

## Acceptance gate

`score_game_repair.py` requires six independently restarted runs ordered off/on,
on/off, off/on. Each run needs complete hashed frame timestamps, finalized/no-loss
evidence and contiguous annotations for settled crowds, movement, arrivals,
first entry, restart revisits and loading screens. Only intervals intersecting
an annotated loading screen are exempt; phase boundary intervals remain in the
global pause gate. Settled crowd measurements span at least 60 seconds after
at least 60 seconds of settling.

Candidate runs and every phase must reach average FPS >=59, p99 frame interval
<=20 ms and zero pauses >50 ms. The scorer rejects diagnostic hooks, context
sampling, heavyweight traces, changed pair settings/selections, missing verified
hook/correctness identities, nonunique restarts or unverified controls, combat,
textures, fullscreen, animations and cursor. It requires 60 FPS, 2560x1600,
legacy pacing and MoltenVK 1.4.2.

No six-run gameplay evidence exists yet. The largest zone-entry pause remains
unattributed, gameplay acceptance is false, and rollout is prohibited until both
the measurements and the user's experience pass. Keep the working app and rollback.
