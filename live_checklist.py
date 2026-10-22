"""Create an offline, hash-bound walkthrough sheet for the actual beta installer."""
import json
from pathlib import Path
from account_qualification import ACCOUNT_CHECKS
from reliability_qualification import CHECKS as RELIABILITY_CHECKS


CHECKS = {
    'installer_install': ('Install in Applications', 'Open this PKG in Finder and complete Installer. Open Wizard101 Standalone from Applications. Confirm the official app and Desktop candidate are still present.'),
    'installer_reinstall': ('Reinstall and reuse data', 'Run the same PKG again. Reopen the app and confirm the existing standalone game, preferences and optional saved Keychain login are still usable.'),
    'fresh_user_no_terminal': ('Fresh-user walkthrough', 'Have a new user follow INSTALL.html from download to Play without Terminal or developer tools. Include macOS Privacy & Security → Open Anyway. Record Mac model and macOS version.'),
    'rosetta_first_run': ('Prepare a Mac without Rosetta', 'On an Apple Silicon Mac without Rosetta, follow Prepare Mac, complete Apple’s installation prompt and return to Check again. Confirm game setup becomes available.'),
    'multiple_installations': ('Choose an existing game', 'With at least two known game installations present, check the friendly source names and select one. Also use the manual picker. Confirm the original files and settings remain usable.'),
    'gui_cancel_resume': ('Cancel and resume an import', 'Begin an import, cancel during progress, then Continue setup using the same source. Confirm progress, completion, and preservation of the original game.'),
    'network_interruption': ('Recover from an interrupted download', 'During fresh setup or an update, disconnect the network. Confirm a useful status, reconnect, retry and verify the staged download completes.'),
    'insufficient_storage': ('Recover from low storage', 'On a disposable test destination with insufficient free space, begin setup or import. Confirm a useful message and that retry succeeds after space is available. Preserve existing user files.'),
    'updates': ('Check and apply game updates', 'Use Check game updates, then Play. Confirm the update status is clear and required content is verified before launch.'),
    'native_login': ('Sign in', 'Sign in using a US standalone account through the native launcher and reach character selection.'),
    'character_selection': ('Choose a character', 'Select your character and enter the world successfully.'),
    'fresh_install_gameplay': ('Play after fresh setup', 'On a fresh standalone data folder, complete game setup and play. Check movement, a zone change and combat.'),
    'session_survives_launcher_exit': ('Continue after launcher handoff', 'Confirm the launcher exits after handing off and that the game remains playable.'),
    'audio': ('Hear game audio', 'Check music, effects and audio during gameplay.'),
    'keyboard_mouse': ('Use controls', 'Check keyboard movement, mouse camera, menus and combat controls.'),
    'cursor': ('Check the larger cursor', 'Check cursor size, appearance and click position in menus and gameplay.'),
    'fullscreen': ('Switch fullscreen and windowed', 'Switch between fullscreen and windowed modes and confirm rendering and input continue normally.'),
    'graphics': ('Preserve existing graphics', 'Confirm the previous resolution and graphics settings, including 2560×1600 where used. Inspect text, HUD, effects and world rendering.'),
    'performance_accepted': ('Accept frame pacing in real play', 'Compare with the retained Standalone Candidate at the same graphics and 60 FPS settings. Check cold entry, revisit, crowded Commons, arrivals, movement and combat. Record your acceptance or observed regression.'),
}
CHECKS.update(ACCOUNT_CHECKS)
CHECKS.update(RELIABILITY_CHECKS)


def write_checklist(destination, evidence):
    if set(evidence['gates']) != set(CHECKS):
        raise ValueError('Live checklist must cover every release gate')
    template = (Path(__file__).parent / 'installer/LIVE-CHECKS.html').read_text()
    data = json.dumps(dict(evidence=evidence, checks=CHECKS), ensure_ascii=True)
    # Keep JSON inert even if a future observation contains an HTML end tag.
    data = data.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    Path(destination).write_text(template.replace('__W101_CHECK_DATA__', data))
