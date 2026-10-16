"""Live acceptance for the US / Steam candidate, bound to the final artifacts."""
import json
from pathlib import Path


ACCOUNT_CHECKS = {
    'us_existing_characters': ('US account and characters', 'Choose US, enter credentials locally, and confirm the expected existing characters. Never record passwords or session keys.'),
    'us_gameplay': ('US gameplay', 'Enter the world. Check movement, a zone change, combat, audio, input and the larger cursor.'),
    'us_relaunch': ('US relaunch', 'Close the game and reopen the candidate. Confirm the remembered provider, username and Remember me preference, then reach the same characters and gameplay.'),
    'us_continued_play': ('US continued play', 'Confirm the launcher exits after handoff. Keep playing for at least 10 minutes and change zones after handoff.'),
    'steam_official_flow': ('Verify Steam authentication', 'With a signed-in Mac Steam client and Wizard101 in its library, verify the candidate obtains a Wizard101 Web API ticket and the account server accepts it. Confirm this against the official Steam launcher flow. Do not copy tickets into observations.'),
    'steam_existing_characters': ('Steam account and characters', 'Choose Steam. Enter the Wizard101 credentials created through Steam locally and confirm the expected existing characters.'),
    'steam_gameplay': ('Steam gameplay', 'Enter the world. Check movement, a zone change, combat, audio, input and the larger cursor.'),
    'steam_relaunch': ('Steam relaunch', 'Close the game and reopen the candidate. Confirm the remembered provider, username and Remember me preference, then reach the same characters and gameplay.'),
    'steam_continued_play': ('Steam continued play', 'Confirm the launcher exits after handoff. Keep playing for at least 10 minutes and change zones after handoff. Check for ticket expiry or loss of Steam authentication.'),
    'provider_persistence': ('Remember the selected provider', 'Switch US to Steam to US, reopening the launcher between changes. Confirm each selection survives relaunch.'),
    'provider_credential_isolation': ('Keep credentials separate', 'Confirm each provider restores only its own username, Remember me choice and saved password. Forget a Steam password and confirm the US password remains. Include identical usernames if available.'),
    'provider_cancel_errors': ('Cancel and reject credentials', 'Cancel US sign-in and Steam ticket preparation, then retry. Confirm rejected credentials stay with the selected provider and never trigger another account type.'),
    'steam_unavailable': ('Handle unavailable Steam', 'Check missing, signed-out and offline Steam. Confirm useful recovery messages, no account fallback, and that US still works. Restore the Steam installation after a missing-client test.'),
    'provider_shared_content': ('Reuse downloaded content', 'Switch US to Steam to US. Confirm the same game folder and downloaded worlds are reused without another installation or bulk download.'),
    'provider_shared_settings': ('Preserve graphics and pacing', 'At the previous settings, including 2560 by 1600 and 60 FPS where used, compare cold entry, revisit, crowded Commons, arrivals, movement and combat. Confirm graphics, cursor and frame pacing remain acceptable.'),
}
ACCOUNT_GATES = list(ACCOUNT_CHECKS)


def template(hashes, installer_sha256):
    return dict(account_qualification=1, components=hashes, installer_sha256=installer_sha256,
                gates=dict.fromkeys(ACCOUNT_GATES, False), observations={})


def validate_accounts(evidence, hashes, installer_sha256):
    if evidence.get('components') != hashes or evidence.get('installer_sha256') != installer_sha256:
        raise ValueError('Account evidence must match the final app and installer exactly')
    missing = [gate for gate in ACCOUNT_GATES if evidence.get('gates', {}).get(gate) is not True]
    if missing:
        raise ValueError('Unverified US / Steam checks: ' + ', '.join(missing))
    if not all(isinstance(evidence.get('observations', {}).get(gate), str)
               and evidence['observations'][gate].strip() for gate in ACCOUNT_GATES):
        raise ValueError('Record a local observation for every US / Steam check')


def write_account_checks(directory, hashes, installer_sha256):
    directory = Path(directory)
    evidence = template(hashes, installer_sha256)
    (directory / 'ACCOUNT-LIVE-TEMPLATE.json').write_text(json.dumps(evidence, indent=2) + '\n')
    page = (Path(__file__).parent / 'installer/LIVE-CHECKS.html').read_text()
    page = page.replace('Community beta checks', 'US / Steam candidate checks')
    page = page.replace('BETA-LIVE-TEMPLATE.json', 'ACCOUNT-LIVE-TEMPLATE.json')
    page = page.replace('Wizard101-Beta-Live-Results.json', 'Wizard101-Account-Live-Results.json')
    page = page.replace('the illustrated installation guide', 'the candidate instructions')
    page = page.replace('href="INSTALL.html"', 'href="ACCOUNTS.md"')
    data = json.dumps(dict(evidence=evidence, checks=ACCOUNT_CHECKS), ensure_ascii=True)
    data = data.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    (directory / 'ACCOUNT-LIVE-CHECKS.html').write_text(page.replace('__W101_CHECK_DATA__', data))
