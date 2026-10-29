# Wizard101 diagnostic build 16

This is a separate Apple Silicon diagnostic candidate based on the published
3.2 build 15. It shares the existing game data and preferences. Keep the build
15 app for rollback. Open the candidate from its extracted folder; it does not
need to replace the app in Applications. Do not run both launchers together.
The candidate is ad hoc signed, unsigned by Developer ID and not notarized.

## What changed

- A progressing download no longer fails simply because three consecutive
  connections drop before their requested range ends. Requests that transfer no
  additional bytes still have bounded retries; cancellation, the one-hour
  deadline, range validation and the final official CRC remain enforced.
- A network error after the final bytes leaves the complete download available
  for checksum verification rather than truncating it on the next request.
- Rejected staged downloads are retained as `.rejected-<UUID>` files. Installed
  content is replaced only after successful verification and a transaction.
- **Settings → Save Diagnostic Report** includes report schema 3: the latest 20
  typed transfer/verification events, the primary failure, manifest revision,
  archive, requested byte range, received bytes, HTTP/network result and CRC
  outcome. A failure remains available if later events leave the 20-event window.
- The report is automatically packaged into a uniquely named ZIP and selected
  in Finder. **Show Reports** finds saved ZIPs again; **Share Latest Report…**
  opens the Mac sharing menu. Files are kept in the existing data folder's
  `Diagnostics` directory, with private permissions. Sharing happens only when
  the user chooses a destination.
- The last launch records full visual preload or the explicit one-launch
  streaming choice. Old launches with no mode are marked unavailable.
- Reports recheck Novus, housing Novus, shared, Mob and Equipment archives, plus
  the most recent failed archive, against the dated manifest from the last patch
  check. Complete files, valid streamed headers, partial staging, missing files
  and failed verification are separate states. This report check is read-only.

The Wine runtime and renderer binaries and graphics defaults are identical to
build 15. Novus rendering is still under investigation. This candidate is not
evidence of a graphics or frame-pacing fix. Full visual preload remains the
default; **Use streaming once** is offered only after an eligible failure and
applies to one Play attempt. No graphics settings, caches or game data need to
be cleared.

## Tester sequence

1. Keep the build 15 app. Quit Wizard101 and both launchers before opening
   **Wizard101 Diagnostics Build 16.app** from this extracted folder. If macOS
   blocks opening it, use **System Settings → Privacy & Security → Open Anyway**.
2. Keep the same character, resolution, graphics settings and frame-rate choice
   as the affected build 15 session. Press **Play** to attempt full preload.
3. If preload fails, capture the complete on-screen error, especially the archive
   filename and HTTP/network code. Immediately use **Settings → Save Diagnostic
   Report**, before another retry. The new ZIP is selected in Finder; keep it
   as the preload-failure report. Its name includes build number and UTC time.
4. If **Use streaming once** is offered, choose it explicitly and sign in. If it
   is not offered, retain the failure report; do not force a bypass. If full
   preload succeeds, record that result and test Novus in that mode.
5. Revisit the same affected Novus location. Capture a screenshot and record the
   location and screenshot time with time zone. Immediately save another report
   as another ZIP. Note whether waiting 60 seconds or leaving and
   re-entering changes the scene; record the time of each observation.
6. Return the two saved ZIPs, error/screenshot and these short notes:
   Mac model/macOS, preload result, chosen launch mode, Novus location, screenshot
   times and waiting/re-entry result. If available, include a build 15 report from
   the same sequence with identical settings.

Reports contain typed observations and allowlisted settings/token counts.
They do not contain passwords, account names, Steam tickets, session keys,
command arguments, environment values, HTTP headers, raw response bodies or raw
game log lines. No report is uploaded automatically.

## Investigation tools

`read_diagnostic_report.py REPORT.zip` (or `REPORT.json`) summarizes report schemas 1, 2 and 3.
Absent fields mean unavailable, including the launch mode in build 15 reports.

For a fresh current-manifest content check without downloading/replacing game
archives, close the game and run:

```sh
"Wizard101 Diagnostics Build 16.app/Contents/MacOS/Wizard101Native" --audit-content
```

Use repeated `--archive NAME.wad` arguments for specific affected archives.
The command downloads only the small manifest into temporary storage and emits
JSON. It does not sign in, launch Wine, install game content or update the saved
checksum cache. A valid streamed header does not prove the complete body is
present. Report generation itself uses a dated manifest and makes no network
request.

## Build and rollback

```sh
python3 build_reliability_candidate.py \
  --base-app "/path/to/retained/build15/Wizard101 Standalone.app" \
  --build-number 16 \
  --output "dist/diagnostic-build16/Wizard101 Diagnostics Build 16.app"
```

The builder rejects replacement output paths, verifies the retained base remains
unchanged, checks every runtime/renderer component against build 15 and runs the
native self-tests. For rollback, quit the candidate/game and reopen the retained
build 15 app. Keep partial, rejected and cached downloads for analysis.

The tester's five reported streamed logins are user-attested. Reproducing their
preload failure and the exact Novus scene, including any behavior after waiting
or re-entry, remains pending. Automated fixtures cannot establish live graphics
or gameplay acceptance.
