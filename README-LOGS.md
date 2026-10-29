# Wizard101 for Mac: use build 16 and send us your logs

**[Download Diagnostic Build 16](https://github.com/Zanehisako/wizard101-standalone/releases/download/v3.2-community-beta.3/Wizard101-Diagnostics-Build16.zip)** · **[Send feedback on Discord](https://discord.gg/b2KVmJ84P)**

## Open the diagnostic app

1. Quit Wizard101 and the other launcher. Keep your previous app for rollback.
2. Extract the download and open **Wizard101 Diagnostics Build 16.app**.
3. If macOS blocks it, use **System Settings → Privacy & Security → Open Anyway**.
4. Sign in as usual and press **Play**. Keep the same character and graphics
   settings when comparing a problem.

Requires an Apple Silicon Mac, macOS 13 or later, Rosetta and internet access.
This experimental app is unsigned by Developer ID and not notarized. It reuses
your existing standalone game data and settings.

## Save a report when something goes wrong

1. Reproduce the error or visual problem and take a screenshot.
2. Immediately open the launcher's **Settings** using the gear button.
3. Click **Save Diagnostic Report** and wait for Finder to open.
4. Keep the selected ZIP. Its name starts with
   `Wizard101-Diagnostics-build16-` and includes the report's UTC time.

If the launcher closed after starting the game, reopen the diagnostic app and
save the report before pressing **Play** again. Save a new ZIP after each
problem, before retrying; earlier reports are kept.

| Button in Settings | What it does |
| --- | --- |
| **Save Diagnostic Report** | Creates one report ZIP and selects it in Finder. |
| **Show Reports** | Finds your saved report ZIPs, including after reopening the app. |
| **Share Latest Report…** | Opens the Mac sharing menu so you can choose a destination. |

The default reports folder is:

```text
~/Library/Application Support/Wizard101 Native/Diagnostics
```

To open it manually, use **Finder → Go → Go to Folder…** and paste that path.

## Send the ZIP to us

1. [Join our Discord server](https://discord.gg/b2KVmJ84P).
2. Post a message describing the issue in the server.
3. Drag the selected report ZIP from Finder into your message, attach your
   screenshot, then send it. The ZIP can stay compressed.

Copy this template into your message:

```text
App: 3.2 beta 3 / Build 16
Mac model and macOS:
Account type: US or Steam
What happened / exact error:
Steps to reproduce:
Game location and time (with time zone):
Preload completed, failed, or Use streaming once selected:
Did waiting or leaving/re-entering change anything?
Attachments: report ZIP and screenshot
```

For a **preload failure**, capture the filename and error code, then save the
report before retrying. Full preload is the default. If offered, **Use streaming
once** applies to one Play attempt; the next Play retries full preload.

For a **Novus visual problem**, save another report immediately after seeing it.
Include the exact location and whether waiting 60 seconds or leaving and
re-entering changes the scene. Send both report ZIPs if you encountered both
problems. Novus rendering is still under investigation.

Reports contain diagnostic information and selected settings. Passwords, account
names, Steam tickets, session keys and raw log lines are excluded. **Saving a
report does not send it automatically.**
