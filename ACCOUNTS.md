# US / Steam accounts — 3.2 experimental beta

The 3.2 release adds a remembered **US / Steam** account selector. On 2026-10-16,
the project owner confirmed Steam was working locally and requested publication.
Steam remains experimental: full gameplay, relaunch, expected characters and
continued play for ten minutes after launcher exit still require recorded
qualification for both providers. Keep the previous launcher for rollback.
The previous US-only 3.1 beta's qualification does not cover this build.

Wizard101's [official Steam release](https://store.steampowered.com/app/799960/Wizard101/)
supports Windows. This community launcher's native Mac ticket exchange is an
experimental integration. It does not add official macOS Steam support.

## Sign in

Choose **US** for an account created on the US Wizard101 website. Existing saved
usernames, Remember me preferences and Mac Keychain passwords stay assigned to US.

Choose **Steam** for a US Wizard101 account created through Steam. Enter the
**Wizard101 username and password created through Steam**, as shown by the
[official account form](https://www.wizard101.com/patchClient/New?abs=1).
Steam opens automatically when you press Play. Sign in to the macOS Steam client,
go online, and make sure Wizard101 is in that Steam account's library. Then retry
Play if prompted. The launcher never asks for your Steam password or Steam Guard
code. Missing, outdated, offline or signed-out Steam produces a retryable message.
Build 7 finds the running client's API even when the registered Steam app is only
a bootstrapper. It waits for Steam's app connection before requesting a ticket;
Cancel remains available during this wait. If Play fails, its message remains in
the selected provider's form after dismissing the alert.

## Build 8 local Steam diagnosis

Code `996708736` is `AuthenFailed`; by itself it does not establish an incorrect
password. Build 8 keeps the provider, numeric code, response stage and a safe
reason category in a typed error. The exact official launcher reasons `AuthDown`,
`AuthBanned`, `AuthQuarantined` and `AccountClientMismatch` have fixed recovery
messages. Empty, malformed or unrecognized reason text produces a neutral
rejection. No arbitrary server text, account identity, password, ticket or
session key is included in the error or diagnostic output.

Build a separate candidate for one local Steam retry:

```sh
python3 portable/build_account_diagnostic.py \
  --base-app '/Applications/Wizard101 Standalone.app' \
  --output '/new/output/Wizard101 Steam Diagnosis.app'
```

This app reuses the installed runtime, renderer and shared game folder. It leaves
the installed launcher available. Enter credentials only in the candidate's local
form. A rejection writes just `provider`, `code`, `reason` and `stage` to
`~/Library/Application Support/Wizard101 Native/State/AuthenticationFailure.json`.
Starting another operation clears the previous diagnostic. Cancellation and
untyped errors do not write that file. Normal packaged apps disable this local
diagnostic file.

The `--synthetic-auth-probe` command uses a random nonexistent US identity and
typed errors. It never reads saved credentials or requests Steam tickets, and is
not a real-account or gameplay test.

Ticket handling, credential construction and request fields are unchanged in
this diagnostic build. Compare the resulting failure against the official
Windows **Steam** launcher before changing those fields. The local non-Steam
launcher and game-client disassembly below do not establish Steam-launcher
equivalence. The owner subsequently confirmed Steam working and authorized the experimental
3.2 release. That confirmation does not complete every live check below. Normal
release packages disable local diagnostic output; full qualification remains
required before promotion or automated installed-launcher replacement.

## Provider storage and shared content

The account selector, username and Remember me preference survive reopening the
launcher. Each provider has a separate Keychain service, including when both
accounts use the same username. **Forget saved password** affects the selected
provider and username. Switching providers clears the password field and loads
only that provider's remembered password. Rejected credentials stay with the
selected provider; the launcher does not retry another account type.

Both providers use the same installation under
`~/Library/Application Support/Wizard101 Native`. Switching accounts does not
import, copy or redownload the game. The usual official update check still runs
before Play. Resolution, graphics, 60 FPS, legacy pacing, larger cursor and
downloaded content remain shared. EU authentication, account linking, Steam
overlay and Steam Wallet integration are outside this candidate.

## Local acceptance before replacement

Keep `/Applications/Wizard101 Standalone.app` and the previous installer. Open
the **candidate app directly from its output folder** to test without installing
its PKG. Close the installed launcher first. The candidate intentionally reuses
the existing standalone game folder and preference domain.

For **each** provider:

1. Choose the provider, enter credentials locally, and select Play.
2. Confirm the expected existing characters, select one, and play: movement,
   a zone change and combat. Check audio, input and the larger cursor.
3. Confirm the launcher exits and the game stays playable for at least 10 minutes,
   including a zone change after handoff.
4. Close the game, reopen the candidate, and verify the provider, username and
   Remember me choice. Confirm the same characters and gameplay on relaunch.

Switch US → Steam → US. Check that usernames/passwords stay separate, downloaded
worlds are reused, and the previous resolution (including 2560×1600), graphics and
frame pacing remain intact. Compare crowded Commons, arrivals, revisit, movement
and combat at the same settings. Test Cancel during Steam ticket preparation and
retry. Signed-out, offline or missing Steam must stop Steam sign-in while US still
works. Never put passwords, Steam tickets or session keys in observations.

`ACCOUNT-LIVE-CHECKS.html` and `ACCOUNT-LIVE-TEMPLATE.json` accompany the candidate.
They bind the checks to its exact app and installer hashes. Keep untested checks
unchecked. Replacement uses `install_account_candidate.py` and retains a rollback app; it refuses
installation without matching passes and observations for both providers. It checks
without installing by default; add `--install` only after acceptance:

```sh
python3 portable/install_account_candidate.py --app '/path/Wizard101 Standalone.app' \
  --installer '/path/Wizard101-AppleSilicon-community-beta.pkg' \
  --evidence '/path/Wizard101-Account-Live-Results.json' --install
```

The helper prints the retained previous app's path. To roll back, close the game
and launcher, move the new app aside in Finder, and rename that backup to
`Wizard101 Standalone.app`. Both apps continue to use the same external game data.

## Protocol evidence and limits

The official r806919 Windows game client (SHA-256
`544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e`)
contains these independently inspected code paths:

- `0x141302a40` calls `ISteamUser023::GetAuthTicketForWebApi("Wizard101")`.
- `0x141303150` handles the callback, checks success, and copies exactly
  `m_cubTicket` raw bytes from offset 12 into the SteamAuthTicket string.
- `0x1416e19ef` formats SteamID as an unsigned decimal 64-bit number;
  `0x1416e1a35` sets SteamAuthTicket. `0x141336500` supplies IsSteamPatcher.
- The installed `LoginMessages.xml` verifies V3 field order and types. Validation
  uses UserID/PassKey3 and contains no provider or ticket field.

The local official **non-Steam** Windows launcher (SHA-256
`944f4b93b1fcd3a6191296ee2dfe59d5edc39892e6a49edf693ce5b432b63c8a`)
compares `Reason` to the four exact tokens above in its `AuthenFailed` branch at
`0x4571d2`–`0x45744a`. This establishes the diagnostic categories, not the Steam
request construction. The previously downloaded `WizardLauncher-Steam.exe` is
an HTTP 403 page, not an executable, and cannot support a comparison.

Valve's [ticket API documentation](https://partner.steamgames.com/doc/api/ISteamUser#GetAuthTicketForWebApi)
requires waiting for GetTicketForWebApiResponse_t. The native bridge does so with
manual callback dispatch, verifies the current AppID is 799960, verifies ownership
and online login, and retains the ticket through handoff. It dynamically loads the
installed Mac Steam client; no Steam SDK or library is bundled. Tickets stay in
memory and never enter logs, preferences, Keychain or game arguments.
On 2026-10-16 the corrected bridge obtained a successful 234-byte ticket from the
signed-in local Mac Steam client for AppID 799960 and identity `Wizard101`.
This test did not submit Wizard101 credentials or start the game. Regression
tests cover bootstrapper discovery and the initial invalid-handle startup race.

The candidate exchanges the Mac Steam ticket for a KingsIsle session, validates
that session, then uses the existing direct `-U` handoff for both providers. It
deliberately avoids the client's Windows-only `-ST` (Steam Required) startup path.
That does not implement Windows Steam inside Wine. The owner confirmed this candidate working locally. Expected characters,
relaunch and ten minutes of ongoing gameplay still need recorded live checks.

The Steam launcher depot requires account ownership and denied anonymous access
during research. Its exact launcher-specific behavior is not independently
qualified. Static protocol evidence, ticket acquisition and synthetic tests are not real-account
or gameplay acceptance.
